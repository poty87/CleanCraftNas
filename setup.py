"""Build dell'eseguibile e dell'installer MSI di CleanCraftNas con cx_Freeze.

    .venv\\Scripts\\python.exe setup.py bdist_msi

L'MSI contiene Python, Tk, sv_ttk e Pillow: sul PC di destinazione non serve installare altro.
Si installa per l'utente corrente (niente permessi di amministratore). L'installazione chiede la cartella
(predefinita %LOCALAPPDATA%\\Programs\\CleanCraftNas) e la lingua, e crea i collegamenti nel menu Start e
sul Desktop. Senza interfaccia la lingua si passa così: msiexec /i CleanCraftNas-x.y.z.msi CCN_LANGUAGE=en
"""

import re
import sys
from pathlib import Path

from cx_Freeze import Executable, setup
from cx_Freeze.command.bdist_msi import bdist_msi

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
from translations import LANGUAGES  # noqa: E402

VERSION = re.search(r'^VERSION = "(.+)"', (ROOT / "src" / "cleancraftnas.py").read_text(encoding="utf-8"), re.M)[1]
NAME = "CleanCraftNas"
EXE = "CleanCraftNas.exe"
ICON = str(ROOT / "assets" / "icon.ico")
DESCRIPTION = "Deletes from disk the photos in Lightcraft's trash and empties it"
# non cambiarlo mai: è ciò che permette a una nuova versione di sostituire quella installata
# (anche le versioni 1.0–1.1, che si chiamavano "Pulizia cestino Lightcraft")
UPGRADE_CODE = "{A12F739D-0076-4137-9AA2-477F6CC22D4C}"

shortcuts = [
    # (Shortcut, Directory_, Name, Component_, Target, Arguments, Description, Hotkey, Icon_, IconIndex, ShowCmd, WkDir)
    ("StartMenuShortcut", "ProgramMenuFolder", f"CLEANCR|{NAME}", "TARGETDIR", f"[TARGETDIR]{EXE}", None,
     DESCRIPTION, None, None, None, None, "TARGETDIR"),
    ("DesktopShortcut", "DesktopFolder", f"CLEANCR|{NAME}", "TARGETDIR", f"[TARGETDIR]{EXE}", None,
     DESCRIPTION, None, None, None, None, "TARGETDIR"),
]


class BdistMsiWithLanguage(bdist_msi):
    """L'MSI di cx_Freeze con una pagina in più, dopo la scelta della cartella, per la lingua dell'app.

    La scelta finisce in HKCU\\Software\\CleanCraftNas\\Language; l'app la usa finché l'utente non sceglie
    un'altra lingua nelle Impostazioni.
    """

    def add_config(self):
        super().add_config()
        db = self.db
        from msilib import add_data

        add_data(db, "Property", [("CCN_LANGUAGE", "auto")])
        view = db.OpenView("UPDATE `Property` SET `Value`='TARGETDIR;REINSTALLMODE;CCN_LANGUAGE' "
                           "WHERE `Property`='SecureCustomProperties'")
        view.Execute(None)
        view.Close()
        choices = [("auto", "Automatic (Windows language)")] + list(LANGUAGES.items())
        add_data(db, "ComboBox", [("CCN_LANGUAGE", i + 1, code, label) for i, (code, label) in enumerate(choices)])
        add_data(db, "Registry", [("RegLanguage", 1, r"Software\CleanCraftNas", "Language", "[CCN_LANGUAGE]",
                                   "TARGETDIR")])
        add_data(db, "InstallUISequence", [("LanguageDlg", "not Installed", 1235)])

    def add_ui(self):
        super().add_ui()
        from cx_Freeze.command._pydialog import PyDialog

        dialog = PyDialog(self.db, "LanguageDlg", x=self.x, y=self.y, w=self.width, h=self.height, attr=self.modal,
                          title=self.title, first="LangCombo", default="Next", cancel="Cancel")
        dialog.title("Language · Lingua · Sprache · Idioma · Langue")
        dialog.text("Hint", 15, 60, 330, 50, 3,
                    "Choose the language of CleanCraftNas. You can change it later in Settings.\r\n\r\n"
                    "Scegli la lingua di CleanCraftNas: potrai cambiarla in seguito dalle Impostazioni.")
        # 0x20000 = ComboList: si sceglie solo dall'elenco
        dialog.control("LangCombo", "ComboBox", 15, 120, 220, 16, 3 | 0x20000, "CCN_LANGUAGE", None, "Next", None)
        # i controlli col Tab devono formare un giro chiuso (errore 2810): "Indietro" è disattivo e ne resta fuori
        dialog.backbutton("< Back", None, active=False)
        button = dialog.nextbutton("Next >", "Cancel")
        button.event("EndDialog", "Return")
        button = dialog.cancelbutton("Cancel", "LangCombo")
        button.event("SpawnDialog", "CancelDlg")


setup(
    name=NAME,
    version=VERSION,
    description=DESCRIPTION,
    author="poty87",
    url="https://github.com/poty87/CleanCraftNas",
    cmdclass={"bdist_msi": BdistMsiWithLanguage},
    options={
        "build_exe": {
            "packages": ["sv_ttk", "tkinter", "PIL"],
            "include_files": [(ICON, "assets/icon.ico")],
            "excludes": ["unittest", "pydoc", "email", "http", "xmlrpc"],
            "include_msvcr": True,
        },
        "bdist_msi": {
            "upgrade_code": UPGRADE_CODE,
            "all_users": False,
            "initial_target_dir": rf"[LocalAppDataFolder]Programs\{NAME}",
            "install_icon": ICON,
            "add_to_path": False,
            "output_name": f"CleanCraftNas-{VERSION}.msi",
            "data": {"Shortcut": shortcuts},
            "summary_data": {"author": "poty87", "comments": f"{NAME} installer"},
        },
    },
    executables=[Executable(str(ROOT / "src" / "cleancraftnas.py"), base="gui", target_name=EXE, icon=ICON)],
)
