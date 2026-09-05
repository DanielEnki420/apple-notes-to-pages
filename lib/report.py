#!/usr/bin/env python3
"""report.py — Abgleich: gefunden / uebernommen / fehlgeschlagen."""
import json, os, sys

DE = os.environ.get('EXPORT_NOTES_LANG', 'de') == 'de'

def t(de, en):
    return de if DE else en

def main():
    work = sys.argv[1]
    ergebnis = sys.argv[2] if len(sys.argv) > 2 else ''
    man = json.load(open(os.path.join(work, 'manifest.json'), encoding='utf-8'))
    try:
        rep = json.load(open(os.path.join(work, 'report.json'), encoding='utf-8'))
    except Exception:
        rep = {'ok': 0, 'failed': [], 'empty': [], 'images': 0}

    gefunden = man['total']
    lesefehler = man.get('errors', [])
    uebernommen = rep.get('ok', 0)
    fehlgeschlagen = rep.get('failed', [])
    leer = rep.get('empty', [])

    print(t('  Notizen gefunden:        %d', '  Notes found:             %d') % (gefunden + len(lesefehler)))
    print(t('  davon gelesen:           %d', '  of those read:           %d') % gefunden)
    print(t('  ins Dokument uebernommen: %d', '  included in document:    %d') % uebernommen)
    print(t('  Bilder uebernommen:      %d', '  images included:         %d') % rep.get('images', 0))
    print(t('  fehlgeschlagen:          %d', '  failed:                  %d') % (len(lesefehler) + len(fehlgeschlagen)))
    gesperrt = rep.get('locked', [])
    if gesperrt:
        print(t('  davon passwortgeschuetzt: %d (Titel enthalten, Inhalt von Apple gesperrt)', '  password-protected:      %d (title kept, content locked by Apple)')
              % len(gesperrt))
        for g in gesperrt:
            print('    · %s' % (g.get('title') or '(ohne Titel)')[:70])
    if leer:
        print(t('  ohne darstellbaren Inhalt: %d (als Hinweis im Dokument vermerkt)', '  without displayable content: %d (noted in the document)') % len(leer))

    for e in lesefehler:
        print(t('    ! nicht lesbar: %s — %s', '    ! unreadable: %s — %s') % (e.get('title', e.get('folder', '?')),
                                               e.get('message', '')[:90]))
    for e in fehlgeschlagen:
        print(t('    ! nicht uebernommen: %s — %s', '    ! not included: %s — %s') % (e.get('title', '?'), e.get('grund', '')[:90]))
    for s in man.get('skipped', []):
        print(t('  bewusst ausgelassen: Ordner „%s" (%s)', '  deliberately skipped: folder "%s" (%s)') % (s['folder'], s['reason']))

    if ergebnis and os.path.exists(ergebnis):
        size = 0
        if os.path.isdir(ergebnis):
            for root, _, files in os.walk(ergebnis):
                size += sum(os.path.getsize(os.path.join(root, f)) for f in files)
        else:
            size = os.path.getsize(ergebnis)
        print(t('  Dateigroesse:            %.1f MB', '  file size:               %.1f MB') % (size / 1048576))

    fehlend = (gefunden + len(lesefehler)) - uebernommen
    if fehlend == 0:
        print(t('  → Vollstaendig: jede gefundene Notiz ist im Dokument enthalten.', '  → Complete: every note found is present in the document.'))
    else:
        print(t('  → ACHTUNG: %d Notizen fehlen im Dokument (siehe Liste oben).', '  → WARNING: %d notes are missing from the document (see list above).') % fehlend)
    return 0

if __name__ == '__main__':
    sys.exit(main())
