#!/bin/zsh
# Sichert einen abgeschlossenen Lauf vor jedem Vergleich (außerhalb der Sandbox auszuführen).
# Aufruf: sichern.sh <Laufordner> <Nummer>   z. B. sichern.sh /private/tmp/n-lauf-AbCd1234 1
set -euo pipefail
HIER="${0:A:h}"; ZIEL="${HIER:h}"; LAUF="$1"; NR="$2"
[[ -d "$LAUF/arbeit/ausgabe" ]] || { echo "keine Ausgabe in $LAUF/arbeit/ausgabe"; exit 2; }
[[ ! -e "$ZIEL/ausgabe-$NR" && ! -e "$ZIEL/lauf-$NR" ]] || { echo "ausgabe-$NR oder lauf-$NR existiert schon"; exit 3; }
python3 "$HIER/pruefe_protokoll.py" "$LAUF" > /dev/null
cp -R "$LAUF/arbeit/ausgabe" "$ZIEL/ausgabe-$NR"
mkdir -p "$ZIEL/lauf-$NR"
cp -R "$LAUF/codex-home/sessions" "$ZIEL/lauf-$NR/sessions"
cp "$LAUF/lauf.log" "$LAUF/letzte-antwort.txt" "$LAUF/AUDIT.json" "$LAUF/AUDIT.md" "$ZIEL/lauf-$NR/"
echo "$LAUF" > "$ZIEL/lauf-$NR/LAUFORDNER.txt"
(cd "$ZIEL" && find "ausgabe-$NR" "lauf-$NR" -type f ! -name "SICHERUNG.sha256" -print0 | sort -z | xargs -0 shasum -a 256 > "lauf-$NR/SICHERUNG.sha256")
echo "gesichert: ausgabe-$NR, lauf-$NR; SHA-256 von SICHERUNG.sha256: $(shasum -a 256 "$ZIEL/lauf-$NR/SICHERUNG.sha256" | cut -d' ' -f1)"
echo "SHA-256 von AUSGABE.sha256: $(shasum -a 256 "$ZIEL/ausgabe-$NR/AUSGABE.sha256" 2>/dev/null | cut -d' ' -f1)"
