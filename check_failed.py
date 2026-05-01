#!/usr/bin/env python3
"""
Per ogni download fallito in failed_downloads.txt:
  1. Scarica l'immagine non-HD dal wiki come riferimento
  2. Chiama wiki API (?action=parse&prop=images) per ottenere tutte le
     immagini .jpg della pagina del campione
  3. Scarica i candidati in parallelo (con cache)
  4. Confronto con phash (imagehash) + correlazione istogramma
  5. Mostra GUI con candidati ordinati per somiglianza decrescente
  6. L'utente clicca il preferito → salvato in alternatives/{Champion}/
"""

import io
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional, cast
from urllib.parse import quote

import json
import requests
from PIL import Image, ImageTk
from rich.console import Console

try:
    import imagehash as _imagehash  # type: ignore[import-untyped]
    _HAS_IMAGEHASH: bool = True
except ImportError:
    _imagehash = None  # type: ignore[assignment]
    _HAS_IMAGEHASH = False

console = Console()

FAILED_DOWNLOADS_FILE = "failed_downloads.txt"
SHARED_EXCEPTIONS_FILE = Path("shared_exceptions.json")
ALTERNATIVES_DIR = Path("alternatives")
WIKI_IMAGE_BASE = "https://wiki.leagueoflegends.com/en-us/images/"
WIKI_API_URL    = "https://wiki.leagueoflegends.com/en-us/api.php"
REQUEST_TIMEOUT = 30
MAX_CANDIDATES  = 25   # quanti candidati mostrare al massimo
MAX_DL_WORKERS  = 8    # download paralleli

THUMB_W, THUMB_H = 240, 135   # thumbnail 16:9
COLS = 3

# ── Tema ────────────────────────────────────────────────────────────────────────
BG_DARK = "#1a1a2e"
BG_CARD = "#16213e"
BG_HOVER = "#0f3460"
BG_SEL  = "#1b4332"
ACCENT  = "#e94560"
GREEN   = "#4CAF50"
MUTED   = "#a8a8b3"
WHITE   = "#ffffff"

# ── Cache thread-safe: filename → Image | None, + raw bytes ──────────────────
_img_cache:  dict[str, Optional[Image.Image]] = {}
_raw_cache:  dict[str, bytes] = {}
_cache_lock  = threading.Lock()


# ─── Parsing failed_downloads.txt ────────────────────────────────────────────

def parse_failed_downloads(filepath: str) -> list[dict]:
    """Restituisce lista di {champion, file} da failed_downloads.txt."""
    entries: list[dict] = []
    current: dict = {}
    with open(filepath, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip()
            if line.startswith("Champion :"):
                current["champion"] = line.split(":", 1)[1].strip()
            elif line.startswith("File     :"):
                current["file"] = line.split(":", 1)[1].strip()
            elif line.startswith("---"):
                if "champion" in current and "file" in current:
                    entries.append(current)
                current = {}
    if "champion" in current and "file" in current:
        entries.append(current)
    return entries


# ─── Wiki API ────────────────────────────────────────────────────────────────



def get_wiki_jpg_images(filename: str) -> list[str]:
    """Chiama l'API wiki e restituisce tutti i .jpg listati nella pagina File:<filename>."""
    params = {
        "action": "parse",
        "page": f"File:{filename}",
        "format": "json",
        "prop": "images",
    }
    try:
        r = requests.get(WIKI_API_URL, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []
    if "error" in data:
        return []
    images: list[str] = data.get("parse", {}).get("images", [])
    return [img for img in images if img.lower().endswith(".jpg")]


def get_image_infos(filenames: list[str]) -> dict[str, dict]:
    """Fetch width/height for a list of wiki image filenames (batch, ≤50 per request)."""
    result: dict[str, dict] = {}
    BATCH = 50
    for i in range(0, len(filenames), BATCH):
        batch = filenames[i : i + BATCH]
        titles = "|".join(f"File:{name}" for name in batch)
        params = {
            "action": "query",
            "format": "json",
            "titles": titles,
            "prop": "imageinfo",
            "iiprop": "size",
        }
        try:
            r = requests.get(WIKI_API_URL, params=params, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception:
            continue
        for page in data.get("query", {}).get("pages", {}).values():
            if "imageinfo" not in page:
                continue
            # wiki normalises spaces↔underscores; normalise back with replace
            fname = page["title"].removeprefix("File:").replace(" ", "_")
            info = page["imageinfo"][0]
            result[fname] = {
                "width": info.get("width", 0),
                "height": info.get("height", 0),
            }
    return result


# ─── Download con cache ──────────────────────────────────────────────────────

def _download_wiki_image(filename: str) -> Optional[Image.Image]:
    """Scarica e mette in cache un'immagine dal wiki."""
    with _cache_lock:
        if filename in _img_cache:
            return _img_cache[filename]

    url = WIKI_IMAGE_BASE + quote(filename, safe="()")
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        raw = r.content
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        img = None
        raw = b""

    with _cache_lock:
        _img_cache[filename] = img
        if raw:
            _raw_cache[filename] = raw
    return img


# ─── Similarità ─────────────────────────────────────────────────────────────

def _phash_sim(a: Image.Image, b: Image.Image) -> float:
    """Similarità strutturale via perceptual hash [0,1]."""
    if not _HAS_IMAGEHASH:
        return 0.5
    try:
        h1 = _imagehash.phash(a)  # type: ignore[union-attr]
        h2 = _imagehash.phash(b)  # type: ignore[union-attr]
        return max(0.0, 1.0 - (h1 - h2) / 32.0)
    except Exception:
        return 0.5


def _hist_sim(a: Image.Image, b: Image.Image) -> float:
    """Correlazione istogramma RGB normalizzata [0,1]."""
    try:
        resample = Image.Resampling.LANCZOS
    except AttributeError:
        resample = Image.LANCZOS  # type: ignore[attr-defined]
    size = (200, 112)
    ha = a.resize(size, resample).histogram()
    hb = b.resize(size, resample).histogram()
    n = len(ha)
    ma, mb = sum(ha) / n, sum(hb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ha, hb))
    da = sum((x - ma) ** 2 for x in ha) ** 0.5
    db = sum((y - mb) ** 2 for y in hb) ** 0.5
    if da == 0 or db == 0:
        return 0.0
    return (num / (da * db) + 1) / 2


def compute_similarity(ref: Image.Image, cand: Image.Image) -> float:
    """Score combinato: 55% phash + 45% istogramma."""
    p = _phash_sim(ref, cand)
    h = _hist_sim(ref, cand)
    return 0.55 * p + 0.45 * h if _HAS_IMAGEHASH else h


# ─── GUI ─────────────────────────────────────────────────────────────────────

class SkinSelectorApp:
    def __init__(self, entries: list[dict]) -> None:
        self.entries = entries
        self.idx = 0

        self.root = tk.Tk()
        self.root.title("Check Failed Downloads — Selettore skin")
        self.root.configure(bg=BG_DARK)
        self.root.minsize(960, 640)

        self._photo_refs: list[ImageTk.PhotoImage] = []
        self._ref_photo: Optional[ImageTk.PhotoImage] = None
        self._card_frames: list[tk.Frame] = []
        self._spinner_lbl: Optional[tk.Label] = None

        self._sel_wiki_name: Optional[str] = None
        self._sel_image: Optional[Image.Image] = None

        self._current_champion = ""
        self._current_target_hd = ""

        self._build_ui()
        self.root.after(100, self._load_entry)

    # ── Layout ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Header
        header = tk.Frame(self.root, bg=BG_CARD, pady=6)
        header.pack(fill="x")
        self._title_var = tk.StringVar(value="Caricamento...")
        tk.Label(header, textvariable=self._title_var,
                 font=("Helvetica", 14, "bold"), fg=ACCENT, bg=BG_CARD).pack()
        self._progress_var = tk.StringVar()
        tk.Label(header, textvariable=self._progress_var,
                 font=("Helvetica", 10), fg=MUTED, bg=BG_CARD).pack()

        # Main
        main = tk.Frame(self.root, bg=BG_DARK)
        main.pack(fill="both", expand=True, padx=12, pady=8)

        # Sinistra — riferimento
        ref_panel = tk.Frame(main, bg=BG_CARD)
        ref_panel.pack(side="left", fill="y", padx=(0, 10))
        tk.Label(ref_panel, text="Riferimento (non-HD)",
                 font=("Helvetica", 10, "bold"), fg=MUTED, bg=BG_CARD, pady=6).pack()
        self._ref_img_lbl = tk.Label(ref_panel, bg=BG_HOVER,
                                      width=THUMB_W, height=THUMB_H)
        self._ref_img_lbl.pack(padx=8, pady=(0, 4))
        self._ref_name_var = tk.StringVar()
        tk.Label(ref_panel, textvariable=self._ref_name_var,
                 font=("Helvetica", 8), fg=MUTED, bg=BG_CARD,
                 wraplength=THUMB_W + 10).pack(padx=8, pady=(0, 4))
        self._loading_var = tk.StringVar()
        tk.Label(ref_panel, textvariable=self._loading_var,
                 font=("Helvetica", 9), fg=ACCENT, bg=BG_CARD,
                 wraplength=THUMB_W + 10).pack(padx=8, pady=(0, 8))

        # Destra — candidati scrollabili
        cand_outer = tk.Frame(main, bg=BG_DARK)
        cand_outer.pack(side="left", fill="both", expand=True)
        tk.Label(cand_outer, text="Candidati dal wiki — clicca per selezionare",
                 font=("Helvetica", 10, "bold"), fg=MUTED, bg=BG_DARK, pady=4).pack()

        canvas_frame = tk.Frame(cand_outer, bg=BG_DARK)
        canvas_frame.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(canvas_frame, bg=BG_DARK, highlightthickness=0)
        vsb = ttk.Scrollbar(canvas_frame, orient="vertical",
                             command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._scroll_frame = tk.Frame(self._canvas, bg=BG_DARK)
        self._canvas_win = self._canvas.create_window(
            (0, 0), window=self._scroll_frame, anchor="nw")
        self._scroll_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(
                scrollregion=self._canvas.bbox("all")))
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfig(self._canvas_win, width=e.width))
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self._canvas.bind_all(ev, self._on_mousewheel)

        # Bottom
        bottom = tk.Frame(self.root, bg=BG_CARD, pady=8)
        bottom.pack(fill="x", side="bottom")
        tk.Button(bottom, text="✓  Conferma selezione", command=self._confirm,
                  font=("Helvetica", 11, "bold"), fg=WHITE, bg=GREEN,
                  activebackground="#388E3C", activeforeground=WHITE,
                  relief="flat", padx=18, pady=7, cursor="hand2",
                  ).pack(side="left", padx=(12, 8))
        tk.Button(bottom, text="→  Salta", command=self._skip,
                  font=("Helvetica", 11), fg=WHITE, bg="#555577",
                  activebackground="#444466", activeforeground=WHITE,
                  relief="flat", padx=18, pady=7, cursor="hand2",
                  ).pack(side="left")
        tk.Button(bottom, text="🔗  SHARED", command=self._flag_shared,
                  font=("Helvetica", 11, "bold"), fg=WHITE, bg="#7b2d8b",
                  activebackground="#5a1f66", activeforeground=WHITE,
                  relief="flat", padx=18, pady=7, cursor="hand2",
                  ).pack(side="left", padx=(8, 0))
        self._status_var = tk.StringVar()
        tk.Label(bottom, textvariable=self._status_var,
                 font=("Helvetica", 10), fg=MUTED, bg=BG_CARD,
                 ).pack(side="right", padx=14)

    # ── Caricamento entry ────────────────────────────────────────────────────

    def _load_entry(self) -> None:
        if self.idx >= len(self.entries):
            messagebox.showinfo(
                "Completato",
                f"Tutti i {len(self.entries)} entry sono stati processati.")
            self.root.quit()
            return

        entry = self.entries[self.idx]
        champion: str = entry["champion"]
        filename: str = entry["file"]
        target_hd = Path(filename).stem + "_HD.jpg"

        self._current_champion = champion
        self._current_target_hd = target_hd
        self._sel_wiki_name = None
        self._sel_image = None

        self._title_var.set(f"{champion}  —  {filename}")
        self._progress_var.set(f"Entry {self.idx + 1} di {len(self.entries)}")
        self._ref_name_var.set(filename)
        self._loading_var.set("⏳ Caricamento...")
        self._ref_img_lbl.configure(image="", text="…")
        self._status_var.set("")
        self._clear_candidates()
        self._show_spinner("Recupero immagini dal wiki…")
        self.root.update()

        threading.Thread(
            target=self._background_load,
            args=(champion, filename),
            daemon=True,
        ).start()

    # ── Background load ──────────────────────────────────────────────────────

    def _background_load(self, champion: str, filename: str) -> None:
        # 1. Riferimento non-HD
        ref_img = _download_wiki_image(filename)

        # 2. Lista immagini wiki — ora query sulla pagina File:<filename>
        self.root.after(0, lambda: self._loading_var.set(
            "⏳ Lista immagini wiki…"))
        candidates_names = [
            n for n in get_wiki_jpg_images(filename)
            if n.replace(" ", "_") != filename.replace(" ", "_")
        ]
        total = len(candidates_names)

        # 3. Download parallelo candidati + fetch info dimensioni
        downloaded: list[tuple[str, Image.Image]] = []

        def _dl(name: str) -> tuple[str, Optional[Image.Image]]:
            return name, _download_wiki_image(name)

        with ThreadPoolExecutor(max_workers=MAX_DL_WORKERS) as exe:
            futures = {exe.submit(_dl, n): n for n in candidates_names}
            done = 0
            for fut in as_completed(futures):
                done += 1
                name, img = fut.result()
                if img is not None:
                    downloaded.append((name, img))
                d, t = done, total
                self.root.after(0, lambda d=d, t=t:
                                self._loading_var.set(f"⏳ {d}/{t} scaricate…"))

        # 4. Fetch risoluzione immagini
        self.root.after(0, lambda: self._loading_var.set("⏳ Recupero risoluzioni…"))
        image_infos = get_image_infos(candidates_names)

        # 5. Calcola similarità e ordina
        self.root.after(0, lambda: self._loading_var.set("⏳ Calcolo similarità…"))
        scored: list[tuple[float, str, Image.Image, int, int]] = []
        for name, img in downloaded:
            score = compute_similarity(ref_img, img) if ref_img else 0.0
            info = image_infos.get(name, {})
            w, h = info.get("width", 0), info.get("height", 0)
            scored.append((score, name, img, w, h))
        scored.sort(key=lambda t: t[0], reverse=True)

        self.root.after(
            0, self._on_load_done, ref_img, scored[:MAX_CANDIDATES], filename)

    def _on_load_done(
        self,
        ref_img: Optional[Image.Image],
        candidates: list[tuple[float, str, Image.Image, int, int]],
        filename: str,
    ) -> None:
        self._loading_var.set("")

        if ref_img is not None:
            self._ref_photo = ImageTk.PhotoImage(self._make_thumb(ref_img))
            self._ref_img_lbl.configure(image=self._ref_photo, text="")
        else:
            self._ref_img_lbl.configure(image="", text="Non disponibile", fg=MUTED)
            self._ref_photo = None

        self._build_candidates(candidates)
        note = "  ⚠ ref non trovata sul wiki" if ref_img is None else ""
        self._status_var.set(f"{len(candidates)} candidato/i trovati{note}")

    # ── Spinner ──────────────────────────────────────────────────────────────

    def _show_spinner(self, msg: str) -> None:
        if self._spinner_lbl is not None:
            self._spinner_lbl.destroy()
        self._spinner_lbl = tk.Label(
            self._scroll_frame, text=f"⏳  {msg}",
            font=("Helvetica", 12), fg=MUTED, bg=BG_DARK, pady=40)
        self._spinner_lbl.grid(row=0, column=0, columnspan=COLS)

    # ── Griglia candidati ────────────────────────────────────────────────────

    def _clear_candidates(self) -> None:
        if self._spinner_lbl is not None:
            self._spinner_lbl.destroy()
            self._spinner_lbl = None
        for w in self._card_frames:
            w.destroy()
        self._card_frames.clear()
        self._photo_refs.clear()

    def _build_candidates(
        self, candidates: list[tuple[float, str, Image.Image, int, int]]
    ) -> None:
        self._clear_candidates()

        if not candidates:
            self._spinner_lbl = tk.Label(
                self._scroll_frame,
                text="Nessuna immagine .jpg trovata nella pagina wiki.",
                font=("Helvetica", 11), fg=MUTED, bg=BG_DARK, pady=20)
            self._spinner_lbl.grid(row=0, column=0)
            return

        for col in range(COLS):
            self._scroll_frame.columnconfigure(col, weight=1)

        for i, (score, name, img, w, h) in enumerate(candidates):
            row, col = divmod(i, COLS)
            is_hd = "_hd." in name.lower()
            card = tk.Frame(
                self._scroll_frame, bg=BG_CARD, relief="flat",
                cursor="hand2", highlightthickness=2,
                highlightbackground=BG_CARD)
            card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")

            photo = ImageTk.PhotoImage(self._make_thumb(img))
            self._photo_refs.append(photo)

            img_lbl = tk.Label(card, image=photo, bg=BG_CARD)
            img_lbl.pack()

            name_lbl = tk.Label(card, text=name,
                                 font=("Helvetica", 8), fg=MUTED, bg=BG_CARD,
                                 wraplength=THUMB_W + 10)
            name_lbl.pack()

            score_lbl = tk.Label(card, text=f"Similarità: {score:.1%}",
                                  font=("Helvetica", 9, "bold"), fg=ACCENT,
                                  bg=BG_CARD, pady=2)
            score_lbl.pack()

            res_text = f"{w}×{h}" if (w and h) else "—"
            if is_hd:
                hd_lbl = tk.Label(card, text=f"★ HD  {res_text}",
                                   font=("Helvetica", 9, "bold"),
                                   fg="#00d4ff", bg=BG_CARD, pady=2)
            else:
                hd_lbl = tk.Label(card, text=res_text,
                                   font=("Helvetica", 9), fg=MUTED,
                                   bg=BG_CARD, pady=2)
            hd_lbl.pack()

            for widget in (card, img_lbl, name_lbl, score_lbl, hd_lbl):
                widget.bind(
                    "<Button-1>",
                    lambda _e, n=name, im=img, c=card: self._select(n, im, c))

            self._card_frames.append(card)

        self._canvas.yview_moveto(0)

    # ── Selezione ────────────────────────────────────────────────────────────

    def _select(self, name: str, img: Image.Image, card: tk.Frame) -> None:
        for w in self._card_frames:
            w.configure(highlightbackground=BG_CARD)  # type: ignore[call-arg]
            for child in w.winfo_children():
                try:
                    cast(tk.Widget, child).configure(bg=BG_CARD)  # type: ignore[call-arg]
                except tk.TclError:
                    pass
            try:
                w.configure(bg=BG_CARD)  # type: ignore[call-arg]
            except tk.TclError:
                pass

        card.configure(bg=BG_SEL, highlightbackground=GREEN,  # type: ignore[call-arg]
                       highlightthickness=2)
        for child in card.winfo_children():
            try:
                cast(tk.Widget, child).configure(bg=BG_SEL)  # type: ignore[call-arg]
            except tk.TclError:
                pass

        self._sel_wiki_name = name
        self._sel_image = img
        self._status_var.set(f"✓ Selezionato: {name}")

    # ── Azioni ───────────────────────────────────────────────────────────────

    def _confirm(self) -> None:
        if self._sel_wiki_name is None or self._sel_image is None:
            messagebox.showwarning(
                "Nessuna selezione",
                "Clicca su un'immagine prima di confermare.")
            return

        dest_dir = ALTERNATIVES_DIR / self._current_champion
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / self._current_target_hd

        # Salva i byte originali per non perdere qualità JPEG
        raw = _raw_cache.get(self._sel_wiki_name)
        if raw:
            dest.write_bytes(raw)
        else:
            self._sel_image.save(str(dest), format="JPEG", quality=95)

        console.print(
            f"[green]✓[/] [bold]{self._current_champion}[/]  "
            f"{self._sel_wiki_name} → {dest}")
        self._status_var.set(f"Salvato → {dest}")
        self.root.update()

        self.idx += 1
        self.root.after(200, self._load_entry)

    def _flag_shared(self) -> None:
        if self._sel_wiki_name is None or self._sel_image is None:
            messagebox.showwarning(
                "Nessuna selezione",
                "Clicca su un'immagine prima di flaggare come SHARED.")
            return

        # Salva in alternatives/SHARED/ con il nome del file wiki selezionato
        dest_dir = ALTERNATIVES_DIR / "SHARED"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / self._sel_wiki_name
        raw = _raw_cache.get(self._sel_wiki_name)
        if raw:
            dest.write_bytes(raw)
        else:
            self._sel_image.save(str(dest), format="JPEG", quality=95)

        # Aggiorna shared_exceptions.json
        original_key = Path(self._current_target_hd).stem
        shared_value = Path(self._sel_wiki_name).stem
        exceptions: dict = {}
        if SHARED_EXCEPTIONS_FILE.exists():
            try:
                exceptions = json.loads(SHARED_EXCEPTIONS_FILE.read_text(encoding="utf-8"))
            except Exception:
                exceptions = {}
        exceptions[original_key] = shared_value
        SHARED_EXCEPTIONS_FILE.write_text(
            json.dumps(exceptions, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )

        console.print(
            f"[magenta]🔗[/] [bold]{self._current_champion}[/]  "
            f"{original_key} → [bold]SHARED[/] {shared_value}")
        self._status_var.set(f"SHARED: {original_key} → {shared_value}")
        self.root.update()

        self.idx += 1
        self.root.after(200, self._load_entry)

    def _skip(self) -> None:
        console.print(
            f"[yellow]→[/] Saltato: "
            f"{self._current_champion} / {self._current_target_hd}")
        self.idx += 1
        self._load_entry()

    # ── Utilità ──────────────────────────────────────────────────────────────

    def _make_thumb(self, img: Image.Image) -> Image.Image:
        try:
            resample = Image.Resampling.LANCZOS
        except AttributeError:
            resample = Image.LANCZOS  # type: ignore[attr-defined]
        thumb = img.copy()
        thumb.thumbnail((THUMB_W, THUMB_H), resample)
        return thumb

    def _on_mousewheel(self, event: tk.Event) -> None:
        if event.num == 4 or event.delta > 0:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:
            self._canvas.yview_scroll(1, "units")

    def run(self) -> None:
        self.root.mainloop()


# ─── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    entries = parse_failed_downloads(FAILED_DOWNLOADS_FILE)
    if not entries:
        console.print("[yellow]Nessun entry trovato in failed_downloads.txt[/]")
        return

    if not _HAS_IMAGEHASH:
        console.print(
            "[yellow]⚠  imagehash non installato — "
            "installa con: pip install imagehash[/]\n"
            "[dim]  Verrà usata solo la correlazione istogramma.[/]")

    console.print(f"[green]✓[/] {len(entries)} download falliti da esaminare")
    SkinSelectorApp(entries).run()


if __name__ == "__main__":
    main()
