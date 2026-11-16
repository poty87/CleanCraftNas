"""CleanCraftNas.

Cancella dal disco i file delle foto che sono nel cestino ("Recently Deleted") di una libreria
Lightcraft e poi le toglie dalla libreria, così cestino e disco restano allineati.

Le foto vengono lette da catalog.snap; le modifiche alla libreria passano sempre da
lightcraft-cli (photo.deletePermanently), mai scrivendo i file della libreria a mano.
"""

import ctypes
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import winreg
from ctypes import wintypes
from tkinter import filedialog, font as tkfont, ttk

import sv_ttk
from PIL import Image, ImageOps, ImageTk

from translations import DATE_FORMATS, LANGUAGES, TEXTS

APP_NAME = "CleanCraftNas"
VERSION = "1.2.0"
LOCAL = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
# impostazioni e registro dell'utente: l'app installata vive in una cartella che non si modifica
DATA_DIR = os.path.join(LOCAL, APP_NAME)
OLD_DATA_DIR = os.path.join(LOCAL, "Pulizia cestino Lightcraft")  # nome delle versioni fino alla 1.1
SETTINGS = os.path.join(DATA_DIR, "settings.json")
LOG = os.path.join(DATA_DIR, "cleancraftnas.log")
REG_KEY = r"Software\CleanCraftNas"  # la lingua scelta durante l'installazione
DEFAULT_CLI = os.path.join(LOCAL, r"Programs\ArtCraft\LightCraft\lightcraft-cli.exe")
# file con lo stesso nome della foto che vengono cancellati insieme a lei
COMPANIONS = (".xmp", ".jpg", ".jpeg")
BACKUPS_KEPT = 5
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def resource(*parts):
    """Percorso di un file dell'app, sia da sorgente sia dall'eseguibile installato."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


# ---------------------------------------------------------------- lingua

LANG = "en"


def t(key, **values):
    text = TEXTS[key].get(LANG) or TEXTS[key]["en"]
    return text.format(**values) if values else text


def windows_language():
    """Lingua dell'interfaccia di Windows, se è tra quelle supportate."""
    primary = {0x10: "it", 0x09: "en", 0x07: "de", 0x0A: "es", 0x0C: "fr", 0x16: "pt"}
    try:
        return primary.get(ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF, "en")
    except (AttributeError, OSError):
        return "en"


def installer_language():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY) as key:
            return winreg.QueryValueEx(key, "Language")[0]
    except OSError:
        return None


def resolve_language(setting):
    """"auto" o una lingua non supportata diventano la lingua di Windows."""
    return setting if setting in LANGUAGES else windows_language()


# ---------------------------------------------------------------- impostazioni e registro

def load_settings():
    for path in (SETTINGS, os.path.join(OLD_DATA_DIR, "impostazioni.json")):
        try:
            with open(path, encoding="utf-8-sig") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return {}


def save_settings(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def log(text):
    os.makedirs(DATA_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{stamp} {text}\n")


# ---------------------------------------------------------------- Lightcraft

def lightcraft_running():
    """Nomi dei processi Lightcraft in esecuzione (app o riga di comando)."""
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    names = {line.split('","')[0].strip('"').lower() for line in out.splitlines() if line}
    return sorted(n for n in names if n in ("lightcraft.exe", "lightcraft-cli.exe"))


def library_open_reason(lib):
    """Chiave del testo che spiega perché la libreria non si può modificare adesso, oppure None."""
    if lightcraft_running():
        return "st_open_app"
    if os.path.exists(os.path.join(lib, "catalog.lock.owner")):
        return "st_open_lock"
    return None


def is_library(lib):
    return bool(lib) and os.path.isfile(os.path.join(lib, "catalog.snap"))


def is_cli(path):
    return bool(path) and os.path.isfile(path) and os.path.basename(path).lower() == "lightcraft-cli.exe"


def read_catalog(lib):
    with open(os.path.join(lib, "catalog.snap"), encoding="utf-8") as f:
        return json.load(f)["catalog"]


def run_cli(cli, lib, commands):
    """Esegue comandi con lightcraft-cli sulla libreria; restituisce le risposte JSON."""
    fd, script = tempfile.mkstemp(suffix=".jsonl", prefix="cleancraftnas-")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        for name, params in commands:
            f.write(json.dumps({"command": name, "params": params}) + "\n")
    try:
        r = subprocess.run([cli, "run", "--library", lib, "--script", script],
                           capture_output=True, text=True, encoding="utf-8", creationflags=NO_WINDOW)
    finally:
        os.remove(script)
    replies = []
    for line in r.stdout.splitlines():
        try:
            replies.append(json.loads(line))
        except ValueError:
            pass
    if r.returncode != 0 or not replies or not all(x.get("ok") for x in replies):
        detail = r.stderr.strip() or "; ".join(str(x.get("error")) for x in replies if not x.get("ok"))
        raise RuntimeError(f"lightcraft-cli ({r.returncode}): {detail}")
    return replies


# ---------------------------------------------------------------- piano di cancellazione

def camera_name(meta):
    """"RICOH IMAGING COMPANY, LTD. RICOH GR IV" → "RICOH GR IV": il modello ripete già la marca."""
    camera, make = (meta.get("camera") or "").strip(), (meta.get("make") or "").strip()
    if make and camera.lower().startswith(make.lower()) and len(camera) > len(make):
        camera = camera[len(make):].strip()
    return camera


def build_plan(lib):
    """Elenca le foto nel cestino e i file da cancellare per ciascuna."""
    cat = read_catalog(lib)
    photos = cat["photos"].values()

    def path_of(p):
        s = p.get("source") or {}
        return s.get("path") if s.get("type") == "file" else None

    # percorsi ancora usati da foto attive: quei file non si toccano mai
    active = {os.path.normcase(path_of(p)) for p in photos if not p.get("deleted") and path_of(p)}
    planned = set()  # un file compare una volta sola, anche se è il JPG di un'altra foto nel cestino
    plan = []
    for p in sorted((p for p in photos if p.get("deleted")), key=lambda p: path_of(p) or ""):
        path = path_of(p)
        meta = p.get("meta") or {}
        item = {"id": int(p["id"]), "name": p.get("file_name") or "", "path": path, "files": [], "note": None,
                "captured": p.get("captured"), "camera": camera_name(meta),
                "size_px": (p.get("width"), p.get("height")), "kind": p.get("kind")}
        if not path:
            item["note"] = "note_demo"
        elif os.path.normcase(path) in active:
            item["note"] = "note_shared"
        elif not os.path.exists(path):
            item["note"] = "note_missing"
        elif os.path.normcase(path) in planned:
            item["note"] = "note_dup"
        else:
            item["files"].append(path)
            base = os.path.splitext(path)[0]
            folder = os.path.dirname(path)
            try:
                names = {n.lower(): n for n in os.listdir(folder)}
            except OSError:
                names = {}
            for ext in COMPANIONS:
                for cand in (os.path.basename(base) + ext, os.path.basename(path) + ext):
                    real = names.get(cand.lower())
                    if not real:
                        continue
                    full = os.path.join(folder, real)
                    key = os.path.normcase(full)
                    if key != os.path.normcase(path) and key not in active and key not in planned \
                            and full not in item["files"]:
                        item["files"].append(full)
        planned.update(os.path.normcase(f) for f in item["files"])
        item["sizes"] = [os.path.getsize(f) for f in item["files"]]
        item["bytes"] = sum(item["sizes"])
        plan.append(item)
    return plan


# ---------------------------------------------------------------- anteprime

RAW_EXTS = (".dng", ".orf", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".rw2", ".pef")
PREVIEW_MAX = 1600  # lato lungo dell'anteprima tenuta in memoria


def _embedded_jpeg(data):
    """La JPEG incorporata più grande che Pillow sa leggere (i raw ne contengono una o più).

    I dati raw compressi iniziano anche loro con FFD8 (JPEG senza perdita), ma Pillow non li apre: restano esclusi.
    """
    best, best_px, pos = None, 0, 0
    for _ in range(64):
        pos = data.find(b"\xff\xd8\xff", pos)
        if pos < 0:
            break
        try:
            im = Image.open(io.BytesIO(data[pos:]))
            if im.format == "JPEG" and im.mode in ("RGB", "L", "CMYK") and im.width * im.height > best_px:
                best, best_px = pos, im.width * im.height
        except Exception:  # noqa: BLE001 — un candidato non leggibile si salta
            pass
        pos += 3
    if best is None:
        return None
    im = Image.open(io.BytesIO(data[best:]))
    im.load()
    return im


def load_preview(path):
    """Immagine Pillow dell'anteprima del file, già ruotata e ridotta; None se non si può fare."""
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXTS:
        with open(path, "rb") as f:
            data = f.read()
        im = _embedded_jpeg(data)
        if im is None:
            return None
        try:  # l'orientamento sta nell'intestazione TIFF del raw, non nella JPEG incorporata
            orientation = Image.open(io.BytesIO(data)).getexif().get(0x0112, 1)
        except Exception:  # noqa: BLE001
            orientation = 1
        im = {3: lambda i: i.rotate(180, expand=True), 6: lambda i: i.rotate(270, expand=True),
              8: lambda i: i.rotate(90, expand=True)}.get(orientation, lambda i: i)(im)
    else:
        im = Image.open(path)
        im.draft("RGB", (PREVIEW_MAX, PREVIEW_MAX))
        im = ImageOps.exif_transpose(im)
    im = im.convert("RGB")
    im.thumbnail((PREVIEW_MAX, PREVIEW_MAX), Image.LANCZOS)
    return im


# ---------------------------------------------------------------- cancellazione

class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


FO_DELETE = 3
FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400


def delete_file(path):
    """Cestino di Windows per i dischi locali; sul NAS il file va nel cestino di Synology, se attivo."""
    op = SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=path + "\0\0",
                         fFlags=FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted or os.path.exists(path):
        raise OSError(f"code {rc}")


def backup_library(lib):
    # accanto alla libreria, non dentro: la cartella della libreria resta di Lightcraft
    root = os.path.join(os.path.dirname(lib), "CleanCraftNas backup - " + os.path.basename(lib))
    dest = os.path.join(root, datetime.datetime.now().strftime("%Y-%m-%d %H.%M.%S"))
    os.makedirs(dest)
    for name in ("catalog.snap", "catalog.log", "view.json"):
        src = os.path.join(lib, name)
        if os.path.exists(src):
            shutil.copy2(src, dest)
    for old in sorted(os.listdir(root))[:-BACKUPS_KEPT]:
        shutil.rmtree(os.path.join(root, old), ignore_errors=True)
    return dest


def execute(lib, cli, plan):
    """Cancella i file e toglie dalla libreria le foto i cui file non ci sono più (o restano ad altre foto)."""
    reason = library_open_reason(lib)
    if reason:
        raise RuntimeError(t(reason))
    backup = backup_library(lib)
    log(f"--- cleanup of {lib} (backup: {backup})")
    removed, failed, deleted_files = [], [], 0
    for item in plan:
        ok = True
        for f in item["files"]:
            if not os.path.exists(f):
                log(f"already gone {f}")
                continue
            try:
                delete_file(f)
                deleted_files += 1
                log(f"deleted {f}")
            except OSError as e:
                ok = False
                failed.append(f"{f}: {e}")
                log(f"ERROR {f}: {e}")
        if ok:
            removed.append(item["id"])
    if removed:
        run_cli(cli, lib, [("photo.deletePermanently", {"ids": removed})])
    left = sum(1 for p in read_catalog(lib)["photos"].values() if p.get("deleted"))
    log(f"removed from library: {len(removed)}, files deleted: {deleted_files}, errors: {len(failed)}, "
        f"still in trash: {left}")
    return {"removed": len(removed), "files": deleted_files, "failed": failed, "left": left, "backup": backup}


# ---------------------------------------------------------------- aspetto

def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            if unit == "B":
                return f"{n:.0f} {unit}"
            text = f"{n:.1f} {unit}"
            return text if LANG == "en" else text.replace(".", ",")
        n /= 1024


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
        app = master._root()  # la finestra principale ha i caratteri; si centra su chi apre la finestra
        frame = ttk.Frame(self, padding=(24, 22, 24, 18))
        frame.pack(fill="both", expand=True)

        bg, accent = LEVELS[level]
        top = ttk.Frame(frame)
        top.pack(fill="x")
        badge = tk.Canvas(top, width=40, height=40, highlightthickness=0, bd=0,
                          bg=ttk.Style(self).lookup("TFrame", "background") or "#1c1c1c")
        badge.create_oval(2, 2, 38, 38, fill=bg, outline=accent, width=2)
        badge.create_text(20, 20, text=GLYPHS[level], fill=accent, font=app.f_strong)
        badge.pack(side="left", anchor="n")
        texts = ttk.Frame(top)
        texts.pack(side="left", fill="x", expand=True, padx=(14, 0))
        ttk.Label(texts, text=heading, style="Strong.TLabel", wraplength=440, justify="left").pack(anchor="w")
        if body:
            ttk.Label(texts, text=body, wraplength=440, justify="left", font=app.f_body).pack(anchor="w", pady=(6, 0))
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

        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
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


class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.title(t("settings"))
        self.resizable(False, False)
        self.transient(app)
        set_icon(self)
        self.saved = False
        frame = ttk.Frame(self, padding=(24, 22, 24, 18))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=t("settings"), style="Title.TLabel").pack(anchor="w")

        ttk.Label(frame, text=t("lang_label").upper(), style="Muted.TLabel").pack(anchor="w", pady=(18, 4))
        self.lang_codes = ["auto", *LANGUAGES]
        names = [t("lang_auto"), *LANGUAGES.values()]
        self.lang = ttk.Combobox(frame, values=names, state="readonly", width=40)
        current = app.settings.get("language") or "auto"
        self.lang.current(self.lang_codes.index(current) if current in self.lang_codes else 0)
        self.lang.pack(anchor="w")

        ttk.Label(frame, text=t("cli_label").upper(), style="Muted.TLabel").pack(anchor="w", pady=(18, 4))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.cli = tk.StringVar(value=app.settings.get("cli") or DEFAULT_CLI)
        ttk.Entry(row, textvariable=self.cli, width=58).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text=t("btn_browse"), command=self.browse).pack(side="left", padx=(8, 0))
        ttk.Label(frame, text=t("cli_hint"), style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        ttk.Label(frame, text=f"{APP_NAME} · " + t("about", version=VERSION), style="Muted.TLabel").pack(
            anchor="w", pady=(18, 0))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text=t("btn_save"), style="Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(buttons, text=t("btn_cancel"), command=self.destroy).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_reqwidth()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        dark_title_bar(self)
        self.deiconify()
        self.grab_set()

    def browse(self):
        start = os.path.dirname(self.cli.get()) if os.path.isdir(os.path.dirname(self.cli.get())) else LOCAL
        path = filedialog.askopenfilename(parent=self, title=t("cli_pick"), initialdir=start,
                                          filetypes=[("lightcraft-cli.exe", "lightcraft-cli.exe")])
        if path:
            self.cli.set(os.path.normpath(path))

    def save(self):
        cli = self.cli.get().strip()
        # il percorso predefinito si accetta anche se Lightcraft non c'è ancora: lo si chiede al momento di cancellare
        if cli and os.path.normcase(cli) != os.path.normcase(DEFAULT_CLI) and not is_cli(cli):
            Dialog.ask(self, t("settings"), t("cli_bad"), cli, level="warn")
            return
        self.app.settings["language"] = self.lang_codes[self.lang.current()]
        if cli and os.path.normcase(cli) != os.path.normcase(DEFAULT_CLI):
            self.app.settings["cli"] = cli
        else:
            self.app.settings.pop("cli", None)
        save_settings(self.app.settings)
        self.saved = True
        self.destroy()


# ---------------------------------------------------------------- finestra principale

class App(tk.Tk):
    def __init__(self):
        global LANG
        super().__init__()
        self.withdraw()
        self.title(APP_NAME)
        self.geometry("1240x740")
        self.minsize(900, 560)
        set_icon(self)
        sv_ttk.set_theme("dark")
        self.settings = load_settings()
        LANG = resolve_language(self.settings.get("language") or installer_language())
        self.plan = []
        self.reason = None
        self.previews = {}  # percorso -> immagine Pillow (o None se non leggibile)
        self._fonts()
        self._styles()
        self._build()
        dark_title_bar(self)
        self.deiconify()
        if is_library(self.settings.get("library")):
            self.after(150, self.refresh)
        else:
            self.set_status("info", t("st_choose"))

    def _fonts(self):
        family = "Segoe UI Variable Text" if "Segoe UI Variable Text" in tkfont.families() else "Segoe UI"
        self.f_title = tkfont.Font(family=family, size=18, weight="bold")
        self.f_body = tkfont.Font(family=family, size=10)
        self.f_small = tkfont.Font(family=family, size=9)
        self.f_strong = tkfont.Font(family=family, size=11, weight="bold")
        self.f_stat = tkfont.Font(family=family, size=20, weight="bold")

    def _styles(self):
        st = ttk.Style(self)
        st.configure("Muted.TLabel", foreground=MUTED, font=self.f_small)
        st.configure("Title.TLabel", font=self.f_title)
        st.configure("Strong.TLabel", font=self.f_strong)
        st.configure("Stat.TLabel", font=self.f_stat)
        st.configure("Treeview", rowheight=30, font=self.f_body)
        st.configure("Treeview.Heading", font=self.f_small)

    def _build(self):
        """Costruisce tutta la finestra nella lingua corrente (si richiama quando la lingua cambia)."""
        self.outer = outer = ttk.Frame(self, padding=(24, 20, 24, 18))
        outer.pack(fill="both", expand=True)

        # intestazione
        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Button(head, text="⚙  " + t("settings"), command=self.open_settings).pack(side="right", anchor="n")
        ttk.Label(head, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(head, text=t("subtitle"), style="Muted.TLabel").pack(anchor="w", pady=(2, 0))

        # libreria
        card = ttk.Frame(outer, style="Card.TFrame", padding=(16, 12))
        card.pack(fill="x", pady=(16, 0))
        info = ttk.Frame(card)
        info.pack(side="left", fill="x", expand=True)
        ttk.Label(info, text=t("library"), style="Muted.TLabel").pack(anchor="w")
        self.lib_name = ttk.Label(info, style="Strong.TLabel")
        self.lib_name.pack(anchor="w", pady=(2, 0))
        self.lib_path = ttk.Label(info, style="Muted.TLabel")
        self.lib_path.pack(anchor="w")
        self.btn_refresh = ttk.Button(card, text="↻  " + t("refresh"), command=self.refresh)
        self.btn_refresh.pack(side="right")
        ttk.Button(card, text=t("change_library"), command=self.choose).pack(side="right", padx=(0, 8))
        self.update_library_label()

        # stato
        self.banner = tk.Frame(outer, highlightthickness=0, bd=0)
        self.banner.pack(fill="x", pady=(12, 0))
        self.banner_bar = tk.Frame(self.banner, width=4)
        self.banner_bar.pack(side="left", fill="y")
        self.banner_text = tk.Label(self.banner, anchor="w", justify="left", font=self.f_body, padx=12, pady=9,
                                    fg=TEXT)
        self.banner_text.pack(side="left", fill="x", expand=True)
        self.banner.bind("<Configure>", lambda e: self.banner_text.configure(wraplength=max(200, e.width - 40)))

        # numeri
        stats = ttk.Frame(outer)
        stats.pack(fill="x", pady=(12, 0))
        self.stat_vars = {}
        for i, key in enumerate(("photos", "files", "bytes")):
            box = ttk.Frame(stats, style="Card.TFrame", padding=(16, 10))
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            stats.columnconfigure(i, weight=1)
            ttk.Label(box, text=t("stat_" + key).upper(), style="Muted.TLabel").pack(anchor="w")
            var = tk.StringVar(value="–")
            ttk.Label(box, textvariable=var, style="Stat.TLabel").pack(anchor="w")
            self.stat_vars[key] = var

        # piede: va messo prima dell'elenco, così l'elenco non lo spinge fuori dalla finestra
        foot = ttk.Frame(outer)
        foot.pack(side="bottom", fill="x", pady=(14, 0))
        ttk.Button(foot, text=t("open_log"), command=self.open_log).pack(side="left")
        ttk.Label(foot, text=f"v{VERSION}", style="Muted.TLabel").pack(side="left", padx=(12, 0))
        self.go = ttk.Button(foot, text=t("go"), style="Accent.TButton", command=self.confirm)
        self.go.pack(side="right")
        self.progress = ttk.Progressbar(foot, mode="indeterminate", length=160)
        self.go.state(["disabled"])

        # elenco e anteprima, divisi da un separatore trascinabile
        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(14, 0))
        listf = ttk.Frame(panes)
        cols = ("name", "folder", "size", "note")
        self.tree = ttk.Treeview(listf, columns=cols, show="headings", selectmode="browse")
        for c, title, w, anchor, stretch in (("name", t("col_file"), 230, "w", False),
                                             ("folder", t("col_folder"), 240, "w", True),
                                             ("size", t("col_size") + "   ", 100, "e", False),
                                             ("note", "   " + t("col_status"), 150, "w", False)):
            self.tree.heading(c, text=title, anchor=anchor)
            self.tree.column(c, width=w, minwidth=60, anchor=anchor, stretch=stretch)
        self.tree.tag_configure("muted", foreground=MUTED)
        self.tree.tag_configure("companion", foreground="#c4c7c5")
        sb = ttk.Scrollbar(listf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", lambda e: self.open_large())
        self.tree.bind("<Return>", lambda e: self.open_large())
        panes.add(listf, weight=3)

        prev = ttk.Frame(panes, style="Card.TFrame", padding=12)
        card_bg = ttk.Style(self).lookup("Card.TFrame", "background") or "#2b2b2b"
        self.preview_img = tk.Label(prev, bg=card_bg, fg=MUTED, font=self.f_small, cursor="hand2",
                                    text=t("preview_hint"))
        self.preview_img.pack(fill="both", expand=True)
        self.preview_img.bind("<Configure>", lambda e: self.render_preview())
        self.preview_img.bind("<Button-1>", lambda e: self.open_large())
        self.preview_name = ttk.Label(prev, style="Strong.TLabel")
        self.preview_name.pack(anchor="w", pady=(10, 0))
        self.preview_info = ttk.Label(prev, style="Muted.TLabel", justify="left")
        self.preview_info.pack(anchor="w", pady=(2, 0))
        panes.add(prev, weight=2)
        # l'elenco chiede più spazio di quello che gli serve: all'avvio il separatore va messo a mano
        self.after(60, lambda: panes.sashpos(0, int(panes.winfo_width() * 0.6)))

        self.rows = {}  # riga dell'elenco -> foto del piano
        self.current = None  # foto mostrata nell'anteprima
        self._tk_img = None

    def set_status(self, level, text):
        bg, accent = LEVELS[level]
        self.banner.configure(bg=bg)
        self.banner_bar.configure(bg=accent)
        self.banner_text.configure(bg=bg, text=text)

    def update_library_label(self):
        lib = self.settings.get("library") or ""
        self.lib_name.configure(text=os.path.basename(lib) if lib else t("no_library"))
        self.lib_path.configure(text=lib or t("no_library_hint"))

    def set_busy(self, busy, text=None):
        if busy:
            self.go.state(["disabled"])
            self.btn_refresh.state(["disabled"])
            self.progress.pack(side="right", padx=(0, 12))
            self.progress.start(12)
            self.config(cursor="watch")
            if text:
                self.set_status("info", text)
        else:
            self.progress.stop()
            self.progress.pack_forget()
            self.btn_refresh.state(["!disabled"])
            self.config(cursor="")

    # ---- azioni

    def open_settings(self):
        d = SettingsDialog(self)
        self.wait_window(d)
        if d.saved:
            self.apply_settings()

    def apply_settings(self):
        """Dopo il salvataggio delle impostazioni: se la lingua è cambiata, ricostruisce la finestra."""
        global LANG
        before = LANG
        LANG = resolve_language(self.settings.get("language"))
        if LANG != before:
            self.outer.destroy()
            self._build()
            self.title(APP_NAME)
            self.refresh() if is_library(self.settings.get("library")) else self.set_status("info", t("st_choose"))

    def cli(self):
        cli = self.settings.get("cli") or DEFAULT_CLI
        if is_cli(cli):
            return cli
        Dialog.ask(self, APP_NAME, t("cli_missing_title"), t("cli_missing"), level="warn")
        cli = filedialog.askopenfilename(title=t("cli_pick"), filetypes=[("lightcraft-cli.exe", "lightcraft-cli.exe")])
        if cli and is_cli(cli):
            self.settings["cli"] = os.path.normpath(cli)
            save_settings(self.settings)
            return self.settings["cli"]
        return None

    def choose(self):
        start = self.settings.get("library") or os.path.expanduser("~")
        lib = filedialog.askdirectory(title=t("pick_library"), initialdir=start)
        if not lib:
            return
        lib = os.path.normpath(lib)
        if not is_library(lib):
            Dialog.ask(self, APP_NAME, t("pick_library"), t("not_library"), level="error")
            return
        self.settings["library"] = lib
        save_settings(self.settings)
        self.refresh()

    def refresh(self):
        self.update_library_label()
        lib = self.settings.get("library")
        if not is_library(lib):
            self.set_status("warn", t("st_lib_gone"))
            return
        self.set_busy(True, t("st_reading"))
        self.tree.delete(*self.tree.get_children())

        def work():
            try:
                plan = build_plan(lib)
                reason = library_open_reason(lib)
                self.after(0, self.show, plan, reason, None)
            except Exception as e:  # noqa: BLE001 — qualsiasi errore va mostrato all'utente
                self.after(0, self.show, [], None, e)
        threading.Thread(target=work, daemon=True).start()

    def show(self, plan, reason, error):
        self.set_busy(False)
        self.plan, self.reason = plan, reason
        if error:
            self.set_status("error", t("st_read_error", error=error))
            return
        self.rows.clear()
        self.show_preview(None)
        for item in plan:
            if not item["files"]:
                row = self.tree.insert("", "end", values=(item["name"], os.path.dirname(item["path"] or ""), "",
                                                          t(item["note"])), tags=("muted",))
                self.rows[row] = item
                continue
            for i, (f, size) in enumerate(zip(item["files"], item["sizes"])):
                note = t("st_delete") if i == 0 else t("st_companion")
                row = self.tree.insert("", "end", values=(os.path.basename(f), os.path.dirname(f), human(size), note),
                                       tags=() if i == 0 else ("companion",))
                self.rows[row] = item
        n_files = sum(len(i["files"]) for i in plan)
        self.stat_vars["photos"].set(str(len(plan)))
        self.stat_vars["files"].set(str(n_files))
        self.stat_vars["bytes"].set(human(sum(i["bytes"] for i in plan)))
        if reason:
            self.set_status("warn", t(reason))
        elif not plan:
            self.set_status("ok", t("st_empty"))
        else:
            self.set_status("info", t("st_ready", go=t("go")))
            self.go.state(["!disabled"])

    def confirm(self):
        n_files = sum(len(i["files"]) for i in self.plan)
        total = sum(i["bytes"] for i in self.plan)
        answer = Dialog.ask(self, t("confirm_title"), t("confirm_head", files=n_files, size=human(total)),
                            t("confirm_body", photos=len(self.plan)), level="warn",
                            buttons=[("cancel", t("btn_cancel"), False), ("delete", t("btn_delete"), True)],
                            default="cancel")
        if answer != "delete":
            return
        cli = self.cli()
        if not cli:
            return
        lib, plan = self.settings["library"], self.plan
        self.set_busy(True, t("st_working"))

        def work():
            try:
                self.after(0, self.done, execute(lib, cli, plan), None)
            except Exception as e:  # noqa: BLE001
                log(f"ERROR: {e}")
                self.after(0, self.done, None, e)
        threading.Thread(target=work, daemon=True).start()

    def done(self, result, error):
        self.set_busy(False)
        if error:
            Dialog.ask(self, APP_NAME, t("error_title"), str(error), level="error")
        else:
            detail = ""
            if result["failed"]:
                detail = t("done_failed") + "\n" + "\n".join(result["failed"][:20]) + "\n\n"
            detail += t("done_backup") + "\n" + result["backup"]
            Dialog.ask(self, APP_NAME, t("done_warn_title") if result["failed"] else t("done_title"),
                       t("done_body", removed=result["removed"], files=result["files"], left=result["left"]),
                       level="warn" if result["failed"] else "ok", detail=detail)
        self.refresh()

    def open_log(self):
        if os.path.exists(LOG):
            os.startfile(LOG)
        else:
            Dialog.ask(self, APP_NAME, t("open_log"), t("log_empty"))

    # ---- anteprima

    def on_select(self, _event=None):
        sel = self.tree.selection()
        self.show_preview(self.rows.get(sel[0]) if sel else None)

    def show_preview(self, item):
        self.current = item
        if item is None:
            self.preview_name.configure(text="")
            self.preview_info.configure(text="")
            self._tk_img = None
            self.preview_img.configure(image="", text=t("preview_hint"))
            return
        self.preview_name.configure(text=item["name"])
        lines = []
        if item.get("captured"):
            try:
                when = datetime.datetime.fromisoformat(item["captured"][:19])
                lines.append(t("taken", date=when.strftime(DATE_FORMATS.get(LANG, "%d/%m/%Y")),
                               time=when.strftime("%H:%M")))
            except ValueError:
                pass
        if item.get("camera"):
            lines.append(item["camera"])
        w, h = item.get("size_px") or (None, None)
        if w and h:
            lines.append(f"{w} × {h} px · {human(item['bytes'])}" if item["bytes"] else f"{w} × {h} px")
        self.preview_info.configure(text="\n".join(lines))
        path = item.get("path")
        if not path or not os.path.exists(path) or item.get("kind") == "video":
            self._tk_img = None
            self.preview_img.configure(image="", text=t("preview_none"))
            return
        if path in self.previews:
            self.render_preview()
            return
        self._tk_img = None
        self.preview_img.configure(image="", text=t("preview_loading"))

        def work():
            try:
                im = load_preview(path)
            except Exception:  # noqa: BLE001 — un file illeggibile mostra solo il messaggio
                im = None
            self.after(0, self._preview_loaded, path, im)
        threading.Thread(target=work, daemon=True).start()

    def _preview_loaded(self, path, im):
        self.previews[path] = im
        if self.current and self.current.get("path") == path:
            self.render_preview()

    def render_preview(self):
        item = self.current
        im = self.previews.get(item.get("path")) if item else None
        if im is None:
            if item and item.get("path") in self.previews:
                self.preview_img.configure(image="", text=t("preview_none"))
            return
        w, h = max(50, self.preview_img.winfo_width() - 8), max(50, self.preview_img.winfo_height() - 8)
        fit = im.copy()
        fit.thumbnail((w, h), Image.LANCZOS)
        self._tk_img = ImageTk.PhotoImage(fit)
        self.preview_img.configure(image=self._tk_img, text="")

    def open_large(self):
        item = self.current
        im = self.previews.get(item.get("path")) if item else None
        if im is None:
            return
        win = tk.Toplevel(self)
        win.title(item["name"])
        win.configure(bg="#111111")
        set_icon(win)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        big = im.copy()
        big.thumbnail((int(sw * 0.85), int(sh * 0.8)), Image.LANCZOS)
        photo = ImageTk.PhotoImage(big)
        lbl = tk.Label(win, image=photo, bg="#111111", bd=0, cursor="hand2")
        lbl.image = photo
        lbl.pack(padx=12, pady=12)
        tk.Label(win, text=t("close_hint"), bg="#111111", fg=MUTED, font=self.f_small).pack(pady=(0, 8))
        x = (sw - big.width - 24) // 2
        y = max(0, (sh - big.height - 60) // 2 - 20)
        win.geometry(f"+{x}+{y}")
        for seq in ("<Escape>", "<Button-1>"):
            win.bind(seq, lambda e: win.destroy())
        dark_title_bar(win)
        win.focus_force()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    App().mainloop()


if __name__ == "__main__":
    main()
