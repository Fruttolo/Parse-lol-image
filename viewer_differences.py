import os
import shutil
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from PIL import Image, ImageTk

class LoLTwoWaySync:
    def __init__(self, root):
        self.root = root
        self.root.title("LoL Splash Arts - Dual Folder Sync")
        self.root.geometry("1200x800")
        self.root.configure(bg="#1e1e1e")

        # --- CONFIGURAZIONE PERCORSI ---
        self.dir_a = Path("/home/salvo/Immagini/splash_arts_lol")
        self.dir_b = Path(__file__).parent / "splash_arts"

        self.selected_file = None
        self.selected_side = None 
        
        self._setup_ui()
        self.refresh_data()

    def _setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Treeview", background="#2d2d2d", foreground="white", fieldbackground="#2d2d2d", rowheight=25)
        style.map("Treeview", background=[('selected', '#3498db')])

        # --- AREA ANTEPRIMA ---
        preview_frame = tk.Frame(self.root, bg="#1e1e1e", height=320)
        preview_frame.pack(fill=tk.X, padx=10, pady=10)
        preview_frame.pack_propagate(False)

        self.pre_a_container = tk.Label(preview_frame, text="Seleziona un file", bg="#121212", fg="#555", font=('Arial', 9))
        self.pre_a_container.pack(expand=True, fill=tk.BOTH, padx=5)

        # --- AREA LISTE ---
        lists_frame = tk.Frame(self.root, bg="#1e1e1e")
        lists_frame.pack(expand=True, fill=tk.BOTH, padx=10, pady=5)

        # Colonna A (Sinistra)
        col_a = tk.Frame(lists_frame, bg="#1e1e1e")
        col_a.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        tk.Label(col_a, text="FILE SOLO IN A", bg="#1e1e1e", fg="#e74c3c", font=('Arial', 10, 'bold')).pack(pady=5)
        
        # Aggiungiamo una colonna "HiddenPath" che non mostreremo
        self.list_a = ttk.Treeview(col_a, columns=("FullPath"), show="tree")
        self.list_a.pack(expand=True, fill=tk.BOTH)
        self.list_a.bind("<<TreeviewSelect>>", lambda e: self._on_select('A'))
        
        btn_frame_a = tk.Frame(col_a, bg="#1e1e1e")
        btn_frame_a.pack(pady=10, fill=tk.X)
        
        self.btn_move_to_b = tk.Button(btn_frame_a, text="Sposta in B ➔", state=tk.DISABLED, 
                                      bg="#27ae60", fg="white", font=('Arial', 10, 'bold'), command=lambda: self._transfer('A', 'B'))
        self.btn_move_to_b.pack(pady=5, fill=tk.X)
        
        self.btn_move_all_to_b = tk.Button(btn_frame_a, text="Sposta TUTTI in B ➔➔", 
                                          bg="#2980b9", fg="white", font=('Arial', 9), command=lambda: self._transfer_all('A', 'B'))
        self.btn_move_all_to_b.pack(pady=5, fill=tk.X)

        # Colonna B (Destra)
        col_b = tk.Frame(lists_frame, bg="#1e1e1e")
        col_b.pack(side=tk.RIGHT, expand=True, fill=tk.BOTH)
        tk.Label(col_b, text="FILE SOLO IN B", bg="#1e1e1e", fg="#3498db", font=('Arial', 10, 'bold')).pack(pady=5)
        
        self.list_b = ttk.Treeview(col_b, columns=("FullPath"), show="tree")
        self.list_b.pack(expand=True, fill=tk.BOTH)
        self.list_b.bind("<<TreeviewSelect>>", lambda e: self._on_select('B'))

        btn_frame_b = tk.Frame(col_b, bg="#1e1e1e")
        btn_frame_b.pack(pady=10, fill=tk.X)
        
        self.btn_move_to_a = tk.Button(btn_frame_b, text="⬅ Sposta in A", state=tk.DISABLED, 
                                      bg="#27ae60", fg="white", font=('Arial', 10, 'bold'), command=lambda: self._transfer('B', 'A'))
        self.btn_move_to_a.pack(pady=5, fill=tk.X)
        
        self.btn_move_all_to_a = tk.Button(btn_frame_b, text="⬅⬅ Sposta TUTTI in A", 
                                          bg="#2980b9", fg="white", font=('Arial', 9), command=lambda: self._transfer_all('B', 'A'))
        self.btn_move_all_to_a.pack(pady=5, fill=tk.X)

    def _get_relative_files(self, base_path):
        res = set()
        if base_path.exists():
            for p in base_path.rglob("*"):
                if p.is_file() and p.suffix.lower() in ['.jpg', '.jpeg', '.png']:
                    # Memorizziamo il percorso relativo (es: 'Aatrox/skin01.jpg')
                    res.add(p.relative_to(base_path))
        return res

    def refresh_data(self):
        """Aggiorna le liste mostrando il nome del file (e SHARED se applicabile)."""
        self.list_a.delete(*self.list_a.get_children())
        self.list_b.delete(*self.list_b.get_children())

        files_a = self._get_relative_files(self.dir_a)
        files_b = self._get_relative_files(self.dir_b)

        # Solo in A
        for rel_p in sorted(files_a - files_b):
            # Mostra: "NomeFile.jpg" oppure "NomeFile.jpg (SHARED)" se il file è in SHARED
            if rel_p.parent.name == "SHARED":
                display_name = f"{rel_p.name} (SHARED)"
            else:
                display_name = rel_p.name
            self.list_a.insert("", "end", text=display_name, values=(str(rel_p),))

        # Solo in B
        for rel_p in sorted(files_b - files_a):
            if rel_p.parent.name == "SHARED":
                display_name = f"{rel_p.name} (SHARED)"
            else:
                display_name = rel_p.name
            self.list_b.insert("", "end", text=display_name, values=(str(rel_p),))

    def _on_select(self, side):
        tree = self.list_a if side == 'A' else self.list_b
        other_tree = self.list_b if side == 'A' else self.list_a
        
        selection = tree.selection()
        if not selection: return

        other_tree.selection_remove(other_tree.selection())

        item = tree.item(selection[0])
        rel_path_str = item['values'][0] # Qui abbiamo il path relativo salvato prima
        
        self.selected_file = Path(rel_path_str)
        self.selected_side = side

        # Determina il path assoluto per l'anteprima
        base_dir = self.dir_a if side == 'A' else self.dir_b
        full_path = base_dir / self.selected_file

        if side == 'A':
            self.btn_move_to_b.config(state=tk.NORMAL)
            self.btn_move_to_a.config(state=tk.DISABLED)
            self._show_preview(full_path, self.pre_a_container)
        else:
            self.btn_move_to_a.config(state=tk.NORMAL)
            self.btn_move_to_b.config(state=tk.DISABLED)
            self._show_preview(full_path, self.pre_a_container)

    def _show_preview(self, full_path, container):
        try:
            img = Image.open(full_path)
            # Resize proporzionale per l'anteprima
            img.thumbnail((550, 300), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            container.config(image=photo, text="")
            container.image = photo 
        except:
            container.config(image='', text="Impossibile caricare anteprima")

    def _transfer(self, from_side, to_side):
        if not self.selected_file: return

        src_dir = self.dir_a if from_side == 'A' else self.dir_b
        dst_dir = self.dir_b if from_side == 'A' else self.dir_a

        src_path = src_dir / self.selected_file
        dst_path = dst_dir / self.selected_file

        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)
            
            # Pulisci e ricarica
            self.selected_file = None
            self.refresh_data()
            self.pre_a_container.config(image='', text="Sincronizzato")
        except Exception as e:
            messagebox.showerror("Errore", f"Errore durante la copia: {e}")

    def _transfer_all(self, from_side, to_side):
        src_dir = self.dir_a if from_side == 'A' else self.dir_b
        dst_dir = self.dir_b if from_side == 'A' else self.dir_a
        
        files_src = self._get_relative_files(src_dir)
        files_dst = self._get_relative_files(dst_dir)
        
        # File solo nel sorgente
        files_to_transfer = files_src - files_dst
        
        if not files_to_transfer:
            messagebox.showinfo("Info", "Nessun file da trasferire")
            return
        
        try:
            for rel_p in files_to_transfer:
                src_path = src_dir / rel_p
                dst_path = dst_dir / rel_p
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dst_path)
            
            # Pulisci e ricarica
            self.selected_file = None
            self.refresh_data()
            self.pre_a_container.config(image='', text="Seleziona un file")
            messagebox.showinfo("Successo", f"Trasferiti {len(files_to_transfer)} file")
        except Exception as e:
            messagebox.showerror("Errore", f"Errore durante il trasferimento: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = LoLTwoWaySync(root)
    root.mainloop()