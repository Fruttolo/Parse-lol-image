#!/usr/bin/env python3
"""
League of Legends Champion Splash Art Downloader

Fetches the champion list from Data Dragon (Riot's official CDN),
then retrieves splash art image names from the League of Legends Wiki API,
and downloads them locally.
"""

import argparse
import csv
import datetime
import hashlib
import os
import time
import re
import requests

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    MofNCompleteColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich import box

console = Console()

# ── Configuration ──────────────────────────────────────────────────────────────

DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
DDRAGON_CHAMPIONS_URL = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"
)

WIKI_API_URL = "https://wiki.leagueoflegends.com/en-us/api.php"
WIKI_IMAGE_BASE_URL = "https://wiki.leagueoflegends.com/en-us/images/"

OUTPUT_DIR = "splash_arts"
REQUEST_DELAY = 0.8   # seconds between requests (be polite to the servers)
REQUEST_TIMEOUT = 30  # seconds

# Only allow safe filenames (no path traversal)
SAFE_FILENAME_RE = re.compile(r"^[\w\s\(\)'\-\.]+$")


# ── Data fetching ───────────────────────────────────────────────────────────────

def get_champion_names() -> tuple[list[tuple[str, str]], str]:
    """Return a sorted list of (ddragon_key, display_name) for every champion."""
    r = requests.get(DDRAGON_VERSIONS_URL, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    version: str = r.json()[0]

    r = requests.get(
        DDRAGON_CHAMPIONS_URL.format(version=version), timeout=REQUEST_TIMEOUT
    )
    r.raise_for_status()
    data = r.json()

    champions = [
        (champ_id, info["name"])
        for champ_id, info in data["data"].items()
    ]
    return sorted(champions, key=lambda c: c[1]), version


def get_skin_images(champion_name: str, original_only: bool) -> list[str]:
    """
    Query the wiki API for the list of images on a champion's page and
    return only the splash-art filenames (those ending in 'Skin.jpg').

    If original_only is True, only the OriginalSkin image is returned.
    """
    params = {
        "action": "parse",
        "page": champion_name,
        "format": "json",
        "prop": "images",
    }
    r = requests.get(WIKI_API_URL, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    payload = r.json()

    if "error" in payload:
        return []

    images: list[str] = payload.get("parse", {}).get("images", [])
    skin_images = [img for img in images if img.lower().endswith("skin.jpg")]

    if original_only:
        skin_images = [img for img in skin_images if "Original" in img]

    return skin_images


def download_image(filename: str, output_path: str) -> None:
    """Download a single splash-art image from the wiki CDN."""
    url = WIKI_IMAGE_BASE_URL + requests.utils.quote(filename)
    r = requests.get(url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

    content_type = r.headers.get("Content-Type", "")
    if not content_type.startswith("image/"):
        raise ValueError(f"Unexpected content type: {content_type}")

    with open(output_path, "wb") as f:
        f.write(r.content)


# ── Hash report ────────────────────────────────────────────────────────────────

def compute_image_hashes(directory: str) -> dict[str, list[str]]:
    """Compute SHA-256 hashes for all .jpg files in *directory*.

    Returns a mapping ``{hash_hex: [filename, ...]}``.
    """
    hash_to_files: dict[str, list[str]] = {}
    for filename in sorted(os.listdir(directory)):
        if not filename.lower().endswith(".jpg"):
            continue
        filepath = os.path.join(directory, filename)
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                sha256.update(chunk)
        digest = sha256.hexdigest()
        hash_to_files.setdefault(digest, []).append(filename)
    return hash_to_files


def save_hash_report(directory: str = OUTPUT_DIR, output_csv: str = "image_hashes.csv") -> str:
    """Generate a CSV with each SHA-256 hash, count, and filenames."""
    hash_to_files = compute_image_hashes(directory)

    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["hash", "count", "filenames"])
        for digest, files in sorted(hash_to_files.items(), key=lambda x: -len(x[1])):
            writer.writerow([digest, len(files), "; ".join(files)])

    return output_csv


# ── Helpers ─────────────────────────────────────────────────────────────────────

def safe_filename(filename: str) -> str:
    """Validate an image filename from the wiki.

    Raises ValueError for suspicious names (e.g. path-traversal attempts).
    """
    base = os.path.basename(filename)
    if not SAFE_FILENAME_RE.match(base):
        raise ValueError(f"Unexpected filename from wiki: {filename!r}")
    return base


# ── Reports ─────────────────────────────────────────────────────────────────────

def save_merge_report(merges: list[dict], output_csv: str = "merge_report.csv") -> str:
    """Save a CSV listing every group of images fused during deduplication."""
    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["merged_name", "count", "originals"])
        for record in merges:
            writer.writerow([
                record["merged_name"],
                len(record["originals"]),
                "; ".join(record["originals"]),
            ])
    return output_csv


def save_champion_report(champ_stats: list[dict], output_csv: str = "champion_report.csv") -> str:
    """Save a per-champion CSV report with found/downloaded/skipped/failed counts."""
    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["champion", "found", "downloaded", "skipped", "failed"])
        for stats in champ_stats:
            writer.writerow([
                stats["champion"],
                stats["found"],
                stats["downloaded"],
                stats["skipped"],
                stats["failed"],
            ])
    return output_csv


# ── Deduplication ───────────────────────────────────────────────────────────────

def deduplicate_images(
    directory: str, progress: Progress, task_id
) -> tuple[int, list[dict]]:
    """Remove duplicate images in *directory*, keeping one file per hash group.

    Returns (number of files deleted, list of merge records).
    """
    hash_to_files = compute_image_hashes(directory)
    deleted = 0
    merges: list[dict] = []

    dup_groups = [(d, f) for d, f in hash_to_files.items() if len(f) >= 2]
    progress.update(task_id, total=max(len(dup_groups), 1), completed=0, visible=True)

    for i, (digest, files) in enumerate(dup_groups, start=1):
        stems = [os.path.splitext(f)[0] for f in sorted(files)]
        merged_name = "__".join(stems) + ".jpg"

        progress.update(
            task_id,
            description=f"[yellow]Fusione[/] {merged_name[:55]}",
            completed=i,
        )

        keep_path = os.path.join(directory, files[0])
        merged_path = os.path.join(directory, merged_name)
        os.rename(keep_path, merged_path)

        for duplicate in files[1:]:
            os.remove(os.path.join(directory, duplicate))
            deleted += 1

        merges.append({"merged_name": merged_name, "originals": sorted(files)})

    return deleted, merges


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="League of Legends Champion Splash Art Downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Esempi:\n"
            "  python parse.py            # scarica tutte le skin, rimuove duplicati\n"
            "  python parse.py -o         # scarica solo le skin originali\n"
            "  python parse.py -k         # mantiene i duplicati\n"
            "  python parse.py -o -k      # solo originali e mantiene i duplicati\n"
        ),
    )
    parser.add_argument(
        "-o",
        dest="original_only",
        action="store_true",
        default=False,
        help="Scarica solo le splash art originali (default: tutte le skin)",
    )
    parser.add_argument(
        "-k",
        dest="keep_duplicates",
        action="store_true",
        default=False,
        help="Mantieni i duplicati (default: elimina i duplicati)",
    )
    return parser.parse_args()


# ── Main ────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    original_only = args.original_only
    remove_duplicates = not args.keep_duplicates

    console.rule("[bold yellow]League of Legends Splash Art Downloader")
    console.print(
        f"  Modalità  : [bold]{'solo originali' if original_only else 'tutte le skin'}[/]\n"
        f"  Duplicati : [bold]{'da eliminare' if remove_duplicates else 'mantenuti (-k)'}[/]\n"
    )

    # ── Fetch champion list ────────────────────────────────────────────────────
    with console.status("[bold green]Recupero lista campioni da Data Dragon..."):
        champions, version = get_champion_names()
    console.print(f"  [green]✓[/] {len(champions)} campioni trovati (versione {version})\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Build the set of image stems already present (including merged files).
    covered_stems: set[str] = set()
    for fname in os.listdir(OUTPUT_DIR):
        if fname.lower().endswith(".jpg"):
            stem = os.path.splitext(fname)[0]
            for part in stem.split("__"):
                covered_stems.add(part)

    total_downloaded = 0
    total_skipped = 0
    total_failed = 0
    failed_items: list[tuple[str, str, str]] = []
    champ_stats: list[dict] = []

    # ── Main download loop ─────────────────────────────────────────────────────
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=35),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        champ_task = progress.add_task(
            "[bold green]Campioni", total=len(champions)
        )
        img_task = progress.add_task("[cyan]—", total=1, completed=0, visible=False)

        for champ_id, champ_name in champions:
            stats = {
                "champion": champ_name,
                "found": 0,
                "downloaded": 0,
                "skipped": 0,
                "failed": 0,
            }

            progress.update(
                champ_task,
                description=f"[bold green]{champ_name}[/] — wiki",
            )
            progress.update(img_task, visible=False, completed=0, total=1)

            # Fetch wiki skin list
            try:
                time.sleep(REQUEST_DELAY)
                skin_images = get_skin_images(champ_name, original_only=original_only)
            except requests.RequestException as exc:
                total_failed += 1
                stats["failed"] += 1
                failed_items.append((champ_name, "(wiki API)", str(exc)))
                champ_stats.append(stats)
                progress.advance(champ_task)
                continue

            if not skin_images:
                champ_stats.append(stats)
                progress.advance(champ_task)
                continue

            stats["found"] = len(skin_images)
            progress.update(img_task, total=len(skin_images), completed=0, visible=True)

            for img_idx, raw_filename in enumerate(skin_images, start=1):
                try:
                    filename = safe_filename(raw_filename)
                except ValueError as exc:
                    total_failed += 1
                    stats["failed"] += 1
                    failed_items.append((champ_name, raw_filename, str(exc)))
                    progress.update(img_task, completed=img_idx)
                    continue

                stem = os.path.splitext(filename)[0]

                progress.update(
                    img_task,
                    description=f"[cyan]{filename[:55]}",
                    completed=img_idx,
                )
                progress.update(
                    champ_task,
                    description=f"[bold green]{champ_name}[/] — {img_idx}/{len(skin_images)} immagini",
                )

                output_path = os.path.join(OUTPUT_DIR, filename)
                if os.path.exists(output_path) or stem in covered_stems:
                    total_skipped += 1
                    stats["skipped"] += 1
                    continue

                try:
                    time.sleep(REQUEST_DELAY)
                    download_image(filename, output_path)
                    total_downloaded += 1
                    stats["downloaded"] += 1
                    covered_stems.add(stem)
                except (requests.RequestException, ValueError, OSError) as exc:
                    total_failed += 1
                    stats["failed"] += 1
                    failed_items.append((champ_name, filename, str(exc)))

            champ_stats.append(stats)
            progress.advance(champ_task)

        # ── Deduplication ──────────────────────────────────────────────────────
        merges: list[dict] = []
        deleted = 0
        if remove_duplicates:
            progress.update(
                champ_task,
                description="[yellow]Rimozione duplicati...",
                visible=False,
            )
            progress.update(img_task, description="[yellow]Analisi hash...", visible=True)
            deleted, merges = deduplicate_images(OUTPUT_DIR, progress, img_task)

    # ── Summary table ──────────────────────────────────────────────────────────
    console.print()
    table = Table(
        title="Riepilogo", box=box.ROUNDED, show_header=True, header_style="bold magenta"
    )
    table.add_column("", style="dim")
    table.add_column("Valore", justify="right")
    table.add_row("Scaricate",    f"[green]{total_downloaded}[/]")
    table.add_row("Già presenti", f"[blue]{total_skipped}[/]")
    table.add_row("Errori",       f"[red]{total_failed}[/]")
    if remove_duplicates:
        table.add_row("File fusi",    str(deleted))
    table.add_row("Cartella",     os.path.abspath(OUTPUT_DIR))
    console.print(table)
    console.print()

    # ── Write reports ──────────────────────────────────────────────────────────
    if failed_items:
        report_path = "failed_downloads.txt"
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("=== Failed Downloads Report ===\n")
            f.write(f"Generated: {timestamp}\n")
            f.write(f"Total failures: {len(failed_items)}\n\n")
            for champ, filename, reason in failed_items:
                f.write(f"Champion : {champ}\n")
                f.write(f"File     : {filename}\n")
                f.write(f"Reason   : {reason}\n")
                f.write("-" * 60 + "\n")
        console.print(f"  [red]✗[/] Errori       → [bold]{os.path.abspath(report_path)}[/]")

    if remove_duplicates and merges:
        merge_csv = save_merge_report(merges)
        console.print(f"  [yellow]↻[/] Fusioni      → [bold]{os.path.abspath(merge_csv)}[/]")

    champ_csv = save_champion_report(champ_stats)
    console.print(f"  [blue]·[/] Campioni     → [bold]{os.path.abspath(champ_csv)}[/]")

    hash_csv = save_hash_report(OUTPUT_DIR)
    console.print(f"  [blue]·[/] Hash         → [bold]{os.path.abspath(hash_csv)}[/]")

    console.print()


if __name__ == "__main__":
    main()
