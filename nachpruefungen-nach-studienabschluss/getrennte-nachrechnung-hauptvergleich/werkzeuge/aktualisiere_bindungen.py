"""Berechnet alle in VORAB-N.md tabellarisch gebundenen SHA-256 neu und meldet Änderungen.
Zeilen der Form | `pfad` ... | `sha` | ; Pfade relativ zu diesem Ordner, sonst unter eingang/, Sollwerte im Repository."""
import hashlib, re, sys, os
from pathlib import Path
H = Path(__file__).resolve().parents[1]
REPO = H.parents[2] / 'communication-pruning-framework'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def finde(name):
    for k in (H / name, H / 'eingang' / name, REPO / name.replace('communication-pruning-framework/', ''), H.parents[1] / 'output' / name):
        if k.is_file(): return k
    return None
p = H / 'VORAB-N.md'; t = p.read_text(encoding='utf-8'); neu = []; aend = 0; fehlt = []
for z in t.split('\n'):
    m = re.match(r'\|\s*(?:Sollwert |Z56 |Zahlen der Arbeit: )?`([^`]+)`.*\|\s*`([0-9a-f]{64})`\s*\|\s*$', z)
    if m and not m.group(1).startswith('protokolle/'):
        name = m.group(1); f = finde(name if not name.startswith('pruefroutine') else '')
        if name.startswith('pruefroutine-studienlaeufe/'): f = REPO / 'nachpruefungen-nach-studienabschluss' / name
        if name.startswith('thesis-rev25'): f = H.parents[0] / 'council-feedback-rev25-2026-10-27' / 'quellen' / name
        if f and f.is_file():
            s = sha(f)
            if s != m.group(2): z = z.replace(m.group(2), s); aend += 1; print('geändert:', name)
        else: fehlt.append(name)
    neu.append(z)
t = '\n'.join(neu)
b = sum(f.stat().st_size for f in (H / 'eingang').rglob('*') if f.is_file()); n = sum(1 for f in (H / 'eingang').rglob('*') if f.is_file())
t = re.sub(r'(Eingangspaket `eingang/`: 18\.091 Dateien und `MANIFEST\.sha256`, zusammen )[\d.]+( Bytes)', lambda m: m.group(1) + f'{b:,}'.replace(',', '.') + m.group(2), t)
p.write_text(t, encoding='utf-8')
r = H / 'README.md'; u = r.read_text(encoding='utf-8')
u = re.sub(r'(18\.092 Dateien einschließlich `MANIFEST\.sha256`, )[\d.]+( Bytes)', lambda m: m.group(1) + f'{b:,}'.replace(',', '.') + m.group(2), u)
r.write_text(u, encoding='utf-8')
print('Änderungen:', aend, '| nicht gefunden:', fehlt, '| Paket:', n, 'Dateien,', b, 'Bytes')
