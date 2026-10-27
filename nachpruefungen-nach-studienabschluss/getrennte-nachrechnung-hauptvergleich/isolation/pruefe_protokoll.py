"""Prüft das vollständige Codex-Sitzungsprotokoll eines Laufs (außerhalb der Sandbox auszuführen).
Aufruf: python3 pruefe_protokoll.py <LAUF-Ordner>
Schreibt <LAUF>/AUDIT.json und <LAUF>/AUDIT.md: jeden Werkzeugaufruf mit Eingabe, Treffer auf Netzmuster,
Aufrufe anderer Werkzeuge als Shell/Patch (Plugins, MCP, Websuche) und absolute Pfade außerhalb des Laufordners."""
import json, re, sys, glob, hashlib
from pathlib import Path
LAUF = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 and sys.argv[1] != "--selbsttest" else Path("/private/tmp/n-lauf-TEST")
NETZ = re.compile(r'\b(curl|wget|git\s+(clone|fetch|pull)|pip\s+(install|download)|conda\s+install|npm\s+(install|i)\b|ssh|scp|nc\s|telnet|urllib|requests\.|http\.client|socket\.|aiohttp|httpx|https?://)', re.I)
ERLAUBT = [LAUF, Path('/opt/anaconda3'), Path('/usr'), Path('/bin'), Path('/sbin'), Path('/dev/null'), Path('/dev/stdout'),
           Path('/dev/stderr'), Path('/Users/jannikhiller/.nvm/versions/node/v25.2.1')]
def innerhalb(pfad):
    """Komponentenweiser Vergleich: Geschwisterordner wie <LAUF>-kopie gelten nicht als innerhalb."""
    q = Path(pfad)
    for wurzel in ERLAUBT:
        try:
            q.relative_to(wurzel); return True
        except ValueError:
            pass
    return False
PFAD = re.compile(r'(?<![\w.])(/(?:Users|private|tmp|var|Volumes|opt|etc|Library|System|Applications)[^\s"\'`;|&)]*)')
STANDARD = {'exec', 'exec_command', 'shell', 'local_shell', 'apply_patch', 'update_plan', 'write_stdin', 'view_image'}
if len(sys.argv) > 1 and sys.argv[1] == '--selbsttest':
    faelle = {str(LAUF / 'arbeit' / 'x.py'): True, str(LAUF) + '-kopie/x.py': False, '/private/tmp/n-lauf-ANDERER/x': False,
              '/opt/anaconda3/bin/python': True, '/Users/jannikhiller/Desktop/x': False, '/Users/jannikhiller/.nvm/versions/node/v25.2.10/x': False}
    fehler = [f for f, soll in faelle.items() if innerhalb(f) != soll]
    print('Selbsttest', 'bestanden' if not fehler else 'FEHLER: ' + ', '.join(fehler)); sys.exit(1 if fehler else 0)
sitzungen = sorted(glob.glob(str(LAUF / 'codex-home' / 'sessions' / '**' / '*.jsonl'), recursive=True))
aufrufe, netz, fremd, pfade = [], [], [], []
for s in sitzungen:
    for zeile in open(s, encoding='utf-8'):
        d = json.loads(zeile); p = d.get('payload') if isinstance(d.get('payload'), dict) else {}
        typ = p.get('type', '')
        if typ in ('function_call', 'custom_tool_call', 'local_shell_call', 'mcp_tool_call', 'web_search_call', 'tool_search_call'):
            name = p.get('name') or typ
            eingabe = p.get('input') or p.get('arguments') or json.dumps(p.get('action', {}), ensure_ascii=False)
            if not isinstance(eingabe, str): eingabe = json.dumps(eingabe, ensure_ascii=False)
            nr = len(aufrufe) + 1
            aufrufe.append({'nr': nr, 'typ': typ, 'name': name, 'eingabe': eingabe})
            if typ in ('mcp_tool_call', 'web_search_call', 'tool_search_call') or name not in STANDARD:
                fremd.append(nr)
            if NETZ.search(eingabe): netz.append({'nr': nr, 'treffer': sorted(set(m.group(0) for m in NETZ.finditer(eingabe)))})
            for m in PFAD.finditer(eingabe):
                pf = m.group(1)
                if not innerhalb(pf.rstrip('/.,')): pfade.append({'nr': nr, 'pfad': pf})
erg = {'lauf': str(LAUF), 'sitzungsdateien': [{'datei': s, 'sha256': hashlib.sha256(Path(s).read_bytes()).hexdigest()} for s in sitzungen],
       'werkzeugaufrufe': len(aufrufe), 'netz_treffer': netz, 'andere_werkzeuge': fremd, 'pfade_ausserhalb': pfade, 'aufrufe': aufrufe}
(LAUF / 'AUDIT.json').write_text(json.dumps(erg, ensure_ascii=False, indent=1), encoding='utf-8')
md = [f'# Protokollprüfung {LAUF.name}', '', f'Sitzungsdateien: {len(sitzungen)}; Werkzeugaufrufe: {len(aufrufe)}',
      f'Netzmuster: {len(netz)}; andere Werkzeuge als Shell/Patch: {len(fremd)}; Pfade außerhalb des Laufordners: {len(pfade)}', '']
for x in netz: md.append(f'- Netz, Aufruf {x["nr"]}: {", ".join(x["treffer"])}')
for x in fremd: md.append(f'- anderes Werkzeug, Aufruf {x}: {aufrufe[x-1]["name"]}')
for x in pfade: md.append(f'- Pfad außerhalb, Aufruf {x["nr"]}: {x["pfad"]}')
(LAUF / 'AUDIT.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
print('\n'.join(md[:4]))
