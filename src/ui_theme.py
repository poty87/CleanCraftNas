"""Aspetto comune di app e installazione guidata: tema scuro, caratteri, finestre di dialogo."""

import ctypes
import os
import sys
import tkinter as tk
from tkinter import font as tkfont, ttk

import sv_ttk

from i18n import t

# colori del banner di stato e delle icone delle finestre: (sfondo, accento)
LEVELS = {
    "info": ("#1d2633", "#60a5fa"),
    "ok": ("#16261d", "#4ade80"),
    "warn": ("#2c2416", "#fbbf24"),
    "error": ("#2d1a1c", "#f87171"),
}
GLYPHS = {"info": "i", "ok": "✓", "warn": "!", "error": "✕"}
MUTED = "#9aa0a6"
TEXT = "#e8eaed"
ACCENT = "#60a5fa"


def resource(*parts):
    """Percorso di un file distribuito con il programma (sorgente, cx_Freeze o PyInstaller)."""
    if hasattr(sys, "_MEIPASS"):  # PyInstaller, file unico
        base = sys._MEIPASS
    elif getattr(sys, "frozen", False):  # cx_Freeze
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def dark_title_bar(window):
    """Barra del titolo scura su Windows 10/11."""
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (nuovo e vecchio numero)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except (AttributeError, OSError):
        pass


def set_icon(window):
    try:
        window.iconbitmap(resource("assets", "icon.ico"))
    except tk.TclError:
        pass


def setup_theme(root):
    """Tema scuro, caratteri e stili condivisi; i caratteri restano come attributi di root (f_title, f_body…)."""
    sv_ttk.set_theme("dark")
    family = "Segoe UI Variable Text" if "Segoe UI Variable Text" in tkfont.families() else "Segoe UI"
    root.f_title = tkfont.Font(family=family, size=18, weight="bold")
    root.f_body = tkfont.Font(family=family, size=10)
    root.f_small = tkfont.Font(family=family, size=9)
    root.f_strong = tkfont.Font(family=family, size=11, weight="bold")
    root.f_stat = tkfont.Font(family=family, size=20, weight="bold")
    st = ttk.Style(root)
    st.configure("Muted.TLabel", foreground=MUTED, font=root.f_small)
    st.configure("Title.TLabel", font=root.f_title)
    st.configure("Strong.TLabel", font=root.f_strong)
    st.configure("Body.TLabel", font=root.f_body)
    st.configure("Stat.TLabel", font=root.f_stat)
    st.configure("Treeview", rowheight=30, font=root.f_body)
    st.configure("Treeview.Heading", font=root.f_small)
    # l'elenco che si apre dai menu a tendina è un Listbox Tk: va allineato a mano ai caratteri dell'app
    root.option_add("*TCombobox*Listbox.font", root.f_body)


def center_on(window, master):
    window.update_idletasks()
    x = master.winfo_rootx() + (master.winfo_width() - window.winfo_reqwidth()) // 2
    y = master.winfo_rooty() + (master.winfo_height() - window.winfo_reqheight()) // 3
    window.geometry(f"+{max(0, x)}+{max(0, y)}")


class Dialog(tk.Toplevel):
    """Finestra modale con il tema dell'app, al posto delle messagebox di sistema.

    buttons: [(chiave del risultato, testo, principale?)]; Esc e la chiusura restituiscono None.
    """

    def __init__(self, master, title, heading, body, level="info", buttons=None, detail=None, default=None):
        super().__init__(master)
        self.withdraw()
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        set_icon(self)
        self.result = None
        root = master._root()  # la finestra principale ha i caratteri; si centra su chi apre la finestra
        frame = ttk.Frame(self, padding=(24, 22, 24, 18))
        frame.pack(fill="both", expand=True)

        bg, accent = LEVELS[level]
        top = ttk.Frame(frame)
        top.pack(fill="x")
        badge = tk.Canvas(top, width=40, height=40, highlightthickness=0, bd=0,
                          bg=ttk.Style(self).lookup("TFrame", "background") or "#1c1c1c")
        badge.create_oval(2, 2, 38, 38, fill=bg, outline=accent, width=2)
        badge.create_text(20, 20, text=GLYPHS[level], fill=accent, font=root.f_strong)
        badge.pack(side="left", anchor="n")
        texts = ttk.Frame(top)
        texts.pack(side="left", fill="x", expand=True, padx=(14, 0))
        ttk.Label(texts, text=heading, style="Strong.TLabel", wraplength=440, justify="left").pack(anchor="w")
        if body:
            ttk.Label(texts, text=body, wraplength=440, justify="left", style="Body.TLabel").pack(anchor="w", pady=(6, 0))
        if detail:
            lines = sum(max(1, -(-len(line) // 58)) for line in detail.split("\n"))  # righe a capo comprese
            box = tk.Text(texts, height=min(10, lines), width=58, wrap="char", relief="flat",
                          bg="#141414", fg=TEXT, insertbackground=TEXT, font=("Consolas", 9), padx=8, pady=6)
            box.insert("1.0", detail)
            box.configure(state="disabled")
            box.pack(anchor="w", pady=(10, 0), fill="x")

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(20, 0))
        buttons = buttons or [("ok", t("btn_ok"), True)]
        focus = None
        for key, text, primary in reversed(buttons):
            b = ttk.Button(row, text=text, style="Accent.TButton" if primary else "TButton",
                           command=lambda k=key: self.close(k))
            b.pack(side="right", padx=(8, 0))
            b.bind("<Return>", lambda e, k=key: self.close(k))
            if key == (default or buttons[-1][0]):
                focus = b
        self.bind("<Escape>", lambda e: self.close(None))
        self.protocol("WM_DELETE_WINDOW", lambda: self.close(None))

        center_on(self, master)
        dark_title_bar(self)
        self.deiconify()
        self.grab_set()
        (focus or self).focus_set()

    def close(self, result):
        self.result = result
        self.grab_release()
        parent = self.master
        self.destroy()
        if isinstance(parent, tk.Toplevel) and parent.winfo_exists():
            parent.grab_set()  # torna modale la finestra da cui era stata aperta (es. Impostazioni)

    @classmethod
    def ask(cls, master, *args, **kwargs):
        d = cls(master, *args, **kwargs)
        master.wait_window(d)
        return d.result
