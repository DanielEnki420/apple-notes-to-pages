# Apple Notes → Pages

Merges **all** your Apple Notes into **one** Pages document — with a clickable
table of contents, preserved formatting and embedded images. One command,
repeatable, strictly read-only.

![macOS](https://img.shields.io/badge/tested%20on-macOS%2026-lightgrey)
![License](https://img.shields.io/badge/License-MIT-blue)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)

```bash
./export-notes
```

> Runs with no installation: only macOS built-ins (AppleScript/JXA, `sips`) and
> the Python standard library. No `pip install`, no network access, no
> third-party services.

*[Deutsche Fassung](README.de.md)*

---

## Installation

```bash
git clone https://github.com/DanielEnki420/apple-notes-to-pages.git
cd apple-notes-to-pages
./export-notes --test
```

No build step, nothing to install. If you downloaded a ZIP instead of cloning,
make the script executable once: `chmod +x export-notes`.

**Requirements**

| | |
|---|---|
| macOS | with Apple Notes (always present) |
| Pages | free from the Mac App Store — without it you get a DOCX |
| Python 3 | the system one is enough (`/usr/bin/python3`) |

macOS ships Python 3 with the Command Line Tools. If it is missing, the first
run offers to install them, or you can trigger it with
`xcode-select --install`.

Pillow (PIL) is **optional**. When present it is used for image scaling;
otherwise the script falls back to `sips`, a macOS built-in, which handles
sizing, scaling and format conversion just as well. Both paths are tested.

**On the first run** macOS asks once for permission to control Notes and Pages.
Confirm both prompts — without them the script cannot read your notes. You can
review this later under System Settings → Privacy & Security → Automation.

## Tested with

Developed and verified on **macOS 26.6 with Pages 15.3** against a single
iCloud account holding ~270 notes. It should work on older macOS versions — the
interfaces it uses (Notes and Pages scripting, `sips`) have been around for
years — but that is untested. The same goes for other account types
(Gmail, Exchange, "On My Mac"), shared notes, and much larger collections.

If you run into trouble on a different setup, an issue with your macOS and
Pages version is genuinely useful.

## Usage

```bash
./export-notes              # full export
./export-notes --test       # 3 notes only, to try it out
./export-notes --docx       # produce DOCX only, skip the Pages step
./export-notes --status     # what changed since the last export?
./export-notes --cleanup # delete the intermediate files (see Privacy)
```

**Result:** `iCloud Drive/Apple Notes Export/Apple Notes Gesamtexport.pages`

`--status` takes a fresh look at Apple Notes and compares it with the last
export. It reads titles and dates only, no content, so it finishes in about a
second.

### Note order

```bash
./export-notes --order diary     # oldest first (default, "diary")
./export-notes --order reverse  # newest first
./export-notes --order modified    # most recently edited first
./export-notes --order folder       # grouped by folder, as in Notes
./export-notes --order title        # alphabetical
```

`diary` sorts by **creation date**, not by last modification — otherwise an
old note would jump to the front the moment you touch it. The three
chronological orders group the table of contents by year; `folder` groups it by
folder name.

### Output formats

```bash
./export-notes --formats pages,pdf        # additionally a PDF
./export-notes --formats pages,pdf,epub   # PDF and e-book
# available: pages, pdf, epub, word, text
```

Image quality in PDF and EPUB is adjustable. For roughly 270 notes the
resulting PDF is about 4.5 MB at `good`, 7 MB at `better` and 71 MB at `best` —
which is why `good` is the default.

```bash
./export-notes --formats pages,pdf --quality better
```

### Scheduled export

```bash
./export-notes --schedule daily              # every day at 20:00
./export-notes --schedule weekly          # Sundays at 20:00
./export-notes --schedule daily --at 03:30   # your own time
./export-notes --schedule status                # show what is set up
./export-notes --schedule off                   # turn it off
```

Other options carry over, e.g. `--schedule daily --formats pages,pdf`.
Scheduling uses launchd, the macOS mechanism for recurring jobs.

Two things to know: Pages briefly opens on screen during an automated run —
unavoidable, as Pages only exports in the foreground. And on the first run macOS
asks once for permission to control Notes and Pages; that prompt has to be
confirmed or the scheduled export aborts.

### Language

Messages follow your system language (German or English). Override it with
`--lang de|en` or the environment variable `EXPORT_NOTES_LANG`. The German
option names (`--reihenfolge`, `--formate`, `--zeitplan`, `--bildqualitaet`,
`--aufraeumen`, `--um`) remain valid aliases.

## What the document contains

- A title page, then a clickable table of contents grouped by year (or folder)
- Per note: the title as **Heading 1**, then folder and date, then the content
- Every note starts on a new page
- Preserved: bold, italic, underline, strikethrough, bullet and numbered lists,
  tables, links, images and monospaced text (terminal output and code stay
  recognisable as such)

Pages can additionally show its own automatically maintained table of contents
via **View → Show Table of Contents**, because every note title is a real
Heading 1 paragraph.

## Privacy and safety

- Apple Notes is accessed **read-only**. No note is ever modified, moved or
  deleted.
- Existing exports are **never overwritten**. If the target file exists, the run
  produces `Apple Notes Gesamtexport (2).pages` and so on.
- No network access, no third-party services, nothing gets installed.
- The "Recently Deleted" folder is deliberately skipped (change `SKIP_ORDNER`
  in `export-notes`).
- **While exporting, your note contents sit in `work/` as plain text.** That
  directory is in `.gitignore` and must never be committed anywhere. Run
  `./export-notes --cleanup` afterwards to remove it; the finished document
  is kept.

## Known limits

**Password-protected notes.** Apple does not hand the contents of locked notes
to automation — with any tool, not just this one. Such notes appear in the
document with their title and a visible note, so nothing goes missing silently.
Unlock them in Apple Notes and export again if you need their content.

**Large images** are scaled down to 1400 px on the longest edge so the document
stays responsive in Pages. Adjustable via `MAX_PIXELS` in `lib/build_docx.py`.
Scaling uses Pillow when available and `sips` otherwise.

**HEIC photos** (from iPhone) are converted to JPEG using the macOS built-in
`sips`, because DOCX does not know that format.

## Verifying the result yourself

Two pitfalls that easily cause false alarm:

**Pages' plain-text export omits table contents.** Checking an exported document
for completeness via "Export → Plain Text" will appear to lose everything inside
tables. Export as PDF instead for a meaningful check.

**PDF text cannot be extracted naively.** Umlauts and the fl/fi/ff ligatures come
out mangled with simple extraction, and kerning splits words into fragments. A
plain string comparison then reports gaps that are not there.

## How it works

```
export-notes           main script, drives the process
lib/extract.js         reads the notes (JXA, read-only) → HTML + manifest.json
lib/build_docx.py      builds a DOCX from it (standard library + PIL only)
lib/pruefe_docx.py     validates the DOCX before Pages ever sees it
lib/to_pages.js        has Pages save it natively and export other formats
lib/report.py          reconciliation: found / included / failed
lib/diff_manifest.py   comparison with the last export (--status)
lib/zeitplan.sh        sets up and removes the launchd schedule
work/                  intermediate state and manifest (safe to delete)
logs/                  one log per run
```

### Why the detour through DOCX

The `.pages` format is proprietary; only Pages itself can write it reliably.
DOCX is the least lossy path there: Pages imports headings, page breaks, lists,
tables and embedded images cleanly. The final step is done by Pages itself via
automation.

### Why the file briefly lands in the Pages folder

Pages comes from the App Store and runs in a sandbox — it cannot write to an
arbitrary directory. So it saves into its own iCloud folder first, and the
script then moves the finished file to "Apple Notes Export".

## License

MIT — see [LICENSE](LICENSE).
