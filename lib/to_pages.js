#!/usr/bin/env osascript -l JavaScript
/*
 * to_pages.js — DOCX in Pages oeffnen und nativ als .pages sichern.
 * Aufruf: osascript -l JavaScript to_pages.js <docx> <zielpfad> <pages-container>
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

function run(argv) {
  const docxPath  = argv[0];
  const zielPfad  = argv[1];
  const container = argv[2];

  const fm = $.NSFileManager.defaultManager;
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

  P.save(doc, { in: Path(stage), as: 'Pages Format' });
  delay(1);
  try { doc.close({ saving: 'no' }); } catch (e) {}

  // Pages haengt beim nativen Sichern die Endung des UTI an
  // (com.apple.iwork.pages.pages-tef). Wir geben den Pfad zurueck,
  // der tatsaechlich entstanden ist; das Shell-Script benennt um.
  const kandidaten = [stage + '.pages-tef', stage, stage + '.pages'];
  for (let k = 0; k < kandidaten.length; k++) {
    if (fm.fileExistsAtPath($(kandidaten[k]))) return kandidaten[k];
  }
  throw new Error('Pages meldete Erfolg, es wurde aber keine Datei gefunden.');
}
