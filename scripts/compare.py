import argparse
import filecmp
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

parser = argparse.ArgumentParser(description="Confronta due cartelle di splash arts")
parser.add_argument("percorso_a", help="Percorso della cartella A (splash arts locali)")
args = parser.parse_args()

percorso_a = args.percorso_a
percorso_b = str(ROOT / "splash_arts")
nome_report = str(ROOT / "differenze_cartelle.txt")

def confronta_cartelle(path1, path2, report_file):
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("="*60 + "\n")
        f.write(f"REPORT CONFRONTO NOMI\n")
        f.write(f"Cartella A: {path1}\n")
        f.write(f"Cartella B: {path2}\n")
        f.write("="*60 + "\n\n")
        
        _analizza_ottimizzato(path1, path2, f)
    
    print(f"Confronto completato. Report salvato in: {report_file}")

def _analizza_ottimizzato(dir1, dir2, f_report):
    comparatore = filecmp.dircmp(dir1, dir2)
    
    # Usiamo un buffer per accumulare le differenze di questa specifica cartella
    buffer_testo = ""
    
    if comparatore.left_only:
        buffer_testo += f"--- MANCANTI IN B (Presenti in: {dir1}) ---\n"
        for item in sorted(comparatore.left_only):
            buffer_testo += f"  -- {item}\n"
            
    if comparatore.right_only:
        # Aggiunge una riga vuota tra le due sezioni solo se la prima esiste
        if buffer_testo: buffer_testo += "\n"
        buffer_testo += f"--- MANCANTI IN A (Presenti in: {dir2}) ---\n"
        for item in sorted(comparatore.right_only):
            buffer_testo += f"  -- {item}\n"

    # Scriviamo nel file SOLO se il buffer non è vuoto
    if buffer_testo:
        f_report.write(buffer_testo)
        f_report.write("\n" + "."*30 + "\n\n") # Separatore tra cartelle diverse

    # Ricorsione sulle sottocartelle comuni
    for nome_sub in sorted(comparatore.subdirs.keys()):
        _analizza_ottimizzato(
            os.path.join(dir1, nome_sub),
            os.path.join(dir2, nome_sub),
            f_report
        )

if __name__ == "__main__":
    if not os.path.exists(percorso_a):
        parser.error(f"Il percorso A non esiste: {percorso_a}")
    if not os.path.exists(percorso_b):
        parser.error(f"Il percorso B non esiste: {percorso_b}")
    confronta_cartelle(percorso_a, percorso_b, nome_report)