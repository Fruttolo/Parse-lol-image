#!/usr/bin/env python3
"""
Resolve duplicate / similar splash arts by collapsing each group into a single
file inside splash_arts/SHARED/, named after data/shared_exceptions.json.

Reads:
    duplicate_images.txt  (hash groups, paths relative to splash_arts/)
    other_similar.txt     (similarity pairs, paths relative to repo root) — optional
    data/shared_exceptions.json  (Champion_SkinName_HD -> shared name)

For every cluster of duplicates/similars:
    - if at least one member is mapped in shared_exceptions and all mapped
      members agree on the same shared name, keep ONE file, copy it to
      SHARED/<clean(shared_name)>.jpg and delete the per-champion originals.
    - otherwise (no mapping, or conflicting mappings) the cluster is written to
      unresolved_duplicates.txt for manual review.

By default this acts (copies/deletes files). Pass --dry-run to preview only.

Usage:
    python scripts/resolve_duplicates.py [--dry-run] [--no-review]
        [--duplicates FILE] [--similar FILE] [--exceptions FILE]
        [--folder PATH] [--output FILE]
"""

import argparse
import json
import re
import shutil
from pathlib import Path

from rich.console import Console

console = Console()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SPLASH_ARTS_DIR = ROOT / "splash_arts"
SHARED_DIR = SPLASH_ARTS_DIR / "SHARED"

DEFAULT_DUPLICATES = ROOT / "duplicate_images.txt"
DEFAULT_SIMILAR = ROOT / "other_similar.txt"
DEFAULT_EXCEPTIONS = DATA_DIR / "shared_exceptions.json"
DEFAULT_OUTPUT = ROOT / "unresolved_duplicates.txt"

# Same junk pattern as parse_skin.py: _old, _old2, _unused, ...
_JUNK_RE = re.compile(r"_(old|unused)\d*", re.IGNORECASE)


def clean_skin_name(name: str) -> str:
    """Remove suffixes like _old, _old1, _unused from a skin name."""
    return _JUNK_RE.sub("", name)


# ── Cluster building (union-find) ────────────────────────────────────────────
class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[Path, Path] = {}

    def find(self, x: Path) -> Path:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: Path, b: Path) -> None:
        self.parent[self.find(b)] = self.find(a)

    def groups(self) -> list[list[Path]]:
        clusters: dict[Path, list[Path]] = {}
        for node in self.parent:
            clusters.setdefault(self.find(node), []).append(node)
        return [sorted(members) for members in clusters.values()]


def parse_duplicates(dup_file: Path, folder: Path, uf: UnionFind) -> None:
    """Add hash-duplicate groups from duplicate_images.txt to the union-find."""
    if not dup_file.exists():
        console.print(f"[yellow]⚠  {dup_file.name} not found — skipping.[/]")
        return

    current: list[Path] = []

    def flush() -> None:
        for p in current[1:]:
            uf.union(current[0], p)
        current.clear()

    for line in dup_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("hash "):
            flush()
        else:
            current.append((folder / line).resolve())
    flush()


def parse_similar(sim_file: Path, uf: UnionFind) -> None:
    """Add similarity pairs from other_similar.txt to the union-find."""
    if not sim_file.exists():
        console.print(f"[dim]{sim_file.name} not found — skipping similar pairs.[/]")
        return

    for line in sim_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "  vs  " not in line:
            continue
        # format: "<score>  <path_a>  vs  <path_b>"  (paths relative to ROOT)
        _, _, rest = line.partition("  ")
        a_str, _, b_str = rest.partition("  vs  ")
        a = (ROOT / a_str.strip()).resolve()
        b = (ROOT / b_str.strip()).resolve()
        uf.union(a, b)


# ── Resolution ───────────────────────────────────────────────────────────────
def resolve(
    clusters: list[list[Path]],
    exceptions: dict[str, str],
    apply: bool,
) -> list[list[Path]]:
    """
    Collapse resolvable clusters into SHARED/. Return the list of unresolved
    clusters (no mapping or conflicting mappings).
    """
    unresolved: list[list[Path]] = []
    resolved_count = 0
    deleted_count = 0

    SHARED_DIR.mkdir(parents=True, exist_ok=True)

    for members in clusters:
        # Map each member by its file stem (Champion_SkinName_HD).
        mapped: dict[Path, str] = {
            m: exceptions[m.stem] for m in members if m.stem in exceptions
        }
        shared_values = set(mapped.values())

        if len(shared_values) != 1:
            # 0 -> no member is a shared exception; >1 -> conflicting targets.
            unresolved.append(members)
            continue

        shared_name = next(iter(shared_values))
        target = SHARED_DIR / (clean_skin_name(shared_name) + ".jpg")

        # Pick the source to keep: prefer a mapped member that exists on disk.
        existing = [m for m in members if m.exists()]
        source = next((m for m in mapped if m.exists()), None)
        if source is None:
            source = existing[0] if existing else None

        rel_target = target.relative_to(ROOT)
        console.print(
            f"[magenta]🔗 SHARED[/] [cyan]{rel_target}[/] "
            f"[dim]({len(members)} files)[/]"
        )

        if source is None:
            console.print(
                f"   [yellow]no source file on disk; "
                f"will only delete remaining originals[/]"
            )

        # Copy one file into SHARED (unless already there).
        if source is not None and not target.exists():
            if apply:
                shutil.copy2(source, target)
            console.print(f"   keep [green]{source.relative_to(ROOT)}[/] → {rel_target}")
        elif target.exists():
            console.print(f"   [dim]{rel_target} already exists[/]")

        # Delete every per-champion original.
        for m in existing:
            if apply:
                m.unlink(missing_ok=True)
            deleted_count += 1
            console.print(f"   [red]✗ delete[/] {m.relative_to(ROOT)}")

        resolved_count += 1

    mode = "[green]APPLIED[/]" if apply else "[yellow]DRY RUN[/]"
    console.print(
        f"\n{mode}  resolved [bold]{resolved_count}[/] clusters, "
        f"deleted [bold]{deleted_count}[/] originals, "
        f"[bold]{len(unresolved)}[/] unresolved."
    )
    return unresolved


def _save_exceptions(exceptions: dict[str, str], path: Path) -> None:
    """Write the shared_exceptions mapping back to disk (sorted, pretty)."""
    path.write_text(
        json.dumps(exceptions, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ── Tema GUI (allineato a scripts/check_failed.py) ───────────────────────────
BG_DARK = "#1a1a2e"
BG_CARD = "#16213e"
BG_HOVER = "#0f3460"
BG_SEL = "#1b4332"
ACCENT = "#e94560"
GREEN = "#4CAF50"
MUTED = "#a8a8b3"
WHITE = "#ffffff"

BIG_W, BIG_H = 900, 506  # single big preview 16:9


class ClusterReviewApp:
    """
    Window showing one unresolved cluster at a time. A single large image is
    shown; left/right arrows cycle through the cluster members. The currently
    displayed image is the selection. Bottom buttons:
      - "Keep → SHARED": prompts for a skin name, copies the displayed image to
        SHARED/<name>_HD.jpg, deletes the other cluster members, and maps every
        member stem to <name>_HD in shared_exceptions.json.
      - "Skip": leaves the cluster untouched.
    """

    def __init__(
        self,
        unresolved: list[list[Path]],
        exceptions: dict[str, str],
        exceptions_path: Path,
    ) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.unresolved = unresolved
        self.exceptions = exceptions
        self.exceptions_path = exceptions_path
        self.idx = 0

        self._photo_ref = None  # keep a ref so Tk doesn't GC the image
        self._cur = 0  # index of the currently displayed member

        self.root = tk.Tk()
        self.root.title("Resolve duplicates — Selettore cluster")
        self.root.configure(bg=BG_DARK)
        self.root.minsize(1100, 780)

        self._build_ui()
        self.root.after(50, self._render_cluster)

    # ── Layout ────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        tk = self.tk
        ttk = self.ttk

        # Header
        header = tk.Frame(self.root, bg=BG_CARD, pady=6)
        header.pack(fill="x")
        self._title_var = tk.StringVar(value="Caricamento...")
        tk.Label(header, textvariable=self._title_var,
                 font=("Helvetica", 14, "bold"), fg=ACCENT, bg=BG_CARD).pack()
        self._progress_var = tk.StringVar()
        tk.Label(header, textvariable=self._progress_var,
                 font=("Helvetica", 10), fg=MUTED, bg=BG_CARD).pack()

        # Single big preview with left/right arrows
        cand_outer = tk.Frame(self.root, bg=BG_DARK)
        cand_outer.pack(fill="both", expand=True, padx=12, pady=(4, 0))

        viewer = tk.Frame(cand_outer, bg=BG_DARK)
        viewer.pack(fill="both", expand=True)

        arrow_kw = dict(font=("Helvetica", 28, "bold"), fg=WHITE, bg=BG_CARD,
                        activebackground=BG_HOVER, activeforeground=WHITE,
                        relief="flat", width=2, cursor="hand2")
        tk.Button(viewer, text="‹", command=self._prev, **arrow_kw
                  ).pack(side="left", fill="y", padx=(0, 8))
        tk.Button(viewer, text="›", command=self._next, **arrow_kw
                  ).pack(side="right", fill="y", padx=(8, 0))

        self._img_lbl = tk.Label(viewer, bg=BG_CARD)
        self._img_lbl.pack(side="left", fill="both", expand=True)

        # Name of the currently displayed image
        self._name_var = tk.StringVar()
        tk.Label(cand_outer, textvariable=self._name_var,
                 font=("Helvetica", 10, "bold"), fg=WHITE, bg=BG_DARK,
                 pady=4).pack()

        # Arrow keys also navigate
        self.root.bind("<Left>", lambda _e: self._prev())
        self.root.bind("<Right>", lambda _e: self._next())

        # Bottom buttons (centered)
        bottom = tk.Frame(self.root, bg=BG_CARD, pady=10)
        bottom.pack(fill="x", side="bottom")
        btn_row = tk.Frame(bottom, bg=BG_CARD)
        btn_row.pack(anchor="center")
        tk.Button(btn_row, text="✔  Tieni → SHARED", command=self._on_keep,
                  font=("Helvetica", 11, "bold"), fg=WHITE, bg=GREEN,
                  activebackground="#388E3C", activeforeground=WHITE,
                  relief="flat", padx=18, pady=8, cursor="hand2",
                  ).pack(side="left", padx=6)
        tk.Button(btn_row, text="→  Salta", command=self._skip,
                  font=("Helvetica", 11), fg=WHITE, bg="#555577",
                  activebackground="#444466", activeforeground=WHITE,
                  relief="flat", padx=18, pady=8, cursor="hand2",
                  ).pack(side="left", padx=6)
        self._status_var = tk.StringVar()
        tk.Label(bottom, textvariable=self._status_var,
                 font=("Helvetica", 10), fg=MUTED, bg=BG_CARD,
                 ).pack(pady=(4, 0))

    # ── Render cluster ──────────────────────────────────────────────────────────
    def _render_cluster(self) -> None:
        members = self.unresolved[self.idx]
        self._title_var.set(f"Cluster {self.idx + 1} / {len(self.unresolved)}")
        self._progress_var.set(f"{len(members)} immagini")
        self._status_var.set("")
        self._cur = 0
        self._show_current()

    def _show_current(self) -> None:
        """Render the currently displayed cluster member in the big preview."""
        from PIL import Image, ImageTk

        members = self.unresolved[self.idx]
        m = members[self._cur]

        try:
            resample = Image.Resampling.LANCZOS
        except AttributeError:
            resample = Image.LANCZOS  # type: ignore[attr-defined]

        try:
            img = Image.open(m)
            img.thumbnail((BIG_W, BIG_H), resample)
            photo = ImageTk.PhotoImage(img)
            self._photo_ref = photo
            self._img_lbl.configure(image=photo, text="")
        except Exception as exc:  # missing / unreadable file
            self._photo_ref = None
            self._img_lbl.configure(
                image="", text=f"[illeggibile]\n{exc}", fg=ACCENT,
                font=("Helvetica", 12), width=60, height=20)

        self._name_var.set(
            f"{m.stem}    ·    {self._cur + 1} / {len(members)}")

    # ── Navigazione ─────────────────────────────────────────────────────────────
    def _prev(self) -> None:
        members = self.unresolved[self.idx]
        self._cur = (self._cur - 1) % len(members)
        self._show_current()

    def _next(self) -> None:
        members = self.unresolved[self.idx]
        self._cur = (self._cur + 1) % len(members)
        self._show_current()

    # ── Azioni ──────────────────────────────────────────────────────────────────
    def _next_cluster(self) -> None:
        self.idx += 1
        if self.idx >= len(self.unresolved):
            self.root.destroy()
        else:
            self._render_cluster()

    def _on_keep(self) -> None:
        from tkinter import messagebox, simpledialog

        members = self.unresolved[self.idx]
        chosen = members[self._cur]
        if not chosen.exists():
            messagebox.showerror("Errore", f"File scelto mancante:\n{chosen}")
            return

        name = simpledialog.askstring(
            "Nome skin",
            "Nome skin condivisa (senza _HD):",
            initialvalue=clean_skin_name(chosen.stem).removesuffix("_HD"),
            parent=self.root,
        )
        if not name:
            return  # annullato — resta sul cluster
        name = name.strip().removesuffix("_HD")
        shared_value = f"{name}_HD"
        target = SHARED_DIR / (clean_skin_name(shared_value) + ".jpg")

        # Conferma se quel nome è già usato come mappatura condivisa da stem
        # diversi da quelli di questo cluster.
        member_stems = {m.stem for m in members}
        if any(
            v == shared_value and k not in member_stems
            for k, v in self.exceptions.items()
        ) and not messagebox.askyesno(
            "Nome già usato",
            f'"{shared_value}" è già usato come mappatura condivisa.\n'
            f"Usarlo comunque per questo cluster?",
        ):
            return

        if target.exists() and not messagebox.askyesno(
            "Sovrascrivere?", f"{target.name} esiste già. Sovrascrivere?"
        ):
            return

        # Copy chosen image into SHARED, delete the per-champion originals.
        shutil.copy2(chosen, target)
        for m in members:
            if m.exists():
                m.unlink()
            self.exceptions[m.stem] = shared_value
        _save_exceptions(self.exceptions, self.exceptions_path)

        console.print(
            f"[magenta]🔗 SHARED[/] [cyan]{target.relative_to(ROOT)}[/] "
            f"← tenuto [green]{chosen.stem}[/], mappati {len(members)} stem"
        )
        self._next_cluster()

    def _skip(self) -> None:
        console.print(f"[yellow]→[/] Saltato cluster {self.idx + 1}")
        self._next_cluster()

    def run(self) -> None:
        self.root.mainloop()


def review_unresolved(
    unresolved: list[list[Path]],
    exceptions: dict[str, str],
    exceptions_path: Path,
) -> None:
    """Open the cluster-review GUI for the unresolved clusters."""
    if not unresolved:
        console.print("[green]No unresolved clusters to review.[/]")
        return

    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    ClusterReviewApp(unresolved, exceptions, exceptions_path).run()
    console.print("[green]Review finished.[/]")


def write_unresolved(unresolved: list[list[Path]], output: Path) -> None:
    """Write the unresolved clusters report."""
    lines = [
        "=== Unresolved Duplicates ===",
        f"Total clusters: {len(unresolved)}",
        "(no shared_exceptions mapping, or conflicting mappings)",
        "",
    ]
    for i, members in enumerate(unresolved, 1):
        lines.append(f"# cluster {i} ({len(members)} files)")
        for m in members:
            try:
                rel = m.relative_to(ROOT)
            except ValueError:
                rel = m
            lines.append(str(rel))
        lines.append("")

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(f"Wrote unresolved report to [cyan]{output.relative_to(ROOT)}[/]")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve duplicate/similar splash arts into SHARED/",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't touch files; just report (default: apply)")
    parser.add_argument("--duplicates", type=Path, default=DEFAULT_DUPLICATES,
                        help="Hash-duplicate groups file")
    parser.add_argument("--similar", type=Path, default=DEFAULT_SIMILAR,
                        help="Similarity pairs file (optional)")
    parser.add_argument("--no-similar", action="store_true",
                        help="Ignore the similar pairs file (use only hash duplicates)")
    parser.add_argument("--exceptions", type=Path, default=DEFAULT_EXCEPTIONS,
                        help="shared_exceptions.json mapping")
    parser.add_argument("--folder", type=Path, default=SPLASH_ARTS_DIR,
                        help="Base folder for duplicate_images.txt paths")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Unresolved clusters report")
    parser.add_argument("--no-review", action="store_true",
                        help="Skip the manual review window (default: open it to "
                             "resolve clusters — copies to SHARED + updates exceptions)")
    args = parser.parse_args()

    if not args.exceptions.exists():
        console.print(f"[red]Exceptions file not found:[/] {args.exceptions}")
        raise SystemExit(1)
    exceptions: dict[str, str] = json.loads(args.exceptions.read_text(encoding="utf-8"))
    console.print(f"Loaded [bold]{len(exceptions)}[/] shared exceptions")

    uf = UnionFind()
    parse_duplicates(args.duplicates, args.folder, uf)
    if args.no_similar:
        console.print("[dim]--no-similar: skipping similar pairs.[/]")
    else:
        parse_similar(args.similar, uf)

    clusters = uf.groups()
    console.print(f"Built [bold]{len(clusters)}[/] duplicate/similar clusters\n")

    apply = not args.dry_run
    if not apply:
        console.print("[yellow]DRY RUN — omit --dry-run to copy/delete files.[/]\n")

    unresolved = resolve(clusters, exceptions, apply)
    write_unresolved(unresolved, args.output)

    if not args.no_review:
        review_unresolved(unresolved, exceptions, args.exceptions)


if __name__ == "__main__":
    main()
