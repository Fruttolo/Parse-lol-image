import filecmp
import os

# --- CONFIGURAZIONE ---
percorso_a = "/home/salvo/Immagini/splash_arts_lol"
percorso_b = "/home/salvo/Progetti/Parse-lol-image/splash_arts"
nome_report = "differenze_cartelle.txt"

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
    if os.path.exists(percorso_a) and os.path.exists(percorso_b):
        confronta_cartelle(percorso_a, percorso_b, nome_report)
    else:
        print("Errore: Uno o entrambi i percorsi non esistono.")