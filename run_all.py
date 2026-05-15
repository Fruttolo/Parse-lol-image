#!/usr/bin/env python3
"""
Wrapper per eseguire tutti gli script in sequenza.
"""

import subprocess
import sys
from pathlib import Path
from rich.console import Console

console = Console()

# Scripts da eseguire in ordine
SCRIPTS = [
    "list_champions.py",
    "parse_skin.py",
    "check_failed.py",
    "check_hashes.py",
    "compare.py",
]

# Script GUI da lanciare alla fine
GUI_SCRIPT = "viewer_differences.py"

WORKSPACE_DIR = Path(__file__).parent


def run_script(script_name: str) -> bool:
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
        result = subprocess.run(
            [sys.executable, str(script_path)],
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


def main() -> None:
    console.print("[bold magenta]═" * 30 + "[/]")
    console.print("[bold magenta]  WRAPPER - Esecuzione script LoL[/bold magenta]")
    console.print("[bold magenta]═" * 30 + "[/]")
    
    results: dict[str, bool] = {}
    
    for script_name in SCRIPTS:
        success = run_script(script_name)
        results[script_name] = success
        
        # Se uno script fallisce, chiedi conferma prima di continuare
        if not success:
            response = input("\n[yellow]Continuare con i prossimi script? (s/n):[/] ").strip().lower()
            if response != "s":
                console.print("[yellow]Esecuzione annullata.[/]")
                break
    
    # Report finale
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
        
        # Avvia direttamente la GUI
        console.print("[yellow]Avvio interfaccia grafica...[/]")
        gui_path = WORKSPACE_DIR / GUI_SCRIPT
        if gui_path.exists():
            try:
                subprocess.run([sys.executable, str(gui_path)], cwd=WORKSPACE_DIR)
            except Exception as e:
                console.print(f"[red]Errore nel lancio della GUI: {e}[/]")
        else:
            console.print(f"[red]File non trovato: {GUI_SCRIPT}[/]")
        
        sys.exit(0)
    else:
        console.print(f"[yellow]{total - successful} script hanno riscontrato errori.[/]")
        sys.exit(1)


if __name__ == "__main__":
    main()
