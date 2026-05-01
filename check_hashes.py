import hashlib
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

SPLASH_DIR = os.path.join(os.path.dirname(__file__), "splash_arts")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "duplicate_images.txt")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_WORKERS = 16

console = Console()


def hash_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_images() -> list[str]:
    paths = []
    for root, _, files in os.walk(SPLASH_DIR):
        for filename in files:
            if os.path.splitext(filename)[1].lower() in IMAGE_EXTENSIONS:
                paths.append(os.path.join(root, filename))
    return paths


def find_duplicates(image_paths: list[str]) -> dict[str, list[str]]:
    hash_map: dict[str, list[str]] = defaultdict(list)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Hashing immagini...", total=len(image_paths))

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(hash_file, p): p for p in image_paths}
            for future in as_completed(futures):
                path = futures[future]
                file_hash = future.result()
                hash_map[file_hash].append(os.path.basename(path))
                progress.advance(task)

    return {h: names for h, names in hash_map.items() if len(names) > 1}


def write_output(duplicates: dict[str, list[str]]) -> None:
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for file_hash, names in duplicates.items():
            f.write(f"hash {file_hash}\n")
            for name in names:
                f.write(f"{name}\n")
            f.write("\n")


def main() -> None:
    console.print(f"[bold]Scanning:[/bold] {SPLASH_DIR}")
    image_paths = collect_images()
    console.print(f"Trovate [cyan]{len(image_paths)}[/cyan] immagini.")

    duplicates = find_duplicates(image_paths)

    if not duplicates:
        console.print("[green]Nessun duplicato trovato.[/green]")
        return

    write_output(duplicates)
    total_files = sum(len(v) for v in duplicates.values())
    console.print(
        f"[yellow]Trovati {len(duplicates)} gruppi di duplicati "
        f"({total_files} file totali).[/yellow]"
    )
    console.print(f"Risultati salvati in: [bold]{OUTPUT_FILE}[/bold]")


if __name__ == "__main__":
    main()
