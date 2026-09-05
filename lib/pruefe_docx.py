#!/usr/bin/env python3
"""pruefe_docx.py — Erzeugtes DOCX pruefen, bevor Pages es zu sehen bekommt.

Ein beschaedigtes Dokument wuerde Pages mit einem Dialog stehen lassen oder
still ein leeres Ergebnis liefern. Lieber vorher abbrechen und es sagen.
"""
import os, sys, zipfile
import xml.dom.minidom as MD

DE = os.environ.get('EXPORT_NOTES_LANG', 'de') == 'de'

def t(de, en):
    return de if DE else en

PFLICHT = ['[Content_Types].xml', '_rels/.rels', 'word/document.xml',
           'word/styles.xml', 'word/_rels/document.xml.rels']

def main():
    if len(sys.argv) < 2:
        print(t('Aufruf: pruefe_docx.py <datei.docx>', 'Usage: pruefe_docx.py <file.docx>'), file=sys.stderr)
        return 2
    pfad = sys.argv[1]
    fehler = []
    try:
        z = zipfile.ZipFile(pfad)
    except Exception as e:
        print(t('Datei ist kein lesbares DOCX-Paket: %s', 'File is not a readable DOCX package: %s') % e)
        return 1

    namen = set(z.namelist())
    for p in PFLICHT:
        if p not in namen:
            fehler.append(t('Bestandteil fehlt: %s', 'missing part: %s') % p)

    for n in namen:
        if n.endswith(('.xml', '.rels')):
            try:
                MD.parseString(z.read(n))
            except Exception as e:
                fehler.append(t('%s ist kein gueltiges XML: %s', '%s is not valid XML: %s') % (n, str(e)[:70]))

    kaputt = z.testzip()
    if kaputt:
        fehler.append(t('beschaedigter Eintrag im Paket: %s', 'damaged entry in package: %s') % kaputt)

    # Jede Bild-Beziehung muss auch als Datei vorhanden sein
    try:
        rels = z.read('word/_rels/document.xml.rels').decode('utf-8')
        import re
        for ziel in re.findall(r'Target="(media/[^"]+)"', rels):
            if 'word/' + ziel not in namen:
                fehler.append(t('verwaiste Bildverknuepfung: %s', 'orphaned image reference: %s') % ziel)
    except Exception:
        pass

    if fehler:
        for f in fehler[:10]:
            print('  ' + f)
        return 1
    absaetze = z.read('word/document.xml').decode('utf-8').count('<w:p>')
    bilder = len([n for n in namen if n.startswith('word/media/')])
    print(t('%d Absaetze, %d Bilder, Paket in Ordnung', '%d paragraphs, %d images, package is sound') % (absaetze, bilder))
    return 0

if __name__ == '__main__':
    sys.exit(main())
