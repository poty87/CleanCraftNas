# CleanCraftNas manual

<a href="manuale.md">🇮🇹 Italiano</a>

CleanCraftNas deletes from disk, even on the NAS, the photos you moved to LightCraft's trash, then empties the trash. To
install and connect the whole suite (NAS, PC, phone) start from the
**[suite guide](https://github.com/poty87/PresetCraftAppLicator/blob/main/docs/suite-guide.md)**.

## Contents

1. [Requirements and installation](#1-requirements-and-installation)
2. [The main window](#2-the-main-window)
3. [Choosing what happens to each photo](#3-choosing-what-happens-to-each-photo)
4. [The cleanup, step by step](#4-the-cleanup-step-by-step)
5. [Raws already converted to DNG](#5-raws-already-converted-to-dng)
6. [Backups](#6-backups)
7. [Settings](#7-settings)
8. [Safety: what it never does](#8-safety-what-it-never-does)
9. [Updating and uninstalling](#9-updating-and-uninstalling)
10. [Common problems](#10-common-problems)

---

## 1. Requirements and installation

**You need:** Windows 10 or 11 (64-bit) and LightCraft installed (CleanCraftNas uses its `lightcraft-cli.exe`). For photos
on the NAS, the shared folder mapped to a fixed drive letter (for example `Y:`) and the password saved in Windows: see
[Preparing the PC](https://github.com/poty87/PresetCraftAppLicator/blob/main/docs/suite-guide.md#4-preparing-the-pc).
Recommended: the **recycle bin** turned on for the NAS shared folder, so every deletion can be recovered.

**Installation.** Download `CleanCraftNas-Setup-x.y.z.exe` from [Releases](https://github.com/poty87/CleanCraftNas/releases/latest)
and run it: **language**, **license**, **folder** (default `%LOCALAPPDATA%\Programs\CleanCraftNas`), optional Desktop
shortcut. It installs for your user only, without administrator rights, and already contains everything it needs.

**First start.** Click **＋ Add library…** and choose the LightCraft library folder (the one containing `catalog.snap`). If
`lightcraft-cli.exe` is not in the usual place the app asks for it.

---

## 2. The main window

- **LIBRARY** — the drop-down with the libraries you added. **＋ Add library…** adds more; **Remove from list** only
  forgets one (photos and backups stay). Libraries with the same name show the folder that contains them; a library that
  can't be found right now (drive not connected, folder moved) is marked ⚠. The app reopens the last one used.
- **Refresh** — reads the trash again. **⚙ Settings**. **☰** — *Raws already converted to DNG…*
- **The three numbers:** *Photos in the trash*, *Files to delete*, *Space to free up*.
- **The status line** says whether you can proceed: *Lightcraft is closed…*, *Lightcraft is open. Close it and click
  “Refresh”*, *PresetCraftAppLicator is working on this library…*, *This library's trash is empty*.
- **The list** — one row per file: the photo, the **JPEG** of the same shot (RAW+JPEG) and the **XMP** sidecar. The row
  colour says what will happen ([chapter 3](#3-choosing-what-happens-to-each-photo)).
  - Columns: *File*, *Folder*, *Size*, *Status*, *On disk* (✓/✗), *Created*, *Modified*, *Camera*, *Author*. Choose which
    to show with **☰ Columns** or by right-clicking the headings; drag a heading to move it (or *Move left* / *Move
    right*); *Restore default columns*. The order is remembered.
  - Click a heading to sort (again to reverse); the files of one shot stay together.
  - **Also remove JPEGs with the same name** — on (default), the JPEG of a RAW+JPEG pair goes with the raw; off, the JPEG
    stays on disk.
- **Preview** on the right: click a row to see it, double-click to enlarge (Esc or click to close), with the capture date.
- **At the bottom:** **Backups…**, **Open log**, the version (and *Version x.y.z available* when there is one) and the red
  **Delete from disk and empty the trash** button.

Notes that can appear in the Status column: *File kept: another photo uses it*, *File already gone from disk*, *Already
listed with another photo*, *No file (demo photo)*.

---

## 3. Choosing what happens to each photo

Right-click one or more rows (Shift/Ctrl + click to select several):

| Colour | Menu item | What happens |
|---|---|---|
| red (default) | **Delete from disk and trash** | the files are deleted and the photo leaves LightCraft's trash |
| yellow | **Remove from trash only** | the photo leaves the trash, the files stay where they are |
| green | **Leave in trash** | nothing: the photo stays in LightCraft's trash |

Yellow and green choices are remembered per library. Photos whose file is gone (*Not found: trash only*) are recognised
automatically and only removed from the trash. The same menu has **Show in File Explorer**.

---

## 4. The cleanup, step by step

1. In LightCraft press `Delete` on the photos you don't want: they move to **Recently Deleted**.
2. Close LightCraft.
3. Open CleanCraftNas (or click **Refresh**): check the list, the colours and the previews.
4. Click **Delete from disk and empty the trash**. The confirmation sums up how many files and how much space, what
   happens to each group and where the files go (NAS or Windows recycle bin). **Proceed**.
5. CleanCraftNas:
   1. **backs up** the library;
   2. **deletes the files** of the red photos (with the JPEG and XMP of the same shot);
   3. **empties LightCraft's trash** with LightCraft's own command (`lightcraft-cli photo.deletePermanently`), only for
      the photos whose files were deleted and for the yellow ones. The library files are never edited by hand.
6. The final summary says how many photos left the library, how many files were deleted, how many photos are still in the
   trash, which files could not be deleted and where the backup is.

---

## 5. Raws already converted to DNG

When a proprietary raw (CR2, NEF, ORF, ARW, RAF, RW2…) is converted to DNG — for example by PresetCraftAppLicator, which
imports the DNG and leaves the original next to it — the original stays on the NAS taking space. **☰ › Raws already
converted to DNG…** lists them for the chosen library, with *Original raw*, *DNG in the library* and size, and deletes
the ones you select.

A raw is listed **only if** all of these are true:

- no photo of any library in CleanCraftNas's list uses it (active or in the trash);
- the DNG next to it is in the library, active;
- the DNG records that very raw as its original (`OriginalRawFileName`, written by Adobe DNG Converter);
- the DNG is lossless.

The raws go to the NAS recycle bin (or the Windows one) and are written to the log; the library does not change: the
DNGs stay with all their edits. **Careful:** CleanCraftNas only checks the LightCraft libraries in its list; if you also
use those raws with other programs (for example a Lightroom catalog), keep them.

---

## 6. Backups

Before every cleanup the app copies the library's catalog (`catalog.snap`, `catalog.log`, `view.json`) to a
`CleanCraftNas backup - <library name>` folder, next to the library or in the folder chosen in Settings, and keeps the
last 5 (adjustable).

**Backups…** lists the backups of the chosen library (also those in other folders or made by older versions) with date
and size: **Open folder**, **Delete selected**, **Delete all** (they go to the Recycle Bin). To go back to a backup: close
LightCraft and copy the three backup files over the library's ones.

---

## 7. Settings

| Item | What it does |
|---|---|
| **Language** | Automatic (Windows language), Italiano, English, Deutsch, Español, Français, Português; changes at once. |
| **Path to lightcraft-cli.exe** | It is in LightCraft's installation folder (usually `%LOCALAPPDATA%\Programs\ArtCraft\LightCraft`). |
| **Backups** | *Next to the library (default)* or *In this folder:*; *Backups to keep per library*. |
| **Updates** | *Check for updates at startup*, *Check now*. |

At the bottom, *☕ Buy me a coffee* and the version.

---

## 8. Safety: what it never does

- **It does not run while LightCraft is open** (the app or `lightcraft-cli`) and checks again right before deleting; it
  also waits while PresetCraftAppLicator is writing to the library.
- **It never deletes a file used by a photo still in the library** (for example the original of a virtual copy you
  trashed).
- **It never deletes permanently:** files on the NAS go to the shared folder's recycle bin (if turned on: on Synology
  `#recycle`, on QNAP `@Recycle`), files on the PC go to the Windows Recycle Bin.
- If a file can't be deleted, its photo **stays in the trash** and the error shows in the summary and in the log.
- Every operation is written to the log `%LOCALAPPDATA%\CleanCraftNas\cleancraftnas.log` (**Open log**).

---

## 9. Updating and uninstalling

- At every start the app asks GitHub which version was released last; when there is a newer one, **⬆ Version x.y.z
  available** appears at the bottom: it downloads the setup, checks its size and SHA-256 and starts it, keeping folder,
  language and settings.
- Or download and run the new setup: it recognises the installed version and offers **Update**. Installing an older
  version over a newer one is refused.
- Running the setup of the same version again: **Reinstall** (to repair it) or **Uninstall**; you can also uninstall from
  Windows *Settings › Apps*. Settings and log stay on the PC.
- Silent install: `CleanCraftNas-Setup-x.y.z.exe --silent [--dir "…"] [--lang en] [--no-desktop]`, and
  `--silent --uninstall`; there is also the `CleanCraftNas-x.y.z.msi` package (properties `CCN_LANGUAGE`, `CCN_DESKTOP`,
  `TARGETDIR`).

---

## 10. Common problems

| Problem | Solution |
|---|---|
| *Lightcraft is open* but you closed it | Check that no `lightcraft-cli` is running; click **Refresh**. |
| *The library still appears to be open* | LightCraft did not close cleanly: open and close it once. |
| ⚠ next to the library | The drive or NAS is not connected (`Y:` missing): connect it and click **Refresh**. |
| Photos show *File already gone from disk* | The NAS drive letter changed or the files were moved: with the right letter they show again. If the files really are gone, the photo is only removed from the trash. |
| A file won't delete | It is open in another program or the NAS folder is not writable for your user: the photo stays in the trash, try again later. |
| You deleted something by mistake | Recover the file from the NAS (or Windows) recycle bin and, if needed, the library from the [backup](#6-backups). |
