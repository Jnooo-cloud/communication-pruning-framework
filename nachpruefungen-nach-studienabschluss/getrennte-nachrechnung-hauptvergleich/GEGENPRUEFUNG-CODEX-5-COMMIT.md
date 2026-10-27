commitfähig: nein

## Muss

1. **Wörtliche Prüfung auf offene F4/F11-Vermerke nicht bestanden.** Der aktuelle Stand nennt die Freigaben korrekt: `VORAB-N.md:5,286,293,311,312` und `README.md:1,22,23`. In den mitzucommitenden früheren Prüfberichten stehen jedoch weiterhin Aussagen, dass F4/F11 Vorschläge seien oder die Freigabe ausstehe: `GEGENPRUEFUNG-CODEX-2.md:25,47,49`, `GEGENPRUEFUNG-CODEX-3.md:7,35` und `GEGENPRUEFUNG-CODEX-4.md:7,16,34`. Die vier alten Berichte sind in `VORAB-N.md:239` und der Dateiliste enthalten. Sie beschreiben erkennbar den damaligen Prüfstand und sind als historische Belege nicht falsch. Die Vorgabe „nirgendwo“ ist bei wörtlicher Anwendung trotzdem nicht erfüllt. Falls sie nur den aktiven Status meint, sind `VORAB-N.md` und `README.md` auf dem geprüften Stand konsistent. Ich habe die historischen Berichte nicht geändert.

2. **Die übrigen Muss-Prüfungen sind bestanden.** Die Dateiliste unter `/private/tmp/claude-501/-Users-jannikhiller-Desktop-ai-operations-Studium-OS-Masterarbeit/1c3ab582-4237-431b-a7a8-7704e3443b3a/scratchpad/commit-dateien.txt:1` hat 33 eindeutige Pfade, entspricht der aus `VORAB-N.md:239` abgeleiteten Menge vollständig, und jeder Pfad ist vorhanden. Es gibt keine zusätzlichen oder fehlenden Pfade. Kein Eintrag überschreitet 50 MiB; der größte ist `eingang/laufliste.tsv` mit 1.795.392 Bytes. In der Liste stehen weder `eingang/protokolle/`, MuSiQue-Daten, `answer.py`, `evaluate_v1.0.py` noch `.agent-log`. Der direkte Sollmengenabgleich gegen Abschnitt 9.3 ergab 33 von 33.

3. **Kein Zugangsdatenmaterial in den 33 gelisteten Dateien gefunden.** Der Scan auf gängige API-Schlüsselpräfixe, JWTs, Bearer-Werte, OAuth-Felder und Codex-Auth-Strukturen ergab einen Kandidaten in `isolation/TEST-v2-lauf.log:25`. Das ist ein Diagnosewort nach „Bearer“, kein Tokenformat. Der Wert wurde nicht ausgegeben. Die Codex-Auth-Datei im Home-Verzeichnis wurde nicht geöffnet.

## Soll

- Der Ausdruck „selbst geschriebene Dateien aus `eingang/`“ in `VORAB-N.md:239` ist weit ausgelegt. Die Liste enthält `AUFTRAG.md`, `METHODENAUSZUG.md`, `laufliste.tsv`, `bewertung/metrics/metric.py` und das Manifest. Laut `VORAB-N.md:27,28,29,34` ist `AUFTRAG.md` für N geschrieben und `metric.py` ein Platzhalter für N; der Methodenauszug ist ein ausgewählter wörtlicher Auszug und die Laufliste eine gefilterte Projektion. Ich halte die fünf gelisteten Dateien für die gemeinte Paketmenge, aber nicht alle vier Nutzdateien sind im engen Sinn neu verfasste Inhalte.
- Der Arbeitsbaum ist nicht sauber. `git status --short --branch` zeigte unter anderem `M research-machine/LITERATURSTATUS.md` und zahlreiche nicht gelistete ungetrackte Pfade. Aktueller Branch: `research-run-b-anmelde-verankert`; `HEAD`, `main` und `origin/main` zeigen alle auf `d78b5c8c56b8dc263492a72c6ffc242bd93999d9`. `git diff --cached --quiet` endete mit Exit 0. Daher die im Scratchpad geführte explizite 33-Pfade-Liste unverändert verwenden.
- `VORAB-N.md:30,331` bindet `zuordnung/HERKUNFT-PROTOKOLLE.tsv` per Hash, die Datei ist aber nicht Teil von Abschnitt 9.3 oder der Commitliste. Ich habe die 18.080 Zuordnungen gegen Eingangsmanifest und Z56-Dateimanifest geprüft: keine fehlenden oder abweichenden Hashes. Der Commit erhält dennoch nur den Hash der Zuordnung, nicht deren Inhalt. Das ist kein Widerspruch zur ausdrücklich geplanten Dateiliste, sollte aber als bewusste Grenze des Zeitbelegs verstanden werden.

## Kann

- Die Hashzeile zur Zuordnung und die nicht committeten Rohprotokolle sind derzeit überprüfbar: alle 18.080 Paketpfade haben genau eine Zuordnung, und jeder Hash stimmt mit Eingangsmanifest und Z56-Dateimanifest überein. Die Zuordnung selbst bleibt außerhalb dieses Commits.
- Die Aussage „Isolationsprobe Fassung 3 bestanden“ stützt sich auf den gespeicherten Befund `isolation/TEST-ERGEBNIS.md:1,19-23` und das Laufprotokoll. Eine neue Sandboxprobe habe ich nicht ausgeführt. `GEGENPRUEFUNG-CODEX-4.md:39` hält fest, dass die erneute Probe in dieser Umgebung an `sandbox_apply: Operation not permitted` scheiterte. Der angeforderte Selbsttest des Protokollprüfers lief hier separat erfolgreich.

## Gate-Ausgaben

Die Gates liefen in einer durch `mktemp -d` angelegten Kopie unter dem Scratchpad. `eingang/protokolle/` wurde mit 18.080 Dateien kopiert. Externe Quellen, die der Bindungsprüfer erwartet, waren in der Kopie nur lesbar verknüpft. Die geprüfte Nachricht steht in `/private/tmp/claude-501/-Users-jannikhiller-Desktop-ai-operations-Studium-OS-Masterarbeit/1c3ab582-4237-431b-a7a8-7704e3443b3a/scratchpad/commit-nachricht.txt:1,8,9,10,12,13`.

| Prüfung | Exit | Beobachtete Schlüsselausgabe |
|---|---:|---|
| `/opt/anaconda3/bin/python -I vergleich/gegenprobe.py` | 0 | `bestanden: true`; die Gruppen A bis F bestanden |
| `/opt/anaconda3/bin/python -I werkzeuge/leckpruefung.py` | 0 | `bestanden: true`; 18.092 Dateien, 18.080 Protokolle, 120 Ergebniszahlen, 2.474 Textformen; keine Befunde, nur ausgewiesene INFO-Treffer |
| `/opt/anaconda3/bin/python -I werkzeuge/pruefe_wortgleichheit.py` | 0 | `wortgleich` |
| `/opt/anaconda3/bin/python -I isolation/pruefe_protokoll.py --selbsttest` | 0 | `Selbsttest bestanden` |
| `/opt/anaconda3/bin/python -I werkzeuge/aktualisiere_bindungen.py`, zweimal | 0, 0 | beide Male `Änderungen: 0`, `nicht gefunden: []`, 18.092 Paketdateien und 448.900.017 Bytes |
| Manifestprüfung aller Eingangsdateien | 0 | 18.091 Einträge, 0 fehlend, 0 abweichend, 0 zusätzlich, 0 fehlerhaft; SHA-256 `4a7ef3f82031fc0d04bdb0f80b4cb1ca8ade16b4dfbb8bcb778de83f06b2f19f` |
| SHA-256-Verweise in den Tabellen von `VORAB-N.md` | 0 | 38 von 38 Tabellenverweisen stimmen. Die fünf in Commit `3ca3c6a` gebundenen Dateien stimmen ebenfalls mit ihren Git-Inhalten überein. Die referenzierte `MANIFEST-RUNS.jsonl.gz` hat den angegebenen SHA-256 `ce043658ddad913113ce30c31f5f3a7918655c74ef4ce72a5d91a04005dfc3b1`. |
| `git diff --cached --quiet` | 0 | Staging-Bereich leer |

Der Vergleich mit `VORAB-N.vor-freigabe.md` und `README.vor-freigabe.md` aus demselben Scratchpad zeigt nur die Status-, F4/F11- und O1/O2-Freigabevermerke. Die Zitate in `VORAB-N.md:311,312` stimmen genau mit den angegebenen Chatworten überein. Die Commitnachricht behauptet in den Zeilen 8,9,10,12,13 keine nicht bestandene Gateprüfung; ihre Hashbindungs-, Gegenprobe-, Leck-, Wortgleichheits- und Selbsttestangaben stimmen mit den Läufen oben überein. Die gespeicherte Fassung-3-Isolationsprobe ist als früherer Lauf belegt, nicht als in dieser Prüfung wiederholt.
