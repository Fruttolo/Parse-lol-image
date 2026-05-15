#!/usr/bin/env python3
"""
Download HD splash arts for all League of Legends champions.
Reads skin list from champions.txt and saves images to splash_arts/.
"""

import json
import os
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

CHAMPIONS_FILE = "champions.txt"
SPLASH_ARTS_DIR = Path("splash_arts")
SHARED_DIR = SPLASH_ARTS_DIR / "SHARED"
FAILED_DOWNLOADS_FILE = "failed_downloads.txt"
WIKI_IMAGE_BASE = "https://wiki.leagueoflegends.com/en-us/images/"
SHARED_EXCEPTIONS_FILE = "shared_exceptions.json"
OTHER_EXCEPTIONS_FILE = "other_exceptions.json"
REQUEST_TIMEOUT = 30
MAX_WORKERS = 10

# Maps expected HD filename → actual filename in SHARED_DIR
SHARED_EXCEPTIONS: dict[str, str] = {}
OTHER_EXCEPTIONS: dict[str, str] = {}


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


def parse_champions(filepath: str) -> dict[str, list[str]]:
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
    if _exists(save_path):
        return champion, skin_filename, True, "already exists", ""

    # Handle explicit shared exception: download mapped filename to SHARED_DIR
    hd_stem = hd_name.removesuffix(".jpg")
    if hd_stem in SHARED_EXCEPTIONS:
        exception_name = SHARED_EXCEPTIONS[hd_stem] + ".jpg"
        exception_path = SHARED_DIR / exception_name
        if _exists(exception_path):
            return champion, skin_filename, True, "already exists", "shared"
        exception_url = WIKI_IMAGE_BASE + quote(exception_name, safe="")
        try:
            exc_response = requests.get(exception_url, timeout=REQUEST_TIMEOUT, stream=True)
            if exc_response.status_code == 404:
                return champion, skin_filename, False, f"404 Not Found: {exception_url}", ""
            exc_response.raise_for_status()
            SHARED_DIR.mkdir(parents=True, exist_ok=True)
            with open(exception_path, "wb") as f:
                for chunk in exc_response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return champion, skin_filename, True, "downloaded (shared exception)", "shared"
        except requests.RequestException as exc:
            if exception_path.exists():
                exception_path.unlink(missing_ok=True)
            return champion, skin_filename, False, str(exc), ""

    # Skip if already downloaded via shared path
    retry_name = stripped_filename(champion, hd_name)
    retry_save_path = SHARED_DIR / retry_name
    if _exists(retry_save_path):
        return champion, skin_filename, True, "already exists", "shared"

    url = WIKI_IMAGE_BASE + quote(hd_name, safe="")

    try:
        save_dir.mkdir(parents=True, exist_ok=True)
        response = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)

        if response.status_code == 404:
            # Retry 1: same name, PNG format
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

            # Retry 2: champion prefix stripped → SHARED_DIR (jpg)
            if retry_name != hd_name:
                retry_url = WIKI_IMAGE_BASE + quote(retry_name, safe="")
                try:
                    retry_response = requests.get(retry_url, timeout=REQUEST_TIMEOUT, stream=True)
                    if retry_response.status_code == 200:
                        retry_response.raise_for_status()
                        SHARED_DIR.mkdir(parents=True, exist_ok=True)
                        with open(retry_save_path, "wb") as f:
                            for chunk in retry_response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        return champion, skin_filename, True, "downloaded (retry shared)", "shared"
                    elif retry_response.status_code != 404:
                        retry_response.raise_for_status()
                except requests.RequestException as exc:
                    if retry_save_path.exists():
                        retry_save_path.unlink(missing_ok=True)
                    return champion, skin_filename, False, str(exc), ""

                # Retry 3: stripped name, PNG format → SHARED_DIR
                retry_png_name = retry_name.removesuffix(".jpg") + ".png"
                retry_png_save_path = SHARED_DIR / retry_png_name
                retry_png_url = WIKI_IMAGE_BASE + quote(retry_png_name, safe="")
                try:
                    retry_png_response = requests.get(retry_png_url, timeout=REQUEST_TIMEOUT, stream=True)
                    if retry_png_response.status_code == 200:
                        retry_png_response.raise_for_status()
                        SHARED_DIR.mkdir(parents=True, exist_ok=True)
                        with open(retry_png_save_path, "wb") as f:
                            for chunk in retry_png_response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        return champion, skin_filename, True, "downloaded (retry shared png)", "shared"
                    elif retry_png_response.status_code != 404:
                        retry_png_response.raise_for_status()
                except requests.RequestException as exc:
                    if retry_png_save_path.exists():
                        retry_png_save_path.unlink(missing_ok=True)
                    return champion, skin_filename, False, str(exc), ""
                
            # FALLBACK: Cerca nella mappa OTHER_EXCEPTIONS se tutti i retry sono falliti
            if hd_stem in OTHER_EXCEPTIONS:
                other_name = OTHER_EXCEPTIONS[hd_stem] + ".jpg"
                other_path = SHARED_DIR / other_name
                if _exists(other_path):
                    return champion, skin_filename, True, "downloaded (other exception)", "other"
                other_url = WIKI_IMAGE_BASE + quote(other_name, safe="")
                try:
                    other_response = requests.get(other_url, timeout=REQUEST_TIMEOUT, stream=True)
                    if other_response.status_code == 200:
                        other_response.raise_for_status()
                        SHARED_DIR.mkdir(parents=True, exist_ok=True)
                        with open(other_path, "wb") as f:
                            for chunk in other_response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        return champion, skin_filename, True, "downloaded (other exception)", "other"
                    elif other_response.status_code != 404:
                        other_response.raise_for_status()
                except requests.RequestException:
                    if other_path.exists():
                        other_path.unlink(missing_ok=True)
                    return champion, skin_filename, False, str(exc), ""

            return champion, skin_filename, False, f"404 Not Found: {url}", ""

        response.raise_for_status()

        with open(save_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return champion, skin_filename, True, "downloaded", ""

    except requests.RequestException as exc:
        # Remove partial file if it was created
        if save_path.exists():
            save_path.unlink(missing_ok=True)
        return champion, skin_filename, False, str(exc), ""


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
                elif "already exists" in msg:
                    skipped += 1
                    progress.update(
                        task,
                        description=f"[dim]↷ {champion}/{skin}[/]",
                    )
                elif retry_type == "shared":
                    retried_shared += 1
                    progress.update(
                        task,
                        description=f"[yellow]↺ {champion}/{skin}",
                    )
                elif retry_type == "other":
                    retried_other += 1
                    progress.update(
                        task,
                        description=f"[blue]◆ {champion}/{skin}",
                    )
                else:
                    downloaded += 1
                    progress.update(
                        task,
                        description=f"[green]✓ {champion}/{skin}",
                    )

                progress.advance(task)

    write_failed_report(sorted(failed))

    console.print(f"\n[bold]Done.[/]")
    console.print(f"  Downloaded : [green]{downloaded}[/]")
    console.print(f"  Retry SHARED : [yellow]{retried_shared}[/] (saved to {SHARED_DIR}/)")
    console.print(f"  Retry OTHER EXCEPTIONS : [blue]{retried_other}[/] (fallback)")
    console.print(f"  Skipped    : [dim]{skipped}[/] (already present)")
    console.print(f"  Failed     : [{'red' if failed else 'green'}]{len(failed)}[/]")
    if failed:
        console.print(f"\n[yellow]See {FAILED_DOWNLOADS_FILE} for details.[/]")


if __name__ == "__main__":
    main()
