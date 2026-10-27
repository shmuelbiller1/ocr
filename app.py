"""Local Hebrew-script transcription workbench: dependency-free Windows UI.

Run: python app.py
OCR is intentionally unavailable until a real licensed engine adapter is installed.
"""
from __future__ import annotations
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from datetime import datetime
from engine import EngineRegistry, EngineUnavailable

APP = "Hebrew Notes Workbench"
EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".pdf"}

class Workbench(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP)
        self.geometry("1120x760")
        self.minsize(800, 550)
        self.documents = []
        self.registry = EngineRegistry()
        self.current = None
        self.configure(bg="#f4f5f7")
        self.build_ui()

    def build_ui(self):
        frame = ttk.Frame(self, padding=15)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="כתב יד ← טקסט מוקלד", font=("Segoe UI", 21, "bold")).pack(anchor="e")
        ttk.Label(frame, text="Offline Hebrew-script workbench • Review before printing").pack(anchor="w", pady=(2, 10))
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="Add documents", command=self.add_files).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="Add folder", command=self.add_folder).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="Run OCR", command=self.run_ocr).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="Save text", command=self.save_text).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="Print text", command=self.print_text).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="Engine status", command=self.engine_status).pack(side="right")
        self.spelling = tk.BooleanVar(value=False)
        self.grammar = tk.BooleanVar(value=False)
        self.style = tk.BooleanVar(value=False)
        settings = ttk.Frame(frame)
        settings.pack(fill="x", pady=(0, 8))
        for title, var in [("Spelling suggestions", self.spelling), ("Grammar suggestions", self.grammar), ("לשון הספר suggestions", self.style)]:
            ttk.Checkbutton(settings, text=title, variable=var, command=self.notify_optional).pack(side="left", padx=(0, 12))
        panes = ttk.Panedwindow(frame, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.LabelFrame(panes, text="Source documents", padding=7)
        right = ttk.LabelFrame(panes, text="Editable transcription (right-to-left)", padding=7)
        panes.add(left, weight=1)
        panes.add(right, weight=2)
        self.filelist = tk.Listbox(left, exportselection=False, font=("Segoe UI", 10))
        self.filelist.pack(fill="both", expand=True)
        self.filelist.bind("<<ListboxSelect>>", self.select_document)
        self.source = ttk.Label(left, text="Select a document to see its path", wraplength=280)
        self.source.pack(fill="x", pady=(8, 2))
        ttk.Label(left, text="Original files are never modified.\nImage preview is not yet implemented.", foreground="#666").pack(anchor="w")
        self.textbox = tk.Text(right, wrap="word", undo=True, font=("Arial", 17), padx=14, pady=12)
        self.textbox.pack(fill="both", expand=True)
        self.textbox.tag_configure("rtl", justify="right")
        self.textbox.bind("<KeyRelease>", lambda event: self.textbox.tag_add("rtl", "1.0", "end"))
        self.status = tk.StringVar(value="Ready. OCR and correction engines are not installed.")
        ttk.Label(frame, textvariable=self.status, padding=(0, 8)).pack(anchor="w")

    def add_files(self):
        paths = filedialog.askopenfilenames(title="Choose scans", filetypes=[("Scanned pages", "*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff"), ("All files", "*.*")])
        self.add_paths(paths)

    def add_folder(self):
        folder = filedialog.askdirectory(title="Choose a folder of scanned pages")
        if folder:
            self.add_paths(str(p) for p in sorted(Path(folder).iterdir()) if p.is_file())

    def add_paths(self, paths):
        existing = set(self.documents)
        for item in paths:
            path = str(Path(item).resolve())
            if Path(path).suffix.lower() in EXTS and path not in existing:
                self.documents.append(path)
                self.filelist.insert("end", Path(path).name)
                existing.add(path)
        self.status.set(f"{len(self.documents)} document(s) selected. No OCR performed.")

    def select_document(self, event=None):
        selected = self.filelist.curselection()
        if selected:
            self.current = self.documents[selected[0]]
            self.source.configure(text=self.current)

    def run_ocr(self):
        if not self.current:
            messagebox.showinfo(APP, "Select a document first.")
            return
        try:
            result = self.registry.transcribe(self.current)
        except EngineUnavailable as exc:
            messagebox.showwarning("OCR not available", str(exc))
            self.status.set("OCR unavailable; no transcription was generated.")
            return
        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", result.text)
        self.textbox.tag_add("rtl", "1.0", "end")
        self.status.set(f"Recognized using {result.engine_name}; verify every line before export.")

    def notify_optional(self):
        if self.spelling.get() or self.grammar.get() or self.style.get():
            self.status.set("Correction modules not installed yet. Selecting an option does not modify the text.")

    def save_text(self):
        content = self.textbox.get("1.0", "end-1c")
        if not content.strip():
            messagebox.showinfo(APP, "No text to save. OCR is not bundled; you may type or paste text into the editor.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("UTF-8 text", "*.txt")])
        if path:
            Path(path).write_text(content, encoding="utf-8-sig")
            self.status.set(f"Saved editable text: {path}")

    def print_text(self):
        content = self.textbox.get("1.0", "end-1c")
        if not content.strip():
            messagebox.showinfo(APP, "There is no text to print.")
            return
        messagebox.showinfo("Printing", "Printing is not yet bundled. Save text, then open it with a document editor to print. No print job was sent.")

    def engine_status(self):
        messagebox.showinfo("Installed engines", self.registry.status())

def main():
    Workbench().mainloop()

if __name__ == "__main__":
    main()
