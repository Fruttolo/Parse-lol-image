# LoL Splash Arts Manager

Un progetto completo per gestire le immagini HD di tutti i champion di League of Legends. Include script per scaricare, verificare duplicati, confrontare cartelle e sincronizzare immagini.

## Struttura del Progetto

```
./
├── run_all.py                   # Wrapper principale - esegue tutti gli script in sequenza
├── requirements.txt
├── scripts/
│   ├── parse_skin.py            # Scarica immagini HD da wiki.leagueoflegends.com
│   ├── check_hashes.py          # Rileva immagini duplicate
│   ├── compare.py               # Confronta due cartelle per trovare differenze
│   ├── viewer_differences.py    # GUI per visualizzare e sincronizzare file
│   ├── check_failed.py          # Recupera immagini mancanti e propone alternative
│   └── list_champions.py        # Genera champions.txt con skin di ogni champion
├── data/
│   ├── champions.txt            # Lista champion e skin (generato da list_champions.py)
│   ├── other_exceptions.json    # Mappatura skin alternative
│   └── shared_exceptions.json   # Mappatura skin condivise
└── splash_arts/                 # Cartella principale per le immagini HD (gitignored)
```

File generati a runtime (gitignored):
- `failed_downloads.txt` — download falliti (da parse_skin.py)
- `duplicate_images.txt` — duplicati trovati (da check_hashes.py)
- `differenze_cartelle.txt` — differenze tra cartelle (da compare.py)
- `download_report.txt` — report dei download effettuati (da parse_skin.py)

## Installazione

### Requisiti
- Python 3.8+

```bash
pip install -r requirements.txt
```

### `requirements.txt`
```
requests
Pillow
imagehash
rich
```

## Uso

### 1. Esecuzione automatica
```bash
python3 run_all.py [percorso_splash_arts_locale]
```
Esegue tutti gli script in ordine. Se viene fornito il percorso a una cartella locale di splash arts, esegue anche il confronto tra cartelle e, se ci sono differenze, avvia automaticamente la GUI.

Se il percorso è omesso, il confronto e la GUI vengono saltati.

Se uno script fallisce, viene chiesta conferma prima di continuare con i successivi.

### 2. Scaricare immagini HD
```bash
python3 scripts/parse_skin.py
```
Scarica tutte le HD splash arts dal wiki, con retry automatico per file mancanti.

### 3. Verificare duplicati
```bash
python3 scripts/check_hashes.py
```
Genera `duplicate_images.txt` con tutti i duplicati trovati.

### 4. Confrontare cartelle
```bash
python3 scripts/compare.py <percorso_cartella_locale>
```
Confronta la cartella locale specificata con `splash_arts/` e genera `differenze_cartelle.txt` con i file mancanti in ciascuna delle due.

### 5. GUI per sincronizzazione
```bash
python3 scripts/viewer_differences.py <percorso_cartella_locale>
```
Interfaccia grafica per visualizzare le differenze e trasferire (o eliminare) immagini tra le due directory. Supporta anteprima delle immagini, trasferimento singolo o massivo e cancellazione.

### 6. Recupero download falliti
```bash
python3 scripts/check_failed.py
```
Analizza download falliti e propone immagini alternative tramite wiki API.

### 7. Generare lista champion
```bash
python3 scripts/list_champions.py
```
Crea `data/champions.txt` con tutti i champion e le loro skin.

## Funzionalità Chiave

| Script | Funzione | Output |
|--------|----------|--------|
| `run_all.py` | Wrapper sequenziale | Report completo + GUI opzionale |
| `scripts/parse_skin.py` | Download HD | `splash_arts/` + `failed_downloads.txt` + `download_report.txt` |
| `scripts/check_hashes.py` | Rilevamento duplicati | `duplicate_images.txt` |
| `scripts/compare.py` | Confronto cartelle | `differenze_cartelle.txt` |
| `scripts/viewer_differences.py` | GUI sincronizzazione | Interfaccia Tkinter |
| `scripts/check_failed.py` | Alternative download | `alternatives/{champion}/` |
| `scripts/list_champions.py` | Lista champion | `data/champions.txt` |
