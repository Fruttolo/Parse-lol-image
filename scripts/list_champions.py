#!/usr/bin/env python3
"""
Save the full League of Legends champion list (with splash art skins) to a text file.
"""

from pathlib import Path

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, MofNCompleteColumn

console = Console()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
DDRAGON_CHAMPIONS_URL = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"
)
WIKI_API_URL = "https://wiki.leagueoflegends.com/en-us/api.php"
REQUEST_TIMEOUT = 30
MAX_WORKERS = 2
OUTPUT_FILE = DATA_DIR / "champions.txt"

# escludi skin che contengono queste stringhe
EXCEPTIONS = [
    "(2022)",
    "Riven_ReignitedWorlds2012Skin",
]


def get_skin_filenames(champ_name: str) -> list[str]:
    """Return the wiki image filenames (e.g. 'Aatrox_OriginalSkin.jpg') for a champion."""
    params = {
        "action": "parse",
        "page": champ_name,
        "format": "json",
        "prop": "images",
    }
    r = requests.get(WIKI_API_URL, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    payload = r.json()

    if "error" in payload:
        return []

    images: list[str] = payload.get("parse", {}).get("images", [])
    
    # Filtra gli immagini che sono skin e non contengono stringhe di EXCEPTIONS
    filtered_images = []
    for img in images:
        if not img.lower().endswith("skin.jpg"):
            continue
        # Verifica che img non contenga nessuna delle stringhe in EXCEPTIONS
        if any(ex.lower() in img.lower() for ex in EXCEPTIONS):
            continue
        filtered_images.append(img)

    return filtered_images


def main() -> None:
    r = requests.get(DDRAGON_VERSIONS_URL, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    version: str = r.json()[0]

    r = requests.get(
        DDRAGON_CHAMPIONS_URL.format(version=version), timeout=REQUEST_TIMEOUT
    )
    r.raise_for_status()
    data = r.json()

    champions = sorted(
        ((champ_id, info["name"]) for champ_id, info in data["data"].items()),
        key=lambda c: c[1],
    )

    console.print(f"[green]✓[/] {len(champions)} champions found (version {version})")

    results: list[tuple[str, list[str]]] = [None] * len(champions)

    def fetch(index: int, champ_name: str) -> tuple[int, str, list[str]]:
        wiki_name = champ_name.split(" &")[0] if " &" in champ_name else champ_name
        try:
            skins = get_skin_filenames(wiki_name)
        except requests.RequestException:
            skins = []
        if " &" in champ_name:
            full_prefix = champ_name.replace(" ", "_") + "_"
            skins = [s for s in skins if not s.startswith(full_prefix)]
        return index, champ_name, skins

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=35),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[bold green]Fetching skins...", total=len(champions))
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(fetch, i, champ_name): champ_name
                for i, (_, champ_name) in enumerate(champions)
            }
            for future in as_completed(futures):
                index, champ_name, skins = future.result()
                results[index] = (champ_name, skins)
                progress.update(task, description=f"[bold green]{champ_name}")
                progress.advance(task)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"League of Legends champions — version {version}\n")
        f.write(f"Total: {len(champions)}\n")
        f.write("=" * 40 + "\n\n")
        for champ_name, skins in results:
            f.write(f"{champ_name}\n")
            if skins:
                for skin in skins:
                    f.write(f"  - {skin}\n")
            else:
                f.write("  (no skins found)\n")
            f.write("\n")

    console.print(f"[blue]·[/] Saved to [bold]{OUTPUT_FILE}[/]")


if __name__ == "__main__":
    main()
