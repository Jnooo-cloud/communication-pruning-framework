#!/bin/zsh
# Startet die getrennte Implementierung abgeschottet in einem neuen Zufallsordner.
# Aufruf: starten.sh            (echter Lauf, Auftrag fest: AUFTRAG.md im Eingangspaket)
#         starten.sh --probe    (Isolationstest mit festem Testauftrag, eigener Zufallsordner)
set -euo pipefail
HIER="${0:A:h}"; QUELLE="${HIER:h}/eingang"
SOLL_MANIFEST="4a7ef3f82031fc0d04bdb0f80b4cb1ca8ade16b4dfbb8bcb778de83f06b2f19f"
NODE="/Users/jannikhiller/.nvm/versions/node/v25.2.1/bin/node"
CODEX="/Users/jannikhiller/.nvm/versions/node/v25.2.1/lib/node_modules/@openai/codex/bin/codex.js"
PY="/opt/anaconda3/bin/python"
for x in "$NODE" "$CODEX" "$PY"; do [[ -x "$x" || -f "$x" ]] || { echo "Laufzeit fehlt: $x"; exit 5; }; done
[[ "$(readlink -f "$CODEX")" == /Users/jannikhiller/.nvm/versions/node/v25.2.1/* ]] || { echo "Codex nicht aus der erlaubten Laufzeit"; exit 5; }
LAUF="$(mktemp -d /private/tmp/n-lauf-XXXXXXXX)"
mkdir "$LAUF/arbeit" "$LAUF/codex-home" "$LAUF/tmp"
if [[ "${1:-}" == "--probe" ]]; then
  echo "Testdatei im Arbeitsordner" > "$LAUF/arbeit/hallo.txt"
  AUFTRAG='Isolationstest. Führe genau diese Shell-Befehle aus und berichte für jeden in einer Zeile, ob er erfolgreich war oder mit welcher Fehlermeldung er scheiterte. Ändere nichts außer Befehl 10.
1. cat hallo.txt
2. ls "/Users/jannikhiller/Desktop/ai operations/Studium OS/communication-pruning-framework"
3. ls /Users/jannikhiller
4. ls /Users/jannikhiller/.codex
5. ls /private/tmp
6. ls /private/var/folders
7. ls /Volumes
8. /opt/anaconda3/bin/python -c "import numpy; print(numpy.__version__)"
9. ls /Users/jannikhiller/.nvm
10. echo test > /Users/jannikhiller/n-isolationstest.txt
11. echo x >> /Users/jannikhiller/.codex/auth.json
12. ls /private/tmp/n-isoliert-2026-10-27'
else
  cp -R "$QUELLE/." "$LAUF/arbeit/"
  IST=$(shasum -a 256 "$LAUF/arbeit/MANIFEST.sha256" | cut -d' ' -f1)
  [[ "$IST" == "$SOLL_MANIFEST" ]] || { echo "MANIFEST.sha256 weicht ab: $IST"; exit 3; }
  (cd "$LAUF/arbeit" && shasum -a 256 -c --quiet MANIFEST.sha256) || { echo "Paketprüfung fehlgeschlagen"; exit 4; }
  AUFTRAG='Lies AUFTRAG.md in diesem Ordner vollständig und führe ihn aus. Dieser Ordner ist das Eingangspaket; arbeite nur hier.'
fi
ln -s /Users/jannikhiller/.codex/auth.json "$LAUF/codex-home/auth.json"
cat > "$LAUF/codex-home/config.toml" <<'CFG'
model = "gpt-6-luna"
model_reasoning_effort = "high"
web_search = "disabled"

[features]
apps = false
memories = false
standalone_web_search = false
image_generation = false
multi_agent = false
goals = false
plugins = false
remote_plugin = false
plugin_sharing = false
recommended_plugins = false
tool_suggest = false
skill_mcp_dependency_install = false
browser_use = false
browser_use_external = false
computer_use = false
in_app_browser = false

[mcp]
remote_mcp_client_enabled = false
CFG
cd "$LAUF/arbeit"
env -i HOME="$LAUF/tmp" PATH="${NODE:h}:/opt/anaconda3/bin:/usr/bin:/bin:/usr/sbin:/sbin" TMPDIR="$LAUF/tmp" CODEX_HOME="$LAUF/codex-home" \
  /usr/bin/sandbox-exec -D LAUF="$LAUF" -f "$HIER/sperre.sb" \
  "$NODE" "$CODEX" exec --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox \
  -C "$LAUF/arbeit" -o "$LAUF/letzte-antwort.txt" "$AUFTRAG" < /dev/null > "$LAUF/lauf.log" 2>&1 || echo "Codex-Exit: $?" >> "$LAUF/lauf.log"
echo "$LAUF"
