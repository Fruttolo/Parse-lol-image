#!/usr/bin/env python3
"""
League of Legends Champion Splash Art Downloader

Fetches the champion list from Data Dragon (Riot's official CDN),
then retrieves splash art image names from the League of Legends Wiki API,
and downloads them locally.
"""

import os
import time
import re
import requests

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

def get_champion_names() -> list[tuple[str, str]]:
    """Return a sorted list of (ddragon_key, display_name) for every champion."""
    print("Fetching champion list from Data Dragon...")
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
    print(f"Found {len(champions)} champions (version {version}).")
    return sorted(champions, key=lambda c: c[1])


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
        print(f"  Wiki API error: {payload['error'].get('info', 'unknown error')}")
        return []

    images: list[str] = payload.get("parse", {}).get("images", [])

    skin_images = [
        img for img in images if img.lower().endswith("skin.jpg")
    ]

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


# ── Helpers ─────────────────────────────────────────────────────────────────────

def safe_dirname(name: str) -> str:
    """
    Return a filesystem-safe version of a champion name by removing
    characters that are not letters, digits, spaces, hyphens or apostrophes.
    """
    safe = re.sub(r"[^\w\s'\-\.]", "_", name)
    return safe.strip()


def safe_filename(filename: str) -> str:
    """
    Validate that an image filename from the wiki contains only expected
    characters before using it to build a file path.

    Raises ValueError for suspicious names (e.g. path-traversal attempts).
    """
    # Strip any path components that might have snuck in
    base = os.path.basename(filename)
    if not SAFE_FILENAME_RE.match(base):
        raise ValueError(f"Unexpected filename from wiki: {filename!r}")
    return base


# ── Main ────────────────────────────────────────────────────────────────────────

def ask_update() -> bool:
    """Ask the user whether to update (download missing files).

    Returns True if the user wants to update, False to exit.
    """
    print("=== League of Legends Splash Art Downloader ===\n")
    while True:
        choice = (
            input(
                "Vuoi aggiornare? Controllerò i file già scaricati e scaricherò quelli mancanti.\n"
                "  Digita 'si' per aggiornare, 'no' per uscire: "
            )
            .strip()
            .lower()
        )
        if choice in ("si", "s", "yes", "y", "sì"):
            print()
            return True
        if choice in ("no", "n"):
            print("\nNessuna operazione eseguita. Uscita.")
            return False
        print("  Per favore digita 'si' o 'no'.\n")


def ask_download_mode() -> bool:
    """Ask the user whether to download only original skins or all skins.

    Returns True if original-only, False if all skins.
    """
    while True:
        choice = (
            input(
                "Download only original splash arts or all skins?\n"
                "  Type 'originali' for original only, 'tutte' for all: "
            )
            .strip()
            .lower()
        )
        if choice in ("originali", "o", "original", "originals"):
            print("\nMode: original splash arts only.\n")
            return True
        if choice in ("tutte", "t", "all", "skins"):
            print("\nMode: all skin splash arts.\n")
            return False
        print("  Please type 'originali' or 'tutte'.\n")


def main() -> None:
    if not ask_update():
        return

    original_only = ask_download_mode()
    champions = get_champion_names()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    total_downloaded = 0
    total_skipped = 0
    total_failed = 0
    failed_items: list[tuple[str, str, str]] = []  # (champion, filename, reason)

    for idx, (champ_id, champ_name) in enumerate(champions, start=1):
        print(f"[{idx:3}/{len(champions)}] {champ_name}")


        # Query the wiki API for skin images
        try:
            time.sleep(REQUEST_DELAY)
            skin_images = get_skin_images(champ_name, original_only=original_only)
        except requests.RequestException as exc:
            msg = f"Could not fetch wiki data: {exc}"
            print(f"  ✗ {msg}")
            total_failed += 1
            failed_items.append((champ_name, "(wiki API)", msg))
            continue

        if not skin_images:
            print(f"  — No splash arts found on wiki page.")
            continue

        print(f"  {len(skin_images)} splash art(s) found.")

        # Download each image
        for raw_filename in skin_images:
            try:
                filename = safe_filename(raw_filename)
            except ValueError as exc:
                msg = f"Unsafe filename: {exc}"
                print(f"  ✗ Skipping unsafe filename: {exc}")
                total_failed += 1
                failed_items.append((champ_name, raw_filename, msg))
                continue

            output_path = os.path.join(OUTPUT_DIR, filename)

            if os.path.exists(output_path):
                print(f"  ↷ {filename} (already exists, skipping)")
                total_skipped += 1
                continue

            try:
                time.sleep(REQUEST_DELAY)
                download_image(filename, output_path)
                print(f"  ✓ {filename}")
                total_downloaded += 1
            except (requests.RequestException, ValueError, OSError) as exc:
                msg = str(exc)
                print(f"  ✗ Failed to download {filename}: {msg}")
                total_failed += 1
                failed_items.append((champ_name, filename, msg))

    print(
        f"\n=== Done! ===\n"
        f"  Downloaded : {total_downloaded}\n"
        f"  Skipped    : {total_skipped}\n"
        f"  Failed     : {total_failed}\n"
        f"  Saved to   : {os.path.abspath(OUTPUT_DIR)}"
    )

    if failed_items:
        import datetime
        report_path = os.path.join(OUTPUT_DIR, "failed_downloads.txt")
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"=== Failed Downloads Report ===\n")
            f.write(f"Generated: {timestamp}\n")
            f.write(f"Total failures: {len(failed_items)}\n\n")
            for champ, filename, reason in failed_items:
                f.write(f"Champion : {champ}\n")
                f.write(f"File     : {filename}\n")
                f.write(f"Reason   : {reason}\n")
                f.write("-" * 60 + "\n")
        print(f"\n  Report errori salvato in: {os.path.abspath(report_path)}")


if __name__ == "__main__":
    main()
