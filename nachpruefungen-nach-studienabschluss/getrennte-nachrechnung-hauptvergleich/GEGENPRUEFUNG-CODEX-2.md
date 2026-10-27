# Zweite Gegenprüfung der Vorabfestlegung N

Stand: 27.10.2026

## Urteil

**freigabefähig: nein.** Die vier verlangten Kontrollläufe bestehen und das Eingangsmanifest ist intakt. Die technische Trennung genügt aber nicht für die Aussage „getrennte Implementierung ohne Zugriff auf Code und Ergebniszeilen“. Außerdem stimmen mehrere dokumentierte Prüfsummen nicht mit den geprüften Dateien überein. O1 und O2 sind inhaltlich festgelegt, aber ihre ausdrückliche Autorenfreigabe ist im geprüften Paket nicht belegt.

## Erneut ausgeführte Prüfungen

Alle drei Skripte liefen aus einer vollständigen temporären Kopie unter `/private/tmp`; diese Kopie wurde danach gelöscht. `vergleich/gegenprobe.py` lief mit `/opt/anaconda3/bin/python -I` und endete mit Exit 0. Alle sechs Proben waren bestanden: Nullprobe, Reihenfolge, Änderungen, Feldänderungen, Festschreibung und nachträgliche Änderung. Die Feldprobe fand 9 von 9 erwarteten Meldungen.

`werkzeuge/leckpruefung.py` endete mit Exit 0: 18.092 Dateien, 18.080 Protokolle, 120 Ergebniszahlen in 2.474 Schreibweisen, keine Befunde; gemeldete Manifestprüfsumme `a01df8af63ef37a3eeaa328ac280b560c226a5df2227e9b9d82e5836be43a0cb`. `werkzeuge/pruefe_wortgleichheit.py` endete mit Exit 0 und gab `wortgleich` aus. Zusätzlich wurden alle 18.091 Einträge in `eingang/MANIFEST.sha256` gegen die Dateien der temporären Kopie geprüft: null fehlende oder abweichende Dateien. Der Hash der Manifestdatei selbst stimmt mit dem vorgegebenen Wert überein.

In `vergleich/vergleich.py:35` ist derselbe Eingangsmanifest-Hash fest gebunden. Der Vergleich verlangt außerdem `--ausgabe-sha` (`vergleich.py:753`) und prüft den Hash, alle gelisteten Dateien sowie zusätzliche, doppelte und unsichere Pfade (`vergleich.py:227-264`).

## Status der ersten Gegenprüfung

| Erstbefund | Status | Beleg |
|---|---|---|
| Muss 1: technische Isolation | **Nicht behoben.** Teile der Sperre wirken für die getesteten Pfade, aber der Startweg und das Profil lassen konkrete Umgehungen offen. | `isolation/starten.sh:5`; `isolation/sperre.sb:2-14`; `isolation/TEST-ERGEBNIS.md:27,32-33` |
| Muss 2: verpflichtende Ausgabe-Prüfsumme | **Im Vergleichsskript behoben.** Pflichtwert, genaue Gleichheit und vollständige Manifestprüfung sind implementiert und in den Gegenproben geprüft. Die Prüfsummendokumentation ist jedoch teilweise veraltet, siehe Muss 2 unten. | `vergleich/vergleich.py:227-264,753`; Gegenprobe E und F |
| Muss 3: Endantwort prüfen | **Behoben.** Die Ausgabeantwort wird exakt mit `finished.answer` aus dem durch Laufliste und Eingangsmanifest gebundenen Rohprotokoll verglichen. Geänderte und fehlende Antworten sind Gegenproben. | `vergleich/vergleich.py:277-335,376-381`; Gegenprobe D |
| Muss 4: Gegenproben erweitern | **Behoben.** Status, `run_id`, Paarindex, Arm, unbekannte Beträge, Endantwort, doppelte und fehlende Läufe sowie Festschreibungsfehler werden verändert. | `vergleich/gegenprobe.py`; gespeichertes Ergebnis, Proben A bis F |
| Muss 5: O1 und O2 schließen | **Inhaltlich geschlossen, Freigabe nicht belegt.** F4 und F11 stehen in Vorabfestlegung und Auftrag. Es fehlt im geprüften Paket ein konkreter Beleg, dass Jannik genau diese zwei methodischen Entscheidungen freigegeben hat. | `VORAB-N.md:286,293,308-309`; `eingang/AUFTRAG.md:58-60`; `AGENTS.md:17` |
| Soll: Rechentoleranz von Rundungsbericht trennen | **Behoben.** Der Bericht soll ungerundeten Wert, Rundung und Toleranzurteil getrennt ausweisen. | `VORAB-N.md:191-215` |
| Soll: Klasse (c) begrenzen | **Behoben.** Klasse (c) verlangt einen vorab nummerierten Regelpunkt, beide Werte und die Rechenfolge; sonst gilt Klasse (d). | `VORAB-N.md:217-234` |
| Kann: unbekannte Beträge deduplizieren | **Textlich behoben.** Auftrag 3.7 zählt je `attempt_id` höchstens einmal, auch wenn beide Bedingungen zutreffen. Eine eigene Überlappungsprobe ist optional. | `eingang/AUFTRAG.md:39` |
| O3 | **Entscheidung dokumentiert, Zeitanker offen.** Der gezielte Commit ist vorgesehen, aber laut Kopfzeile noch nicht erfolgt. | `VORAB-N.md:5,237-244` |
| O4 | **Behoben.** `VORAB-N.md` bleibt außerhalb von `eingang/`; die Wortgleichheitsprüfung besteht. | `VORAB-N.md:9,311`; Prüfung oben |
| O5 | **Für die spätere Textübernahme dokumentiert.** Die Änderungen an E28, E32 und E39 sind als spätere Anforderung festgehalten, hier aber noch nicht umgesetzt. | `VORAB-N.md:312` |

## Offene Befunde

### Muss

1. **Die Isolation ist nicht fail-closed.** `sperre.sb` beginnt mit `(allow default)` und sperrt nur ausgewählte Pfade. Andere lokale Verzeichnisse bleiben zugänglich. `starten.sh:5` liest die frei angegebene Promptdatei mit `cat` vor dem Start der Sandbox. `$W` und der Promptpfad werden nicht auf einen frischen, kanonischen Arbeitsordner mit ausschließlich `eingang/` begrenzt. Der dokumentierte Test bestätigt zudem, dass Schreiben außerhalb der gesperrten Bereiche möglich ist (`TEST-ERGEBNIS.md:27,32`). Die Ausnahme für `~/.codex/auth.json` macht die Host-Anmeldedaten im Sandbox-Prozessbaum les- und schreibbar (`sperre.sb:13-14`).

   Die Beschreibung des Netzes ist offen: `VORAB-N.md:303` sagt korrekt, dass es nicht gesperrt wird. Eine nachträgliche Suche nach ausgewählten Befehlsnamen in einem Sitzungsprotokoll ist aber keine technische Netzsperre. Im Paket liegt kein vollständiger, roh nachvollziehbarer Auditlauf zur Netzwerkprüfung vor; `.agent-log/tools.log` enthält Entwicklungsbefehle, nicht den vollständigen Sandbox-Test. Außerdem verbietet `eingang/AUFTRAG.md:18` wörtlich Netzzugriffe und Modellaufrufe jeder Art, während `VORAB-N.md:303` die Netzwerkverbindung des Codex-Modells als erforderlich beschreibt.

   **Fix:** Die getrennte Rechnung in einer Wegwerf-VM oder einem separaten Konto ausführen, in dem nur eine verifizierte Kopie von `eingang/` und die nötige Laufzeit verfügbar sind. Arbeitsordner und Prompt vor jedem Start kanonisieren und auf diesen Bereich begrenzen; keine beliebige Promptdatei vor der Sandbox lesen. Den Host-Token nicht an beliebige Kindprozesse freigeben. Für Rechnerbefehle Egress sperren und einen etwa nötigen Modellkanal ausdrücklich, eng und mit unveränderlichem Protokoll festlegen. Vor der Freigabe lesende und schreibende Zugriffe auf Code-, Ergebnis-, Prompt- und Nachbarpfade direkt testen. Bis dahin die zitierte Isolationsaussage nicht verwenden.

2. **Die gespeicherte Versionsbindung ist inkonsistent.** `VORAB-N.md` bindet in Abschnitt 14 nicht die aktuell geprüften Bytes. Tatsächliche SHA-256-Werte aus den Dateien sind: `vergleich/vergleich.py` `f7c76236a6f95d760c63d0a67880860a4e555252c17fe752bfc5977bb4069f59`; `pruefung/LECKPRUEFUNG.json` `09e07e1c2dd6d9ad9ddcb32ace99cb80ac533c91b65921be3fe547789d462125`; `vergleich/gegenprobe/GEGENPROBE-ERGEBNIS.json` `fdfe6e265c99987392332678305c4cf9664f1afc0b3fdd9160288117fe8b89ab`; die Markdown-Ausgabe `54e11f37cf8b4356461aeb2d9bb056d1658eb32a32aa06c79838dbece916c2be`. Die dort eingetragenen Werte weichen jeweils ab. Auch `VORAB-N.md:27` nennt für `AUFTRAG.md` `fbcaf157...`, tatsächlich ist es `c46ad3da4d02470d1a28a352e9a806d6c6ce3b0e91f8cbfc3ac04a09399c376a`. Der Eingangsmanifest-Hash selbst ist dagegen korrekt und alle seine Einträge stimmen.

   **Fix:** Die abweichenden Werte in `VORAB-N.md:27,318,320-321,327` aus den freizugebenden Dateien neu berechnen und ersetzen. Paketgröße in `VORAB-N.md:23` und `README.md:37` ebenfalls korrigieren: die Prüfung meldet 448.899.891 Bytes, dokumentiert sind 448.899.798. Danach die Versionsbindung erneut prüfen.

3. **O1 und O2 dürfen nicht als freigegebene Festlegungen gelten, solange ihre Autorenfreigabe nicht belegt ist.** Die Vorabfestlegung bezeichnet F4 und F11 als Entscheidungen gemäß Gegenprüfung, nennt aber an diesen Stellen keine Zustimmung von Jannik. Die Projektregel verlangt sie für methodische Entscheidungen ausdrücklich (`AGENTS.md:17`).

   **Fix:** Die konkrete Freigabe von F4 und F11 mit einem identifizierbaren Entscheidungsbeleg verknüpfen. Falls sie nicht erteilt wurde, beide als Vorschläge/offen kennzeichnen und vor Umsetzung eine konkrete Entscheidung einholen.

4. **Der vorab festgelegte Zeitanker fehlt noch.** Der Kopf von `VORAB-N.md` sagt „Commit als Zeitnachweis: offen“. Damit ist die Vorabfassung vor Beginn der getrennten Implementierung nicht nachweisbar eingefroren.

   **Fix:** Vor Implementierung den in Abschnitt 9.3 festgelegten gezielten Commit der dort genannten Dateien erstellen und Commit-ID sowie gebundene Prüfsummen festhalten. Der Auftrag hier ist review-only; dieser Commit wurde in dieser Gegenprüfung nicht erstellt.

### Soll

1. **„Ohne Zugriff auf Ergebniszeilen“ muss enger definiert werden.** Die Leckprüfung fand keine abgeleiteten Dateien wie `P-ROWS.json`, `P-ANALYSIS.json`, `result.json` oder Framework-Auswertungscode. Das Eingangsverzeichnis enthält aber 18.080 Rohjournale; der Auftrag nutzt daraus `finished.answer`, Status und Kosten. Das sind Rohbeobachtungen je Lauf, keine abgeleiteten Ergebniszeilen. Der Satz ist nur präzise, wenn mit „Ergebniszeilen“ die abgeleiteten P-ROWS gemeint sind.

   **Fix:** In der Isolationserklärung ausdrücklich sagen, dass P-ROWS/P-ANALYSIS und Studiencode fehlen, die Rohjournale mit Endantworten und Status aber bereitgestellt werden. Falls auch diese Beobachtungen vorenthalten werden sollen, passt das nicht zum gegenwärtigen Rechenauftrag.

2. **Prüfstatus zwischen Einstiegstexten vereinheitlichen.** `README.md:22` nennt die Codex-Gegenprüfung abgeschlossen; `VORAB-N.md:5` führt sie weiter als offen. Der Befund hier lautet nein zur Freigabefähigkeit.

   **Fix:** Nach Klärung der Muss-Punkte beide Statusangaben so aktualisieren, dass „Prüfung durchgeführt“ und „Freigabe erteilt“ nicht verwechselt werden.

### Kann

Die in Auftrag 3.7 festgelegte Deduplizierung ist eindeutig. Optional kann die spätere Implementierungsprüfung einen künstlichen Fall aufnehmen, in dem dieselbe `attempt_id` sowohl einen Nullbetrag als auch einen offenen Start hat, und bestätigen, dass er einmal zählt.
