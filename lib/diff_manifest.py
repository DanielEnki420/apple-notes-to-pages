#!/usr/bin/env python3
"""diff_manifest.py — Was hat sich seit dem letzten Export geaendert?"""
import json, os, sys

def load(p):
    try:
        return {n['id']: n for n in json.load(open(p, encoding='utf-8'))['notes']}
    except Exception:
        return {}

def main():
    jetzt = load(sys.argv[1])
    vorher = load(sys.argv[2]) if len(sys.argv) > 2 and os.path.exists(sys.argv[2]) else {}
    if not vorher:
        print('  Kein frueherer Export hinterlegt — beim naechsten Lauf steht hier der Vergleich.')
        return 0
    neu = [n for i, n in jetzt.items() if i not in vorher]
    weg = [n for i, n in vorher.items() if i not in jetzt]
    geaendert = [n for i, n in jetzt.items()
                 if i in vorher and n.get('modified') != vorher[i].get('modified')]
    print('  seit dem letzten Export:')
    print('    neu:        %d' % len(neu))
    print('    geaendert:  %d' % len(geaendert))
    print('    entfernt:   %d' % len(weg))
    for n in (neu + geaendert)[:15]:
        print('      · %s' % (n.get('title') or '(ohne Titel)')[:70])
    if not (neu or geaendert or weg):
        print('    → nichts veraendert; ein erneuter Export ist nicht noetig.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
