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
python3 run_all.py
```
Esegue tutti gli script in ordine. Al termine mostra un report e, se ci sono differenze tra cartelle, avvia automaticamente la GUI.

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
python3 scripts/compare.py
```
Genera `differenze_cartelle.txt` con file mancanti o diversi tra due cartelle.

### 5. GUI per sincronizzazione
```bash
python3 scripts/viewer_differences.py
```
Interfaccia grafica per visualizzare e trasferire immagini tra due directory.

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
| `run_all.py` | Wrapper sequenziale | Report completo + GUI |
| `scripts/parse_skin.py` | Download HD | `splash_arts/` + `failed_downloads.txt` |
| `scripts/check_hashes.py` | Rilevamento duplicati | `duplicate_images.txt` |
| `scripts/compare.py` | Confronto cartelle | `differenze_cartelle.txt` |
| `scripts/viewer_differences.py` | GUI sincronizzazione | Interfaccia Tkinter |
| `scripts/check_failed.py` | Alternative download | `alternatives/{champion}/` |
| `scripts/list_champions.py` | Lista champion | `data/champions.txt` |
