<!-- status: Arbeitsordner der getrennten Nachrechnung N | Vorabfestlegung festgeschrieben (268c0ddb8) | Lauf 1 abgeschlossen und vor dem Vergleich festgeschrieben (053c6d10d) | Vergleich und Einordnung erledigt: 18.080 Läufe gleich, 4 Meldungen Klasse (c) | 2026-10-28 -->

# Getrennte Nachrechnung des Hauptvergleichs (N)

Stand 28.10.2026: alle sieben Schritte erledigt. Vorabfestlegung festgeschrieben (Commit 268c0ddb8), Lauf 1 in der Sandbox ausgeführt und vor dem Vergleich festgeschrieben (Commit 053c6d10d, Abschnitt „Lauf 1“ unten), Vergleich in `vergleich/bericht-1/VERGLEICH-ERGEBNIS.md`, Einordnung der vier Meldungen (alle Klasse (c)) in `vergleich/bericht-1/EINORDNUNG-1.md`.

## Inhalt

| Pfad | Zweck | sieht die Implementierung |
|---|---|---|
| `VORAB-N.md` | Vorabfestlegung: Umfang, Eingaben mit Prüfsummen, Rechenregeln, Toleranzen, Abweichungsklassen, Grenzen, geschlossene Punkte | nein |
| `eingang/` | Eingangspaket: Auftrag, Methodenauszug, Laufliste, 18.080 Laufprotokolle, MuSiQue-Dev, Bewertungsskript, Plandateien, Formatbeschreibung, `MANIFEST.sha256` | ja, nur dieses, als Kopie |
| `werkzeuge/` | Skripte, die das Paket gebaut und geprüft haben | nein |
| `zuordnung/HERKUNFT-PROTOKOLLE.tsv` | Paketpfad jedes Protokolls zu seinem Quellpfad unter `eval-harness/eval/runs` | nein |
| `pruefung/LECKPRÜFUNG.json` | Ergebnis der Leckprüfung | nein |
| `vergleich/vergleich.py` | Vergleich der festgeschriebenen Ausgabe mit P-ROWS, P-ANALYSIS, Arbeit 6.3 und Endantworten aus gebundenen Rohprotokollen | nein (enthält die Zahlen aus 6.3) |
| `vergleich/gegenprobe.py`, `vergleich/gegenprobe/` | Gegenprobe an einer Pseudoausgabe aus P-ROWS, P-ANALYSIS und Rohprotokollantworten | nein |

## Ablauf

1. **Vorabfestlegung** (erledigt am 27.10.): `VORAB-N.md`, Paket mit Manifest, Leckprüfung, `vergleich.py` und Gegenprobe.
2. **Gegenprüfung durch Codex** (vier Runden durchgeführt; F4 und F11 von Jannik am 27.10.2026 freigegeben): `VORAB-N.md`, `eingang/AUFTRAG.md`, `eingang/METHODENAUSZUG.md`, `werkzeuge/leckpruefung.py` mit Ergebnis, `vergleich/vergleich.py`, `vergleich/gegenprobe.py`. O1 bis O5 sind in `VORAB-N.md` Abschnitt 13 entschieden, O1 und O2 (F4, F11) mit Janniks Freigabe vom 27.10.2026. Das Eingangsmanifest wurde nach der Auftragsänderung neu geschrieben. Leckprüfung, Wortgleichheitsprüfung und Gegenprobe sind dokumentiert.
3. **Gezielter Commit als Zeitnachweis** (erledigt: Commit `268c0ddb80559537d649662c6c5ae3ad0b41315e` vom 27.10.2026, 23:21:06 +01:00, gepusht auf `research-run-b-anmelde-verankert` und `main`), nach Ansage, nach Janniks Freigabe von F4 und F11 (erteilt am 27.10.2026) und der Codex-Prüfung des Commits, ausschließlich der in `VORAB-N.md` 9.3 genannten Dateien mit `git add -f`. Keine Zweitkopie unter `project/`. Keine Protokolle und keine MuSiQue-Daten ins Repository; sie bleiben über `MANIFEST.sha256` gebunden. Danach Push auf den privaten Remote.
4. **Implementierung** in getrennter Sitzung (Codex) über `isolation/starten.sh`: neuer Zufallsordner, Kopie von `eingang/` mit Manifestprüfung, geschlossene Sandbox, Zusatzdienste aus, fester Auftrag (`AUFTRAG.md`), siehe `VORAB-N.md` Abschnitt Isolation. Netzzugriffe der ausgeführten Befehle sind verboten, aber nicht technisch gesperrt; danach `isolation/pruefe_protokoll.py` über das Sitzungsprotokoll. Der Codex-Prozess selbst nutzt das Netz nur für die Modellverbindung. Rückgabe: Pfad von `ausgabe/` und SHA-256 von `AUSGABE.sha256`.
5. **Festschreiben**: `isolation/sichern.sh <Laufordner> 1` (Protokollprüfung, Ausgabe nach `ausgabe-1/`, Sitzungsprotokolle, `lauf.log`, Antwort und Audit nach `lauf-1/`, Prüfsummen in `lauf-1/SICHERUNG.sha256`), SHA-256 von `AUSGABE.sha256` und `SICHERUNG.sha256` notieren und committen, bevor verglichen wird.
6. **Vergleich**, erst dann:

   ```
   python3 -I vergleich/vergleich.py --ausgabe ausgabe-1 --bericht vergleich/bericht-1 --ausgabe-sha <SHA-256 von AUSGABE.sha256>
   ```

   Exit 0: keine Meldung; Exit 1: Meldungen in `vergleich/bericht-1/VERGLEICH-ERGEBNIS.{json,md}`; Exit 2: Festschreibung oder Sollwertdatei verletzt, kein Vergleich.
7. **Einordnung**: eine getrennte Instanz ordnet jede Meldung nach `VORAB-N.md` Abschnitt 8 ein, am Plantext, nicht am Code. Klasse (a): höchstens eine Korrekturrunde nach `ausgabe-korrektur-1/`, Hinweis nur auf die verletzte Regel. Klasse (b) mit Folgen für Lesart oder Kernzahlen: Jannik entscheidet vor jeder Textänderung. Danach die Textstellen E28, E30 bis E33, E39, E40.

## Kennzahlen des Pakets

18.092 Dateien einschließlich `MANIFEST.sha256`, 448.900.017 Bytes, davon 18.080 Laufprotokolle. SHA-256 von `eingang/MANIFEST.sha256`: `4a7ef3f82031fc0d04bdb0f80b4cb1ca8ade16b4dfbb8bcb778de83f06b2f19f`.

## Prüfstatus

- Gegenprobe `vergleich/gegenprobe.py`: bestanden. Null- und Reihenfolgeprobe hatten keine Meldung; die Änderungsprobe meldete alle vorgegebenen Änderungen; alle neun Feld- und Laufmengenmeldungen wurden gefunden. Fehlender Hash, Zusatzdatei, doppelter oder unsicherer Manifestpfad sowie eine Dateiänderung nach der Festschreibung blockierten jeweils mit Exit 2.
- Wortgleichheitsprüfung: bestanden, Abschnitte 3 bis 5 in `AUFTRAG.md` und `VORAB-N.md` sind wortgleich.
- Leckprüfung werkzeuge/leckpruefung.py: bestanden, Exit 0. Geprüft wurden 120 Ergebniszahlen in 2.474 Textformen; keine Befunde.
- Die eigentliche Nachrechnung wurde nicht ausgeführt.

## Lauf 1 (27.10.2026)

- Aufruf des Startskripts 23:22:29, Rückkehr 23:27:56 mit Exit 0 (lokale Zeit, Ausgabe des Aufrufs in `lauf-1-start.log`, außerhalb von `SICHERUNG.sha256`). Die Codex-Sitzung selbst lief laut Sitzungsprotokoll von 23:22:47 bis 23:27:55. Laufordner `/private/tmp/n-lauf-qovPQe7t`, Startskript unverändert gegenüber Commit 268c0ddb8.
- Die Implementierung arbeitete, wie `AUFTRAG.md` Zeile 22 verlangt, in einer Kopie des Pakets (`arbeit/nachrechnung-n/`) und schrieb `ausgabe/` dorthin. `sichern.sh` erwartet `arbeit/ausgabe/`; deshalb wurde der Ordner vor der Sicherung unverändert nach `arbeit/ausgabe/` kopiert (`cp -Rp`) und mit `shasum -c AUSGABE.sha256` an beiden Orten geprüft. Inhalt identisch.
- Codex-Prüfung des Sicherungs-Commits: `GEGENPRUEFUNG-CODEX-6-SICHERUNG.md`, commitfähig: ja; die zwei Soll-Hinweise (Pfadtreffer genauer benennen, Herkunft der Zeiten) sind hier umgesetzt.
- SHA-256 von `ausgabe-1/AUSGABE.sha256`: `1c467a83784cecc738e9e36d107b3853b8999721820cb4d456def9dd31b62b8d`.
- SHA-256 von `lauf-1/SICHERUNG.sha256`: `b76d3fb047feef5fdd576eb008ffedfacfb48594ce7eeeb1eecd4a2791734396`.
- Protokollprüfung (`lauf-1/AUDIT.md`): 40 Werkzeugaufrufe, 0 Netzmuster, 0 andere Werkzeuge als Shell und Patch. 6 Treffer „Pfad außerhalb“ (fünfmal `/tmp/manifest-check-n.txt`, einmal der Elternpfad `/tmp`) gehören alle zu derselben Umleitung: Die Umleitung einer Manifestprüfung dorthin wurde von der Sandbox mit „operation not permitted“ abgewiesen, die Datei entstand nicht; die Implementierung hat das selbst im Zugriffsprotokoll vermerkt.
- Suche nach Zugangsdaten in `ausgabe-1/` und `lauf-1/`: nur Fehltreffer (MuSiQue-Kennungen `task-…`, verschlüsselte Denkblöcke der Sitzung).
