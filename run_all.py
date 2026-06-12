#!/usr/bin/env python3
"""
Wrapper per eseguire tutti gli script in sequenza.
"""

import argparse
import subprocess
import sys
from pathlib import Path
from rich.console import Console

console = Console()

parser = argparse.ArgumentParser(description="Esegue tutti gli script LoL in sequenza")
parser.add_argument("splash_arts_path", nargs="?", default=None,
                    help="Percorso della cartella locale di splash arts (opzionale). "
                         "Se omesso, compare e viewer vengono saltati.")
parser.add_argument("--quick-scan", action="store_true",
                    help="Salta find_similar (scansione immagini simili).")
cli_args = parser.parse_args()

# Scripts da eseguire in ordine
SCRIPTS_PRE = [
    "scripts/list_champions.py",
]

# check_hashes / find_similar / resolve_duplicates sono gestiti nel loop
# dedup (run_dedup_loop). Qui restano solo gli script che girano dopo.
SCRIPTS_POST: list[str] = []

if cli_args.splash_arts_path:
    SCRIPTS_POST.append("scripts/compare.py")

# Script GUI da lanciare alla fine
GUI_SCRIPT = "scripts/viewer_differences.py"

WORKSPACE_DIR = Path(__file__).parent

REPORT_FILES = [
    "failed_downloads.txt",
    "duplicate_images.txt",
    "other_similar.txt",
    "differenze_cartelle.txt",
    "download_report.txt",
    "unresolved_duplicates.txt",
]


def cleanup_reports() -> None:
    for filename in REPORT_FILES:
        path = WORKSPACE_DIR / filename
        if path.exists():
            path.unlink()
            console.print(f"[dim]Eliminato: {filename}[/]")


def check_non_404_failures() -> None:
    """Block execution if failed_downloads.txt contains non-404 failures."""
    failed_file = WORKSPACE_DIR / "failed_downloads.txt"
    if not failed_file.exists():
        return
    non_404: list[str] = []
    for line in failed_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("Reason   :"):
            reason = line[len("Reason   :"):].strip()
            if not reason.startswith("404"):
                non_404.append(reason)
    if non_404:
        console.print("\n[bold red]✗ Download falliti per motivi diversi dalla 404:[/]")
        for r in non_404:
            console.print(f"  [red]{r}[/]")
        console.print(
            "\n[bold yellow]Riprova il download prima di continuare "
            "(potrebbe essere un problema di rete temporaneo).[/]"
        )
        sys.exit(1)


def run_script(script_name: str, extra_args: list[str] | None = None) -> bool:
    """
    Esegue uno script e ritorna True se ha successo, False altrimenti.
    """
    script_path = WORKSPACE_DIR / script_name

    if not script_path.exists():
        console.print(f"[red]✗[/] {script_name}: file non trovato")
        return False

    console.print(f"\n[bold cyan]→ Esecuzione: {script_name}[/bold cyan]")
    console.print("-" * 60)

    try:
        cmd = [sys.executable, str(script_path)] + (extra_args or [])
        result = subprocess.run(
            cmd,
            cwd=WORKSPACE_DIR,
            check=False,
        )
        
        if result.returncode == 0:
            console.print(f"[green]✓[/] {script_name} completato con successo")
            return True
        else:
            console.print(f"[red]✗[/] {script_name} terminato con errore (exit code: {result.returncode})")
            return False
            
    except Exception as e:
        console.print(f"[red]✗[/] {script_name}: eccezione — {e}")
        return False


def _print_report(results: dict[str, bool]) -> None:
    console.print(f"\n[bold magenta]═" * 30 + "[/]")
    console.print("[bold]Report finale:[/]")
    console.print("[bold magenta]═" * 30 + "[/]")

    for script_name, success in results.items():
        status = "[green]✓ OK[/]" if success else "[red]✗ ERRORE[/]"
        console.print(f"  {script_name:<20} {status}")

    total = len(results)
    successful = sum(1 for s in results.values() if s)
    console.print(f"\n[bold]Risultato: {successful}/{total} script completati con successo[/]")

    if successful == total:
        console.print("[green][bold]Tutti gli script eseguiti correttamente![/bold][/]")

        if not cli_args.splash_arts_path:
            console.print("[dim]Percorso splash arts non specificato: confronto saltato.[/]")
        else:
            diff_file = WORKSPACE_DIR / "differenze_cartelle.txt"
            has_differences = diff_file.exists() and "MANCANTI" in diff_file.read_text(encoding="utf-8")

            if not has_differences:
                console.print("[green]Nessuna differenza trovata tra le cartelle. Interfaccia grafica non avviata.[/]")
            else:
                console.print("[yellow]Avvio interfaccia grafica...[/]")
                gui_path = WORKSPACE_DIR / GUI_SCRIPT
                if gui_path.exists():
                    try:
                        subprocess.run(
                            [sys.executable, str(gui_path), cli_args.splash_arts_path],
                            cwd=WORKSPACE_DIR,
                        )
                    except Exception as e:
                        console.print(f"[red]Errore nel lancio della GUI: {e}[/]")
                else:
                    console.print(f"[red]File non trovato: {GUI_SCRIPT}[/]")

        sys.exit(0)
    else:
        console.print(f"[yellow]{total - successful} script hanno riscontrato errori.[/]")
        sys.exit(1)


def has_failed_downloads() -> bool:
    failed_file = WORKSPACE_DIR / "failed_downloads.txt"
    if not failed_file.exists():
        return False
    text = failed_file.read_text(encoding="utf-8")
    return any(line.startswith("Champion :") for line in text.splitlines())


def count_hash_duplicates() -> int:
    """Numero di file con hash uguale elencati in duplicate_images.txt."""
    dup_file = WORKSPACE_DIR / "duplicate_images.txt"
    if not dup_file.exists():
        return 0
    return sum(
        1 for line in dup_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("hash ")
    )


def has_similar() -> bool:
    """True se other_similar.txt contiene almeno una coppia di immagini simili."""
    sim_file = WORKSPACE_DIR / "other_similar.txt"
    if not sim_file.exists():
        return False
    return any("  vs  " in line for line in sim_file.read_text(encoding="utf-8").splitlines())


def _run_check_hashes(results: dict[str, bool]) -> bool | None:
    """
    Esegue check_hashes ripulendo prima lo stale report. Ritorna True/False per
    successo dello script, None se lo script è fallito (chiamante deve uscire).
    """
    # check_hashes scrive duplicate_images.txt SOLO se trova duplicati:
    # rimuovi lo stale così il conteggio riflette la scansione corrente.
    dup_file = WORKSPACE_DIR / "duplicate_images.txt"
    if dup_file.exists():
        dup_file.unlink()

    if not run_script("scripts/check_hashes.py"):
        results["scripts/check_hashes.py"] = False
        return None
    results["scripts/check_hashes.py"] = True
    return True


def run_dedup_loop(results: dict[str, bool]) -> bool:
    """
    find_similar gira UNA SOLA volta all'inizio (sotto flag). check_hashes →
    resolve_duplicates viene poi ripetuto finché restano file con hash uguale;
    dalla seconda passata in poi si guarda SOLO il report degli hash. Ritorna
    False se uno script fallisce.
    """
    # 1. Prima passata hash
    if _run_check_hashes(results) is None:
        return False

    # 2. find_similar una sola volta (salvo --quick-scan)
    sim = False
    if not cli_args.quick_scan:
        if not run_script("scripts/find_similar.py"):
            results["scripts/find_similar.py"] = False
            return False
        results["scripts/find_similar.py"] = True
        sim = has_similar()

    dup_count = count_hash_duplicates()

    # 3. Niente hash né similar → finito
    if dup_count == 0 and not sim:
        console.print("[green]Nessun duplicato/simile residuo.[/]")
        return True

    console.print(
        f"\n[bold yellow]⚠ Trovati duplicati/simili "
        f"(hash: {dup_count}, similar: {'sì' if sim else 'no'}) — avvio resolve_duplicates...[/]"
    )
    if not run_script("scripts/resolve_duplicates.py"):
        results["scripts/resolve_duplicates.py"] = False
        return False
    results["scripts/resolve_duplicates.py"] = True

    # 4-6. Loop SOLO hash: ricontrolla, risolvi finché il report hash è vuoto.
    iteration = 1
    prev_dup_count = -1
    while True:
        iteration += 1
        console.print(f"\n[bold yellow]↺ Ricontrollo hash (passo {iteration})[/]")

        if _run_check_hashes(results) is None:
            return False

        dup_count = count_hash_duplicates()

        # 6. Report hash vuoto → avanti
        if dup_count == 0:
            console.print("[green]Nessun hash duplicato residuo.[/]")
            break

        # Stallo: resolve non ha ridotto gli hash duplicati → evita loop infinito
        # (es. cluster saltati nella review).
        if dup_count == prev_dup_count:
            console.print(
                f"[yellow]⚠ {dup_count} file con hash uguale ancora presenti ma "
                f"resolve_duplicates non li ha ridotti — interrompo per evitare un loop.[/]"
            )
            break
        prev_dup_count = dup_count

        # 5. Trovati hash → resolve → torna al ricontrollo
        console.print(
            f"\n[bold yellow]⚠ {dup_count} file con hash uguale — avvio resolve_duplicates...[/]"
        )
        if not run_script("scripts/resolve_duplicates.py"):
            results["scripts/resolve_duplicates.py"] = False
            return False
        results["scripts/resolve_duplicates.py"] = True

    return True


def main() -> None:
    console.print("[bold magenta]═" * 30 + "[/]")
    console.print("[bold magenta]  WRAPPER - Esecuzione script LoL[/bold magenta]")
    console.print("[bold magenta]═" * 30 + "[/]")

    cleanup_reports()

    results: dict[str, bool] = {}

    for script_name in SCRIPTS_PRE:
        success = run_script(script_name)
        results[script_name] = success
        if not success:
            _print_report(results)
            return

    # Loop parse_skin → check_failed finché ci sono failed downloads
    iteration = 0
    while True:
        iteration += 1
        if iteration > 1:
            console.print(f"\n[bold yellow]↺ Retry parse_skin (tentativo {iteration})[/]")
        success = run_script("scripts/parse_skin.py")
        results["scripts/parse_skin.py"] = success

        if not success:
            _print_report(results)
            return

        check_non_404_failures()

        if not has_failed_downloads():
            break

        console.print("\n[bold yellow]⚠ Failed downloads presenti — avvio check_failed...[/]")
        cf_success = run_script("scripts/check_failed.py")
        results["scripts/check_failed.py"] = cf_success
        if not cf_success:
            _print_report(results)
            return

    # Loop check_hashes/find_similar → resolve_duplicates finché ci sono hash uguali
    if not run_dedup_loop(results):
        _print_report(results)
        return

    for script_name in SCRIPTS_POST:
        extra = [cli_args.splash_arts_path] if script_name == "scripts/compare.py" else None
        success = run_script(script_name, extra)
        results[script_name] = success

    _print_report(results)


if __name__ == "__main__":
    main()
