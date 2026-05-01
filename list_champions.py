#!/usr/bin/env python3
"""
Save the full League of Legends champion list (with splash art skins) to a text file.
"""

import time
import requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, MofNCompleteColumn

console = Console()

DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
DDRAGON_CHAMPIONS_URL = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"
)
WIKI_API_URL = "https://wiki.leagueoflegends.com/en-us/api.php"
REQUEST_TIMEOUT = 30
REQUEST_DELAY = 0.8
OUTPUT_FILE = "champions.txt"


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
    return [img for img in images if img.lower().endswith("skin.jpg") and "(2022)" not in img]


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

    results: list[tuple[str, list[str]]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=35),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[bold green]Fetching skins...", total=len(champions))
        for champ_id, champ_name in champions:
            progress.update(task, description=f"[bold green]{champ_name}")
            try:
                time.sleep(REQUEST_DELAY)
                wiki_name = champ_name.split(" &")[0] if " &" in champ_name else champ_name
                skins = get_skin_filenames(wiki_name)
            except requests.RequestException:
                skins = []
            results.append((champ_name, skins))
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
