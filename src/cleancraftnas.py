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
import tempfile
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from tkinter import filedialog, ttk

from PIL import Image, ImageOps, ImageTk

import i18n
import updater
from i18n import registry_value, t
from translations import DATE_FORMATS, LANGUAGES
from ui_theme import (LEVELS, MUTED, TEXT, Dialog, attach_scrollbars, center_on, dark_title_bar, dpi_aware,
                      set_icon, setup_theme)
from version import APP_NAME, VERSION

DONATE_URL = "https://buymeacoffee.com/poty87"

LOCAL = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
# impostazioni e registro dell'utente: l'app installata vive in una cartella che non si modifica
DATA_DIR = os.path.join(LOCAL, APP_NAME)
OLD_DATA_DIR = os.path.join(LOCAL, "Pulizia cestino Lightcraft")  # nome delle versioni fino alla 1.1
SETTINGS = os.path.join(DATA_DIR, "settings.json")
LOG = os.path.join(DATA_DIR, "cleancraftnas.log")
DEFAULT_CLI = os.path.join(LOCAL, r"Programs\ArtCraft\LightCraft\lightcraft-cli.exe")
# file con lo stesso nome della foto che vengono cancellati insieme a lei
COMPANIONS = (".xmp", ".jpg", ".jpeg")
BACKUPS_KEPT = 5
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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

# i lightcraft-cli avviati da PresetCraftAppLicator ({pid: libreria su cui lavora, "" se nessuna}): lavora spesso in
# sottofondo (volti, anteprime, modifiche dal telefono) e non è "Lightcraft aperto", se non sulla stessa libreria
PCA_OWN_CLI = os.path.join(LOCAL, "PresetCraftAppLicator", "watch", "own-cli.json")


def lightcraft_processes():
    """[(nome, pid)] dei processi Lightcraft in esecuzione (app o riga di comando)."""
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    found = []
    for line in out.splitlines():
        cols = line.strip().strip('"').split('","')
        if len(cols) > 1 and cols[0].lower() in ("lightcraft.exe", "lightcraft-cli.exe") and cols[1].isdigit():
            found.append((cols[0].lower(), int(cols[1])))
    return found


def lightcraft_running():
    """Nomi dei processi Lightcraft in esecuzione (app o riga di comando)."""
    return sorted({name for name, _ in lightcraft_processes()})


def pca_cli():
    """I lightcraft-cli di PresetCraftAppLicator: {pid: libreria} (vuoto se non c'è o non si legge)."""
    try:
        with open(PCA_OWN_CLI, encoding="utf-8") as f:
            data = json.load(f)
        return {int(k): v or "" for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def library_open_reason(lib):
    """Chiave del testo che spiega perché la libreria non si può modificare adesso, oppure None."""
    procs = lightcraft_processes()
    pca = pca_cli() if procs else {}
    busy = False
    for name, pid in procs:
        if name == "lightcraft-cli.exe" and pid in pca:
            busy |= bool(pca[pid]) and same_path(pca[pid], lib)  # su un'altra libreria (o nessuna) non conta
        else:
            return "st_open_app"
    if busy:
        return "st_busy_pca"
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
        # il motivo vero sta nella risposta del comando fallito; stderr dice solo "1 command(s) failed"
        errors = [f"{x.get('command')}: {x.get('error')}" for x in replies if not x.get("ok")]
        detail = "; ".join(errors) or r.stderr.strip()
        raise RuntimeError(f"lightcraft-cli ({r.returncode}): {detail}")
    return replies


# ---------------------------------------------------------------- piano di cancellazione

def camera_name(meta):
    """"RICOH IMAGING COMPANY, LTD. RICOH GR IV" → "RICOH GR IV": il modello ripete già la marca."""
    camera, make = (meta.get("camera") or "").strip(), (meta.get("make") or "").strip()
    if make and camera.lower().startswith(make.lower()) and len(camera) > len(make):
        camera = camera[len(make):].strip()
    return camera


def file_times(path):
    """(creazione, ultima modifica) del file in secondi, oppure (None, None) se non c'è."""
    try:
        st = os.stat(path)
        return st.st_ctime, st.st_mtime  # su Windows st_ctime è la data di creazione
    except (OSError, TypeError, ValueError):
        return None, None


def io_workers():
    """Thread per leggere dal disco: il doppio dei core logici, tra 4 e 16. Il lavoro aspetta soprattutto il NAS (non la
    CPU), quindi più thread sovrappongono le attese; oltre 16 un NAS domestico non risponde più in fretta."""
    return max(4, min(16, 2 * (os.cpu_count() or 2)))


def list_folder(folder):
    """File di una cartella: {nome in minuscolo: (nome, dimensione, creazione, modifica)}, oppure None se non si legge.

    Un solo elenco dà anche dimensioni e date (su Windows arrivano insieme ai nomi), senza chiederle file per file."""
    found = {}
    try:
        with os.scandir(folder) as entries:
            for e in entries:
                try:
                    if e.is_file():
                        st = e.stat()
                        created = getattr(st, "st_birthtime", st.st_ctime)  # su Windows st_ctime è la creazione
                        found[e.name.lower()] = (e.name, st.st_size, created, st.st_mtime)
                except OSError:
                    continue
    except OSError:
        return None
    return found


def list_folders(folders):
    """Elenchi di più cartelle, letti in parallelo: {cartella normalizzata: elenco o None}."""
    folders = sorted({os.path.normcase(f) for f in folders if f})
    with ThreadPoolExecutor(max_workers=io_workers()) as pool:
        return dict(zip(folders, pool.map(list_folder, folders)))


def build_plan(lib, jpeg_twins=True):
    """Elenca le foto nel cestino e i file da cancellare per ciascuna."""
    cat = read_catalog(lib)
    photos = cat["photos"].values()

    def path_of(p):
        s = p.get("source") or {}
        return s.get("path") if s.get("type") == "file" else None

    # ogni cartella si legge una volta sola (prima si rileggeva per ogni foto: in una cartella del NAS con 20.000 file
    # sono più di 20 minuti per 1000 foto), e le cartelle si leggono in parallelo
    trashed = [p for p in photos if p.get("deleted")]
    t0 = time.time()
    listings = list_folders(os.path.dirname(path_of(p)) for p in trashed if path_of(p))
    log(f"plan: {len(trashed)} in the trash, {len(listings)} folders listed in {time.time() - t0:.1f} s")

    def info(full):
        """(nome, dimensione, creazione, modifica) del file, oppure None se non c'è."""
        listing = listings.get(os.path.normcase(os.path.dirname(full)))
        if listing is not None:
            return listing.get(os.path.basename(full).lower())
        try:  # cartella non elencabile: si chiede al file direttamente
            st = os.stat(full)
            return os.path.basename(full), st.st_size, st.st_ctime, st.st_mtime
        except OSError:
            return None

    # percorsi ancora usati da foto attive: quei file non si toccano mai
    active = {os.path.normcase(path_of(p)) for p in photos if not p.get("deleted") and path_of(p)}
    planned = set()  # un file compare una volta sola, anche se è il JPG di un'altra foto nel cestino
    plan = []
    for p in sorted(trashed, key=lambda p: path_of(p) or ""):
        path = path_of(p)
        meta = p.get("meta") or {}
        item = {"id": int(p["id"]), "name": p.get("file_name") or "", "path": path, "files": [], "note": None,
                "captured": p.get("captured"), "camera": camera_name(meta),
                # l'autore sta nel campo "creator"; molte fotocamere scrivono il nome solo nel copyright
                "author": (meta.get("creator") or meta.get("copyright") or "").strip(),
                "size_px": (p.get("width"), p.get("height")), "kind": p.get("kind")}
        if not path:
            item["note"] = "note_demo"
        elif os.path.normcase(path) in active:
            item["note"] = "note_shared"
        elif info(path) is None:
            item["note"] = "note_missing"
        elif os.path.normcase(path) in planned:
            item["note"] = "note_dup"
        else:
            item["files"].append(path)
            base = os.path.splitext(path)[0]
            folder = os.path.dirname(path)
            listing = listings.get(os.path.normcase(folder))
            if listing is not None:
                names = {low: entry[0] for low, entry in listing.items()}
            else:
                try:
                    names = {n.lower(): n for n in os.listdir(folder)}
                except OSError:
                    names = {}
            # i JPEG con lo stesso nome (scatti RAW+JPEG non importati) si tolgono solo se richiesto; l'.xmp sempre
            for ext in (COMPANIONS if jpeg_twins else tuple(e for e in COMPANIONS if e not in (".jpg", ".jpeg"))):
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
        details = {f: info(f) for f in item["files"]}
        item["sizes"] = [details[f][1] if details[f] else 0 for f in item["files"]]
        item["bytes"] = sum(item["sizes"])
        # date di creazione e ultima modifica di ogni file (dagli elenchi delle cartelle, già letti)
        timed = []
        for f in item["files"] or ([path] if path else []):
            entry = details.get(f) or info(f)
            timed.append((entry[2], entry[3]) if entry else (None, None))
        item["times"] = timed or [(None, None)]
        # il file della foto c'è ancora sul disco? None per le foto dimostrative, che non hanno file
        item["present"] = None if not path else item["note"] != "note_missing"
        # cosa fare della foto: "full" = file dal disco e foto dal cestino, "trash" = solo dal cestino,
        # "keep" = lasciarla nel cestino. Senza file da cancellare il massimo è "trash".
        item["action"] = "full" if item["files"] else "trash"
        plan.append(item)
    return plan


ACTIONS = ("full", "trash", "keep")


def set_action(item, action):
    """Applica un'azione a una foto; "full" su una foto senza file diventa "trash"."""
    item["action"] = "trash" if action == "full" and not item["files"] else action


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


DELETE_BATCH = 50  # file per ogni chiamata a Windows: meno chiamate, stesso cestino


def delete_file(path):
    """Cestino di Windows per i dischi locali; sul NAS il file va nel cestino di Synology, se attivo."""
    rc = delete_files([path])
    if rc != 0 or os.path.exists(path):
        raise OSError(f"code {rc}")


def delete_files(paths):
    """Sposta più file nel cestino con una sola operazione di Windows; restituisce il codice di Windows (0 = tutto ok).

    Quali file sono davvero spariti lo dice solo un controllo dopo: con un errore alcuni possono essere già andati."""
    op = SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom="\0".join(paths) + "\0\0",
                         fFlags=FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return rc or (1 if op.fAnyOperationsAborted else 0)


def existing(paths):
    """{percorso: esiste?} per molti file, controllati in parallelo (sul NAS ogni controllo è un'attesa di rete)."""
    paths = list(dict.fromkeys(paths))
    if not paths:
        return {}
    with ThreadPoolExecutor(max_workers=io_workers()) as pool:
        return dict(zip(paths, pool.map(os.path.exists, paths)))


# colonne dell'elenco: (id, testo, larghezza, allineamento, si allarga); i clic sulle intestazioni ordinano
COLUMNS = (("name", "col_file", 156, "w", False), ("present", "col_present", 82, "w", False),
           ("folder", "col_folder", 110, "w", True),
           ("size", "col_size", 82, "e", False), ("created", "col_created", 118, "w", False),
           ("modified", "col_modified", 118, "w", False), ("camera", "col_camera", 116, "w", False),
           ("author", "col_author", 110, "w", False), ("note", "col_status", 176, "w", False))
COLUMN_IDS = [c[0] for c in COLUMNS]
STATUS_COLUMN = COLUMN_IDS.index("note")
# colonne visibili finché l'utente non sceglie diversamente (clic destro sull'intestazione o pulsante Colonne)
DEFAULT_COLUMNS = ["name", "present", "folder", "size", "modified", "camera", "note"]

# colori tenui delle righe (testo, sfondo): il testo resta leggibile anche sulle righe colorate
ROW_COLORS = {
    "full": ("#f6e3e3", "#4d2b30"),   # rosso: file dal disco e foto dal cestino
    "trash": ("#f5ecd2", "#4a3f20"),  # giallo: solo dal cestino
    "keep": ("#dff2e5", "#24432f"),   # verde: resta nel cestino
}

BACKUP_PREFIX = "CleanCraftNas backup - "
LEGACY_BACKUP_PREFIX = "Backup pulizia cestino - "  # versioni 1.0–1.1
STAMP = "%Y-%m-%d %H.%M.%S"


def backup_root(lib, settings):
    """Cartella dei backup di una libreria: accanto alla libreria (la sua cartella resta di Lightcraft) o in quella
    scelta nelle Impostazioni, sempre in una sottocartella col nome della libreria."""
    base = settings.get("backup_dir") or os.path.dirname(lib)
    return os.path.join(base, BACKUP_PREFIX + os.path.basename(lib))


def backup_library(lib, root, kept=BACKUPS_KEPT):
    dest = os.path.join(root, datetime.datetime.now().strftime(STAMP))
    os.makedirs(dest)
    for name in ("catalog.snap", "catalog.log", "view.json"):
        src = os.path.join(lib, name)
        if os.path.exists(src):
            shutil.copy2(src, dest)
    for old in [b["path"] for b in list_backups_in(root)][kept:]:
        shutil.rmtree(old, ignore_errors=True)
    return dest


def list_backups_in(root):
    """Backup trovati in una cartella, dal più recente: [{path, when, bytes}]."""
    found = []
    try:
        names = os.listdir(root)
    except OSError:
        return found
    for name in names:
        path = os.path.join(root, name)
        try:
            when = datetime.datetime.strptime(name, STAMP)
        except ValueError:
            continue
        if not os.path.isfile(os.path.join(path, "catalog.snap")):
            continue
        size = sum(os.path.getsize(os.path.join(path, f)) for f in os.listdir(path)
                   if os.path.isfile(os.path.join(path, f)))
        found.append({"path": path, "when": when, "bytes": size})
    return sorted(found, key=lambda b: b["when"], reverse=True)


def list_backups(lib, settings):
    """Tutti i backup della libreria: nella cartella attuale, accanto alla libreria e quelli delle versioni 1.0–1.1."""
    roots = {backup_root(lib, settings), backup_root(lib, {}),
             os.path.join(os.path.dirname(lib), LEGACY_BACKUP_PREFIX + os.path.basename(lib))}
    backups = [b for root in roots for b in list_backups_in(root)]
    return sorted(backups, key=lambda b: b["when"], reverse=True)


def delete_backups(paths):
    """Sposta i backup nel Cestino; toglie le cartelle che restano vuote. Restituisce gli errori."""
    failed = []
    for path in paths:
        try:
            delete_file(path)
            log(f"backup deleted {path}")
        except OSError as e:
            failed.append(f"{path}: {e}")
            log(f"ERROR deleting backup {path}: {e}")
        root = os.path.dirname(path)
        try:
            if os.path.isdir(root) and not os.listdir(root):
                os.rmdir(root)
        except OSError:
            pass
    return failed


def remove_from_trash(cli, lib, ids):
    """Toglie le foto dalla libreria con photo.deletePermanently.

    Lightcraft accetta il comando solo se nella libreria c'è una selezione, anche quando riceve gli id: prima si
    apre il cestino e si selezionano proprio quelle foto. La vista salvata (view.json) poi torna com'era, così
    all'apertura di Lightcraft non ci si ritrova nel cestino.
    """
    view = os.path.join(lib, "view.json")
    try:
        with open(view, "rb") as f:
            saved_view = f.read()
    except OSError:
        saved_view = None
    try:
        run_cli(cli, lib, [("library.source", {"kind": "recentlyDeleted"}),
                           ("library.select", {"ids": ids}),
                           ("photo.deletePermanently", {"ids": ids})])
    finally:
        if saved_view is not None:
            with open(view, "wb") as f:
                f.write(saved_view)


def execute(lib, cli, plan, root, kept=BACKUPS_KEPT):
    """Cancella i file e toglie dalla libreria le foto i cui file non ci sono più (o restano ad altre foto)."""
    reason = library_open_reason(lib)
    if reason:
        raise RuntimeError(t(reason))
    backup = backup_library(lib, root, kept)
    log(f"--- cleanup of {lib} (backup: {backup})")
    removed, failed, deleted_files = [], [], 0
    missing, trash_only = [], []  # nomi delle foto tolte solo dal cestino: file già spariti / scelta dell'utente
    to_delete = []  # foto i cui file vanno cancellati dal disco
    for item in plan:
        if item["action"] == "keep":
            continue
        if item["action"] == "trash" or not item["files"]:
            removed.append(item["id"])
            if item["note"] == "note_missing":
                missing.append(item["path"] or item["name"])
                log(f"not on disk, removed from trash only: {item['path']}")
            else:
                trash_only.append(item["path"] or item["name"])
                log(f"removed from trash only, file kept: {item['path']}")
            continue
        to_delete.append(item)
    # i file si cancellano a blocchi (una chiamata a Windows ogni DELETE_BATCH file), poi si controlla quali sono
    # davvero spariti; una foto esce dal cestino di LightCraft solo se tutti i suoi file sono andati
    before = existing(f for item in to_delete for f in item["files"])
    for f, present in before.items():
        if not present:
            log(f"already gone {f}")
    queue = [f for f, present in before.items() if present]
    errors = {}
    for start in range(0, len(queue), DELETE_BATCH):
        batch = queue[start:start + DELETE_BATCH]
        rc = delete_files(batch)
        after = existing(batch)
        if rc:
            # al primo file che non si può cancellare Windows lascia perdere il resto del blocco: quelli rimasti si
            # riprovano uno alla volta, così in errore resta solo chi non si cancella davvero
            for f in [f for f in batch if after[f]]:
                code = delete_files([f])
                after[f] = os.path.exists(f)
                if after[f]:
                    errors[f] = f"code {code}" if code else "still on disk"
        for f in batch:
            if after[f]:
                errors.setdefault(f, "still on disk")
                log(f"ERROR {f}: {errors[f]}")
            else:
                deleted_files += 1
                log(f"deleted {f}")
    for item in to_delete:
        bad = [f for f in item["files"] if f in errors]
        failed += [f"{f}: {errors[f]}" for f in bad]
        if not bad:
            removed.append(item["id"])
    if removed:
        remove_from_trash(cli, lib, removed)
    left = sum(1 for p in read_catalog(lib)["photos"].values() if p.get("deleted"))
    log(f"removed from library: {len(removed)}, files deleted: {deleted_files}, errors: {len(failed)}, "
        f"not on disk: {len(missing)}, trash only: {len(trash_only)}, still in trash: {left}")
    return {"removed": len(removed), "files": deleted_files, "failed": failed, "left": left, "backup": backup,
            "missing": missing, "trash_only": trash_only, "removed_ids": removed}


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            if unit == "B":
                return f"{n:.0f} {unit}"
            text = f"{n:.1f} {unit}"
            return text if i18n.LANG == "en" else text.replace(".", ",")
        n /= 1024


# ---------------------------------------------------------------- impostazioni

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

        ttk.Label(frame, text=t("backup_label").upper(), style="Muted.TLabel").pack(anchor="w", pady=(18, 4))
        self.backup_mode = tk.StringVar(value="custom" if app.settings.get("backup_dir") else "library")
        self.backup_dir = tk.StringVar(value=app.settings.get("backup_dir") or "")
        ttk.Radiobutton(frame, text=t("backup_next_to"), value="library", variable=self.backup_mode,
                        command=self.backup_mode_changed).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(4, 0))
        ttk.Radiobutton(row, text=t("backup_custom"), value="custom", variable=self.backup_mode,
                        command=self.backup_mode_changed).pack(side="left")
        self.backup_entry = ttk.Entry(row, textvariable=self.backup_dir)
        self.backup_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.backup_browse = ttk.Button(row, text=t("btn_browse"), command=self.browse_backup_dir)
        self.backup_browse.pack(side="left", padx=(8, 0))
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text=t("backup_kept"), style="Body.TLabel").pack(side="left")
        self.kept = tk.IntVar(value=app.settings.get("backups_kept", BACKUPS_KEPT))
        ttk.Spinbox(row, from_=1, to=50, textvariable=self.kept, width=5, state="readonly").pack(side="left",
                                                                                               padx=(10, 0))
        ttk.Label(frame, text=t("backup_hint"), style="Muted.TLabel", wraplength=560, justify="left").pack(
            anchor="w", pady=(4, 0))
        self.backup_mode_changed()

        ttk.Label(frame, text=t("updates_label").upper(), style="Muted.TLabel").pack(anchor="w", pady=(18, 4))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.auto_update = tk.BooleanVar(value=app.settings.get("check_updates", True))
        ttk.Checkbutton(row, text=t("upd_auto"), variable=self.auto_update).pack(side="left")
        ttk.Button(row, text=t("upd_check_now"), command=lambda: app.check_updates(manual=True, parent=self)).pack(
            side="right")
        ttk.Label(frame, text=t("upd_hint"), style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        about = ttk.Frame(frame)
        about.pack(fill="x", pady=(18, 0))
        ttk.Label(about, text=f"{APP_NAME} · " + t("about", version=VERSION), style="Muted.TLabel").pack(side="left")
        # donazioni: la pagina Buy Me a Coffee del progetto, nel browser
        coffee = ttk.Label(about, text=t("donate"), style="Link.TLabel", cursor="hand2")
        coffee.pack(side="right")
        coffee.bind("<Button-1>", lambda e: __import__("webbrowser").open(DONATE_URL))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text=t("btn_save"), style="Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(buttons, text=t("btn_cancel"), command=self.destroy).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self.destroy())

        center_on(self, app)
        dark_title_bar(self)
        self.deiconify()
        self.grab_set()

    def browse(self):
        start = os.path.dirname(self.cli.get()) if os.path.isdir(os.path.dirname(self.cli.get())) else LOCAL
        path = filedialog.askopenfilename(parent=self, title=t("cli_pick"), initialdir=start,
                                          filetypes=[("lightcraft-cli.exe", "lightcraft-cli.exe")])
        if path:
            self.cli.set(os.path.normpath(path))

    def backup_mode_changed(self):
        state = ["!disabled"] if self.backup_mode.get() == "custom" else ["disabled"]
        self.backup_entry.state(state)
        self.backup_browse.state(state)

    def browse_backup_dir(self):
        start = self.backup_dir.get() if os.path.isdir(self.backup_dir.get()) else os.path.expanduser("~")
        path = filedialog.askdirectory(parent=self, title=t("backups_pick"), initialdir=start)
        if path:
            self.backup_dir.set(os.path.normpath(path))

    def save(self):
        cli = self.cli.get().strip()
        # il percorso predefinito si accetta anche se Lightcraft non c'è ancora: lo si chiede al momento di cancellare
        if cli and os.path.normcase(cli) != os.path.normcase(DEFAULT_CLI) and not is_cli(cli):
            Dialog.ask(self, t("settings"), t("cli_bad"), cli, level="warn")
            return
        backup_dir = self.backup_dir.get().strip() if self.backup_mode.get() == "custom" else ""
        if self.backup_mode.get() == "custom" and not os.path.isdir(backup_dir):
            Dialog.ask(self, t("settings"), t("backup_dir_bad"), backup_dir or None, level="warn")
            return
        if backup_dir:
            self.app.settings["backup_dir"] = os.path.normpath(backup_dir)
        else:
            self.app.settings.pop("backup_dir", None)
        self.app.settings["backups_kept"] = max(1, min(50, int(self.kept.get())))
        self.app.settings["language"] = self.lang_codes[self.lang.current()]
        self.app.settings["check_updates"] = bool(self.auto_update.get())
        if cli and os.path.normcase(cli) != os.path.normcase(DEFAULT_CLI):
            self.app.settings["cli"] = cli
        else:
            self.app.settings.pop("cli", None)
        save_settings(self.app.settings)
        self.saved = True
        self.destroy()


class BackupsDialog(tk.Toplevel):
    """Elenco dei backup della libreria corrente, con apertura della cartella ed eliminazione."""

    def __init__(self, app):
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.lib = app.settings.get("library")
        self.title(t("backups_title"))
        self.geometry("760x460")
        self.minsize(620, 360)
        self.transient(app)
        set_icon(self)
        frame = ttk.Frame(self, padding=(24, 22, 24, 18))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=t("backups_title"), style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text=t("backups_intro"), style="Body.TLabel", wraplength=700, justify="left").pack(
            anchor="w", pady=(6, 0))
        self.where = ttk.Label(frame, style="Muted.TLabel", wraplength=700, justify="left")
        self.where.pack(anchor="w", pady=(6, 0))

        buttons = ttk.Frame(frame)
        buttons.pack(side="bottom", fill="x", pady=(14, 0))
        ttk.Button(buttons, text=t("w_close"), style="Accent.TButton", command=self.destroy).pack(side="right")
        self.btn_all = ttk.Button(buttons, text=t("btn_delete_all"), command=lambda: self.delete(all_=True))
        self.btn_all.pack(side="right", padx=(0, 8))
        self.btn_sel = ttk.Button(buttons, text=t("btn_delete_selected"), command=self.delete)
        self.btn_sel.pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text=t("btn_open_folder"), command=self.open_folder).pack(side="left")
        self.total = ttk.Label(buttons, style="Muted.TLabel")
        self.total.pack(side="left", padx=(12, 0))

        listf = ttk.Frame(frame)
        listf.pack(fill="both", expand=True, pady=(14, 0))
        self.tree = ttk.Treeview(listf, columns=("when", "size", "folder"), show="headings", selectmode="extended")
        for c, title, w, anchor, stretch in (("when", t("col_date"), 170, "w", False),
                                             ("size", t("col_size") + "   ", 100, "e", False),
                                             ("folder", "   " + t("col_folder"), 380, "w", True)):
            self.tree.heading(c, text=title, anchor=anchor)
            self.tree.column(c, width=w, minwidth=60, anchor=anchor, stretch=stretch)
        attach_scrollbars(self.tree)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_buttons())
        self.bind("<Escape>", lambda e: self.destroy())

        self.load()
        center_on(self, app)
        dark_title_bar(self)
        self.deiconify()
        self.grab_set()

    def load(self):
        self.tree.delete(*self.tree.get_children())
        self.backups = {}
        if not is_library(self.lib):
            self.where.configure(text=t("no_library"))
            self.update_buttons()
            return
        self.where.configure(text=t("col_folder") + ": " + backup_root(self.lib, self.app.settings))
        fmt = DATE_FORMATS.get(i18n.LANG, "%d/%m/%Y") + "  %H:%M:%S"
        for b in list_backups(self.lib, self.app.settings):
            row = self.tree.insert("", "end", values=(b["when"].strftime(fmt), human(b["bytes"]),
                                                      os.path.dirname(b["path"])))
            self.backups[row] = b
        total = sum(b["bytes"] for b in self.backups.values())
        self.total.configure(text=t("backups_total", count=len(self.backups), size=human(total)) if self.backups
                             else t("backups_none"))
        self.update_buttons()

    def update_buttons(self):
        self.btn_sel.state(["!disabled"] if self.tree.selection() else ["disabled"])
        self.btn_all.state(["!disabled"] if self.backups else ["disabled"])

    def open_folder(self):
        sel = self.tree.selection()
        path = self.backups[sel[0]]["path"] if sel else backup_root(self.lib, self.app.settings) if self.lib else None
        if path and os.path.isdir(path):
            os.startfile(path)
        elif path and os.path.isdir(os.path.dirname(path)):
            os.startfile(os.path.dirname(path))

    def delete(self, all_=False):
        chosen = list(self.backups.values()) if all_ else [self.backups[r] for r in self.tree.selection()]
        if not chosen:
            return
        size = human(sum(b["bytes"] for b in chosen))
        answer = Dialog.ask(self, t("backups_title"), t("backups_delete_head", count=len(chosen), size=size),
                            t("backups_delete_body"), level="warn",
                            buttons=[("cancel", t("btn_cancel"), False), ("delete", t("btn_delete"), True)],
                            default="cancel")
        if answer != "delete":
            return
        self.config(cursor="watch")
        self.update()
        failed = delete_backups([b["path"] for b in chosen])
        self.config(cursor="")
        if failed:
            Dialog.ask(self, t("backups_title"), t("backups_delete_failed"), None, level="error",
                       detail="\n".join(failed[:20]))
        self.load()


# ---------------------------------------------------------------- finestra principale

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title(APP_NAME)
        self.geometry("1380x760")
        self.minsize(960, 560)
        set_icon(self)
        setup_theme(self)
        self.settings = load_settings()
        # fino alla 1.4 c'era una sola libreria: diventa la prima dell'elenco
        libraries = self.settings.setdefault("libraries", [])
        if self.settings.get("library") and self.settings["library"] not in libraries:
            libraries.insert(0, self.settings["library"])
        i18n.set_language(self.settings.get("language") or registry_value("Language"))
        self.plan = []
        self.reason = None
        self.release = None  # ultima release più nuova di questa, se trovata
        self.previews = {}  # percorso -> immagine Pillow (o None se non leggibile)
        self._build()
        dark_title_bar(self)
        self.deiconify()
        self.after(150, self.refresh)
        if self.settings.get("check_updates", True):
            self.after(2500, self.check_updates)  # in silenzio: se c'è una versione nuova compare il link in basso

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

        # libreria: menu a tendina con le librerie salvate
        card = ttk.Frame(outer, style="Card.TFrame", padding=(16, 12))
        card.pack(fill="x", pady=(16, 0))
        info = ttk.Frame(card)
        info.pack(side="left", fill="x", expand=True)
        ttk.Label(info, text=t("library"), style="Muted.TLabel").pack(anchor="w")
        self.lib_combo = ttk.Combobox(info, state="readonly", width=48, font=self.f_strong)
        self.lib_combo.pack(anchor="w", pady=(4, 2))
        self.lib_combo.bind("<<ComboboxSelected>>", self.on_library_selected)
        self.lib_path = ttk.Label(info, style="Muted.TLabel")
        self.lib_path.pack(anchor="w")
        self.btn_refresh = ttk.Button(card, text="↻  " + t("refresh"), command=self.refresh)
        self.btn_refresh.pack(side="right")
        self.btn_remove = ttk.Button(card, text=t("remove_library"), command=self.remove_library)
        self.btn_remove.pack(side="right", padx=(0, 8))
        ttk.Button(card, text="＋  " + t("add_library"), command=self.add_library).pack(side="right", padx=(0, 8))
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
        ttk.Button(foot, text=t("backups_btn"), command=self.open_backups).pack(side="left", padx=(8, 0))
        ttk.Label(foot, text=f"v{VERSION}", style="Muted.TLabel").pack(side="left", padx=(12, 0))
        # compare solo se il controllo all'avvio trova una versione più nuova
        self.update_link = ttk.Label(foot, style="Link.TLabel", cursor="hand2")
        self.update_link.bind("<Button-1>", lambda e: self.offer_update())
        if self.release:
            self.show_update_link()
        self.go = ttk.Button(foot, text=t("go"), style="Accent.TButton", command=self.confirm)
        self.go.pack(side="right")
        self.progress = ttk.Progressbar(foot, mode="indeterminate", length=160)
        self.go.state(["disabled"])

        # elenco e anteprima, divisi da un separatore trascinabile
        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(14, 0))
        listf = ttk.Frame(panes)
        legend = ttk.Frame(listf)
        legend.pack(side="top", fill="x", pady=(0, 6))
        for action in ACTIONS:
            tk.Label(legend, text="    ", bg=ROW_COLORS[action][1], bd=0, highlightthickness=1,
                     highlightbackground="#5f6368").pack(side="left", padx=(0, 6))
            ttk.Label(legend, text=t("act_" + action), style="Muted.TLabel").pack(side="left", padx=(0, 14))
        self.btn_columns = ttk.Button(legend, text="☰  " + t("columns_btn"), command=self.columns_menu_at_button)
        self.btn_columns.pack(side="right")
        # JPEG con lo stesso nome del raw (RAW+JPEG): via insieme al raw, oppure lasciati sul disco
        self.jpeg_twins = tk.BooleanVar(value=bool(self.settings.get("jpeg_twins", True)))

        ttk.Label(legend, text=t("legend_hint"), style="Muted.TLabel").pack(side="right", padx=(0, 12))
        opts = ttk.Frame(listf)
        opts.pack(side="top", fill="x", pady=(0, 6))
        ttk.Checkbutton(opts, text=t("opt_jpeg_twins"), variable=self.jpeg_twins,
                        command=self.jpeg_twins_changed).pack(side="left")
        box = ttk.Frame(listf)  # elenco e barre di scorrimento, disposti con grid
        box.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(box, columns=COLUMN_IDS, show="headings", selectmode="extended")
        for c, key, w, anchor, stretch in COLUMNS:
            self.tree.heading(c, anchor=anchor, command=lambda c=c: self.sort_by(c))
            self.tree.column(c, width=w, minwidth=60, anchor=anchor, stretch=stretch)
        self.tree.configure(displaycolumns=self.visible_columns())
        self.sort = tuple(self.settings.get("sort", ("folder", False)))
        self.update_headings()
        for action, (fg, bg) in ROW_COLORS.items():
            self.tree.tag_configure(action, foreground=fg, background=bg)
        self.tree.tag_configure("companion", foreground=MUTED)  # dopo i colori: vince sul testo
        attach_scrollbars(self.tree)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Button-3>", self.right_click)
        # trascinare un'intestazione sposta la colonna; un clic semplice continua a ordinare
        self.tree.bind("<ButtonPress-1>", self.heading_press, add="+")
        self.tree.bind("<B1-Motion>", self.heading_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self.heading_release, add="+")
        self.tree.bind("<App>", self.row_menu)  # tasto menu della tastiera
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
        self.after(60, lambda: panes.sashpos(0, int(panes.winfo_width() * 0.7)))

        self.rows = {}  # riga dell'elenco -> foto del piano
        self.current = None  # foto mostrata nell'anteprima
        self._tk_img = None

    def set_status(self, level, text):
        bg, accent = LEVELS[level]
        self.banner.configure(bg=bg)
        self.banner_bar.configure(bg=accent)
        self.banner_text.configure(bg=bg, text=text)

    def library_names(self):
        """Nome da mostrare per ogni libreria: la cartella, più quella che la contiene se due si chiamano uguali;
        ⚠ se la cartella non si trova (disco non collegato, cartella spostata)."""
        libs = self.settings.get("libraries", [])
        base = [os.path.basename(p) or p for p in libs]
        names = []
        for path, name in zip(libs, base):
            if base.count(name) > 1:
                name = f"{name}  ({os.path.basename(os.path.dirname(path))})"
            names.append(name if is_library(path) else "⚠  " + name)
        return names

    def update_library_label(self):
        libs = self.settings.get("libraries", [])
        lib = self.settings.get("library") or ""
        self.lib_combo.configure(values=self.library_names())
        if lib in libs:
            self.lib_combo.current(libs.index(lib))
        else:
            self.lib_combo.set(t("no_library"))
        self.lib_path.configure(text=lib or t("no_library_hint"))
        self.btn_remove.state(["!disabled"] if lib in libs else ["disabled"])

    def set_busy(self, busy, text=None):
        if busy:
            self.go.state(["disabled"])
            self.btn_refresh.state(["disabled"])
            self.lib_combo.state(["disabled"])
            self.progress.pack(side="right", padx=(0, 12))
            self.progress.start(12)
            self.config(cursor="watch")
            if text:
                self.set_status("info", text)
        else:
            self.progress.stop()
            self.progress.pack_forget()
            self.btn_refresh.state(["!disabled"])
            self.lib_combo.state(["!disabled", "readonly"])
            self.config(cursor="")

    # ---- aggiornamenti

    def check_updates(self, manual=False, parent=None):
        """Chiede a GitHub l'ultima release in background; manual=True mostra anche "nessun aggiornamento"."""
        def work():
            try:
                release, error = updater.latest_release(), None
            except Exception as e:  # noqa: BLE001 — rete assente, GitHub non raggiungibile…
                release, error = None, e
            self.after(0, self._update_checked, release, error, manual, parent)
        threading.Thread(target=work, daemon=True).start()

    def _update_checked(self, release, error, manual, parent):
        if not error:
            self.settings["last_update_check"] = time.time()
            save_settings(self.settings)
        if release and updater.is_newer(release["version"]):
            self.release = release
            self.show_update_link()
            if manual:
                self.offer_update(parent)
        elif manual:
            owner = parent if parent is not None and parent.winfo_exists() else self
            if error:
                Dialog.ask(owner, t("updates_label"), t("upd_check_failed", error=error), None, level="warn")
            else:
                Dialog.ask(owner, t("updates_label"), t("upd_none", version=VERSION), None, level="ok")

    def show_update_link(self):
        self.update_link.configure(text="⬆ " + t("upd_link", version=self.release["version"]))
        self.update_link.pack(side="left", padx=(10, 0))

    def offer_update(self, parent=None):
        rel = self.release
        if not rel:
            return
        owner = parent if parent is not None and parent.winfo_exists() else self
        notes = "\n".join(rel["notes"].splitlines()[:14]) or None
        answer = Dialog.ask(owner, t("upd_title"), t("upd_head", version=rel["version"]),
                            t("upd_body", current=VERSION), level="info", detail=notes,
                            buttons=[("later", t("btn_later"), False), ("update", t("btn_update_now"), True)])
        if answer != "update":
            return
        if isinstance(owner, tk.Toplevel):
            owner.destroy()
        self.set_busy(True, t("upd_downloading", percent=0))

        def progress(done, total):
            percent = int(done * 100 / total) if total else 0
            self.after(0, lambda: self.set_status("info", t("upd_downloading", percent=percent)))

        def work():
            try:
                path = updater.download(rel, progress)
                self.after(0, self._update_downloaded, path, None)
            except Exception as e:  # noqa: BLE001
                self.after(0, self._update_downloaded, None, e)
        threading.Thread(target=work, daemon=True).start()

    def _update_downloaded(self, path, error):
        self.set_busy(False)
        if error:
            Dialog.ask(self, t("upd_title"), t("upd_error", error=error), None, level="error")
            self.refresh()
            return
        log(f"update {VERSION} -> {self.release['version']}: {path}")
        updater.launch_installer(path)
        self.destroy()  # l'installazione sostituisce i file dell'app: deve trovarla chiusa

    # ---- azioni

    def open_settings(self):
        d = SettingsDialog(self)
        self.wait_window(d)
        if d.saved:
            self.apply_settings()

    def apply_settings(self):
        """Dopo il salvataggio delle impostazioni: se la lingua è cambiata, ricostruisce la finestra."""
        before = i18n.LANG
        i18n.set_language(self.settings.get("language"))
        if i18n.LANG != before:
            self.outer.destroy()
            self._build()
            self.title(APP_NAME)
            self.refresh()

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

    def add_library(self):
        current = self.settings.get("library")
        start = os.path.dirname(current) if current else os.path.expanduser("~")
        lib = filedialog.askdirectory(title=t("pick_library"), initialdir=start)
        if not lib:
            return
        lib = os.path.normpath(lib)
        if not is_library(lib):
            Dialog.ask(self, APP_NAME, t("pick_library"), t("not_library"), level="error")
            return
        libs = self.settings.setdefault("libraries", [])
        known = next((p for p in libs if os.path.normcase(p) == os.path.normcase(lib)), None)
        if known is None:  # già in elenco: ci si sposta su quella
            libs.append(lib)
        self.switch_library(known or lib)

    def remove_library(self):
        lib = self.settings.get("library")
        libs = self.settings.get("libraries", [])
        if lib not in libs:
            return
        name = self.library_names()[libs.index(lib)].replace("⚠  ", "")
        answer = Dialog.ask(self, APP_NAME, t("remove_library_head", name=name), t("remove_library_body"),
                            level="warn", buttons=[("cancel", t("btn_cancel"), False), ("remove", t("btn_remove"), True)],
                            default="cancel")
        if answer != "remove":
            return
        index = libs.index(lib)
        libs.remove(lib)
        self.switch_library(libs[min(index, len(libs) - 1)] if libs else None)

    def on_library_selected(self, _event=None):
        libs = self.settings.get("libraries", [])
        i = self.lib_combo.current()
        if 0 <= i < len(libs) and libs[i] != self.settings.get("library"):
            self.switch_library(libs[i])

    def switch_library(self, lib):
        if lib:
            self.settings["library"] = lib
        else:
            self.settings.pop("library", None)
        save_settings(self.settings)
        self.refresh()

    def clear_list(self):
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        self.plan = []
        self.show_preview(None)
        for var in self.stat_vars.values():
            var.set("–")
        self.go.state(["disabled"])

    def jpeg_twins_changed(self):
        self.settings["jpeg_twins"] = bool(self.jpeg_twins.get())
        save_settings(self.settings)
        self.refresh()

    def refresh(self):
        self.update_library_label()
        self.clear_list()
        lib = self.settings.get("library")
        if not lib:
            self.set_status("info", t("st_choose"))
            return
        if not is_library(lib):
            self.set_status("warn", t("st_lib_gone"))
            return
        self.set_busy(True, t("st_reading"))
        self.tree.delete(*self.tree.get_children())

        def work():
            try:
                t0 = time.time()
                plan = build_plan(lib, self.settings.get("jpeg_twins", True))
                log(f"plan: built in {time.time() - t0:.1f} s")
                reason = library_open_reason(lib)
                log(f"plan: library check done in {time.time() - t0:.1f} s")
                self.after(0, self.show, plan, reason, None, lib)
            except Exception as e:  # noqa: BLE001 — qualsiasi errore va mostrato all'utente
                self.after(0, self.show, [], None, e, lib)
        threading.Thread(target=work, daemon=True).start()

    def show(self, plan, reason, error, lib=None):
        if lib is not None and lib != self.settings.get("library"):
            return  # nel frattempo si è passati a un'altra libreria: il suo caricamento è già partito
        self.set_busy(False)
        self.plan, self.reason = plan, reason
        if error:
            self.set_status("error", t("st_read_error", error=error))
            return
        self.rows.clear()
        self.show_preview(None)
        saved = self.saved_choices()
        for item in plan:
            if str(item["id"]) in saved:
                set_action(item, saved[str(item["id"])])
            entries = list(zip(item["files"], item["sizes"])) or [(item["path"] or item["name"], None)]
            item["rows"] = []
            for i, (f, size) in enumerate(entries):
                created, modified = item["times"][i] if i < len(item["times"]) else (None, None)
                # fotocamera e autore descrivono lo scatto: solo sulla prima riga, non su JPG/XMP compagni
                present = "" if item["present"] is None else t("present_yes" if item["present"] else "present_no")
                row = self.tree.insert("", "end", values=(os.path.basename(f), present, os.path.dirname(f),
                                                          human(size) if size is not None else "",
                                                          self.when(created), self.when(modified),
                                                          item["camera"] if i == 0 else "",
                                                          item["author"] if i == 0 else "", ""))
                self.rows[row] = item
                item["rows"].append(row)
            self.paint(item)
        self.apply_sort()
        self.update_counts()

    @staticmethod
    def when(seconds):
        if seconds is None:
            return ""
        return datetime.datetime.fromtimestamp(seconds).strftime(DATE_FORMATS.get(i18n.LANG, "%d/%m/%Y") + "  %H:%M")

    # ---- colonne visibili

    def visible_columns(self):
        """Colonne da mostrare, nell'ordine scelto dall'utente; la colonna File c'è sempre."""
        chosen = [c for c in (self.settings.get("columns") or DEFAULT_COLUMNS) if c in COLUMN_IDS]
        return chosen if "name" in chosen else ["name"] + chosen

    def menu(self):
        # niente voci disattivate: Windows le disegna "in rilievo", con un carattere che sembra diverso
        return tk.Menu(self, tearoff=0, bg="#2b2b2b", fg=TEXT, activebackground="#3d4a5c", activeforeground=TEXT,
                       selectcolor=TEXT, bd=0, relief="flat", font=self.f_body)

    def right_click(self, event):
        if self.tree.identify_region(event.x, event.y) in ("heading", "separator"):
            self.columns_menu(event.x_root, event.y_root, self.column_at(event.x))
        else:
            self.row_menu(event)

    def column_at(self, x):
        """Id della colonna visibile sotto la coordinata x del tree (None se fuori)."""
        index = self.tree.identify_column(x)  # "#1", "#2"… nell'ordine visibile
        visible = self.visible_columns()
        try:
            return visible[int(index.lstrip("#")) - 1]
        except (ValueError, IndexError):
            return None

    def columns_menu_at_button(self):
        b = self.btn_columns
        self.columns_menu(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def columns_menu(self, x, y, clicked=None):
        menu = self.menu()
        visible = self.visible_columns()
        if clicked in visible:  # tasto destro su un'intestazione: si può spostare quella colonna
            i = visible.index(clicked)
            if i > 0:
                menu.add_command(label="◀  " + t("col_move_left"), command=lambda: self.move_column(clicked, -1))
            if i < len(visible) - 1:
                menu.add_command(label=t("col_move_right") + "  ▶", command=lambda: self.move_column(clicked, 1))
            if len(visible) > 1:
                menu.add_separator()
        self._column_vars = {}
        for c, key, *_ in COLUMNS:
            if c == "name":
                continue  # sempre visibile: non serve una voce per toglierla
            var = tk.BooleanVar(value=c in visible)
            self._column_vars[c] = var
            menu.add_checkbutton(label=t(key), variable=var, command=lambda c=c: self.toggle_column(c))
        menu.add_separator()
        menu.add_command(label=t("columns_reset"), command=self.reset_columns)
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def toggle_column(self, col):
        visible = self.visible_columns()
        if self._column_vars[col].get() and col not in visible:
            # rimessa al suo posto rispetto alle colonne vicine nell'ordine predefinito
            before = [c for c in COLUMN_IDS[:COLUMN_IDS.index(col)] if c in visible]
            visible.insert(visible.index(before[-1]) + 1 if before else 0, col)
        elif not self._column_vars[col].get() and col in visible:
            visible.remove(col)
        self.set_columns(visible)

    def move_column(self, col, step):
        visible = self.visible_columns()
        i = visible.index(col)
        j = max(0, min(len(visible) - 1, i + step))
        visible.insert(j, visible.pop(i))
        self.set_columns(visible)

    def reset_columns(self):
        self.set_columns(list(DEFAULT_COLUMNS))

    def set_columns(self, columns):
        self.settings["columns"] = columns
        save_settings(self.settings)
        self.tree.configure(displaycolumns=self.visible_columns())
        self.update_headings()

    # ---- trascinamento delle intestazioni per cambiare l'ordine delle colonne

    def heading_press(self, event):
        self._drag_col = self.column_at(event.x) if self.tree.identify_region(event.x, event.y) == "heading" else None
        self._drag_x = event.x
        self._dragging = False

    def heading_motion(self, event):
        if getattr(self, "_drag_col", None) and abs(event.x - self._drag_x) > 12:
            self._dragging = True
            self.tree.configure(cursor="sb_h_double_arrow")

    def heading_release(self, event):
        col, dragging = getattr(self, "_drag_col", None), getattr(self, "_dragging", False)
        self._drag_col, self._dragging = None, False
        if not (col and dragging):
            return  # un clic semplice: ci pensa il comando dell'intestazione (ordinamento)
        self.tree.configure(cursor="")
        target = self.column_at(min(max(event.x, 1), self.tree.winfo_width() - 1))
        visible = self.visible_columns()
        if target and target != col:
            visible.remove(col)
            visible.insert(visible.index(target) + (1 if event.x > self._drag_x else 0), col)
            self.set_columns(visible)

    # ---- ordinamento

    def update_headings(self):
        col, reverse = self.sort
        for c, key, width, _anchor, _s in COLUMNS:
            text = t(key) + ((" ▼" if reverse else " ▲") if c == col else "")
            # intestazioni sempre a sinistra e mai più strette del loro titolo (con la freccia), in ogni lingua
            need = self.f_small.measure(t(key) + " ▼") + 34  # titolo, freccia e margini dell'intestazione
            self.tree.heading(c, text=text, anchor="w")
            self.tree.column(c, minwidth=need, width=max(width, need, self.tree.column(c, "width")))

    def sort_by(self, col):
        current, reverse = self.sort
        self.sort = (col, not reverse) if col == current else (col, False)
        self.settings["sort"] = list(self.sort)
        save_settings(self.settings)
        self.update_headings()
        self.apply_sort()

    def apply_sort(self):
        """Riordina per foto: le righe di uno stesso scatto (RAW, JPG, XMP) restano sempre insieme."""
        col, reverse = self.sort

        def key(item):
            first = item["files"][0] if item["files"] else (item["path"] or item["name"])
            created, modified = item["times"][0] if item["times"] else (None, None)
            if col == "name":
                return os.path.basename(first).lower()
            if col == "present":  # prima quelli spariti dal disco
                return ({False: 0, True: 1}.get(item["present"], 2), os.path.basename(first).lower())
            if col == "folder":
                return (os.path.dirname(first).lower(), os.path.basename(first).lower())
            if col == "size":
                return item["bytes"]
            if col == "created":
                return created or 0
            if col == "modified":
                return modified or 0
            if col in ("camera", "author"):  # vuoti in fondo, in entrambi i versi
                value = item[col].lower()
                return (value == "") != reverse, value
            return (ACTIONS.index(item["action"]), item["note"] or "", os.path.basename(first).lower())

        index = 0
        for item in sorted(self.plan, key=key, reverse=reverse):
            for row in item.get("rows", []):
                self.tree.move(row, "", index)
                index += 1

    def row_status(self, item, index):
        if index > 0:
            return t("st_companion")
        if item["action"] == "keep":
            return t("st_keep")
        if item["action"] == "full":
            return t("st_full")
        if item["note"] == "note_missing":
            return t("st_missing")
        return t(item["note"]) if item["note"] else t("st_trash")  # foto senza file da cancellare: il motivo

    def paint(self, item):
        """Colore e stato delle righe della foto secondo la sua azione."""
        for i, row in enumerate(item["rows"]):
            values = list(self.tree.item(row, "values"))
            values[STATUS_COLUMN] = self.row_status(item, i)
            self.tree.item(row, values=values, tags=(item["action"],) + (("companion",) if i else ()))

    def update_counts(self):
        """Numeri in alto, banner e pulsante, contando solo i file che verranno davvero cancellati."""
        plan, reason = self.plan, self.reason
        full = [i for i in plan if i["action"] == "full"]
        self.stat_vars["photos"].set(str(len(plan)))
        self.stat_vars["files"].set(str(sum(len(i["files"]) for i in full)))
        self.stat_vars["bytes"].set(human(sum(i["bytes"] for i in full)))
        todo = any(i["action"] != "keep" for i in plan)
        if reason:
            self.set_status("warn", t(reason))
            self.go.state(["disabled"])
        elif not plan:
            self.set_status("ok", t("st_empty"))
            self.go.state(["disabled"])
        elif not todo:
            self.set_status("info", t("st_all_kept"))
            self.go.state(["disabled"])
        else:
            self.set_status("info", t("st_ready", go=t("go")))
            self.go.state(["!disabled"])

    # ---- scelte per foto (tasto destro)

    def saved_choices(self):
        """Scelte gialle/verdi della libreria corrente, ricordate tra un avvio e l'altro: {id foto: azione}."""
        return self.settings.setdefault("choices", {}).get(self.settings.get("library", ""), {})

    def store_choices(self, keep_ids=None):
        """Salva le scelte diverse da quella predefinita; keep_ids limita alle foto ancora nel cestino."""
        lib = self.settings.get("library", "")
        default = {i["id"]: ("full" if i["files"] else "trash") for i in self.plan}
        choices = {str(i["id"]): i["action"] for i in self.plan if i["action"] != default[i["id"]]}
        if keep_ids is not None:
            choices = {k: v for k, v in choices.items() if int(k) in keep_ids}
        all_choices = self.settings.setdefault("choices", {})
        if choices:
            all_choices[lib] = choices
        else:
            all_choices.pop(lib, None)
        save_settings(self.settings)

    def row_menu(self, event):
        if not self.rows or self.progress.winfo_ismapped():
            return
        row = self.tree.identify_row(event.y) if event.y else self.tree.focus()
        if not row:
            return
        if row not in self.tree.selection():
            self.tree.selection_set(row)
        self.tree.focus(row)
        items = self.selected_items()
        menu = self.menu()
        for action in ACTIONS:
            if action == "full" and not any(i["files"] for i in items):
                continue  # niente file da cancellare tra le righe scelte: la voce non serve
            menu.add_command(label=t("menu_" + action), command=lambda a=action: self.apply_action(a))
        values = self.tree.item(row, "values")
        path = os.path.join(values[COLUMN_IDS.index("folder")], values[0]) if values else ""
        if path and (os.path.exists(path) or os.path.isdir(os.path.dirname(path))):
            menu.add_separator()
            menu.add_command(label=t("menu_explorer"), command=lambda: self.show_in_explorer(path))
        x = event.x_root if event.x_root else self.tree.winfo_rootx() + 40
        y = event.y_root if event.y_root else self.tree.winfo_rooty() + 40
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def selected_items(self):
        """Foto delle righe selezionate, senza doppioni (le righe di uno stesso scatto sono una foto sola)."""
        seen, items = set(), []
        for row in self.tree.selection():
            item = self.rows.get(row)
            if item and item["id"] not in seen:
                seen.add(item["id"])
                items.append(item)
        return items

    def apply_action(self, action):
        for item in self.selected_items():
            set_action(item, action)
            self.paint(item)
        self.store_choices()
        self.update_counts()

    def show_in_explorer(self, path):
        if os.path.exists(path):
            subprocess.Popen(f'explorer /select,"{path}"')
        elif os.path.isdir(os.path.dirname(path)):
            os.startfile(os.path.dirname(path))

    def confirm(self):
        groups = {"full": [], "trash": [], "missing": [], "keep": []}
        for i in self.plan:
            key = "missing" if i["action"] != "keep" and i["note"] == "note_missing" else i["action"]
            groups[key].append(i)
        n_files = sum(len(i["files"]) for i in groups["full"])
        total = sum(i["bytes"] for i in groups["full"])
        lines = [t("sum_" + key, count=len(items)) for key, items in groups.items() if items]
        body = "\n".join("•  " + line for line in lines) + "\n\n"
        body += (t("confirm_bins") + " " if n_files else "") + t("confirm_backup")
        head = t("confirm_head", files=n_files, size=human(total)) if n_files else \
            t("confirm_head_trash", photos=len(groups["trash"]) + len(groups["missing"]))
        answer = Dialog.ask(self, t("confirm_title"), head, body, level="warn",
                            buttons=[("cancel", t("btn_cancel"), False), ("delete", t("btn_go"), True)],
                            default="cancel")
        if answer != "delete":
            return
        cli = self.cli()
        if not cli:
            return
        lib, plan = self.settings["library"], self.plan
        root, kept = backup_root(lib, self.settings), self.settings.get("backups_kept", BACKUPS_KEPT)
        self.set_busy(True, t("st_working"))

        def work():
            try:
                self.after(0, self.done, execute(lib, cli, plan, root, kept), None)
            except Exception as e:  # noqa: BLE001
                log(f"ERROR: {e}")
                self.after(0, self.done, None, e)
        threading.Thread(target=work, daemon=True).start()

    def done(self, result, error):
        self.set_busy(False)
        if error:
            Dialog.ask(self, APP_NAME, t("error_title"), str(error), level="error")
        else:
            # le scelte restano solo per le foto ancora nel cestino
            self.store_choices(keep_ids={i["id"] for i in self.plan} - set(result["removed_ids"]))
            sections = []
            if result["failed"]:
                sections.append(t("done_failed") + "\n" + "\n".join(result["failed"][:20]))
            if result["missing"]:
                sections.append(t("done_missing") + "\n" + "\n".join(result["missing"]))
            if result["trash_only"]:
                sections.append(t("done_trash_only") + "\n" + "\n".join(result["trash_only"]))
            sections.append(t("done_backup") + "\n" + result["backup"])
            body = t("done_body", removed=result["removed"], files=result["files"], left=result["left"])
            if result["missing"]:
                body += "\n" + t("done_missing_count", count=len(result["missing"]))
            Dialog.ask(self, APP_NAME, t("done_warn_title") if result["failed"] else t("done_title"), body,
                       level="warn" if result["failed"] else "ok", detail="\n\n".join(sections))
        self.refresh()

    def open_backups(self):
        self.wait_window(BackupsDialog(self))

    def open_log(self):
        if os.path.exists(LOG):
            os.startfile(LOG)
        else:
            Dialog.ask(self, APP_NAME, t("open_log"), t("log_empty"))

    # ---- anteprima

    def on_select(self, _event=None):
        row = self.tree.focus() if self.tree.focus() in self.tree.selection() else \
            (self.tree.selection() or [None])[0]
        self.show_preview(self.rows.get(row) if row else None)

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
                lines.append(t("taken", date=when.strftime(DATE_FORMATS.get(i18n.LANG, "%d/%m/%Y")),
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
    dpi_aware()
    App().mainloop()


if __name__ == "__main__":
    main()
