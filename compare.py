import filecmp
import os

def confronta_cartelle(path1, path2, report_file):
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"REPORT DIFFERENZE\n")
        f.write(f"Cartella 1: {path1}\n")
        f.write(f"Cartella 2: {path2}\n")
        f.write("-" * 30 + "\n\n")
        
        _analizza_ricorsivamente(path1, path2, f)
    
    print(f"Confronto completato. Risultati salvati in: {report_file}")

def _analizza_ricorsivamente(dir1, dir2, f_report):
    # Confronta le due directory correnti
    comparatore = filecmp.dircmp(dir1, dir2)
    
    # 1. File o cartelle presenti solo in una delle due parti
    if comparatore.left_only:
        f_report.write(f"[SOLO IN {dir1}]:\n")
        for item in comparatore.left_only:
            f_report.write(f" - {item}\n")
            
    if comparatore.right_only:
        f_report.write(f"[SOLO IN {dir2}]:\n")
        for item in comparatore.right_only:
            f_report.write(f" - {item}\n")
            
    # 2. File con lo stesso nome ma contenuto diverso
    if comparatore.diff_files:
        f_report.write(f"[FILE DIFFERENTI] in {dir1} e {dir2}:\n")
        for item in comparatore.diff_files:
            f_report.write(f" - {item}\n")
            
    # 3. File che non è stato possibile confrontare (es. permessi negati)
    if comparatore.funny_files:
        f_report.write(f"[ERRORE CONFRONTO] su questi file:\n")
        for item in comparatore.funny_files:
            f_report.write(f" - {item}\n")

    f_report.write("\n")

    # Ricorsione: entra nelle sottocartelle comuni per continuare il confronto
    for nome_subfolder, sub_comparatore in comparatore.subdirs.items():
        _analizza_ricorsivamente(
            os.path.join(dir1, nome_subfolder),
            os.path.join(dir2, nome_subfolder),
            f_report
        )

# --- CONFIGURAZIONE ---
percorso_a = "/home/salvo/Immagini/splash_arts_lol"
percorso_b = "/home/salvo/Progetti/Parse-lol-image/splash_arts"
nome_report = "differenze_cartelle.txt"

if __name__ == "__main__":
    if os.path.exists(percorso_a) and os.path.exists(percorso_b):
        confronta_cartelle(percorso_a, percorso_b, nome_report)
    else:
        print("Errore: Uno o entrambi i percorsi specificati non esistono.")