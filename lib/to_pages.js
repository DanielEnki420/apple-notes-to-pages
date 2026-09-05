#!/usr/bin/env osascript -l JavaScript
/*
 * to_pages.js — DOCX in Pages oeffnen, nativ sichern und weitere Formate ablegen.
 * Aufruf: osascript -l JavaScript to_pages.js <docx> <zielpfad> <pages-container> [formate]
 *          formate = kommagetrennt aus: pages, pdf, epub, word, text
 *          qualitaet = Good | Better | Best (Bildqualitaet im PDF)
 *
 * Pages stammt aus dem App Store und laeuft in einer Sandbox: es darf nur
 * an wenige Orte schreiben, ein beliebiger Projektordner gehoert nicht dazu.
 * Deshalb wird immer zuerst in den eigenen iCloud-Container von Pages
 * gesichert (dort besteht immer Schreibrecht); das aufrufende Script
 * verschiebt die fertige Datei anschliessend an den Zielort.
 *
 * Ausgabe (stdout): der Pfad, unter dem die .pages-Datei tatsaechlich liegt.
 *
 * Pages wird ueber die Bundle-ID angesprochen, weil der sichtbare App-Name
 * je nach Version wechselt ("Pages" / "Pages Creator Studio").
 */
ObjC.import('Foundation');

// Von Pages unterstuetzte Ausgaben. "pages" laeuft ueber save (natives
// Format), alles andere ueber export.
var FORMATE = {
  pdf:  { endung: 'pdf',  name: 'PDF' },
  epub: { endung: 'epub', name: 'EPUB' },
  word: { endung: 'docx', name: 'Microsoft Word' },
  text: { endung: 'txt',  name: 'unformatted text' }
};

// Pages schreibt Exporte asynchron: der Aufruf kehrt zurueck, bevor die
// Datei fertig auf der Platte liegt. Deshalb aktiv warten, bis sie da ist
// und ihre Groesse sich nicht mehr aendert.
function warteAufDatei(fm, pfad, maxSekunden) {
  // Zwei Phasen, damit ein ausbleibender Export nicht minutenlang blockiert:
  // erst kurz auf das Erscheinen warten, dann geduldig auf das Fertigwerden.
  const ERSCHEINEN = 60;
  let da = false;
  for (let t = 0; t < ERSCHEINEN * 2 && !da; t++) {
    delay(0.5);
    da = fm.fileExistsAtPath($(pfad));
  }
  if (!da) return false;

  let letzte = -1, ruhig = 0;
  for (let t = 0; t < maxSekunden * 2; t++) {
    const attr = fm.attributesOfItemAtPathError($(pfad), $());
    const groesse = attr ? parseInt(attr.js.NSFileSize.js, 10) : 0;
    if (groesse > 0 && groesse === letzte) {
      ruhig++;
      if (ruhig >= 3) return true;      // 1,5 s unveraendert = fertig
    } else {
      ruhig = 0;
    }
    letzte = groesse;
    delay(0.5);
  }
  return true;
}

function run(argv) {
  const docxPath  = argv[0];
  const zielPfad  = argv[1];
  const container = argv[2];
  const formate   = (argv[3] || 'pages').split(',')
                      .map(function (f) { return f.trim().toLowerCase(); })
                      .filter(function (f) { return f.length; });
  const qualitaet = argv[4] || 'Good';

  const fm = $.NSFileManager.defaultManager;
  if (!fm.fileExistsAtPath($(docxPath))) {
    throw new Error('Die Vorlage wurde nicht gefunden: ' + docxPath);
  }
  fm.createDirectoryAtPathWithIntermediateDirectoriesAttributesError(
    $(container), true, $(), $());

  // Zwischenname im Pages-Container, kollisionsfrei
  const base = zielPfad.replace(/^.*\//, '').replace(/\.pages$/, '');
  let stage = container + '/' + base + '.pages';
  let i = 2;
  while (fm.fileExistsAtPath($(stage))) {
    stage = container + '/' + base + ' (' + i + ').pages'; i++;
  }

  const P = Application('com.apple.Pages');
  P.includeStandardAdditions = false;

  const doc = P.open(Path(docxPath));
  delay(2);

  const ergebnisse = [];

  // Weitere Formate zuerst: danach wird das Dokument geschlossen.
  formate.forEach(function (f) {
    if (f === 'pages' || !FORMATE[f]) return;
    const ziel = container + '/' + base + '.' + FORMATE[f].endung;
    try {
      // Ohne Angabe exportiert Pages Bilder in voller Aufloesung — ein
      // PDF wird damit schnell mehrfach so gross wie noetig.
      const opt = {};
      if (f === 'pdf') {
        opt.imageQuality = qualitaet;
      } else if (f === 'epub') {
        opt.title = base;
        opt.author = 'Apple Notizen';
        opt.language = 'de';
        opt.imageQuality = qualitaet;
      }
      P.export(doc, { to: Path(ziel), as: FORMATE[f].name,
                      withProperties: opt });
      if (warteAufDatei(fm, ziel, 600)) ergebnisse.push(f + '\t' + ziel);
      else ergebnisse.push(f + '\tFEHLER: Datei erschien nicht');
    } catch (e) {
      ergebnisse.push(f + '\tFEHLER: ' + e.message);
    }
  });

  if (formate.indexOf('pages') !== -1) {
    P.save(doc, { in: Path(stage), as: 'Pages Format' });
    // Pages haengt beim nativen Sichern die Endung des UTI an
    // (com.apple.iwork.pages.pages-tef).
    const kandidaten = [stage + '.pages-tef', stage, stage + '.pages'];
    let gefunden = null;
    // kurz warten, bis Pages ueberhaupt etwas angelegt hat
    for (let t = 0; t < 120 && !kandidaten.some(function (k) {
           return fm.fileExistsAtPath($(k)); }); t++) { delay(0.5); }
    for (let k = 0; k < kandidaten.length && !gefunden; k++) {
      if (fm.fileExistsAtPath($(kandidaten[k]))
          && warteAufDatei(fm, kandidaten[k], 600)) gefunden = kandidaten[k];
    }
    if (!gefunden) {
      try { doc.close({ saving: 'no' }); } catch (e) {}
      throw new Error('Pages meldete Erfolg, es wurde aber keine Datei gefunden.');
    }
    ergebnisse.unshift('pages\t' + gefunden);
  }

  try { doc.close({ saving: 'no' }); } catch (e) {}
  return ergebnisse.join('\n');
}
