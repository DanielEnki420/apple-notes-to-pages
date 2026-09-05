# Apple Notes → Pages

Führt **alle** Apple-Notizen zu **einem** Pages-Dokument zusammen — mit
klickbarem Inhaltsverzeichnis, erhaltener Formatierung und Bildern.
Ein Befehl, wiederholbar, rein lesend.

![macOS](https://img.shields.io/badge/macOS-13%2B-lightgrey)
![Lizenz](https://img.shields.io/badge/Lizenz-MIT-blue)
![Abhängigkeiten](https://img.shields.io/badge/Abhängigkeiten-keine-brightgreen)

```bash
./export-notes
```

> Läuft ohne Installation: nur macOS-Bordmittel (AppleScript/JXA, `sips`) und
> die Python-Standardbibliothek. Kein `pip install`, kein Netzwerkzugriff,
> keine Fremddienste.

---

## Benutzung

```bash
./export-notes            # vollständiger Export
./export-notes --test     # nur 3 Notizen, zum Ausprobieren
./export-notes --docx     # nur DOCX erzeugen, Pages-Schritt auslassen
./export-notes --status   # was hat sich seit dem letzten Export geändert?
```

### Reihenfolge der Notizen

```bash
./export-notes --reihenfolge tagebuch     # älteste zuerst (Voreinstellung)
./export-notes --reihenfolge rueckwaerts  # neueste zuerst
./export-notes --reihenfolge geaendert    # zuletzt bearbeitete zuerst
./export-notes --reihenfolge ordner       # nach Ordner, wie in Apple Notizen
./export-notes --reihenfolge titel        # alphabetisch
```

`tagebuch` sortiert nach dem **Erstellungsdatum**, nicht nach der letzten
Änderung — sonst rutschte eine alte Notiz nach vorn, sobald man sie einmal
anfasst. Bei den drei zeitlichen Reihenfolgen gliedert das Inhaltsverzeichnis
nach Jahren, bei `ordner` nach Ordnernamen.

**Ergebnis:** `iCloud Drive/Apple Notes Export/Apple Notes Gesamtexport.pages`

`--status` sieht in Apple Notizen frisch nach und vergleicht mit dem letzten
Export — es liest dafür nur Titel und Datum, keine Inhalte, und ist deshalb in
etwa einer Sekunde fertig.

## Was im Dokument steht

- Titelseite, danach ein klickbares Inhaltsverzeichnis, nach Jahren gegliedert
  (bzw. nach Ordnern, siehe Reihenfolge)
- Pro Notiz: Titel als **Überschrift 1**, darunter Ordner und Datum, dann der Inhalt
- Jede Notiz beginnt auf einer neuen Seite
- Übernommen werden: fett, kursiv, unterstrichen, durchgestrichen, Aufzählungen,
  nummerierte Listen, Tabellen, Links, Bilder und Festbreitenschrift
  (Terminal-Ausgaben und Code bleiben als solche erkennbar)

Pages kann zusätzlich sein eigenes, automatisch gepflegtes Inhaltsverzeichnis
einblenden: **Ansicht → Inhaltsverzeichnis einblenden**. Das funktioniert, weil
alle Notiztitel echte Überschrift-1-Absätze sind.

## Sicherheit

- Es wird **ausschließlich lesend** auf Apple Notizen zugegriffen. Keine Notiz
  wird verändert, verschoben oder gelöscht.
- Vorhandene Exporte werden **nie überschrieben**. Existiert die Zieldatei
  bereits, entsteht `Apple Notes Gesamtexport (2).pages` und so weiter.
- Keine Netzwerkzugriffe, keine Fremddienste. Es wird nichts nachinstalliert.
- Der Ordner „Zuletzt gelöscht“ bleibt bewusst außen vor (in `export-notes`
  über `SKIP_ORDNER` änderbar).

## Bekannte Grenzen

**Passwortgeschützte Notizen.** Apple gibt den Inhalt gesperrter Notizen
grundsätzlich nicht an die Automatisierung weiter — unabhängig vom verwendeten
Werkzeug. Solche Notizen erscheinen im Dokument mit Titel und einem sichtbaren
Hinweis, damit keine Notiz stillschweigend fehlt. Wer den Inhalt braucht,
entsperrt die Notiz in Apple Notizen und exportiert erneut.

**Große Bilder** werden auf 1400 px längste Kante verkleinert, damit das
Dokument in Pages flüssig bleibt. Anpassbar über `MAX_PIXELS` in
`lib/build_docx.py`.

**HEIC-Fotos** (vom iPhone) werden über das macOS-Bordmittel `sips` nach JPEG
gewandelt, weil DOCX das Format nicht kennt.

## Wenn etwas klemmt

Antwortet Pages nicht innerhalb von 15 Minuten — etwa weil dort ein Dialog auf
eine Eingabe wartet — bricht das Script diesen Schritt ab und legt stattdessen
das DOCX ab. Der Export geht also nie verloren. Ein Blick in Pages und ein
erneuter Aufruf genügen dann.

## Wenn du das Ergebnis selbst überprüfen willst

Zwei Fallstricke, die leicht zu falschem Alarm führen:

**Der Textexport von Pages lässt Tabelleninhalte aus.** Wer ein exportiertes
Dokument über „Exportieren → Nur Text“ auf Vollständigkeit prüft, vermisst
alles, was in Tabellen steht. Für eine belastbare Prüfung stattdessen als PDF
exportieren.

**PDF-Text lässt sich nicht naiv auslesen.** Umlaute und die Ligaturen fl/fi/ff
kommen bei einfacher Extraktion verstümmelt an, und Kerning zerlegt Wörter in
Fragmente. Ein Abgleich auf Zeichenketten meldet dann Lücken, die keine sind.

## Aufbau

```
export-notes           Hauptscript, steuert den Ablauf
lib/extract.js         liest die Notizen (JXA, nur lesend) → HTML + manifest.json
lib/build_docx.py      baut daraus ein DOCX (nur Standardbibliothek + PIL)
lib/to_pages.js        lässt Pages das DOCX nativ als .pages sichern
lib/pruefe_docx.py     prüft das DOCX, bevor Pages es zu sehen bekommt
lib/report.py          Abgleich gefunden / übernommen / fehlgeschlagen
lib/diff_manifest.py   Vergleich mit dem letzten Export (--status)
work/                  Zwischenstand und Manifest (darf gelöscht werden)
logs/                  ein Protokoll je Lauf
```

### Warum der Umweg über DOCX

Das `.pages`-Format ist proprietär; zuverlässig schreiben kann es nur Pages
selbst. DOCX ist der verlustärmste Weg dorthin: Überschriften, Seitenumbrüche,
Listen, Tabellen und eingebettete Bilder überträgt Pages beim Import sauber.
Den letzten Schritt erledigt Pages selbst per Automatisierung.

### Warum die Datei kurz im Pages-Ordner landet

Pages stammt aus dem App Store und läuft in einer Sandbox — es darf nicht in
einen beliebigen Ordner schreiben. Deshalb sichert es zuerst in seinen eigenen
iCloud-Ordner; das Script verschiebt die fertige Datei danach nach
„Apple Notes Export“.
