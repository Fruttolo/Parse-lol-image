# LoL Splash Arts Manager

Un progetto completo per gestire le immagini HD di tutti i champion di League of Legends. Include script per scaricare, verificare duplicati, confrontare cartelle e sincronizzare immagini.

## 📋 Struttura del Progetto

```
./
├── run_all.py          # Wrapper principale - esegue tutti gli script in sequenza
├── parse_skin.py       # Scarica immagini HD da wiki.leagueoflegends.com
├── check_hashes.py     # Rileva immagini duplicate
├── compare.py          # Confronta due cartelle per trovare differenze
├── viewer_differences.py # GUI per visualizzare e sincronizzare file
├── check_failed.py     # Recupera immagini mancanti e propone alternative
├── list_champions.py  # Genera champions.txt con skin di ogni champion
├── splash_arts/       # Cartella principale per le immagini HD
├── failed_downloads.txt  # Lista download falliti (generato da parse_skin.py)
├── other_exceptions.json  # Mappatura skin alternative
└── shared_exceptions.json # Mappatura skin condivise
```

## 🚀 Installazione

### Requisiti
- Python 3.8+
- Librerie:
```bash
pip install -r requirements.txt
```

### file `requirements.txt`
```
requests
Pillow
imagehash
rich
```

## 📖 Uso

### 1. Esecuzione Automatica
```bash
python3 run_all.py
```
Esegue tutti gli script in ordine, con report finale e lancio automatica della GUI.

### 2. Scaricare Immagini HD
```bash
python3 parse_skin.py
```
Scarica tutte le HD splash arts dal wiki, con retry automatico per file mancanti.

### 3. Verificare Duplicati
```bash
python3 check_hashes.py
```
Genera `duplicate_images.txt` con tutti i duplicati trovati.

### 4. Confrontare Cartelle
```bash
python3 compare.py
```
Genera un report con file mancanti o diversi tra due cartelle.

### 5. GUI per Sincronizzazione
```bash
python3 viewer_differences.py
```
Interfaccia grafica per visualizzare e trasferire immagini tra due directory.

### 6. Recupero Download Falliti
```bash
python3 check_failed.py
```
Analizza download falliti e propone immagini alternative tramite wiki API.

### 7. Generare Lista Champion
```bash
python3 list_champions.py
```
Crea `champions.txt` con tutti i champion e le loro skin.

## 🎯 Funzionalità Chiave

| Script | Funzione | Output |
|--------|----------|--------|
| `run_all.py` | Wrapper sequenziale | Report completo + GUI |
| `parse_skin.py` | Download HD | `splash_arts/` + `failed_downloads.txt` |
| `check_hashes.py` | Rilevamento duplicati | `duplicate_images.txt` |
| `compare.py` | Confronto cartelle | `differenze_cartelle.txt` |
| `viewer_differences.py` | GUI sincronizzazione | Interfaccia Tkinter |
| `check_failed.py` | Alternative download | `alternatives/{champion}/` |
| `list_champions.py` | Lista champion | `champions.txt` |