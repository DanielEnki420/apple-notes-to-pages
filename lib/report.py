#!/usr/bin/env python3
"""report.py — Abgleich: gefunden / uebernommen / fehlgeschlagen."""
import json, os, sys

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

    print('  Notizen gefunden:        %d' % (gefunden + len(lesefehler)))
    print('  davon gelesen:           %d' % gefunden)
    print('  ins Dokument uebernommen: %d' % uebernommen)
    print('  Bilder uebernommen:      %d' % rep.get('images', 0))
    print('  fehlgeschlagen:          %d' % (len(lesefehler) + len(fehlgeschlagen)))
    gesperrt = rep.get('locked', [])
    if gesperrt:
        print('  davon passwortgeschuetzt: %d (Titel enthalten, Inhalt von Apple gesperrt)'
              % len(gesperrt))
        for g in gesperrt:
            print('    · %s' % (g.get('title') or '(ohne Titel)')[:70])
    if leer:
        print('  ohne darstellbaren Inhalt: %d (als Hinweis im Dokument vermerkt)' % len(leer))

    for e in lesefehler:
        print('    ! nicht lesbar: %s — %s' % (e.get('title', e.get('folder', '?')),
                                               e.get('message', '')[:90]))
    for e in fehlgeschlagen:
        print('    ! nicht uebernommen: %s — %s' % (e.get('title', '?'), e.get('grund', '')[:90]))
    for s in man.get('skipped', []):
        print('  bewusst ausgelassen: Ordner „%s" (%s)' % (s['folder'], s['reason']))

    if ergebnis and os.path.exists(ergebnis):
        size = 0
        if os.path.isdir(ergebnis):
            for root, _, files in os.walk(ergebnis):
                size += sum(os.path.getsize(os.path.join(root, f)) for f in files)
        else:
            size = os.path.getsize(ergebnis)
        print('  Dateigroesse:            %.1f MB' % (size / 1048576))

    fehlend = (gefunden + len(lesefehler)) - uebernommen
    if fehlend == 0:
        print('  → Vollstaendig: jede gefundene Notiz ist im Dokument enthalten.')
    else:
        print('  → ACHTUNG: %d Notizen fehlen im Dokument (siehe Liste oben).' % fehlend)
    return 0

if __name__ == '__main__':
    sys.exit(main())
