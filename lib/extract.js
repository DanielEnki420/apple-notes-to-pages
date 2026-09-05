#!/usr/bin/env osascript -l JavaScript
/*
 * extract.js — Apple Notes -> HTML + Manifest
 *
 * STRIKT LESEND. Es wird ausschliesslich lesend auf Notes zugegriffen;
 * keine Property wird je gesetzt, keine Notiz angelegt oder geloescht.
 *
 * Aufruf:  osascript -l JavaScript extract.js <workDir> <limit|0> <skipFolders> [meta]
 *          skipFolders = kommaseparierte Ordnernamen, die uebersprungen werden
 *          meta        = "meta" liest nur Titel/Datum/Status, keine Inhalte.
 *                        Das ist sehr schnell und dient dem Abgleich (--status).
 */
ObjC.import('Foundation');

function writeFile(path, text) {
  const str = $.NSString.alloc.initWithUTF8String(text);
  return str.writeToFileAtomicallyEncodingError(
    $(path).stringByExpandingTildeInPath, true, $.NSUTF8StringEncoding, $());
}

function log(msg) {
  $.NSFileHandle.fileHandleWithStandardError.writeData(
    $.NSString.alloc.initWithUTF8String(msg + '\n')
      .dataUsingEncoding($.NSUTF8StringEncoding));
}

function iso(d) {
  try { return d ? d.toISOString() : null; } catch (e) { return null; }
}

function run(argv) {
  const workDir = argv[0];
  const limit = parseInt(argv[1] || '0', 10);
  const skip = (argv[2] || '').split(',').map(s => s.trim()).filter(s => s.length);
  const nurMeta = (argv[3] || '') === 'meta';

  const fm = $.NSFileManager.defaultManager;
  const notesDir = workDir + '/notes';
  fm.createDirectoryAtPathWithIntermediateDirectoriesAttributesError(
    $(notesDir), true, $(), $());

  // Bundle-ID statt Name: der App-Name kann abweichen (Rebranding),
  // die Bundle-ID ist stabil.
  const Notes = Application('com.apple.Notes');
  Notes.includeStandardAdditions = false;

  const manifest = { generated: new Date().toISOString(), notes: [], errors: [], skipped: [] };
  let idx = 0, done = false;

  const accounts = Notes.accounts;
  for (let a = 0; a < accounts.length && !done; a++) {
    const acc = accounts[a];
    let accName = 'Unbekannt';
    try { accName = acc.name(); } catch (e) {}

    const folders = acc.folders;
    for (let f = 0; f < folders.length && !done; f++) {
      const folder = folders[f];
      let folderName = 'Unbekannt';
      try { folderName = folder.name(); } catch (e) {}

      if (skip.indexOf(folderName) !== -1) {
        manifest.skipped.push({ folder: folderName, account: accName, reason: 'per Konfiguration ausgeschlossen' });
        log('  uebersprungen (Ordner): ' + folderName);
        continue;
      }

      let noteCount = 0;
      try { noteCount = folder.notes.length; } catch (e) { noteCount = 0; }
      if (noteCount === 0) continue;
      log('  Ordner "' + folderName + '" (' + noteCount + ' Notizen)');

      // Metadaten sammeln statt Feld fuer Feld abfragen: ein Apple Event
      // je Eigenschaft statt einem je Notiz. Das ist um Groessenordnungen
      // schneller. Schlaegt ein Sammelzugriff fehl, wird pro Notiz
      // nachgefragt (siehe hole()).
      const notes = folder.notes;
      const meta = {};
      ['name', 'id', 'creationDate', 'modificationDate', 'passwordProtected']
        .forEach(function (prop) {
          try {
            const werte = notes[prop]();
            meta[prop] = (werte && werte.length === noteCount) ? werte : null;
          } catch (e) { meta[prop] = null; }
        });

      function hole(prop, n, fallback) {
        if (meta[prop] !== null && meta[prop] !== undefined) {
          const v = meta[prop][n];
          return (v === undefined || v === null) ? fallback : v;
        }
        try {
          const v = notes[n][prop]();
          return (v === undefined || v === null) ? fallback : v;
        } catch (e) { return fallback; }
      }

      for (let n = 0; n < noteCount && !done; n++) {
        const nid = hole('id', n, null);
        if (nid === null) {
          manifest.errors.push({ folder: folderName, index: n,
            stage: 'zugriff', message: 'Notiz nicht ansprechbar' });
          continue;
        }
        const title = hole('name', n, '') || '(ohne Titel)';

        // Gesperrte Notizen geben ihren Inhalt nicht heraus — das ist
        // Absicht von Apple und muss im Bericht sichtbar bleiben.
        const locked = hole('passwordProtected', n, false) === true;

        // Der Text muss einzeln geholt werden: alle Rumpfe auf einmal
        // waeren zusammen mehrere Dutzend MB im Speicher. Beim reinen
        // Abgleich wird er gar nicht erst angefasst.
        let body = '', bodyErr = null;
        if (!nurMeta) {
          try { body = notes[n].body(); } catch (e) { bodyErr = String(e); }
          if (body === null || body === undefined) {
            body = '';
            if (!bodyErr && !locked) bodyErr = 'body ist leer (missing value)';
          }
        }

        const slug = String(idx).padStart(5, '0');
        const file = notesDir + '/' + slug + '.html';
        const ok = nurMeta ? true : writeFile(file, body);
        if (!ok) {
          manifest.errors.push({ id: nid, title: title, folder: folderName,
            stage: 'schreiben', message: 'HTML konnte nicht geschrieben werden' });
          continue;
        }

        const entry = {
          index: idx, id: nid, title: title,
          folder: folderName, account: accName,
          file: slug + '.html', length: body.length, locked: locked
        };
        entry.created = iso(hole('creationDate', n, null));
        entry.modified = iso(hole('modificationDate', n, null));
        if (bodyErr) entry.warning = bodyErr;

        manifest.notes.push(entry);
        idx++;
        if (idx % 25 === 0) log('    ... ' + idx + ' Notizen gelesen');
        if (limit > 0 && idx >= limit) { done = true; }
      }
    }
  }

  manifest.total = manifest.notes.length;
  writeFile(workDir + '/manifest.json', JSON.stringify(manifest, null, 2));
  log('  fertig: ' + manifest.total + ' Notizen, ' + manifest.errors.length + ' Fehler');
  return JSON.stringify({ total: manifest.total, errors: manifest.errors.length });
}
