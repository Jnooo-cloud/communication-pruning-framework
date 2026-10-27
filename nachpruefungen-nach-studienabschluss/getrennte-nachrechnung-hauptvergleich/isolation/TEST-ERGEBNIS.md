<!-- status: Isolationstest Fassung 3 bestanden | 2026-10-27 -->

# Isolationstest der getrennten Implementierung, Fassung 3

Start mit `isolation/starten.sh --probe`: neuer Zufallsordner `/private/tmp/n-lauf-pZqjLzEW`, geschlossene Sandbox (`isolation/sperre.sb`, Parameter LAUF), geleerte Umgebung, eigener CODEX_HOME, Zusatzdienste und Plugins aus, Modell gpt-6-luna. Der Probeauftrag ist im Startskript fest hinterlegt. Frühere Fassungen: `TEST-ERGEBNIS-v1.md`, `alt/`.

## Antwort von Codex
```
1. Erfolgreich: `cat hallo.txt` gab `Testdatei im Arbeitsordner` aus.
2. Fehlgeschlagen: `Operation not permitted`
3. Fehlgeschlagen: `Operation not permitted`
4. Fehlgeschlagen: `Operation not permitted`
5. Fehlgeschlagen: `Operation not permitted`
6. Fehlgeschlagen: `Operation not permitted`
7. Fehlgeschlagen: `Operation not permitted`
8. Erfolgreich: Python gab NumPy-Version `1.26.4` aus.
9. Fehlgeschlagen: `Operation not permitted`
10. Fehlgeschlagen: `operation not permitted` beim Schreiben von `/Users/jannikhiller/n-isolationstest.txt`
11. Fehlgeschlagen: `operation not permitted` beim Schreiben von `/Users/jannikhiller/.codex/auth.json`
12. Fehlgeschlagen: `Operation not permitted````

## Bewertung
- Gesperrt: Studiencode (2), Benutzerordner (3), Codex-Verläufe (4), temporäre Bereiche (5, 6), Laufwerke (7), Laufzeitordner außerhalb der freigegebenen Node-Version (9), Schreiben in den Benutzerordner (10), Schreiben in die Anmeldedatei (11), früherer Probeordner (12).
- Verfügbar: Arbeitsordner (1), Python mit NumPy 1.26.4 (8).
- Plugins nicht geladen (kein `plugins/cache` im CODEX_HOME), keine Verbindung zu Plugin-Diensten im Laufprotokoll.
- Protokollprüfung (`pruefe_protokoll.py`): 2 Werkzeugaufrufe, 0 Netzmuster, 0 andere Werkzeuge, 14 Pfade außerhalb, alle aus dem Testauftrag. Datei `TEST-v3-AUDIT.md`.
- Nicht gesperrt: Netzzugriffe ausgeführter Befehle (VORAB-N.md, Abschnitt Isolation, Punkt 6a).
