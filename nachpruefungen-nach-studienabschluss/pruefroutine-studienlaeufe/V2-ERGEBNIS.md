<!-- status: Laufergebnis Selbstprüfung | Z56 V2a bis V2f | Plan D-083 | 0 USD, 0 Netzversuche | 2026-10-20 -->

# Z56 V2: Prüfroutine über die gespeicherten Studienprotokolle

20.10.2026. Aufgabe Z56-FRAMEWORK-VALIDIERUNG, Teil V2, Plan `project/dsr/Z56-FRAMEWORK-VALIDIERUNG-PLAN.md` (D-083). Bezug FF1, RQ-1 und RQ-4: Nimmt die unveränderte Prüfroutine des Frameworks die tatsächlich gespeicherten Protokolle aller ausgewerteten Studienläufe an? Ein Lauf (`run-001`), keine Wiederholung. Umsetzer und Prüfer dieser Datei sind derselbe Subagent; das ist eine Selbstprüfung, die getrennte Gegenprüfung ist V4b.

## Ergebnis je Kriterium

| ID | Ergebnis | Beleg |
|---|---|---|
| V2a | bestanden | `MANIFEST.json` (SHA256 `9e98bba5ee626ea6d31087c529c2cbaa531d9bffd1948fdce9266ce8c3b87367`) mit `MANIFEST-RUNS.jsonl` (`35958b6e…`, 53.504 Läufe) und `MANIFEST-FILES.jsonl` (`63c43798…`, 198.363 Dateien, 1.531.241.197 Bytes). Geschrieben 10:28:15 bis 10:30:04 UTC, Prüfung erst ab 10:30:04 UTC (`run-v2.log`). 16 Bindungsprüfungen grün, 0 Zuordnungsprobleme. |
| V2b | bestanden (vollständig ausgeführt) | 47.600 Protokolle der Mehragentenarme: 47.598 von `audit` angenommen, 2 offen gebliebene von `audit_prefix` angenommen, 0 zurückgewiesen. 5.904 Läufe der Direktarme S und S-k nicht anwendbar. `run-001/SUMMARY.json` (`9a776bee…`), `run-001/RESULTS.jsonl` (`c6899304…`). |
| V2c | bestanden | Keine Zurückweisung, also keine unerklärte. Die zwei offenen Läufe entsprechen genau der Zeile „Antwort über der Ausgabegrenze hält die Erhebung nicht an“ der Tabelle 6.1 (Referenzvergleich einmal, Ausfallvergleich einmal). |
| V2d | bestanden | 0 Nachrichten über nicht erlaubte Kanten, 0 Aufrufe nicht aktiver oder ausgefallener Rollen, 0 Nachrichten aus falscher Runde. Aufrufzahl gleich Soll in 46.778 Läufen; 820 Läufe enden kürzer genau an einem `model_failed`-Ereignis (Ausfallregel F-01), 2 offene Läufe enden am Überschreitungsversuch. Kein Lauf mit mehr Aufrufen als Soll, keiner kürzer ohne Grund. |
| V2e | bestanden | Nicht anwendbar: 5.904 von 53.504 Läufen (11,03 %), nur Direktarme S (2.952) und S-k aus Z54 (2.952). Grund: Sie speichern `direct-*.json`, kein Laufprotokoll mit Konfiguration; `audit`/`audit_prefix`/`read_journal` sind nur für Mehragentenprotokolle definiert. Die Z53-Blöcke sind entgegen der Vermutung im Plan anwendbar (gleiches Protokollformat). Getrennte eigene Strukturprüfung der Direktarme siehe unten. |
| V2f | bestanden | Alle 198.363 gelesenen Studiendateien nach der Prüfung hashgleich (`SUMMARY.json`, `v2f.changed_or_missing = []`). Frameworkmanifest 200/200 vor und nach gleich (`framework-check-before.json`, `framework-check-after.json`). |

Netzwerkversuche: 0 (`netguard-build.jsonl`, `netguard-audit.jsonl` enthalten nur je den Ladeeintrag der Sperre). Modellaufrufe: 0. Kosten: 0 US-Dollar.

## Tabelle je Panel und Arm

Annahme = `read_journal` → `audit` bei versiegeltem Protokoll, Präfix = `read_journal` → `audit_prefix` bei offenem Protokoll. Strukturkennzahlen aus eigener Zählung (getrennt von der Prüfroutine, Abschnitt V2d).

| Panel/Arm | Läufe | angenommen | Präfix angenommen | zurückgewiesen | nicht anwendbar | unerlaubte Kanten | nicht aktive Rollen | Aufrufe = Soll | kürzer, Modellausfall | kürzer, offen | Aufrufe gesamt |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P/⟦Q⟧ | 9.040 | 9.040 | 0 | 0 | 0 | 0 | 0 | 8.887 | 153 | 0 | 53.157 |
| P/⟦F*⟧ | 9.040 | 9.040 | 0 | 0 | 0 | 0 | 0 | 8.899 | 141 | 0 | 44.766 |
| R/S | 2.952 | | | | 2.952 | | | | | | |
| R/S-k (Z54) | 2.952 | | | | 2.952 | | | | | | |
| R/D | 2.952 | 2.952 | 0 | 0 | 0 | 0 | 0 | 2.858 | 94 | 0 | 25.981 |
| R/Z | 2.952 | 2.952 | 0 | 0 | 0 | 0 | 0 | 2.886 | 66 | 0 | 17.865 |
| R/Q | 2.952 | 2.951 | 1 | 0 | 0 | 0 | 0 | 2.909 | 42 | 1 | 17.386 |
| R/F | 2.952 | 2.952 | 0 | 0 | 0 | 0 | 0 | 2.898 | 54 | 0 | 14.594 |
| T/Q-ST | 2.952 | 2.952 | 0 | 0 | 0 | 0 | 0 | 2.898 | 54 | 0 | 13.291 |
| T/Q-TF | 2.952 | 2.952 | 0 | 0 | 0 | 0 | 0 | 2.895 | 57 | 0 | 10.126 |
| F/Qc | 2.952 | 2.951 | 1 | 0 | 0 | 0 | 0 | 2.902 | 49 | 1 | 17.414 |
| F/Qf | 2.952 | 2.952 | 0 | 0 | 0 | 0 | 0 | 2.917 | 35 | 0 | 11.628 |
| F/Fc | 2.952 | 2.952 | 0 | 0 | 0 | 0 | 0 | 2.903 | 49 | 0 | 14.611 |
| F/Ff | 2.952 | 2.952 | 0 | 0 | 0 | 0 | 0 | 2.926 | 26 | 0 | 8.804 |
| **Summe** | **53.504** | **47.598** | **2** | **0** | **5.904** | **0** | **0** | **46.778** | **820** | **2** | **249.623** |

Annahmequote der Prüfroutine über alle anwendbaren Läufe: 47.600 von 47.600 (100 %), davon 2 als offenes Präfix. Unter den versiegelten Protokollen tragen 46.406 den Status `completed` und 1.192 `model_failed` (P: 228 bei ⟦Q⟧, 224 bei ⟦F*⟧, wie in Tabelle und Abschlussprüfung der Arbeit). Kein Protokoll hat den Status `incomplete`; kein angenommener Aufruf hat unbekannte Kosten (`unknown_cost_calls` = 0).

## V2a: Datenmanifest und Herleitung

Welche Protokolle die Auswertung verwendet hat, ist aus den Auswertungsskripten und ihren Hashbindungen hergeleitet (`build_manifest.py`, Docstring und `checks` in `MANIFEST.json`):

- **P (9.040 Paare):** Ausgewertet hat `Z51-RETRY-EINZELERSATZ-001/operator/resume_main.py` (`analyze` → `kernel.collect_panel` → `final_analysis.analyze_panel`) den Endzustand `operation/isolated-backup-D074/8fa92e03…/STATE.json`; dessen Datei-SHA `960d6402…` ist gleich dem `state_sha256` des Endhalts `remote-holds/009040-960d6402….json`, der SHA von `P-ANALYSIS.json` gleich dem in `operation/starter/STATUS.json`. Jede der 18.080 Zeilen trägt den Herkunftsschlüssel ihres Abschnitts; die `ORIGINALS.json`-Kette verbindet `FINAL-STUDY-001/live` (Paare 0 bis 99) → `Z51-FORTSETZUNG-001/live` (100 bis 103) → `Z51-RATENLIMIT-001/live` (104 bis 4.532) → `Z51-EINZELERSATZ-001/live` (4.533 bis 5.578) → `Z51-F-EINZELERSATZ-001/live` (5.579 bis 5.963) → `Z51-RETRY-EINZELERSATZ-001/live` (5.964 bis 9.039). Je Zeile ist das Protokoll `blocks/NNNNNN/<Arm>/journal.jsonl` neben der `result.json`, die mit der ausgewerteten Zeile übereinstimmt.
- **R (2.952 Blöcke, sechs Arme):** Ausgewertet ist `Z54-SK-KORREKTUR-001/live/collected/rows-R-SK.json` (`ANALYSIS-R-SK.json`, `rows_sha256` geprüft). Ihre Zeilen ohne S-k sind gleich `Z53/live/collected/rows-R.json`; deren Blöcke 0 bis 2.182 stammen aus dem Z52-Prüfzustand `…/r2183-overlimit/activation/INSPECT-011223-RESULT-001.json` (an `PRIOR-BINDING.json` gebunden, Zeilen gleich), die Blöcke 2.183 bis 2.951 aus `Z53/live/blocks`. Für Z52 wurden alle `result.json` der acht Abschnittsordner der Kette und ihrer sieben mitgeführten Kopienordner (`original`, `retained`) gelesen; Primärquelle ist der früheste Abschnitt, dessen `result.json` gleich der Zeile ist. 1.025 Z52-Läufe haben 2.282 Kopien, alle bytegleich. S-k stammt aus `Z54/live/blocks/R-NNNNN/S-k`.
- **T, F:** `Z53/live/collected/rows-T.json` und `rows-F.json` (`ANALYSIS-T/F.json`, `rows_sha256` geprüft), Protokolle in `Z53/live/blocks/T-NNNNN` bzw. `F-NNNNN`.
- **Erwartete Konfiguration**, nie aus dem Protokoll selbst: ⟦F*⟧, Fc, Ff = `fixed_config_id` C01 beider Kandidaten (`Z51-HAUPTSTUDIE-001/activation/CANDIDATE-AUTHORIZED.json`, `Z52…/recovery-R00038/activation/CANDIDATE.json`, SHA wie in `z53_fast.py` gebunden); ⟦Q⟧, Qc, Qf, Q-ST, Q-TF = `spatial_q` aus dem gespeicherten Auswahlbeleg `selection.json` des Blocks (zusätzlich gleich `choice` in `spatial-measurement.json`, bei T `temporal-measurement.json`); D = dichte Vierergruppe; Z = `z_configuration` des Planblocks; Runden 2, bei Q-ST `temporal_qst`, bei Q-TF `fixed_rounds` = 1; ausgefallene Rolle bei Qf/Ff = erste Rolle der `fault_permutation` in der Konfiguration. Die eigene Zuordnung stimmt in allen Läufen mit `final_execution._configuration` und mit `configuration`/`rounds`/`failed_role` der ausgewerteten Zeile überein; `started.json` jedes Blocks gleich dem Planblock (`PLAN.json`, SHA `42a55ddd…`).
- Nicht im Manifest, weil von der Auswertung nicht verwendet: die 16 unterbrochenen Armläufe in `Z53/live/interrupted`, abgebrochene Teilblöcke früherer Abschnitte und die alten S-k-Läufe bei Temperatur 0 (Direktarm, ohnehin nicht anwendbar).

## V2b: Ausführung

`audit_v2.py run-001` (SHA `1008e913…`) ruft je Mehragentenlauf `communication_pruning.journal.read_journal(Pfad, erwartete Konfiguration)` auf. Das ist der Leser des gespeicherten Formats: Er prüft Hülle, laufende Nummer und Prüfsummenkette und ruft dann bei versiegeltem Protokoll `audit`, sonst `audit_prefix` auf. Frameworkdateien beim Lauf: `audit.py` `d4aebc76…`, `journal.py` `a7687270…`, `contracts.py` `63da89fa…`, `failure_policy.py` `8d3a7ed1…`, gleich dem Manifest vor dem Lauf. Für eine Zurückweisung war zusätzlich ein Lauf von `audit` auf einer eigenen Lesung vorgesehen, um Hüllen- von Inhaltsfehlern zu trennen; er kam nicht zum Einsatz.

Die zwei offenen Läufe:

| Lauf | Protokoll | `audit_prefix` | offener Versuch | Beleg außerhalb des Protokolls | volles `audit` |
|---|---|---|---|---|---|
| R/Q Block 2.182 | Z52 `…/r2183-overlimit/live/blocks/002182/Q/journal.jsonl` | angenommen, 3 gestartet, 2 abgeschlossen | `…:R:02182:Q:1:checking:1` | `terminal-overlimit.json`, Versuch stimmt | weist zurück: „missing terminal event“ |
| F/Qc Block 769 | Z53 `live/blocks/F-00769/Qc/journal.jsonl` | angenommen, 2 gestartet, 1 abgeschlossen | `…:F:00769:Qc:1:linking:1` | `terminal-failure.json` (Regel Z53-1), Versuch stimmt | weist zurück: „missing terminal event“ |

## V2c: Zuordnung zu Tabelle 6.1

Es gibt keine Zurückweisung. Die beiden nur als Präfix angenommenen Läufe sind die zwei Fälle der Zeile „Antwort über der Ausgabegrenze hält die Erhebung nicht an“ (N0925 bis N0928): Der Abbruchversuch hat keinen Ausgang im Protokoll, die Wertung (Modellausfall, volle bezahlte Kosten) steht in der Zeile und im Endbeleg. Die übrigen Abweichungen der Tabelle 6.1 sind für die Prüfroutine nicht sichtbar, weil sie außerhalb der ausgewerteten Protokolle liegen: ersetzte und erneut gesendete Sendeversuche (im Protokoll steht je Aufruf nur der gewertete Ausgang), mehrfach ausgeführte Blöcke R 100 bis 118 (frühere Ausführungen nicht erhalten), Parallelbetrieb und Nachstudie S-k (Direktarm). Für die teils rekonstruierte Prüfsummenkette (R 0 bis 99) heißt die Annahme nur, dass die Kette in sich stimmig ist, nicht dass sie original ist; das entspricht der Folge-Spalte der Tabelle.

## V2d: Strukturkennzahlen (eigene Zählung, getrennt von der Prüfroutine)

Eigene Lesung jedes Protokolls ohne Frameworkcode (`own_parse`, `structure` in `audit_v2.py`): Für jeden gestarteten Aufruf wurde jede weitergegebene Nachricht gegen die erwartete Konfiguration geprüft (Quelle aktiv und nicht ausgefallen; Zusammenführung, eigene Vorrundenantwort oder erlaubte Kante; Vorrunde). Soll je Lauf = Runden × (aktive Rollen − ausgefallene Rolle) + 1 Zusammenführung. Ergebnis über alle 47.600 Läufe: 0 unerlaubte Nachrichten, 0 Nachrichten aus falscher Runde, 0 Aufrufe nicht aktiver Rollen, 0 Aufrufe der ausgefallenen Rolle, 0 Abweichungen bei Lauf-ID, Runden, ausgefallener Rolle und Konfiguration gegenüber dem Soll, 0 Abweichungen zwischen gezählten Starts und `call_count` der ausgewerteten Zeile, Unterdrückungsereignisse in allen abgeschlossenen Qf/Ff-Läufen gleich der Rundenzahl. 249.623 gestartete Aufrufe insgesamt.

Hinweis zur Grenze der Prüfroutine: `audit` erhält nur die Konfiguration, Runden und ausgefallene Rolle liest sie aus dem Protokoll selbst. Ein Lauf mit falscher Rundenzahl würde sie daher bestehen. Diese Bindung prüft hier nur die eigene Zählung (0 Abweichungen); das ist kein Fehler der Studie, aber eine Grenze der Routine.

## V2e: Nicht anwendbare Läufe und getrennte Strukturprüfung

Nicht anwendbar: 5.904 Läufe (11,03 % aller 53.504 ausgewerteten Läufe), nämlich alle Direktarme. **Die folgende Prüfung ist ausdrücklich kein Ergebnis der Prüfroutine.** Eigene Strukturprüfung je Direktlauf: `direct-started.json` bindet Lauf-ID und Höchstzahl (S 1, S-k 5); Proben lückenlos nummeriert; jede Anfrage mit Rolle `single`, Runde 1, ohne Nachrichten; Probenzahl gleich Höchstzahl oder Ende an genau einem Modellausfall; Probenzahl gleich `call_count`. Ergebnis 5.904/5.904 stimmig, 17.711 Proben (S 2.952; S-k 14.759, davon R 1.633 mit 4 Proben und Modellausfall).

## Zusatzbefund: Hat die Studie Prüfergebnisse selbst gespeichert?

Nein, nicht als eigene Prüfergebnisse. Die Prüfroutine lief während der Studie implizit: `Journal.append` ruft vor jedem Schreiben `audit_prefix`, `Journal.finish` ruft `audit`, und jede Inspektion liest jedes Mehragentenprotokoll über `final_execution._mas_result` → `evaluation.read_result` → `read_journal` (Z53 ebenso über `verify_block`). Eine Zurückweisung hätte die Inspektion mit einer Ausnahme angehalten und keine Zeile erzeugt. Gespeichert sind aber nur die abgeleiteten Zeilen (`result.json`, Zustände mit Evidenzhashes), keine Prüfberichte je Lauf; eine Stichprobensuche nach den Berichtsfeldern (`schedule_complete`, `unknown_cost_calls`, `cost_coverage`) in `FINAL-STUDY-001/live`, `Z53/live/handoff`, einem Z53- und einem Z51-Block ergab keinen Treffer. V2b ersetzt das nicht, sondern ist die erste gespeicherte, vollständige Prüfung.

## Abweichungen vom Plan und Grenzen

- ProjectAtlas war in dieser Sitzung nicht verfügbar; Navigation über gezielte Lesezugriffe (Abweichung von AGENTS.md).
- Vor dem gezählten Lauf habe ich die Skripte im Scratchpad getestet: ein vollständiger Probebau des Manifests (Ergebnis inhaltsgleich, 0 Probleme) und eine Stichprobenprüfung über jeden 50. Lauf plus die zwei offenen Läufe mit einer absichtlich falschen Konfiguration als Gegenprobe (wurde wie erwartet zurückgewiesen: „configuration changed“). Danach wurde nur die Zählung der Unterdrückungsereignisse auf abgeschlossene Läufe beschränkt. Die Erwartungen des Plans wurden nicht verändert. Testausgaben liegen im Scratchpad, nicht im Laufordner.
- Die Prüfung sieht nur, was im Laufprotokoll steht (Schnittstellenebene, wie Z37: verdeckte Aufrufe und falsche Preise wären nicht erkennbar). Sendeversuche außerhalb des Protokolls (4 unbekannte Originalabrechnungen in P, 16 unterbrochene Armläufe, frühere Ausführungen R 100 bis 118) sind nicht Gegenstand. Bei den zwei offenen Läufen steht die Abrechnung des Überschreitungsversuchs nur außerhalb des Protokolls; `audit_prefix` meldet deshalb `total_cost_usd = null`.
- Prüfsummen erkennen versehentliche Änderungen, nicht eine vollständige Neuschreibung (Docstring `journal.py`).
- Keine neue Bewertung von Antworten, keine EM/F1-Neuberechnung, keine neue Studienkennzahl außer Annahmequote und Strukturkennzahlen.
- Außerhalb des Z56-Ordners hat sich während des Laufs nur `eval-harness/eval/.agent-log/tools.log` geändert, das Hook-Protokoll der Claude-Code-Bash-Aufrufe (`modified-outside-z56.txt`); keine Studien- oder Frameworkdatei.
- Selbstprüfung durch den Umsetzer; getrennte Prüfung durch Codex (V4b) steht aus, externe Begutachtung gibt es nicht.

## Dateien

`run_v2.sh` (Ablauf), `build_manifest.py`, `audit_v2.py`, `run-v2.log` (Befehle, Zeiten, Hashes), `MANIFEST.json` + Sidecars, `run-001/RESULTS.jsonl` (ein Eintrag je Lauf), `run-001/SUMMARY.json`, `build-*.txt`, `audit-*.txt`, `netguard-*.jsonl`, `framework-check-*.json`, `modified-outside-z56.txt`. Netzsperre: `../v1/netguard/sitecustomize.py` (SHA `39df4a7b…`) plus Sperrbefehle in `../v1/netguard/bin`. Interpreter `/opt/anaconda3/bin/python3` 3.13.9, Commit `05230e09bd3ac8290d4c5cc84d919f6b838c5e4e`.
