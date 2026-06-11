#!/usr/bin/env python3
"""
Find duplicate images in splash_arts using perceptual hash + histogram correlation.

Usage:
    python scripts/find_duplicates.py [--folder PATH] [--threshold FLOAT] [--output FILE] [--workers N] [--no-gpu]

Similarity score is in [0, 1]: 1 = identical, 0 = completely different.
Score = 55% phash + 45% histogram correlation (same as check_failed.py).
If imagehash is not installed, score = histogram correlation only.
GPU (CuPy) is used automatically when available; pass --no-gpu to force CPU.

Install GPU support: pip install cupy-cuda12x
"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import ModuleType

import numpy as np
from PIL import Image
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn

try:
    import imagehash as _imagehash  # type: ignore[import-untyped]
    _HAS_IMAGEHASH: bool = True
except ImportError:
    _imagehash = None  # type: ignore[assignment]
    _HAS_IMAGEHASH = False

console = Console()
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FOLDER = ROOT / "splash_arts"
HIST_RESIZE = (200, 112)

try:
    _RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:
    _RESAMPLE = Image.LANCZOS  # type: ignore[attr-defined]


def _init_gpu(force_cpu: bool) -> tuple[ModuleType, bool]:
    """Return (array_module, using_gpu). Falls back to numpy on any error."""
    if force_cpu:
        return np, False
    try:
        import cupy as cp  # type: ignore[import-untyped]
        cp.array([1.0])    # trigger device init to surface errors early
        return cp, True
    except Exception:
        return np, False


def load_image_features(path: Path) -> tuple[Path, np.ndarray | None, np.ndarray, float]:
    """Load image and compute (phash bits, centered histogram, histogram norm)."""
    img = Image.open(path).convert("RGB")

    phash_bits: np.ndarray | None = None
    if _HAS_IMAGEHASH:
        phash_bits = _imagehash.phash(img).hash.flatten().astype(np.uint8)  # type: ignore[union-attr]

    resized = img.resize(HIST_RESIZE, _RESAMPLE)
    hist = np.array(resized.histogram(), dtype=np.float32)  # 768 values (256 bins × 3 channels)
    centered = hist - hist.mean()
    norm = float(np.linalg.norm(centered))

    return path, phash_bits, centered, norm


def compute_scores(
    xp: ModuleType,
    hist_centered: list[np.ndarray],
    hist_norms: list[float],
    phash_arrays: list[np.ndarray],
) -> np.ndarray:
    """
    Vectorized pairwise similarity matrix on xp (cupy or numpy).
    Returns a plain numpy (N, N) float32 array.
    """
    # ── Histogram Pearson correlation ────────────────────────────────────────
    H = xp.stack([xp.asarray(h) for h in hist_centered])        # (N, 768)
    safe_norms = xp.where(
        xp.array(hist_norms, dtype=xp.float32) > 0,
        xp.array(hist_norms, dtype=xp.float32),
        xp.float32(1.0),
    )
    H_norm = H / safe_norms[:, xp.newaxis]                      # (N, 768) unit vectors
    corr = H_norm @ H_norm.T                                     # (N, N)
    hist_sim = (corr + xp.float32(1.0)) / xp.float32(2.0)       # [-1,1] → [0,1]

    # ── Phash Hamming similarity ─────────────────────────────────────────────
    if _HAS_IMAGEHASH and phash_arrays:
        P = xp.stack([xp.asarray(p) for p in phash_arrays]).astype(xp.int16)  # (N, 64)
        row_sums = P.sum(axis=1)                                 # (N,)
        dot = P @ P.T                                            # (N, N)
        hamming = row_sums[:, xp.newaxis] + row_sums[xp.newaxis, :] - 2 * dot
        phash_sim = xp.maximum(xp.float32(0.0), xp.float32(1.0) - hamming / xp.float32(32.0))
        score_matrix = xp.float32(0.55) * phash_sim + xp.float32(0.45) * hist_sim
    else:
        score_matrix = hist_sim

    # Transfer back to CPU if on GPU
    if hasattr(score_matrix, "get"):
        score_matrix = score_matrix.get()
    return np.asarray(score_matrix, dtype=np.float32)


DEFAULT_KNOWN_DUPLICATES = ROOT / "duplicate_images.txt"


def load_known_duplicate_paths(dup_file: Path, folder: Path) -> set[Path]:
    """
    Parse duplicate_images.txt and return the set of paths to exclude.
    For each hash group, keep the first path and exclude the rest.
    """
    excluded: set[Path] = set()
    if not dup_file.exists():
        return excluded

    current_group: list[Path] = []
    for line in dup_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            if len(current_group) > 1:
                excluded.update(current_group[1:])
            current_group = []
        elif line.startswith("hash "):
            if len(current_group) > 1:
                excluded.update(current_group[1:])
            current_group = []
        else:
            current_group.append((folder / line).resolve())
    if len(current_group) > 1:
        excluded.update(current_group[1:])
    return excluded


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find duplicate images in splash_arts",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER,
                        help="Folder to scan recursively")
    parser.add_argument("--threshold", type=float, default=0.95,
                        help="Minimum similarity score (0=different, 1=identical)")
    parser.add_argument("--output", type=Path, default=ROOT / "other_similar.txt",
                        help="Write results to this file (one pair per line)")
    parser.add_argument("--workers", type=int, default=8,
                        help="Parallel workers for image loading")
    parser.add_argument("--no-gpu", action="store_true",
                        help="Force CPU even if CuPy is available")
    parser.add_argument("--known-duplicates", type=Path, default=DEFAULT_KNOWN_DUPLICATES,
                        help="File with known hash-duplicate groups to skip (default: duplicate_images.txt)")
    args = parser.parse_args()

    xp, using_gpu = _init_gpu(args.no_gpu)
    backend = f"[green]GPU (CuPy)[/]" if using_gpu else "[dim]CPU (numpy)[/]"
    console.print(f"Backend: {backend}")

    if not _HAS_IMAGEHASH:
        console.print(
            "[yellow]⚠  imagehash not installed — using histogram only.[/]\n"
            "[dim]   Install with: pip install imagehash[/]"
        )

    folder: Path = args.folder
    if not folder.exists():
        console.print(f"[red]Folder not found:[/] {folder}")
        sys.exit(1)

    images = sorted(
        p for p in folder.rglob("*")
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    n = len(images)
    console.print(f"Found [bold]{n}[/] images in [cyan]{folder}[/]")

    excluded = load_known_duplicate_paths(args.known_duplicates, folder)
    if excluded:
        before = len(images)
        images = [p for p in images if p.resolve() not in excluded]
        console.print(
            f"Skipped [bold]{before - len(images)}[/] known hash-duplicates "
            f"([dim]{args.known_duplicates.name}[/])"
        )
        n = len(images)
    if n < 2:
        console.print("[yellow]Need at least 2 images to compare.[/]")
        return

    # ── Load features in parallel (CPU) ──────────────────────────────────────
    paths: list[Path] = []
    phash_list: list[np.ndarray] = []
    hist_centered_list: list[np.ndarray] = []
    hist_norms: list[float] = []
    errors = 0

    with Progress(
        SpinnerColumn(), "[progress.description]{task.description}",
        BarColumn(), TaskProgressColumn(), TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Loading features...", total=n)
        with ThreadPoolExecutor(max_workers=args.workers) as exe:
            futures = {exe.submit(load_image_features, p): p for p in images}
            for fut in as_completed(futures):
                try:
                    path, phash_bits, centered, norm = fut.result()
                    paths.append(path)
                    if phash_bits is not None:
                        phash_list.append(phash_bits)
                    hist_centered_list.append(centered)
                    hist_norms.append(norm)
                except Exception as e:
                    errors += 1
                    console.print(f"[dim]Error {futures[fut].name}: {e}[/]")
                progress.advance(task)

    loaded = len(paths)
    console.print(
        f"Loaded [bold]{loaded}[/] images"
        + (f" ([red]{errors} errors[/])" if errors else "")
        + f". Comparing [bold]{loaded * (loaded - 1) // 2:,}[/] pairs..."
    )

    # ── Vectorized pairwise similarity (GPU or CPU) ───────────────────────────
    with console.status("Computing similarity matrix..."):
        score_matrix = compute_scores(xp, hist_centered_list, hist_norms, phash_list)

    # ── Find pairs above threshold (upper triangle) ───────────────────────────
    mask = np.triu(score_matrix >= args.threshold, k=1)
    i_idx, j_idx = np.where(mask)
    scores = score_matrix[i_idx, j_idx]

    order = np.argsort(scores)[::-1]
    i_idx, j_idx, scores = i_idx[order], j_idx[order], scores[order]

    console.print(
        f"\nFound [bold]{len(scores)}[/] duplicate pairs "
        f"(threshold=[yellow]{args.threshold:.2f}[/])\n"
    )

    lines: list[str] = []
    for i, j, s in zip(i_idx, j_idx, scores):
        pa = paths[i].relative_to(ROOT)
        pb = paths[j].relative_to(ROOT)
        line = f"{s:.4f}  {pa}  vs  {pb}"
        lines.append(line)
        console.print(f"[yellow]{s:.1%}[/]  [cyan]{pa}[/]  vs  [green]{pb}[/]")

    if not lines:
        console.print("[dim]No duplicates found.[/]")

    if args.output:
        args.output.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        console.print(f"\nSaved to [cyan]{args.output}[/]")


if __name__ == "__main__":
    main()
