#!/usr/bin/env python3
"""
Download HD splash arts for all League of Legends champions.
Reads skin list from champions.txt and saves images to splash_arts/.
"""

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
OLD_DIR = SPLASH_ARTS_DIR / "OLD"
FAILED_DOWNLOADS_FILE = "failed_downloads.txt"
WIKI_IMAGE_BASE = "https://wiki.leagueoflegends.com/en-us/images/"
REQUEST_TIMEOUT = 30
MAX_WORKERS = 10


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


def old2_filename(hd_name: str) -> str:
    """'Heimerdinger_AlienInvaderSkin_HD.jpg' → 'Heimerdinger_AlienInvaderSkin_old2_HD.jpg'."""
    if hd_name.endswith("_HD.jpg"):
        stem = hd_name[: -len("_HD.jpg")]
        return f"{stem}_old2_HD.jpg"
    stem, ext = hd_name.rsplit(".", 1)
    return f"{stem}_old2.{ext}"


def download_skin(
    champion: str, skin_filename: str
) -> tuple[str, str, bool, str, str]:
    """
    Download a single HD skin image.
    Returns (champion, skin_filename, success, message, retry_type).
    retry_type is '' for a direct download, 'shared' for the first retry
    (champion prefix stripped, saved to SHARED_DIR), or 'old' for the second
    retry (_old2 suffix, saved to OLD_DIR).
    """
    hd_name = hd_filename(skin_filename)
    save_dir = SPLASH_ARTS_DIR / champion
    save_path = save_dir / hd_name

    # Skip if already downloaded (normal path)
    if save_path.exists() and save_path.stat().st_size > 0:
        return champion, skin_filename, True, "already exists", ""

    # Skip if already downloaded via shared path
    retry_name = stripped_filename(champion, hd_name)
    retry_save_path = SHARED_DIR / retry_name
    if retry_save_path.exists() and retry_save_path.stat().st_size > 0:
        return champion, skin_filename, True, "already exists", "shared"

    # Skip if already downloaded via old2 path
    old2_name = old2_filename(hd_name)
    old2_save_path = OLD_DIR / old2_name
    if old2_save_path.exists() and old2_save_path.stat().st_size > 0:
        return champion, skin_filename, True, "already exists", "old"

    url = WIKI_IMAGE_BASE + quote(hd_name, safe="")

    try:
        save_dir.mkdir(parents=True, exist_ok=True)
        response = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)

        if response.status_code == 404:
            # Retry 1: champion prefix stripped → SHARED_DIR
            if retry_name != hd_name:
                retry_url = WIKI_IMAGE_BASE + quote(retry_name, safe="")
                try:
                    retry_response = requests.get(retry_url, timeout=REQUEST_TIMEOUT, stream=True)
                    if retry_response.status_code != 404:
                        retry_response.raise_for_status()
                        SHARED_DIR.mkdir(parents=True, exist_ok=True)
                        with open(retry_save_path, "wb") as f:
                            for chunk in retry_response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        return champion, skin_filename, True, "downloaded (retry shared)", "shared"
                except requests.RequestException as exc:
                    if retry_save_path.exists():
                        retry_save_path.unlink(missing_ok=True)
                    return champion, skin_filename, False, str(exc), ""

            # Retry 2: _old2 suffix on original name → OLD_DIR
            old2_url = WIKI_IMAGE_BASE + quote(old2_name, safe="")
            try:
                old2_response = requests.get(old2_url, timeout=REQUEST_TIMEOUT, stream=True)
                if old2_response.status_code == 404:
                    return champion, skin_filename, False, f"404 Not Found: {url}", ""
                old2_response.raise_for_status()
                OLD_DIR.mkdir(parents=True, exist_ok=True)
                with open(old2_save_path, "wb") as f:
                    for chunk in old2_response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return champion, skin_filename, True, "downloaded (retry old2)", "old"
            except requests.RequestException as exc:
                if old2_save_path.exists():
                    old2_save_path.unlink(missing_ok=True)
                return champion, skin_filename, False, str(exc), ""

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
    retried_old = 0

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
                elif retry_type == "old":
                    retried_old += 1
                    progress.update(
                        task,
                        description=f"[magenta]↺² {champion}/{skin}",
                    )
                elif retry_type == "shared":
                    retried_shared += 1
                    progress.update(
                        task,
                        description=f"[yellow]↺ {champion}/{skin}",
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
    console.print(f"  Retry 1    : [yellow]{retried_shared}[/] (saved to {SHARED_DIR}/)")
    console.print(f"  Retry 2    : [magenta]{retried_old}[/] (saved to {OLD_DIR}/)")
    console.print(f"  Skipped    : [dim]{skipped}[/] (already present)")
    console.print(f"  Failed     : [{'red' if failed else 'green'}]{len(failed)}[/]")
    if failed:
        console.print(f"\n[yellow]See {FAILED_DOWNLOADS_FILE} for details.[/]")


if __name__ == "__main__":
    main()
