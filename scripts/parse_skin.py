#!/usr/bin/env python3
"""
Download HD splash arts for all League of Legends champions.
Reads skin list from champions.txt and saves images to splash_arts/.
"""

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
)

console = Console()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

CHAMPIONS_FILE = DATA_DIR / "champions.txt"
SPLASH_ARTS_DIR = ROOT / "splash_arts"
SHARED_DIR = SPLASH_ARTS_DIR / "SHARED"
FAILED_DOWNLOADS_FILE = ROOT / "failed_downloads.txt"
DOWNLOAD_REPORT_FILE = ROOT / "download_report.txt"
WIKI_IMAGE_BASE = "https://wiki.leagueoflegends.com/en-us/images/"
SHARED_EXCEPTIONS_FILE = DATA_DIR / "shared_exceptions.json"
OTHER_EXCEPTIONS_FILE = DATA_DIR / "other_exceptions.json"
REQUEST_TIMEOUT = 30
MAX_WORKERS = 10

# Maps expected HD filename → actual filename in SHARED_DIR
SHARED_EXCEPTIONS: dict[str, str] = {}
OTHER_EXCEPTIONS: dict[str, str] = {}

ONLY_SHARED: bool = False
ONLY_OTHER: bool = False
SIMPLE_PARSE: bool = False
FORCE: bool = False

# Pattern da rimuovere dal nome file wiki (case-insensitive)
_JUNK_RE = re.compile(r'_(old|unused)\d*', re.IGNORECASE)


def load_shared_exceptions() -> None:
    """Populate SHARED_EXCEPTIONS from shared_exceptions.json (silently skip if missing)."""
    global SHARED_EXCEPTIONS
    try:
        with open(SHARED_EXCEPTIONS_FILE, encoding="utf-8") as f:
            SHARED_EXCEPTIONS = json.load(f)
    except FileNotFoundError:
        pass

def load_other_exceptions() -> None:
    """Populate OTHER_EXCEPTIONS from other_exceptions.json (silently skip if missing)."""
    global OTHER_EXCEPTIONS
    try:
        with open(OTHER_EXCEPTIONS_FILE, encoding="utf-8") as f:
            OTHER_EXCEPTIONS = json.load(f)
    except FileNotFoundError:
        pass


def parse_champions(filepath: str | Path) -> dict[str, list[str]]:
    """Parse champions.txt and return {champion: [skin_filename, ...]}."""
    champions: dict[str, list[str]] = {}
    current_champion: str | None = None

    with open(filepath, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")

            # Skip header lines
            if (
                line.startswith("League of Legends")
                or line.startswith("Total:")
                or line.startswith("=")
            ):
                continue

            # Empty line — reset current champion context
            if not line.strip():
                current_champion = None
                continue

            # Skin entry: "  - Filename.jpg"
            if line.startswith("  - "):
                if current_champion is not None:
                    skin = line.strip()[2:].strip()  # strip leading "- "
                    champions[current_champion].append(skin)
            elif not line.startswith(" "):
                # Champion name line
                current_champion = line.strip()
                champions.setdefault(current_champion, [])

    return champions


def hd_filename(skin_filename: str) -> str:
    """'Aatrox_OriginalSkin.jpg' → 'Aatrox_OriginalSkin_HD.jpg'."""
    stem = skin_filename.rsplit(".", 1)[0]
    return f"{stem}_HD.jpg"


def stripped_filename(champion: str, hd_name: str) -> str:
    """Strip the champion prefix: 'Aatrox_SeaHunterSkin_HD.jpg' → 'SeaHunterSkin_HD.jpg'."""
    prefix = champion.replace(" ", "_") + "_"
    if hd_name.startswith(prefix):
        return hd_name[len(prefix):]
    return hd_name


def clean_skin_name(name: str) -> str:
    """Remove suffixes like _old, _old1, _unused, _unused2 from skin names."""
    p = Path(name)
    return _JUNK_RE.sub('', p.stem) + p.suffix


def _exists(path: Path) -> bool:
    """Return True if path (or its .jpg/.png counterpart) exists and is non-empty."""
    if path.exists() and path.stat().st_size > 0:
        return True
    alt = path.with_suffix(".png" if path.suffix == ".jpg" else ".jpg")
    return alt.exists() and alt.stat().st_size > 0


def download_skin(
    champion: str, skin_filename: str
) -> tuple[str, str, bool, str, str]:
    """
    Download a single HD skin image.
    Returns (champion, skin_filename, success, message, retry_type).
    retry_type is '' for a direct download, or 'shared' for the retry
    (champion prefix stripped, saved to SHARED_DIR).
    """
    hd_name = hd_filename(skin_filename)
    save_dir = SPLASH_ARTS_DIR / champion
    save_path = save_dir / hd_name

    # Skip if already downloaded (normal path)
    if not FORCE and _exists(save_path):
        return champion, skin_filename, True, "already exists", ""

    hd_stem = hd_name.removesuffix(".jpg")
    url = WIKI_IMAGE_BASE + quote(hd_name, safe="")

    # --only-shared: skip skins not in SHARED_EXCEPTIONS
    if ONLY_SHARED and hd_stem not in SHARED_EXCEPTIONS:
        return champion, skin_filename, True, "skipped (not a shared exception)", ""

    # --only-other: skip skins not in OTHER_EXCEPTIONS
    if ONLY_OTHER and hd_stem not in OTHER_EXCEPTIONS:
        return champion, skin_filename, True, "skipped (not an other exception)", ""

    # Step 1: Check SHARED_EXCEPTIONS before any download attempt
    if not SIMPLE_PARSE and hd_stem in SHARED_EXCEPTIONS:
        exception_name_raw = SHARED_EXCEPTIONS[hd_stem] + ".jpg"
        exception_name_clean = clean_skin_name(SHARED_EXCEPTIONS[hd_stem]) + ".jpg"
        exception_path = SHARED_DIR / exception_name_clean
        if not FORCE and _exists(exception_path):
            return champion, skin_filename, True, "already exists", "shared"
        exception_url = WIKI_IMAGE_BASE + quote(exception_name_raw, safe="")
        try:
            exc_response = requests.get(exception_url, timeout=REQUEST_TIMEOUT, stream=True)
            if exc_response.status_code == 200:
                exc_response.raise_for_status()
                SHARED_DIR.mkdir(parents=True, exist_ok=True)
                with open(exception_path, "wb") as f:
                    for chunk in exc_response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return champion, skin_filename, True, "downloaded (shared exception)", "shared"
            elif exc_response.status_code != 404:
                exc_response.raise_for_status()
            else:
                if ONLY_SHARED:
                    return champion, skin_filename, False, f"404 Not Found (shared): {exception_url}", "shared"
        except requests.RequestException as exc:
            if exception_path.exists():
                exception_path.unlink(missing_ok=True)
            return champion, skin_filename, False, str(exc), ""

    # --only-other: skip JPG/PNG steps and go straight to other exception URL
    if ONLY_OTHER:
        other_name_raw = OTHER_EXCEPTIONS[hd_stem] + ".jpg"
        save_dir.mkdir(parents=True, exist_ok=True)
        other_path = save_dir / hd_name
        other_url = WIKI_IMAGE_BASE + quote(other_name_raw, safe="")
        try:
            other_response = requests.get(other_url, timeout=REQUEST_TIMEOUT, stream=True)
            if other_response.status_code == 200:
                other_response.raise_for_status()
                with open(other_path, "wb") as f:
                    for chunk in other_response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return champion, skin_filename, True, "downloaded (other exception)", "other"
            elif other_response.status_code != 404:
                other_response.raise_for_status()
            return champion, skin_filename, False, f"404 Not Found (other): {other_url}", "other"
        except requests.RequestException as exc:
            if other_path.exists():
                other_path.unlink(missing_ok=True)
            return champion, skin_filename, False, str(exc), ""

    try:
        save_dir.mkdir(parents=True, exist_ok=True)

        # Step 2: Normal JPG download
        response = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
        if response.status_code == 200:
            response.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return champion, skin_filename, True, "downloaded", ""
        elif response.status_code != 404:
            response.raise_for_status()

        # Step 3: PNG format
        png_hd_name = hd_name.removesuffix(".jpg") + ".png"
        png_save_path = save_dir / png_hd_name
        png_url = WIKI_IMAGE_BASE + quote(png_hd_name, safe="")
        try:
            png_response = requests.get(png_url, timeout=REQUEST_TIMEOUT, stream=True)
            if png_response.status_code == 200:
                png_response.raise_for_status()
                with open(png_save_path, "wb") as f:
                    for chunk in png_response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return champion, skin_filename, True, "downloaded (png)", ""
            elif png_response.status_code != 404:
                png_response.raise_for_status()
        except requests.RequestException as exc:
            if png_save_path.exists():
                png_save_path.unlink(missing_ok=True)
            return champion, skin_filename, False, str(exc), ""

        # Step 4: Check OTHER_EXCEPTIONS
        if not SIMPLE_PARSE and hd_stem in OTHER_EXCEPTIONS:
            other_name_raw = OTHER_EXCEPTIONS[hd_stem] + ".jpg"
            other_path = save_dir / hd_name
            other_url = WIKI_IMAGE_BASE + quote(other_name_raw, safe="")
            try:
                other_response = requests.get(other_url, timeout=REQUEST_TIMEOUT, stream=True)
                if other_response.status_code == 200:
                    other_response.raise_for_status()
                    with open(other_path, "wb") as f:
                        for chunk in other_response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    return champion, skin_filename, True, "downloaded (other exception)", "other"
                elif other_response.status_code != 404:
                    other_response.raise_for_status()
            except requests.RequestException as exc:
                if other_path.exists():
                    other_path.unlink(missing_ok=True)
                return champion, skin_filename, False, str(exc), ""

        return champion, skin_filename, False, f"404 Not Found: {url}", ""

    except requests.RequestException as exc:
        if save_path.exists():
            save_path.unlink(missing_ok=True)
        return champion, skin_filename, False, str(exc), ""


def write_download_report(
    downloaded_files: list[tuple[str, str, str]],
    skipped: int,
    failed: int,
) -> None:
    """Write a structured report of all successfully downloaded files."""
    with open(DOWNLOAD_REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("=== Download Report ===\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Newly downloaded: {len(downloaded_files)}\n")
        f.write(f"Skipped (already present): {skipped}\n")
        f.write(f"Failed: {failed}\n\n")
        for champion, skin, retry_type in downloaded_files:
            label = f"[{retry_type}] " if retry_type else ""
            f.write(f"{label}{champion}/{skin}\n")


def write_failed_report(failed: list[tuple[str, str, str]]) -> None:
    """Write a structured report of failed downloads."""
    with open(FAILED_DOWNLOADS_FILE, "w", encoding="utf-8") as f:
        f.write("=== Failed Downloads Report ===\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total failures: {len(failed)}\n\n")
        for champion, skin, reason in failed:
            f.write(f"Champion : {champion}\n")
            f.write(f"File     : {skin}\n")
            f.write(f"Reason   : {reason}\n")
            f.write("-" * 60 + "\n")


def main() -> None:
    global ONLY_SHARED, ONLY_OTHER, SIMPLE_PARSE, FORCE

    parser = argparse.ArgumentParser(description="Download LoL HD splash arts.")
    parser.add_argument(
        "--only-shared",
        action="store_true",
        help="Download only skins mapped in shared_exceptions.json; skip all others.",
    )
    parser.add_argument(
        "--only-other",
        action="store_true",
        help="Download only skins mapped in other_exceptions.json; skip all others.",
    )
    parser.add_argument(
        "--simple-parse",
        action="store_true",
        help="Skip SHARED_EXCEPTIONS and OTHER_EXCEPTIONS; attempt direct JPG/PNG only.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download all skins regardless of whether they already exist.",
    )
    args = parser.parse_args()
    ONLY_SHARED = args.only_shared
    ONLY_OTHER = args.only_other
    SIMPLE_PARSE = args.simple_parse
    FORCE = args.force

    load_shared_exceptions()
    load_other_exceptions()
    champions = parse_champions(CHAMPIONS_FILE)
    tasks = [
        (champion, skin)
        for champion, skins in champions.items()
        for skin in skins
    ]

    total_skins = len(tasks)
    console.print(
        f"[green]✓[/] {len(champions)} champions — {total_skins} skins to process"
    )

    failed: list[tuple[str, str, str]] = []
    downloaded_files: list[tuple[str, str, str]] = []
    skipped = 0
    downloaded = 0
    retried_shared = 0
    retried_other = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=35),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[bold cyan]Downloading...", total=total_skins)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(download_skin, champion, skin): (champion, skin)
                for champion, skin in tasks
            }
            for future in as_completed(futures):
                champion, skin, success, msg, retry_type = future.result()

                if not success:
                    failed.append((champion, skin, msg))
                    progress.update(
                        task,
                        description=f"[red]✗ {champion}/{skin}",
                    )
                elif "already exists" in msg or "skipped" in msg:
                    skipped += 1
                    progress.update(
                        task,
                        description=f"[dim]↷ {champion}/{skin}[/]",
                    )
                elif retry_type == "shared":
                    retried_shared += 1
                    downloaded_files.append((champion, skin, "shared"))
                    progress.update(
                        task,
                        description=f"[yellow]↺ {champion}/{skin}",
                    )
                elif retry_type == "other":
                    retried_other += 1
                    downloaded_files.append((champion, skin, "other"))
                    progress.update(
                        task,
                        description=f"[blue]◆ {champion}/{skin}",
                    )
                else:
                    downloaded += 1
                    downloaded_files.append((champion, skin, ""))
                    progress.update(
                        task,
                        description=f"[green]✓ {champion}/{skin}",
                    )

                progress.advance(task)

    write_failed_report(sorted(failed))
    write_download_report(sorted(downloaded_files), skipped, len(failed))

    console.print(f"\n[bold]Done.[/]")
    console.print(f"  Downloaded : [green]{downloaded}[/]")
    console.print(f"  Retry SHARED : [yellow]{retried_shared}[/] (saved to {SHARED_DIR}/)")
    console.print(f"  Retry OTHER EXCEPTIONS : [blue]{retried_other}[/] (fallback)")
    console.print(f"  Skipped    : [dim]{skipped}[/]")
    console.print(f"  Failed     : [{'red' if failed else 'green'}]{len(failed)}[/]")
    console.print(f"  Report     : [dim]{DOWNLOAD_REPORT_FILE}[/]")
    if failed:
        console.print(f"\n[yellow]See {FAILED_DOWNLOADS_FILE} for details.[/]")


if __name__ == "__main__":
    main()
