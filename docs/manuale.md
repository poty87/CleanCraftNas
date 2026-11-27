# Manuale di CleanCraftNas

<a href="manual.md">🇬🇧 English</a>

CleanCraftNas cancella dal disco, anche sul NAS, le foto che hai messo nel cestino di LightCraft, e poi svuota il cestino.
Per installare e collegare tutta la suite (NAS, PC, telefono) parti dalla
**[guida della suite](https://github.com/poty87/PresetCraftAppLicator/blob/main/docs/guida-suite.md)**.

## Indice

1. [Requisiti e installazione](#1-requisiti-e-installazione)
2. [La finestra principale](#2-la-finestra-principale)
3. [Scegliere cosa fare di ogni foto](#3-scegliere-cosa-fare-di-ogni-foto)
4. [La pulizia, passo per passo](#4-la-pulizia-passo-per-passo)
5. [Raw già convertiti in DNG](#5-raw-già-convertiti-in-dng)
6. [Backup](#6-backup)
7. [Impostazioni](#7-impostazioni)
8. [Sicurezza: cosa non fa mai](#8-sicurezza-cosa-non-fa-mai)
9. [Aggiornare e disinstallare](#9-aggiornare-e-disinstallare)
10. [Problemi comuni](#10-problemi-comuni)

---

## 1. Requisiti e installazione

**Serve:** Windows 10 o 11 a 64 bit e LightCraft installato (CleanCraftNas usa il suo `lightcraft-cli.exe`). Per le foto
sul NAS, la cartella condivisa collegata con una lettera fissa (per esempio `Y:`) e la password salvata in Windows: vedi
[Preparare il PC](https://github.com/poty87/PresetCraftAppLicator/blob/main/docs/guida-suite.md#4-preparare-il-pc).
Consigliato: il **cestino** attivo sulla cartella condivisa del NAS, così ogni cancellazione si può recuperare.

**Installazione.** Scarica `CleanCraftNas-Setup-x.y.z.exe` dalle [Release](https://github.com/poty87/CleanCraftNas/releases/latest)
e avvialo: **lingua**, **licenza**, **cartella** (predefinita `%LOCALAPPDATA%\Programs\CleanCraftNas`), collegamento sul
Desktop facoltativo. Si installa solo per il tuo utente, senza permessi di amministratore, e contiene già tutto quello che
serve.

**Primo avvio.** Premi **＋ Aggiungi libreria…** e scegli la cartella della libreria LightCraft (quella che contiene
`catalog.snap`). Se `lightcraft-cli.exe` non è nel posto solito l'app te lo chiede.

---

## 2. La finestra principale

- **LIBRERIA** — il menu a tendina con le librerie aggiunte. **＋ Aggiungi libreria…** ne aggiunge altre; **Togli
  dall'elenco** la dimentica soltanto (foto e backup restano). Le librerie con lo stesso nome mostrano la cartella che le
  contiene; una libreria che ora non si trova (disco non collegato, cartella spostata) ha il segno ⚠. L'app riapre l'ultima
  usata.
- **Aggiorna** — rilegge il cestino. **⚙ Impostazioni**. **☰** — *Raw già convertiti in DNG…*
- **I tre numeri:** *Foto nel cestino*, *File da cancellare*, *Spazio da liberare*.
- **La riga di stato** dice se si può procedere: *LightCraft è chiuso…*, *LightCraft è aperto. Chiudilo e premi
  «Aggiorna»*, *PresetCraftAppLicator sta lavorando su questa libreria…*, *Il cestino di questa libreria è vuoto*.
- **L'elenco** — una riga per file: la foto, il **JPEG** dello stesso scatto (RAW+JPEG) e il file **XMP** accanto. Il colore
  della riga dice cosa succederà ([capitolo 3](#3-scegliere-cosa-fare-di-ogni-foto)).
  - Colonne: *File*, *Cartella*, *Dimensione*, *Stato*, *Su disco* (✓/✗), *Creato*, *Modificato*, *Fotocamera*, *Autore*.
    Scegli quali vedere con **☰ Colonne** o con il tasto destro sulle intestazioni; trascina un'intestazione per spostarla
    (o *Sposta a sinistra* / *Sposta a destra*); *Ripristina colonne predefinite*. L'ordine si ricorda.
  - Clic su un'intestazione per ordinare (di nuovo per invertire); i file dello stesso scatto restano insieme.
  - **Togli anche i JPEG con lo stesso nome** — acceso (predefinito), il JPEG di una coppia RAW+JPEG va via con il raw;
    spento, il JPEG resta sul disco.
- **Anteprima** a destra: clic su una riga per vederla, doppio clic per ingrandirla (Esc o clic per chiudere), con la
  data di scatto.
- **In basso:** **Backup…**, **Apri registro**, la versione (e l'eventuale *Disponibile la versione x.y.z*) e il pulsante
  rosso **Cancella dal disco e svuota il cestino**.

Note che possono comparire nella colonna Stato: *File tenuto: lo usa un'altra foto*, *File già assente dal disco*,
*Già in elenco con un'altra foto*, *Nessun file (foto dimostrativa)*.

---

## 3. Scegliere cosa fare di ogni foto

Tasto destro su una o più righe (Maiusc/Ctrl + clic per selezionarne più di una):

| Colore | Voce del menu | Cosa succede |
|---|---|---|
| rosso (predefinito) | **Cancella da disco e cestino** | i file vengono cancellati e la foto esce dal cestino di LightCraft |
| giallo | **Togli solo dal cestino** | la foto esce dal cestino, i file restano dove sono |
| verde | **Lascia nel cestino** | niente: la foto resta nel cestino di LightCraft |

Le scelte gialle e verdi si ricordano per ogni libreria. Le foto il cui file non c'è più (*Non trovato: solo cestino*)
vengono riconosciute da sole e tolte solo dal cestino. Nello stesso menu c'è **Mostra in Esplora file**.

---

## 4. La pulizia, passo per passo

1. In LightCraft premi `Canc` sulle foto che non vuoi: vanno in **Recently Deleted**.
2. Chiudi LightCraft.
3. Apri CleanCraftNas (o premi **Aggiorna**): controlla l'elenco, i colori e le anteprime.
4. Premi **Cancella dal disco e svuota il cestino**. La conferma riassume quanti file e quanto spazio, cosa succede a
   ciascun gruppo e dove finiscono i file (cestino del NAS o di Windows). **Procedi**.
5. CleanCraftNas:
   1. fa il **backup** della libreria;
   2. **cancella i file** delle foto rosse (con JPEG e XMP dello stesso scatto);
   3. **svuota il cestino** di LightCraft con il comando di LightCraft stesso (`lightcraft-cli photo.deletePermanently`),
      solo per le foto i cui file sono stati cancellati e per quelle gialle. I file della libreria non vengono mai toccati a mano.
6. Il riepilogo finale dice quante foto sono uscite dalla libreria, quanti file sono stati cancellati, quante foto restano
   nel cestino, quali file non si sono potuti cancellare e dov'è il backup.

---

## 5. Raw già convertiti in DNG

Quando un raw proprietario (CR2, NEF, ORF, ARW, RAF, RW2…) viene convertito in DNG — per esempio da PresetCraftAppLicator,
che importa il DNG e lascia l'originale accanto — l'originale resta sul NAS a occupare spazio. **☰ › Raw già convertiti in
DNG…** li elenca per la libreria scelta, con *Raw originale*, *DNG in libreria* e dimensione, e cancella quelli che
selezioni.

Un raw compare **solo se** tutte queste condizioni sono vere:

- nessuna foto di nessuna libreria dell'elenco di CleanCraftNas lo usa (né attiva né nel cestino);
- il DNG accanto è in libreria, attivo;
- il DNG dichiara proprio quel raw come suo originale (`OriginalRawFileName`, scritto da Adobe DNG Converter);
- il DNG è senza perdita (lossless).

I raw finiscono nel cestino del NAS (o di Windows) e sono scritti nel registro; la libreria non cambia: restano i DNG con
tutte le modifiche. **Attenzione:** CleanCraftNas controlla solo le librerie LightCraft del suo elenco; se usi quei raw
anche con altri programmi (per esempio un catalogo di Lightroom), tienili.

---

## 6. Backup

Prima di ogni pulizia l'app copia il catalogo della libreria (`catalog.snap`, `catalog.log`, `view.json`) in una cartella
`CleanCraftNas backup - <nome libreria>`, accanto alla libreria oppure nella cartella scelta nelle Impostazioni, e tiene gli
ultimi 5 (numero modificabile).

**Backup…** elenca i backup della libreria scelta (anche quelli in altre cartelle o fatti da versioni vecchie) con data e
dimensione: **Apri cartella**, **Elimina selezionati**, **Elimina tutti** (vanno nel Cestino). Per tornare a un backup:
chiudi LightCraft e copia i tre file del backup al posto di quelli della libreria.

---

## 7. Impostazioni

| Voce | Cosa fa |
|---|---|
| **Lingua** | Automatica (lingua di Windows), Italiano, English, Deutsch, Español, Français, Português; cambia subito. |
| **Percorso di lightcraft-cli.exe** | Si trova nella cartella di installazione di LightCraft (di solito `%LOCALAPPDATA%\Programs\ArtCraft\LightCraft`). |
| **Backup** | *Accanto alla libreria (predefinito)* o *In questa cartella:*; *Backup da tenere per libreria*. |
| **Aggiornamenti** | *Controlla gli aggiornamenti all'avvio*, *Controlla ora*. |

In fondo *☕ Offrimi un caffè* e la versione.

---

## 8. Sicurezza: cosa non fa mai

- **Non lavora con LightCraft aperto** (né l'app né `lightcraft-cli`) e ricontrolla subito prima di cancellare; aspetta
  anche quando PresetCraftAppLicator sta scrivendo nella libreria.
- **Non cancella un file usato da una foto ancora in libreria** (per esempio l'originale di una copia virtuale che hai
  messo nel cestino).
- **Non cancella in modo definitivo:** i file sul NAS vanno nel cestino della cartella condivisa (se è attivo: su
  Synology `#recycle`, su QNAP `@Recycle`), quelli sul PC nel Cestino di Windows.
- Se un file non si cancella, la sua foto **resta nel cestino** e l'errore compare nel riepilogo e nel registro.
- Ogni operazione è scritta nel registro `%LOCALAPPDATA%\CleanCraftNas\cleancraftnas.log` (**Apri registro**).

---

## 9. Aggiornare e disinstallare

- A ogni avvio l'app chiede a GitHub qual è l'ultima versione; se ce n'è una nuova compare in basso **⬆ Disponibile la
  versione x.y.z**: scarica il setup, ne controlla dimensione e SHA-256 e lo avvia, mantenendo cartella, lingua e impostazioni.
- In alternativa scarica e avvia il nuovo setup: riconosce la versione installata e propone **Aggiorna**. Installare una
  versione più vecchia sopra una più nuova viene rifiutato.
- Avviando di nuovo il setup della stessa versione: **Reinstalla** (per ripararla) o **Disinstalla**; si disinstalla anche da
  *Impostazioni › App* di Windows. Impostazioni e registro restano sul PC.
- Installazione silenziosa: `CleanCraftNas-Setup-x.y.z.exe --silent [--dir "…"] [--lang it] [--no-desktop]`, e
  `--silent --uninstall`; c'è anche il pacchetto `CleanCraftNas-x.y.z.msi` (proprietà `CCN_LANGUAGE`, `CCN_DESKTOP`,
  `TARGETDIR`).

---

## 10. Problemi comuni

| Problema | Soluzione |
|---|---|
| *LightCraft è aperto* ma l'hai chiuso | Controlla che non ci sia un `lightcraft-cli` in esecuzione; premi **Aggiorna**. |
| *La libreria risulta ancora aperta* | LightCraft si è chiuso male: aprilo e richiudilo una volta. |
| ⚠ accanto alla libreria | Il disco o il NAS non è collegato (`Y:` mancante): collegalo e premi **Aggiorna**. |
| Le foto risultano *File già assente dal disco* | La lettera del NAS è cambiata o i file sono stati spostati: con la lettera giusta tornano visibili. Se i file non ci sono davvero, la foto viene solo tolta dal cestino. |
| Un file non si cancella | Il file è aperto in un altro programma o la cartella del NAS non è scrivibile per il tuo utente: la foto resta nel cestino, riprova dopo. |
| Hai cancellato qualcosa per sbaglio | Recupera il file dal cestino del NAS (o di Windows) e, se serve, la libreria dal [backup](#6-backup). |
