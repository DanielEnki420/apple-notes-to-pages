#!/usr/bin/env python3
"""pruefe_docx.py — Erzeugtes DOCX pruefen, bevor Pages es zu sehen bekommt.

Ein beschaedigtes Dokument wuerde Pages mit einem Dialog stehen lassen oder
still ein leeres Ergebnis liefern. Lieber vorher abbrechen und es sagen.
"""
import sys, zipfile
import xml.dom.minidom as MD

PFLICHT = ['[Content_Types].xml', '_rels/.rels', 'word/document.xml',
           'word/styles.xml', 'word/_rels/document.xml.rels']

def main():
    if len(sys.argv) < 2:
        print('Aufruf: pruefe_docx.py <datei.docx>', file=sys.stderr)
        return 2
    pfad = sys.argv[1]
    fehler = []
    try:
        z = zipfile.ZipFile(pfad)
    except Exception as e:
        print('Datei ist kein lesbares DOCX-Paket: %s' % e)
        return 1

    namen = set(z.namelist())
    for p in PFLICHT:
        if p not in namen:
            fehler.append('Bestandteil fehlt: %s' % p)

    for n in namen:
        if n.endswith(('.xml', '.rels')):
            try:
                MD.parseString(z.read(n))
            except Exception as e:
                fehler.append('%s ist kein gueltiges XML: %s' % (n, str(e)[:70]))

    kaputt = z.testzip()
    if kaputt:
        fehler.append('beschaedigter Eintrag im Paket: %s' % kaputt)

    # Jede Bild-Beziehung muss auch als Datei vorhanden sein
    try:
        rels = z.read('word/_rels/document.xml.rels').decode('utf-8')
        import re
        for ziel in re.findall(r'Target="(media/[^"]+)"', rels):
            if 'word/' + ziel not in namen:
                fehler.append('verwaiste Bildverknuepfung: %s' % ziel)
    except Exception:
        pass

    if fehler:
        for f in fehler[:10]:
            print('  ' + f)
        return 1
    absaetze = z.read('word/document.xml').decode('utf-8').count('<w:p>')
    bilder = len([n for n in namen if n.startswith('word/media/')])
    print('%d Absaetze, %d Bilder, Paket in Ordnung' % (absaetze, bilder))
    return 0

if __name__ == '__main__':
    sys.exit(main())
