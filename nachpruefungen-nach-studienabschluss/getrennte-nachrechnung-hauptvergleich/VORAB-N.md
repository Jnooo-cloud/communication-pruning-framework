<!-- status: Vorabfestlegung N, vor jeder Nachrechnung | 2026-10-27 -->

# Vorabfestlegung N: getrennte Nachrechnung des Hauptvergleichs

Stand: Entwurf der vorbereitenden Instanz (Claude) vom 27.10.2026, überarbeitet nach vier Codex-Gegenprüfungen (`GEGENPRUEFUNG-CODEX.md`, `-2.md`, `-3.md`, `-4.md`). Freigabe: F4 und F11 von Jannik am 27.10.2026 freigegeben (Abschnitt 13). Codex-Prüfung des Commits durchgeführt (`GEGENPRUEFUNG-CODEX-5-COMMIT.md`): Dateiliste, Prüfsummen, Gates und Freigabevermerke bestanden; einziger Muss-Punkt waren die Vermerke „offen“ zu F4 und F11 in den Gegenprüfungen 1 bis 4. Diese Berichte geben ihren jeweiligen Prüfstand wieder und bleiben unverändert. Commit als Zeitnachweis: offen, ansagepflichtig.

Grundlage: Einarbeitungsplan zu rev25 (`output/council-feedback-rev25-2026-10-27/PLAN.md`, Abschnitt 4), Planentwurf Abschnitt 1.3 (`synthese/PLAN-ENTWURF.md`), Gegenprüfung P/N (`synthese/gegenpruefung-PN.json`, Einträge K3 und NEU-1 bis NEU-5). Entscheidungen von Jannik: nur der Hauptvergleich (Stufe 1), keine Handnachrechnung durch eine zweite Person.

Diese Datei nennt kein Ergebnis des Hauptvergleichs. Sie gehört nicht zum Eingangspaket, weil sie die Sollwertdateien und Festlegungen nennt, die in Kenntnis des Auswertungscodes getroffen wurden (Abschnitt 12). Was die Implementierung braucht, steht wortgleich in `eingang/AUFTRAG.md` (dort Abschnitte 3 bis 5, hier Abschnitt 5).

## 1 Ziel

Der Weg von den gespeicherten Laufprotokollen zum Ergebnis des Hauptvergleichs wird ein zweites Mal gegangen, ohne den Code von Framework und Auswertung und ohne die ausgewerteten Zeilen: pro Lauf Status, Endantwort, Exact Match, F1, gestartete Modellaufrufe und bekannte Kosten, daraus Paarzahlen, Anteile, Qualitätsdifferenz, Kostensummen, Kostenverhältnis, die Grenzen des studentisierten Bootstraps, das Urteil der Entscheidungsregel und die Lesart nach Tabelle 4.5. Danach wird mit den ausgewerteten Zeilen (`P-ROWS.json`), der Auswertung (`P-ANALYSIS.json`) und den Zahlen der Arbeit (Abschnitt 6.3) verglichen. Bezeichnung in der Arbeit: „Nachrechnung mit einer getrennten Implementierung“, danach „getrennte Nachrechnung“, nie „unabhängig“, „Validierung“ oder „bestätigt“.

## 2 Umfang

- Hauptvergleich ⟦Q⟧ gegen ⟦F*⟧: alle 9.040 Paare, alle 18.080 Läufe. Vollerhebung, keine Stichprobe.
- Nicht enthalten: Referenzvergleich mit Einzelaufruf und Abstimmungsarm (Stufe 2 entfällt, NEU-5), Runden- und Ausfallvergleich, nachträgliche Auswertungen (Sensitivität mit Aufgaben und Familien als Ziehungseinheit, Aufschlüsselung nach Konfiguration, Auswertungen aus Kapitel 7), Nachrichtenrechte (bereits Z56 V2d), Beträge aus gespeicherten Anbieterantworten, Fälle der Messabnahme, Handnachrechnung, Zahl der Aufgaben und Familien in [N1006].
- Keine Modellaufrufe, kein Netz, 0 US-Dollar.

## 3 Eingaben

Eingangspaket `eingang/`: 18.091 Dateien und `MANIFEST.sha256`, zusammen 448.900.017 Bytes. `MANIFEST.sha256` enthält die SHA-256 jeder Datei; seine eigene SHA-256 ist `4a7ef3f82031fc0d04bdb0f80b4cb1ca8ade16b4dfbb8bcb778de83f06b2f19f`.

| Datei in `eingang/` | Herkunft | SHA-256 |
|---|---|---|
| `AUFTRAG.md` | für N geschrieben; Abschnitte 3 bis 5 wortgleich mit Abschnitt 5 dieser Datei | `10ae19e0c87fdb798562ba1b55efe33cb68604fb8a97a0db82cc93dcfd854821` |
| `METHODENAUSZUG.md` | Arbeit rev25, Abschnitt 4.4 und Anhang D, wörtlich aus `council-feedback-rev25-2026-10-27/quellen/thesis-rev25-bereinigt.md` (SHA-256 `023df612bfde1e7a9d54bf7191cf155674342d25178cc3e7ff74082bb11b68db`), ohne [N4004], [N4005], [X0570], [N4006], [X1695] | `07d74b17ba4e44e0363948f6c3c8c6e0471e8690bc7d20a1db1556dd06fee083` |
| `laufliste.tsv` | 18.080 Zeilen aus `MANIFEST-RUNS.jsonl.gz` der Z56-Prüfung (SHA-256 `ce043658ddad913113ce30c31f5f3a7918655c74ef4ce72a5d91a04005dfc3b1`), nur die Felder `arm`, `block_id`, `draw_index`, `slot_id`, `journal`, ohne `row` und `files`; MuSiQue-ID aus `PLAN.json`, `panels.P[draw_index].task_id` | `915d73fad547621ffe47acccb653bbf6b2ee05f7f85f22e7e27c0a8792f5f0a9` |
| `protokolle/Q/*.jsonl`, `protokolle/F/*.jsonl` | die 18.080 `journal.jsonl` aus `eval-harness/eval/runs/…`, einzeln kopiert, ohne `result.json` und andere Blockdateien; jede Kopie bytegleich mit der Prüfsumme im Z56-Dateimanifest `MANIFEST-FILES.jsonl.gz`; Zuordnung Paket zu Quelle in `zuordnung/HERKUNFT-PROTOKOLLE.tsv` (SHA-256 `55caf4a2168399b800517658c1808f10f71d55568c444c532ebd5bd8c7fb81b5`) | je Datei in `MANIFEST.sha256` |
| `daten/musique_ans_v1.0_dev.jsonl` | `archive/neustart-2026-08-30/legacy-artifact/eval-harness/data/vendor/musique-v1.0/data/`, 2.417 Einträge, jede MuSiQue-ID der Laufliste enthalten | `15fa63794d18a94ce12411aca6e2327e65b6e83b0b1490efab3f1962e48abf3b` |
| `bewertung/metrics/answer.py` | `output/quellenpruefung-2026-10-25/quellen/53-stonybrooknlp-musique/`, gesichert am 25.10. aus StonyBrookNLP/musique, Commit `922ac98f19a201998dbdae6d7f2887a5258dbdeb`; unverändert | `10368f619b4d5ef5d83748c05a96c0afd332a14ab5c010740c98d58dfaefe974` |
| `bewertung/evaluate_v1.0.py` | ebenda, gleicher Commit, unverändert; Beleg der Aliasregel (Zeilen 44 bis 46) | `f5fe66ae61dbea5172cba9d428d9924a5811f3457edc945fc1d81369c30e74b7` |
| `bewertung/metrics/metric.py` | für N geschrieben: Platzhalter `class Metric: pass` für die im Original vorhandene Basisklasse, nur für den Import von `answer.py`; die Bewertungsfunktionen hängen nicht davon ab | `ca9446d89f049427ca58e51911a23c675d2452d2d0316282035630c79cc939cf` |
| `plan/PLAN.json` | `communication-pruning-framework` (Commit 3ca3c6a), `auswertungsplan/PLAN.json`; gleich der im Z56-Manifest gebundenen Planfassung | `42a55ddd7dc71738d39fbdb546b0bb60ca19a0d6485f47688de32c893f47f61f` |
| `plan/ANALYSIS-BINDING.json` | ebenda; gleich `bindings.analysis_contract` in `PLAN.json` | `283c02def99e0fb2c88de66a1dd0e8ac2feebaf737bb058981b2be46d5c7ce0a` |
| `plan/METHODEN-UND-INFORMATION.md` | ebenda, `auswertungsplan/dokumente/`; gleich `original_method_contract` in `ANALYSIS-BINDING.json` | `c316809305d5eeef11ec9406ed474e6bb0058c47716130737627f8ce8e47623d` |
| `format/contract.md` | ebenda, `ergebnisse/messabnahme/verdeckt/contract.md`, Schnittstellenvertrag Z37, vor der Studie geschrieben; Formatbeschreibung nach NEU-1, ergänzt um einen Satz in `AUFTRAG.md` 3.2 | `3f96117f930839c25afc33bafa0b98bfb1e1e73984ab47fad170f36fff7674e9` |

Als Formatbeispiel dienen die Protokolle selbst (NEU-1: „unkommentiertes Beispielprotokoll“); ein gesondertes Beispiel liegt nicht bei.

Abweichung vom Planentwurf 1.3: Dort ist die Vorabdatei Eingabe 1. Sie liegt hier nicht im Paket (Begründung oben); ihre Rechenregeln und das Ausgabeformat erhält die Implementierung wortgleich über `AUFTRAG.md`.

## 4 Was die Implementierung nicht sehen darf

Aus dem Plan: `studiencode-ad152f2` und `Masterarbeit/eval-harness/eval` ganz (`communication_pruning`, `study_preparation` einschließlich `intervals.py` und `final_analysis.py`), `nachrechnen/nachrechnen.py`, `nachpruefungen-nach-studienabschluss/` (`audit_v2.py`, `RESULTS.jsonl`), alle `result.json`, `reference.json`, `selection.json`, `STATE.json`, `P-ROWS.json`, `P-ANALYSIS.json`, `ANALYSIS-*.json`, die Arbeit außer dem Methodenauszug, der Plan und die Positionen. Zusätzlich aus diesem Ordner: diese Datei, `vergleich/` (`vergleich.py` enthält die Zahlen aus 6.3, `gegenprobe/` aus P-ROWS gerechnete Werte), `pruefung/`, `zuordnung/`, `werkzeuge/`.

Technik: Die Implementierung arbeitet in einer Kopie von `eingang/` in einem neuen Zufallsordner unter `/private/tmp`, mit technischer Lese- und Schreibsperre auf Benutzerbereich, temporäre Bereiche und Laufwerke (Abschnitt Isolation), und führt ein Zugriffsprotokoll. Netzzugriffe ausgeführter Befehle sind verboten, aber nicht technisch gesperrt; sie werden nach dem Lauf im Sitzungsprotokoll geprüft.

Leckprüfung des Pakets (`werkzeuge/leckpruefung.py`, Ergebnis `pruefung/LECKPRUEFUNG.json`): bestanden. Geprüft wurden (1) Dateibestand: keine `result.json`, `reference.json`, `selection.json`, `STATE.json`, `P-ROWS.json`, `P-ANALYSIS.json`, `ANALYSIS-*.json` außer `ANALYSIS-BINDING.json`, keine Datei aus `communication_pruning`, `study_preparation`, `nachrechnen`, `nachpruefungen`, `studiencode`, `eval-harness`, `ergebnisse`, keine Python-Datei außer den drei unter `bewertung/`, keine Cache-Datei; (2) die sieben übernommenen Originaldateien bytegleich mit ihrer Quelle; (3) genau 18.080 Protokolle, jedes bytegleich mit dem Studienprotokoll laut Z56-Dateimanifest und genau einmal in der Laufliste, Laufliste mit genau den sechs Zuordnungsspalten; (4) Zahlensuche: alle Zahlen aus `P-ANALYSIS.json` und aus Abschnitt 6.3 der Arbeit außer Design- und Planwerten (9.040, 19.999, Seed, Schwellen, Quantile, Wartezeiten), 120 Werte in 2.474 Schreibweisen (Punkt und Komma, Prozentskala, Rundung auf 1 bis 8 Stellen, mindestens drei signifikante Ziffern), als ganze Ziffernfolge gesucht: kein Treffer in `AUFTRAG.md`, `METHODENAUSZUG.md`, `metric.py`; Treffer nur in unveränderten Originaldateien (MuSiQue-Daten, Ziffernfolgen aus Kennungen in `PLAN.json`, Paketkennung und Planwerte in `METHODEN-UND-INFORMATION.md`), die vor der Studie oder extern entstanden sind; (5) der Wortlaut des Methodenauszugs enthält weder „6.3“ noch „Kapitel 6“ noch einen ausgelassenen Absatz noch Ergebnisformulierungen; (6) dieselbe Zahlensuche über diese Datei und `README.md` (ohne Prüfsummen und Seeds): kein Treffer. Textverweise auf `communication_pruning`, `study_preparation` und `intervals.py` stehen nur als Name oder Pfad in `ANALYSIS-BINDING.json`, `contract.md` und in der Verbotsliste von `AUFTRAG.md`.

## 5 Rechenregeln und Ausgabeformat

Wortgleich mit `eingang/AUFTRAG.md`, Abschnitte 3 bis 5; nur die Überschriften stehen hier eine Ebene tiefer. Prüfung der Wortgleichheit: `werkzeuge/pruefe_wortgleichheit.py`.

<!-- REGELN-ANFANG -->
### 3 Rechenregeln pro Lauf

**3.1 Zuordnung.** `laufliste.tsv` nennt pro Lauf `paarindex` (0 bis 9.039), `arm` (`Q` oder `F`), `block_id`, `musique_id`, `lauf_kennung` und `pfad` des Protokolls. Die Zuordnung wird übernommen, nicht neu hergeleitet. Geprüft wird nur auf Plausibilität: Die `run_id` im Protokollkopf endet auf `:` plus `lauf_kennung`, und die Frage im Protokollkopf (`trace.task.question`) ist gleich dem Feld `question` des MuSiQue-Eintrags mit `id` = `musique_id`. Jeder Verstoß wird als Plausibilitätsbefund des Laufs ausgegeben und ändert nichts an der Rechnung.

**3.2 Format.** Maßgeblich ist `format/contract.md`, Abschnitte „Ausführungs- und Nachrichtenvertrag“, „Journal und bestehendes Instrument“ (nur das Format; die dort genannten Funktionen sind nicht Teil dieses Pakets und werden nicht verwendet) und „Zählung und Kosten“. Ergänzung für die Studienprotokolle: Die Beträge stammen aus der Abrechnung des Anbieters (`cost_source` = `provider`, `price_version` = null), nicht aus einer künstlichen Preistabelle; die Sichten 1 bis 3 der Messabnahme und deren Dateien gibt es hier nicht.

**3.3 Status.** Steht im Protokoll eine `finished`-Nutzlast mit `status` = `completed`, ist der Status `ok`; mit `status` = `model_failed` ist er `model_failure`. Fehlt die `finished`-Nutzlast oder hat sie einen anderen Wert, ist der Status `nicht_nachrechenbar`, mit Grund. Ein solcher Lauf wird gezählt und gemeldet, nicht still ausgelassen.

**3.4 Endantwort.** Das Feld `answer` der `finished`-Nutzlast (bei `model_failure` null).

**3.5 Bewertung.** Zulässige Goldantworten eines Laufs sind `answer` und alle `answer_aliases` des MuSiQue-Eintrags mit `id` = `musique_id` in `daten/musique_ans_v1.0_dev.jsonl` (Regel aus `bewertung/evaluate_v1.0.py`, Zeilen 44 bis 46). Exact Match ist `metric_max_over_ground_truths(compute_exact, endantwort, goldantworten)`, F1 ist `metric_max_over_ground_truths(compute_f1, endantwort, goldantworten)`, jeweils mit den unveränderten Funktionen aus `bewertung/metrics/answer.py` (importierbar mit `bewertung/` im Suchpfad; `bewertung/metrics/metric.py` ist nur ein Platzhalter für die im Original vorhandene Basisklasse, die Funktionen hängen nicht davon ab). Vorab festgelegte Ausnahme ([N0212], [N0596] der Arbeit): Ist der Status nicht `ok` oder ist die Endantwort null, kein String oder nach Entfernen von Leerraum leer (`endantwort.strip() == ""`), sind Exact Match 0 und F1 0. Exact Match wird als Ganzzahl 0 oder 1 ausgegeben, F1 als Gleitkommazahl.

**3.6 Gestartete Modellaufrufe.** Zahl der `event`-Nutzlasten mit `event.kind` = `started`.

**3.7 Bekannte Kosten.** Summe aller Beträge `usage.cost_usd`, die nicht null sind, über alle Ereignisse mit `usage`, exakt mit `decimal.Decimal` aus den Zeichenketten gerechnet (keine Gleitkommazahl), ausgegeben als Dezimalzeichenkette ohne Exponent (`format(summe, "f")`). Unbekannte Beträge werden je eindeutiger `attempt_id` höchstens einmal gezählt: Ein Versuch zählt, wenn mindestens ein Ereignis dieses Versuchs `usage.cost_usd` = null enthält oder ein zugehöriges `started`-Ereignis kein abschließendes `completed` oder `model_failed` mit derselben `attempt_id` hat. Ereignisse ohne `attempt_id` werden jeweils einzeln gezählt, wenn sie eine dieser Bedingungen erfüllen. Wenn beide Bedingungen denselben Versuch betreffen, zählt er einmal. Ein unbekannter Betrag geht nicht als gemessene Null ein und wird nicht geschätzt; die Kostenrechnung beruht auf den bekannten Kosten ([X0542] im Methodenauszug).

### 4 Rechenregeln für Paare und Hauptvergleich

**4.1 Paarwert.** Für Paar i ist D_i = EM_Q,i minus EM_F,i, also +1, 0 oder -1 ([N0544]). Paarzahlen: beide richtig, beide falsch, nur Q richtig, nur F richtig; „gleich“ ist beide richtig plus beide falsch.

**4.2 Kennzahlen.** n = 9.040 Paare. Je Arm: Anteil exakt richtig (Mittel von EM), mittlerer F1, Zahl der Läufe mit Status `model_failure`, Kostensumme S (exakt, Decimal), mittlere Kosten S/n (Decimal, mindestens 40 signifikante Stellen), Summe der gestarteten Aufrufe, Summe der unbekannten Beträge. Qualitätsdifferenz Δ = Mittel der D_i, als Anteil (0,01 entspricht 1 Prozentpunkt). Kostenverhältnis ρ = S_Q / S_F, gleich dem Verhältnis der mittleren Kosten ([N0544]). Die Kosten C_Q,i und C_F,i eines Paars sind die bekannten Kosten der beiden Läufe.

**4.3 Standardfehler** ([X1693]). se_Δ = s(D) / √n. se_ρ = s(C_Q minus ρ·C_F) / √n / mittel(C_F), die Näherung erster Ordnung (lineare Näherung) des Verhältnisses der Mittel. s ist die Stichprobenstandardabweichung mit Nenner n minus 1. Gerechnet wird in float64; dafür werden die Kosten pro Lauf aus der Dezimalzeichenkette in float umgewandelt.

**4.4 Studentisierter Bootstrap über ganze Paare** ([N0546], [X1693], `plan/METHODEN-UND-INFORMATION.md` Abschnitt 5).

- B = 19.999 Wiederholungen (`bootstrap_repetitions` in `plan/ANALYSIS-BINDING.json`).
- Zufallszahlen: `numpy.random.Generator(numpy.random.PCG64(seed))`, für jeden Seed ein neuer Generator.
- Für jede Wiederholung b = 0 bis 19.998, in dieser Reihenfolge und je mit genau einem Aufruf: `idx = rng.integers(0, 9040, size=9040)`, also 9.040 Paarindizes mit Zurücklegen. Mehrere Wiederholungen werden nicht in einem Aufruf gezogen.
- Mit denselben `idx` für D, C_Q und C_F werden auf der Ziehung Δ*_b, se*_Δ,b, ρ*_b = Σ C_Q[idx] / Σ C_F[idx] und se*_ρ,b nach 4.3 berechnet (in se*_ρ,b mit ρ*_b).
- Studentisierte Werte: t*_Δ,b = (Δ*_b minus Δ) / se*_Δ,b und t*_ρ,b = (ρ*_b minus ρ) / se*_ρ,b, mit Δ und ρ der Originalstichprobe.
- Quantile nach Ordnungsrang ceil(p·B) ([N0546], METHODEN-UND-INFORMATION.md Abschnitt 5): q_0,975 ist der 19.500. kleinste, q_0,025 der 500. kleinste der 19.999 t*-Werte (Rang ab 1 gezählt).
- Grenzen je Endpunkt θ (Δ oder ρ): untere Grenze = θ minus q_0,975 · se(θ), obere Grenze = θ minus q_0,025 · se(θ), mit dem Standardfehler der Originalstichprobe.
- Regulär berechnete Grenzen werden nicht zusätzlich auf den Parameterbereich begrenzt. Nur nicht aussagekräftige Grenzen werden auf die unten genannten uninformativen Bereiche gesetzt.
- Nicht aussagekräftige Grenzen ([X1693]): Ist se(θ) der Originalstichprobe null oder nicht endlich, ist in mindestens einer Wiederholung t* nicht definiert (se* null oder nicht endlich, oder Σ C_F[idx] ≤ 0) oder ist der Kostennenner instabil, gelten beide Grenzen dieses Endpunkts als nicht aussagekräftig und werden gesetzt auf: Δ untere -1 (-100 Prozentpunkte), Δ obere +1; ρ untere 0, ρ obere unendlich. Keine Wiederholung wird verworfen. Die Zahl der Wiederholungen mit nicht definiertem t* wird je Endpunkt berichtet.
- Instabiler Kostennenner (F4): mittel(C_F) ≤ 0 gilt als instabil. Es wird kein zusätzlicher, aus dem Auswertungscode abgeleiteter Schwellenwert verwendet. Zusätzlich werden mittel(C_F), dessen Standardfehler s(C_F)/√n und deren Quotient ausgegeben. Weicht deshalb der Status der Kostengrenzen vom Sollstatus ab, wird dies als Klasse (c) mit diesen drei Zahlen sowie beiden Statuswerten berichtet.
- Zwei Seeds, jeder für sich vollständig gerechnet:
  - S1 = `primary_bootstrap_seed` aus `plan/ANALYSIS-BINDING.json` = 142211229048427227715370149966446052232.
  - S2 = 25293223086774291045588755186233620233, gebildet nach `seed_rule` in `plan/ANALYSIS-BINDING.json`: erste 16 Bytes von SHA-256, als Ganzzahl Little Endian gelesen, über das kanonische JSON `["Z50-analysis-v1","Z50-STUDY-v1",20260920,"N-Nachrechnung-2"]` (kompakte Trennzeichen `,` und `:`, ASCII, `seed_base` als Zahl). Prüfe vor der Rechnung, dass dieselbe Regel mit `"P-bootstrap"` statt `"N-Nachrechnung-2"` genau S1 ergibt.

**4.5 Entscheidungsregel** ([N0547]). Die Regel ist erfüllt genau dann, wenn die untere Grenze von Δ größer als -0,03 und die obere Grenze von ρ kleiner als 0,90 ist. Gleichheit mit einer Schwelle reicht nicht. Schwellen aus `plan/ANALYSIS-BINDING.json` (`primary_quality_margin`, `primary_cost_ratio_threshold`).

**4.6 Lesart nach Tabelle 4.5** ([N0553] bis [N0572]), je Seed als Wahrheitswerte:

| Feld | Bedingung | Zeile in Tabelle 4.5 |
|---|---|---|
| `regel_erfuellt` | Δ untere > -0,03 und ρ obere < 0,90 | [N0556] |
| `qualitaet_erhalten_3pp` | Δ untere > -0,03 | Teil von [N0556] |
| `ersparnis_10pct_belegt` | ρ obere < 0,90 | Teil von [N0556] |
| `qualitaetsverlust_belegt` | Δ obere < 0 | [N0560] |
| `verlust_ueber_3pp_belegt` | Δ obere < -0,03 | [N0562] |
| `ersparnis_10pct_ausgeschlossen` | ρ untere > 0,90 | [N0564] |
| `mehrkosten_belegt` | ρ untere > 1 | [N0566] |
| `grenze_nicht_berechenbar` | mindestens eine Grenze nach 4.4 nicht aussagekräftig | [N0568] |
| `offen_ohne_nachteil` | nicht `regel_erfuellt`, keine der Aussagen `qualitaetsverlust_belegt`, `ersparnis_10pct_ausgeschlossen`, `mehrkosten_belegt` und nicht `grenze_nicht_berechenbar` | [N0558] |

Dazu `zeilen_tabelle_4_5`: die Kennungen aller zutreffenden Zeilen aus der rechten Spalte, ohne Doppelungen, in der Reihenfolge der Tabelle.

**4.7 Unvollständige Rechnung.** Ist ein Lauf `nicht_nachrechenbar`, werden die Kennzahlen über die Paare mit zwei nachrechenbaren Läufen gerechnet, `vollstaendig` ist dann false, und die Zahl der ausgelassenen Paare wird ausgegeben. Grenzen, Urteil und Lesart gelten dann als nicht nachgerechnet.

### 5 Ausgabeformat

Alles in den Ordner `ausgabe/` deines Arbeitsordners.

**5.1 `laeufe.jsonl`**: genau eine Zeile pro Lauf der Laufliste, sortiert nach `paarindex`, darin `Q` vor `F`; jede Zeile ein JSON-Objekt mit genau diesen Feldern:

| Feld | Typ | Inhalt |
|---|---|---|
| `paarindex` | Ganzzahl | aus `laufliste.tsv` |
| `arm` | `"Q"` oder `"F"` | aus `laufliste.tsv` |
| `lauf_kennung` | String | aus `laufliste.tsv` |
| `run_id` | String oder null | aus dem Protokollkopf |
| `status` | `"ok"`, `"model_failure"` oder `"nicht_nachrechenbar"` | 3.3 |
| `grund` | String oder null | nur bei `nicht_nachrechenbar` |
| `endantwort` | String oder null | 3.4 |
| `exact_match` | 0 oder 1 | 3.5 |
| `f1` | Zahl | 3.5, mit voller Genauigkeit (Pythons `json.dumps`) |
| `gestartete_aufrufe` | Ganzzahl | 3.6 |
| `bekannte_kosten_usd` | String | 3.7, Dezimalzeichenkette |
| `unbekannte_betraege` | Ganzzahl | 3.7 |
| `plausibilitaet` | Liste von Strings | Befunde nach 3.1, leer wenn keine |

**5.2 `aggregat.json`**: ein JSON-Objekt mit diesem Aufbau (Zahlen mit voller Genauigkeit; nicht endliche Werte als Zeichenkette `"Infinity"` oder `"-Infinity"`; Seeds als Zeichenkette):

```json
{
  "schema": "n-nachrechnung-aggregat/v1",
  "n_paare": 0,
  "n_laeufe": 0,
  "vollstaendig": true,
  "nicht_nachrechenbar": {"laeufe": 0, "ausgelassene_paare": 0, "lauf_kennungen": []},
  "paarzahlen": {"beide_richtig": 0, "beide_falsch": 0, "nur_q": 0, "nur_f": 0, "gleich": 0},
  "summe_paarwerte": 0,
  "arme": {
    "Q": {"anteil_exakt_richtig": 0.0, "f1_mittel": 0.0, "modellausfaelle": 0,
          "kosten_summe_usd": "0", "kosten_mittel_usd": "0",
          "gestartete_aufrufe_summe": 0, "unbekannte_betraege": 0},
    "F": {"...": "wie Q"}
  },
  "qualitaetsdifferenz": {"schaetzer": 0.0, "se": 0.0},
  "kostenverhaeltnis": {"schaetzer": 0.0, "se": 0.0,
                        "nenner_mittel": 0.0, "nenner_se": 0.0, "nenner_quotient": 0.0},
  "bootstrap": [
    {"name": "S1", "seed": "142211229048427227715370149966446052232", "wiederholungen": 19999,
     "seedregel_reproduziert_s1": true,
     "differenz":  {"untere": 0.0, "obere": 0.0, "status": "ok", "undefinierte_wiederholungen": 0, "grund": null},
     "verhaeltnis": {"untere": 0.0, "obere": 0.0, "status": "ok", "undefinierte_wiederholungen": 0, "grund": null},
     "regel_erfuellt": false,
     "lesart": {"qualitaet_erhalten_3pp": false, "ersparnis_10pct_belegt": false,
                "qualitaetsverlust_belegt": false, "verlust_ueber_3pp_belegt": false,
                "ersparnis_10pct_ausgeschlossen": false, "mehrkosten_belegt": false,
                "grenze_nicht_berechenbar": false, "offen_ohne_nachteil": false},
     "zeilen_tabelle_4_5": []},
    {"name": "S2", "seed": "25293223086774291045588755186233620233", "...": "wie S1"}
  ],
  "umgebung": {"python": "", "numpy": "", "plattform": ""},
  "festlegungen_ohne_plantext": []
}
```

`status` einer Grenze ist `"ok"` oder `"nicht_aussagekraeftig"`. `summe_paarwerte` ist nur_q minus nur_f. In `festlegungen_ohne_plantext` steht jede Entscheidung, die dieser Auftrag nicht eindeutig vorgab, mit kurzer Begründung.

**5.3 `ZUGRIFFSPROTOKOLL.md`** nach Abschnitt 2, **5.4 `code/`** mit dem ausgeführten eigenen Code, so wie ausgeführt.

**5.5 `AUSGABE.sha256`**: als letzter Schritt geschrieben, SHA-256 aller Dateien in `ausgabe/` außer dieser Datei, im Format von `shasum -a 256` (Prüfsumme, zwei Leerzeichen, Pfad relativ zu `ausgabe/`), nach Pfad sortiert. Danach wird in `ausgabe/` nichts mehr geändert.
<!-- REGELN-ENDE -->

## 6 Bewertungsregel und Bootstrap: Herkunft

- Bewertung mit den Originalfunktionen `normalize_answer`, `compute_exact`, `compute_f1` und `metric_max_over_ground_truths` aus `answer.py`, Maximum über Goldantwort und Aliasse (`evaluate_v1.0.py`, Zeilen 44 bis 46). Vorab benannte, zulässige Abweichung vom Originalskript: Modellausfall und leere Antwort zählen als falsch ([N0212], [N0596]). Das Originalskript ergibt für eine leere Antwort ohnehin EM 0 und F1 0, solange die Goldantwort nach der Normalisierung nicht leer ist; mit `None` würde es einen Fehler auslösen.
- Bootstrap nach Plantext: [N0546] und [X1693] (studentisiert, ganze Paare, gleiche Ziehungsindizes für Qualität und beide Kostenreihen, Standardfehler, Quantile 97,5 % und 2,5 %, nicht aussagekräftige Grenzen), `ANALYSIS-BINDING.json` (B = 19.999, `primary_bootstrap_seed`, `seed_rule`, Schwellen), `METHODEN-UND-INFORMATION.md` Abschnitt 5 (PCG64, erste 16 Bytes von SHA-256 als Little-Endian-Ganzzahl, Quantilrang ceil(p·B), Sperre bei undefiniertem Pivot, uninformative Bereiche).
- Seeds: S1 = `primary_bootstrap_seed`. Die kanonische Form der `seed_rule` wurde durch Nachrechnen bestimmt: `["Z50-analysis-v1","Z50-STUDY-v1",20260920,"P-bootstrap"]` mit kompakten Trennzeichen und `seed_base` als Zahl ergibt genau S1; mit Zeichenkette oder Leerzeichen ergibt sich ein anderer Wert. S2 entsteht nach derselben Form mit dem Stromnamen „N-Nachrechnung-2“ und ist 25293223086774291045588755186233620233. Ein Stromname „N-Handblatt“ entfällt, weil es keine Handnachrechnung gibt.
- Gleicher Seed bedeutet keine gleichen Ziehungen. Bootstrapgrenzen gelten als übereinstimmend, wenn sie innerhalb der Toleranz liegen; eine Abweichung um eine Einheit der letzten gedruckten Stelle ist dann keine Abweichung (NEU-4). Beide Seeds sind voneinander unabhängige Monte-Carlo-Wiederholungen; Übereinstimmung gilt nur im Rahmen der Toleranz, nie als bitgleiche Reproduktion.

## 7 Vergleich und Toleranzen

Verglichen wird mit `vergleich/vergleich.py` (Abschnitt 14), erst nachdem die Ausgabe festgeschrieben ist. `--ausgabe-sha` ist verpflichtend und muss der festgeschriebenen Prüfsumme von `AUSGABE.sha256` entsprechen. Unsichere oder doppelte Manifestpfade, geänderte oder fehlende gelistete Dateien sowie jede nicht gelistete Ausgabedatei brechen den Vergleich ab (Exit 2). Das Skript prüft außerdem die Prüfsummen von `P-ROWS.json`, `P-ANALYSIS.json` und des Eingangsmanifests; Endantworten werden gegen `finished.answer` im durch die gebundene Laufliste benannten und manifestgeprüften Rohprotokoll verglichen. Jede Abweichung wird mit Lauf bzw. Größe, Feld und beiden Werten gemeldet und nicht eingeordnet.

| Größe | verglichen mit | Toleranz |
|---|---|---|
| Laufmenge, `paarindex`, `arm`, `run_id` | P-ROWS: `slot_id`, `draw_index`, `arm`, `run_id` | identisch; Zuordnung über die Lauf-Kennung, nicht über die Zeilenposition |
| `status`, `exact_match`, `gestartete_aufrufe` | P-ROWS: `status`, `em`, `call_count` | exakt |
| `bekannte_kosten_usd` | P-ROWS: `cost_usd` | exakt als Dezimalzahl (Wertgleichheit, nicht Zeichengleichheit) |
| `f1` | P-ROWS: `f1` | Abweichung höchstens 1e-9 |
| `unbekannte_betraege`, `plausibilitaet`, `status` = `nicht_nachrechenbar` | kein Sollwert in P-ROWS | jeder Wert ungleich 0 bzw. jeder Befund wird gemeldet (Plausibilität bzw. Vollständigkeit) |
| `endantwort` | `finished.answer` im Rohprotokoll aus `eingang/laufliste.tsv` | exakt; Protokollpfad und Prüfsumme aus `eingang/MANIFEST.sha256` |
| Paarzahlen, Saldo, Modellausfälle | P-ANALYSIS (Ausfälle), Arbeit [N1006], [N1015] | exakt |
| Kostensummen je Arm | P-ANALYSIS `descriptive_costs.arms.*.total` | exakt als Dezimalzahl |
| Anteile exakt richtig, F1-Mittel, mittlere Kosten, Qualitätsdifferenz, Kostenverhältnis, beide Standardfehler | P-ANALYSIS, ungerundet | relativ höchstens 1e-9 |
| dieselben Punktwerte und die Kostensummen gegen die Arbeit | [N1006], [N1013], [N1015] | auf den gedruckten Stellen gleich, kaufmännisch gerundet: Anteile in Prozent und Differenz in Prozentpunkten auf 2 Stellen, Kostenverhältnis und F1 auf 3, Kostensummen auf 2 |
| Bootstrapgrenzen, je Seed | P-ANALYSIS `P-D`/`P-C`, `lower`/`upper` | Qualitätsdifferenz höchstens ±0,05 Prozentpunkte (±0,0005 als Anteil), Kostenverhältnis höchstens ±0,001; berichtet wird die größte Abweichung über beide Seeds |
| Bootstrapgrenzen gegen die Arbeit | [N1011], [N1013] | numerische Toleranz allein: ±0,0005 für Δ als Anteil, ±0,001 für ρ; zusätzlich kaufmännische Rundung auf die gedruckten Stellen und exakter Vergleich mit dem Druckwert |
| Status der Grenzen | P-ANALYSIS `status`, `undefined_resamples` | „ok“ gegen „nicht ok“ identisch; undefinierte Wiederholungen beide null oder beide nicht null |
| Urteil und Lesart, je Seed | P-ANALYSIS `joint_positive`, `statements`; Arbeit [N1005], [N1011], [N1013] | identisch |
| innere Stimmigkeit der Ausgabe | aus den eigenen Läufen der Ausgabe neu gerechnete Kennzahlen; Lesart aus den eigenen Grenzen | Zählungen und Summen exakt, sonst relativ höchstens 1e-9; Lesart identisch |

Zuordnung der Lesart zu `P-ANALYSIS.json`: `qualitaet_erhalten_3pp` ↔ `quality_preserved_3pp`, `qualitaetsverlust_belegt` ↔ `quality_loss`, `verlust_ueber_3pp_belegt` ↔ `quality_loss_beyond_3pp`, `ersparnis_10pct_belegt` ↔ `cost_saving_at_least_10pct`, `ersparnis_10pct_ausgeschlossen` ↔ `cost_saving_below_10pct`, `mehrkosten_belegt` ↔ `cost_increase`, `regel_erfuellt` ↔ `joint_positive`; „established“ entspricht wahr.

Der Bericht stellt für jeden gedruckten Punkt- und Grenzwert den Sollwert, den ungerundeten Nachrechnungswert und dessen kaufmännische Rundung nebeneinander. Bei Bootstrapgrenzen stehen die Toleranzprüfung und der exakte Vergleich der Rundung getrennt. Schwellenurteil und Lesart nach Tabelle 4.5 werden jeweils exakt verglichen. Die Toleranzwerte für Einzelwerte, F1 und Bootstrapgrenzen stammen aus dem Plan (Abschnitt 4 und Planentwurf 1.3). Ihre Begründung dort beruht auf dem Monte-Carlo-Fehler einer 2,5-%-Grenze bei 19.999 Ziehungen und auf beobachteten Größen; sie wird hier nicht wiederholt, weil sie Ergebniswerte enthält.

## 8 Abweichungsklassen und Folgen

Jede Meldung wird von einer getrennten Instanz eingeordnet, nicht von der Implementierung und nicht von der vorbereitenden Instanz, und zwar am Plantext, nicht am Code.

| Klasse | Bedeutung | Folge |
|---|---|---|
| (a) | Fehler der getrennten Implementierung | höchstens eine dokumentierte Korrekturrunde: Hinweis an die Implementierung nur auf die verletzte Regel, nie auf den Sollwert; korrigierte Ausgabe in `ausgabe-korrektur-1/`, wieder festgeschrieben, dann erneuter Vergleich; beide Stände werden berichtet (wie [N0973]); keine Wiederholung bis zur Übereinstimmung |
| (b) | Fehler in Framework, Auswertung oder ausgewerteter Zeile | Studienwerte werden nicht still ersetzt; ursprünglicher und korrigierter Wert stehen nebeneinander, gekennzeichnet „nach Abschluss der Studie korrigiert“; die Entscheidungsregel wird mit beiden angewandt. Berührt die Korrektur eine Lesart nach Tabelle 4.5 oder eine Zahl in Abstract, Kurzfassung, 6.3, 7.1 oder 8.1, entscheidet Jannik vor jeder Textänderung über die Darstellung; danach ziehen diese Stellen nach |
| (c) | dokumentierte, vorab nummerierte Regel oder Mehrdeutigkeit der Spezifikation | nur mit Zitat des konkreten Regelpunkts; beide Werte und die rechnerische Folge werden berichtet. Ohne vorab nummerierten Regelpunkt gilt Klasse (d) |
| (d) | ungeklärt | als ungeklärt berichtet, ungünstigster Fall beziffert wie in [N0934]; [N1427] wird entsprechend vorsichtiger formuliert |

Weitere Regeln:

- Liegen Bootstrapgrenzen außerhalb der Toleranz, ohne dass ein Einzelwert abweicht, werden beide Verfahren an einem kleinen Fall mit bekanntem Ergebnis geprüft. Liegt die Ursache in einer unvollständigen Beschreibung des Plans, wird das in E28 berichtet; eine Ergänzung von Anhang D gibt es nur nach Janniks Entscheidung.
- Bei den Paaren mit ersetztem Sendeversuch (Tabelle 6.1, [N0934]) gilt das Protokoll, das die Z56-Zuordnung nennt. Ob die ausgewerteten Zeilen dort Beträge außerhalb dieses Protokolls enthalten, hat die vorbereitende Instanz bewusst nicht vorab geprüft. Eine Abweichung dort ist (c), wenn [X0542] und Tabelle 6.1 sie erklären, sonst (b) oder (d).
- Kein Lauf wird still ausgeschlossen. Nicht nachrechenbare Läufe werden gezählt; Grenzen, Urteil und Lesart gelten nur als nachgerechnet, wenn alle 18.080 Läufe nachgerechnet sind.
- Toleranzen, Regeln und Klassen werden nach Sicht auf Ergebnisse nicht geändert. Berichtet wird unabhängig von der Richtung.

## 9 Ablauf und Festschreibung

1. Vorabfestlegung: diese Datei, Eingangspaket mit Manifest, Leckprüfung, `vergleich.py` und Gegenprobe (Stand dieser Datei).
2. Gegenprüfung durch Codex (diese Datei, `AUFTRAG.md`, Methodenauszug, Leckprüfung, `vergleich.py`, `gegenprobe.py`). Nach jeder Änderung an `eingang/`: Manifest und Leckprüfung neu; nach jeder Änderung an `vergleich.py`: Gegenprobe neu; die Prüfsummen in den Abschnitten 3 und 14 ziehen nach.
3. Gezielter Commit als Zeitnachweis, nach Ansage und nach Janniks Freigabe von F4 und F11, ausschließlich der hier aufgelisteten Dateien mit `git add -f`: diese Datei, `README.md`, die vier Codex-Gegenprüfungen (`GEGENPRUEFUNG-CODEX.md`, `-2.md`, `-3.md`, `-4.md`) und die Codex-Prüfung des Commits (`GEGENPRUEFUNG-CODEX-5-COMMIT.md`), die selbst geschriebenen Dateien aus `eingang/` mit `MANIFEST.sha256`, `werkzeuge/`, `pruefung/LECKPRUEFUNG.json`, `vergleich/*.py`, `vergleich/gegenprobe/GEGENPROBE-ERGEBNIS.*` und `isolation/` (`sperre.sb`, `starten.sh`, `sichern.sh`, `pruefe_protokoll.py`, `TEST-ERGEBNIS.md`, `TEST-v3-AUDIT.md`, `TEST-v3-lauf.log`, frühere Fassungen `TEST-ERGEBNIS-v1.md`, `TEST-v2-lauf.log`, `alt/`); die Protokolle bleiben außerhalb des Repositorys und sind über `MANIFEST.sha256` gebunden. Keine Zweitkopie unter `project/`. Push auf den privaten Remote.
4. Implementierung in getrennter Sitzung (Codex), nur mit der Kopie von `eingang/`, nach `AUFTRAG.md`.
5. Festschreiben, vor jedem Vergleich: `isolation/sichern.sh <Laufordner> 1` führt die Protokollprüfung aus und kopiert die Ausgabe nach `ausgabe-1/` sowie Sitzungsprotokolle (`codex-home/sessions/`), `lauf.log`, `letzte-antwort.txt`, `AUDIT.json` und `AUDIT.md` nach `lauf-1/`, mit `lauf-1/SICHERUNG.sha256` über alle gesicherten Dateien. SHA-256 von `AUSGABE.sha256` und von `SICHERUNG.sha256` notieren, `ausgabe-1/` und `lauf-1/` committen (ohne Protokolle des Eingangspakets).
6. Erst dann `vergleich.py` mit `--ausgabe-sha` auf die festgeschriebene Prüfsumme.
7. Einordnung jeder Meldung nach Abschnitt 8, danach die Textstellen E28, E30 bis E33, E39 und E40 nach Ergebnis.

### Prüfergebnisse am 27.10.2026

- Eingangsmanifest nach der Änderung an `AUFTRAG.md` neu geschrieben: 18.091 Einträge, SHA-256 `4a7ef3f82031fc0d04bdb0f80b4cb1ca8ade16b4dfbb8bcb778de83f06b2f19f`.
- `werkzeuge/pruefe_wortgleichheit.py`: Exit 0, Ausgabe `wortgleich`.
- `werkzeuge/leckpruefung.py`: Exit 0, bestanden; 120 Ergebniszahlen in 2.474 Textformen geprüft, keine Befunde. Es gab nur die im Skript ausgewiesenen Informationstreffer in unveränderten Originaldateien und Textverweisen.
- `vergleich/gegenprobe.py`: Exit 0, alle sechs Proben bestanden. Die Feldprobe fand neun von neun erwarteten Meldungen; fehlender Hash, zusätzliche Datei, doppelter und unsicherer Manifestpfad sowie Dateiänderungen nach Festschreibung blockierten mit Exit 2.
- Die eigentliche Nachrechnung wurde nicht ausgeführt.

## 10 Gegenprobe des Vergleichsskripts

`vergleich/gegenprobe.py` erzeugt aus `P-ROWS.json`, `P-ANALYSIS.json` und den gebundenen Endantworten aus den Rohprotokollen eine Pseudoausgabe. Punktwerte und Standardfehler werden aus den Zeilen gerechnet; Grenzen und Status stammen für beide Seeds aus `P-ANALYSIS.json`. Die Pseudoausgabe ist keine Nachrechnung. Ergebnis vom 27.10.2026 (`vergleich/gegenprobe/GEGENPROBE-ERGEBNIS.md`): alle sechs Proben bestanden.

| Probe | erwartet | Ergebnis |
|---|---|---|
| A Nullprobe, unveränderte Pseudoausgabe einschließlich Endantworten aus den Rohprotokollen | keine Meldung | Exit 0, keine Meldung |
| B zwei Zeilen von `laeufe.jsonl` in der Reihenfolge vertauscht | keine Meldung (Vergleich über die Lauf-Kennung, K3 Punkt 8) | keine Meldung |
| C fünf versiegelte Änderungen an einer Kopie von P-ROWS: ein EM gedreht, ein F1 um 1e-8 verändert, eine Aufrufzahl +1, ein Betrag +0,0000001 US-Dollar, die Werte zweier Zeilen vertauscht; dazu eine Kontrolländerung unter der Toleranz (ein F1 um 1e-10) | auf Laufebene genau die fünf Änderungen, die Vertauschung als zwei Meldungen (eine je Zeile); Kontrolle ungemeldet; Folgemeldungen nur in abhängigen Kennzahlen | genau die fünf Änderungen in sechs Läufen, Kontrolle ungemeldet, nur zulässige Folgemeldungen (Anteil, Paarzahlen, Differenz, Kostensumme, mittlere Kosten, Verhältnis und deren Standardfehler) |
| D kontrollierte Feldänderungen: Status `ok` zu `model_failure`, `run_id`, `paarindex`, `arm`, unbekannte Beträge, geänderte und fehlende `endantwort`, doppelter und fehlender Lauf | Meldung je Feld und Laufmengendifferenz | Exit 1, alle neun erwarteten Meldungen gefunden |
| E fehlendes `--ausgabe-sha`, zusätzliche nicht gelistete Datei, doppelter Manifestpfad, unsicherer Manifestpfad | Vergleich jeweils mit Exit 2 abbrechen | viermal Exit 2 |
| F falsche festgeschriebene Prüfsumme und Dateiänderung nach der Festschreibung | Abbruch mit Exit 2 | beide Male Exit 2 |

Die fünf Änderungen aus C wurden mit festem Zufallswert (20261027) gewählt, mit den erwarteten Meldungen gespeichert und vor dem Vergleich per SHA-256 versiegelt; das Siegel blieb danach unverändert. D prüft ausdrücklich `status` von `ok` zu `model_failure`, falsche `run_id`, `paarindex` und `arm`, einen unbekannten Betrag, geänderte und fehlende Endantwort, einen doppelten Lauf und einen fehlenden Lauf. Beide Endantwortfälle melden den Wert gegen `finished.answer` aus dem gebundenen Rohprotokoll. Die Nullprobe zeigt, dass alle unveränderten Endantworten exakt übereinstimmen und die Formeln aus `AUFTRAG.md` 4.2 und 4.3 die Punktwerte und Standardfehler in P-ANALYSIS innerhalb von 1e-9 treffen. Die echte Nachrechnung wurde nicht ausgeführt.

## 11 Grenzen

- Dieselben Laufprotokolle (vom Framework geschrieben) und derselbe Auswertungsplan wie die Auswertung; Fehler im Plan oder in den Protokollen selbst bleiben unentdeckt. Nicht geprüft werden die Vollständigkeit der Protokolle (verdeckte Aufrufe) und die Richtigkeit der gemeldeten Preise (Tabelle 5.5).
- Die Zuordnung Protokoll zu Paar ist aus der Z56-Prüfung vom 20.10. übernommen, die sie über die Gleichheit von `result.json` mit der ausgewerteten Zeile hergeleitet hat. N erkennt Widersprüche zwischen Zeile und Protokoll, aber kein falsch gewähltes Protokoll (NEU-2). Teilweise abgefedert: `run_id` und Frage im Protokollkopf werden gegen Laufliste und MuSiQue geprüft.
- Die Formatbeschreibung `contract.md` wurde in Kenntnis des Framework-Codes geschrieben (NEU-1); die Klammer in E32 gilt.
- Die Bewertungsdefinition (MuSiQue-Skript, Goldantwort plus Aliasse) ist dieselbe wie in der Studie; ein Fehler in dieser Definition wäre nicht erkennbar.
- Keine zweite Person. Die Implementierung übernimmt Codex, das am Framework mitwirkte ([N1623]): getrennt vom Code, nicht von der Werkzeugfamilie.
- Organisatorische, keine technische Trennung.
- Die vorbereitende Instanz kannte Code und Sollwerte. Einzelne Festlegungen ohne Plantext (Abschnitt 12) sind in Kenntnis des Codes getroffen; sie stehen offen in `AUFTRAG.md`. Sie hat zudem die Struktur aller 18.080 Protokolle maschinell gesichtet (Ereignisarten, Felder, Kostenquelle, Präfix der `run_id`, Frage gegen MuSiQue), um die Formatergänzung in `AUFTRAG.md` 3.2 und die Plausibilitätsprüfungen aus 3.1 zu belegen, ohne Werte mit Sollwerten abzugleichen. Die Plausibilitätsprüfungen aus 3.1 ergeben dabei für keinen Lauf einen Befund.
- Die lokale Kopie von `answer.py` wurde nicht erneut gegen GitHub geprüft (kein Netz); die Bytegleichheit mit Commit 922ac98 beruht auf der Sicherung vom 25.10.

## 12 Festlegungen dieser Datei ohne ausdrücklichen Plantext

| Nr. | Festlegung | Herkunft und Wirkung |
|---|---|---|
| F1 | Standardabweichung mit Nenner n minus 1 | Plantext sagt nur „Standardabweichung“. In Kenntnis des Codes gewählt. Die Grenzen hängen davon nicht ab (der Faktor kürzt sich im studentisierten Quotienten), nur der berichtete Standardfehler |
| F2 | Ziehung je Wiederholung mit genau einem Aufruf `rng.integers(0, 9040, size=9040)` | Plantext legt nur PCG64 und Seedregel fest. Die Auswertung zog auf andere Weise; deshalb gilt NEU-4 |
| F3 | kanonische Form der Seedregel (kompakte Trennzeichen, `seed_base` als Zahl) | durch Nachrechnen von S1 bestimmt, nicht aus dem Code |
| F4 | instabiler Kostennenner nur bei mittel(C_F) ≤ 0; kein zusätzlicher codeinformierter Schwellenwert; bei abweichendem Status der Kostengrenzen Klasse (c) mit Nenner-Mittel, Standardfehler, Quotient und beiden Statuswerten | O1 gemäß Gegenprüfung, von Jannik am 27.10.2026 freigegeben (Abschnitt 13); entspricht der Regel in `AUFTRAG.md` 4.4 |
| F5 | bei nicht aussagekräftigem Endpunkt beide Grenzen auf den uninformativen Bereich (Δ: -1 und +1; ρ: 0 und unendlich) | Anhang D nennt nur die untere Qualitäts- und die obere Kostengrenze; die anderen beiden aus den uninformativen Bereichen in METHODEN-UND-INFORMATION.md Abschnitt 5 |
| F6 | „leere Antwort“ = null, kein String oder nur Leerraum; eine erst durch die Normalisierung leere Antwort läuft durch die Originalfunktionen | [N0596] beziffert „leer“ nicht |
| F7 | Zeile [N0558] „ohne dass eine Grenze einen Nachteil belegt“: Nachteil = Qualitätsverlust belegt, Ersparnis von zehn Prozent ausgeschlossen oder Mehrkosten belegt | Tabelle 4.5 zählt die Nachteile nicht auf; die abgeleitete Zeile wird nur auf innere Stimmigkeit geprüft, gegen P-ANALYSIS zählen die Einzelaussagen |
| F8 | Plausibilitätsprüfungen `run_id` und Frage; unbekannte Beträge als Plausibilitätsmeldung | Ergänzung, ändert keine Rechnung |
| F9 | Standardfehler und mittlere Kosten relativ höchstens 1e-9 | Ergänzung zu den Planwerten für Anteile, Differenz und Verhältnis |
| F10 | Grenzen gegen die gedruckten Werte der Arbeit: numerische Toleranz und kaufmännische Rundung getrennt prüfen; undefinierte Wiederholungen nur null gegen nicht null | Ergänzung; die Ziehungen unterscheiden sich (F2) |
| F11 | Reguläre Bootstrapgrenzen werden nach der Formel berechnet und nicht zusätzlich auf den Parameterbereich gekappt | O2 gemäß Gegenprüfung, von Jannik am 27.10.2026 freigegeben (Abschnitt 13); nur nicht aussagekräftige Grenzen erhalten die ausdrücklich festgelegten uninformativen Bereiche |

## Isolation

Die Implementierung läuft technisch abgeschottet, nicht nur nach Absprache (Muss-Befunde der Codex-Gegenprüfungen 1 bis 3). Fassung 3, Dateien in `isolation/`:

1. **Neuer Zufallsordner pro Lauf:** `isolation/starten.sh` legt mit `mktemp -d` einen neuen Ordner `/private/tmp/n-lauf-XXXXXXXX` an, darin `arbeit/` (Kopie des Inhalts von `eingang/`), `codex-home/` und `tmp/`. Vor dem Start werden die SHA-256 von `MANIFEST.sha256` und jeder Manifesteintrag geprüft. Der Auftrag an die Implementierung steht fest im Startskript („Lies AUFTRAG.md in diesem Ordner vollständig und führe ihn aus“); eine frei wählbare Auftragsdatei oder ein frei wählbarer Arbeitsordner gibt es nicht. Ein Probelauf (`--probe`) bekommt einen eigenen Zufallsordner mit festem Testauftrag.
2. **Geschlossene Sandbox:** macOS `sandbox-exec` mit dem Profil `isolation/sperre.sb`. Lesen und Schreiben gesperrt für den gesamten Benutzerbereich `/Users`, alle temporären Bereiche (`/private/tmp`, `/private/var/folders`) und externe Laufwerke (`/Volumes`). Ausnahmen: nur der eigene Laufordner (Parameter `LAUF`, lesen und schreiben), die Laufzeit von Node und Codex unter `~/.nvm/versions/node/v25.2.1` (nur lesen) und die Anmeldedatei `~/.codex/auth.json` (nur lesen). Frühere Läufe und Probeläufe sind damit nicht lesbar. Python mit NumPy liegt unter `/opt/anaconda3` (Systembereich, enthält keine Projektdaten). Die Umgebung wird geleert (`env -i`), HOME und TMPDIR zeigen in den Laufordner, die Pfade von Node, Codex und Python sind fest eingetragen und werden vor dem Start geprüft.
3. **Frische Codex-Umgebung ohne Zusatzdienste:** eigener `CODEX_HOME` im Laufordner, Modell gpt-6-luna, Websuche aus; abgeschaltet sind Apps, Plugins (auch die des ChatGPT-Kontos wie Firecrawl, Notion, Figma), Erinnerungen, Bildgenerierung, Browser- und Computersteuerung, Mehragentenbetrieb und entfernte MCP-Clients. Die Sitzung wird im Laufordner vollständig protokolliert.
4. **Nachweis:** `isolation/TEST-ERGEBNIS.md`. Im Probelauf scheiterten Lesen von Studiencode, Benutzerordner, Codex-Verläufen, temporären Bereichen, früheren Laufordnern und Laufwerken sowie Schreiben in den Benutzerordner und in die Anmeldedatei; Plugins wurden nicht geladen; Arbeitsordner, Laufzeit und NumPy funktionierten.
5. **Prüfung nach dem Lauf:** `isolation/pruefe_protokoll.py <Laufordner>` (außerhalb der Sandbox) liest das vollständige Sitzungsprotokoll, listet jeden Werkzeugaufruf und markiert Netzmuster (curl, wget, git, pip, conda, npm, ssh, urllib, requests, http.client, socket, httpx, URLs), Aufrufe anderer Werkzeuge als Shell und Patch (Plugins, MCP, Websuche) und absolute Pfade außerhalb des Laufordners und der Laufzeit. Sitzungsprotokoll, `AUDIT.json` und `AUDIT.md` werden mit der Ausgabe festgeschrieben.
6. **Kopien außerhalb der gesperrten Bereiche:** Das Profil ist eine Sperrliste für alle Nutzerdatenbereiche, keine vollständige Allowlist (`allow default` mit Sperren). Gesucht wurde deshalb nach Kopien von Studiencode, Ergebniszeilen, Laufprotokollen und Arbeitsfassungen in den nicht gesperrten Bereichen (`/opt`, `/Library`, `/usr/local`, `/private/var` außer `folders`, `/private/etc`, `/Applications`; Namen `intervals.py`, `final_analysis.py`, `P-ROWS.json`, `P-ANALYSIS.json`, `audit_v2.py`, `nachrechnen.py`, `journal.jsonl`, `Masterarbeit-AKTUELL*`, `thesis-rev2*.md`): kein Treffer außer einer gleichnamigen, fremden Bibliotheksdatei (`/opt/anaconda3/.../librosa/core/intervals.py`).
7. **Probeläufe:** Die Isolationstests liefen außerhalb der Codex-Gegenprüfung; in deren eigener Sandbox lässt macOS kein weiteres `sandbox-exec` zu (vierte Gegenprüfung: `sandbox_apply: Operation not permitted`).
8. **Grenzen:** (a) Netzzugriffe ausgeführter Befehle sperrt die Sandbox nicht, weil macOS keine verschachtelte Sandbox zulässt und der Codex-Prozess selbst das Netz für das Modell braucht; der Auftrag verbietet sie, Punkt 5 prüft sie. (b) Die Anmeldedatei ist im Prozessbaum lesbar; ein Prozess könnte das Anmeldetoken über das Netz weitergeben. Das ist ein Risiko für das Konto und wird über Punkt 5 geprüft, es berührt nicht die Trennung von Code und Ergebnissen. (c) Bereitgestellt sind die 18.080 Rohprotokolle mit Endantworten, Status und gemeldeten Beträgen sowie Plan, Methodenauszug und Bewertungsskript; nicht bereitgestellt sind die ausgewerteten Zeilen (`P-ROWS.json`, `result.json`), die Analyseausgaben (`P-ANALYSIS.json`) und der Code von Framework und Auswertung.
9. **Bezeichnung im Text:** „getrennte Implementierung, die weder den Code von Framework und Auswertung noch die ausgewerteten Zeilen erhielt“, mit dem Zusatz, dass die Lesesperre technisch erzwungen und Netzzugriffe anhand des Protokolls geprüft wurden. Jeder Treffer der Prüfung nach Punkt 5 wird berichtet und schwächt diese Bezeichnung.

## 13 Geschlossene Punkte

- **O1 entschieden, freigegeben von Jannik am 27.10.2026:** F4 bleibt maßgeblich. Nur mittel(C_F) ≤ 0 macht den Kostennenner nicht aussagekräftig. Es kommt kein aus dem Auswertungscode abgeleiteter Schwellenwert hinzu. Ein abweichender Status der Kostengrenzen wird als Klasse (c) unter Nennung von F4 mit Nenner-Mittel, Standardfehler, Quotient und beiden Statuswerten berichtet. Vorgelegt wurde Jannik der Unterschied zum Studiencode: Dieser setzt die Kostengrenzen schon dann auf nicht aussagekräftig, wenn mittel(C_F) höchstens das 1,96-Fache seines Standardfehlers beträgt; der Plantext nennt keine Schwelle. Antwort im Chat: „3. Ja passt“.
- **O2 entschieden, freigegeben von Jannik am 27.10.2026:** Reguläre Grenzen folgen der Formel in `AUFTRAG.md` 4.4 ohne zusätzliche Kappung auf Δ ∈ [-1, 1] oder ρ ≥ 0. Nur nicht aussagekräftige Grenzen werden auf die genannten uninformativen Bereiche gesetzt; die Regel ist als F11 nummeriert. Vorgelegt wurde Jannik, dass der Studiencode reguläre Grenzen auf diese Bereiche kappt und der Plantext dazu nichts sagt. Antwort im Chat: „4. sehe ich als nicht notwendig an“; auf Rückfrage gewählt: „Abschneiden unnötig: Die Nachrechnung übernimmt die Grenzen so, wie die Formel sie liefert, ohne Kappung.“
- **O3 entschieden:** Für den Zeitnachweis wird ausschließlich der gezielte Commit der Dateien aus Abschnitt 9.3 mit `git add -f` verwendet. Eine Zweitkopie unter `project/` wird nicht angelegt. Der Commit erfolgt nach der dort genannten Ansage.
- **O4 entschieden:** `VORAB-N.md` bleibt außerhalb von `eingang/`. Der Implementierung werden die Rechenregeln über den wortgleichen Auftrag bereitgestellt.
- **O5 entschieden:** Der spätere Thesistext nennt `AUFTRAG.md` als bereitgestellte Grundlage. Er legt außerdem offen, dass der Auftrag codeinformierte Regeln enthält. E28 und E39 ergänzen die Grundlage; E32 benennt die Codekenntnis und die dadurch beeinflussten Festlegungen.

## 14 Prüfsummen der Werkzeuge und Sollwerte

| Datei | SHA-256 |
|---|---|
| `vergleich/vergleich.py` | `aaeb2cf80b1ff94cbe3255b516b4216925d671d6f022291c8d4dbb151a6a00bf` |
| `vergleich/gegenprobe.py` | `ee746cd8be3518bdc6a46715e98bbc1913f9068a2bfdf2e073a761160a7046c4` |
| `vergleich/gegenprobe/GEGENPROBE-ERGEBNIS.json` | `40113df13d975faf9be052bc734c3272bffb0279f74dbf5fb798234f29371deb` |
| `vergleich/gegenprobe/GEGENPROBE-ERGEBNIS.md` | `2372a7544a25d824388f5378530e32612ad3c0c234e34af19edc9f3ab8d8f035` |
| `werkzeuge/baue_eingang.py` | `fd5ae5f75ae6078d7e04a709ee95c00a602217d05f797223c2de4f9b29a6f9bc` |
| `werkzeuge/baue_methodenauszug.py` | `57c542028a196526e5267aa00ce4e052925adaec411e1880e4d1c3a9b67f7f85` |
| `werkzeuge/schreibe_manifest.py` | `37af03abe4b6bdac8312b40fa2a925653302eb9bae13ede4d9eaacb663c8d55a` |
| `werkzeuge/leckpruefung.py` | `c71d22ec366d4d060ba327d6a5c7bdf54f01882dbd37339a772f2237d5fc391c` |
| `werkzeuge/pruefe_wortgleichheit.py` | `57f34a7c2a0e6ed3328f87d46e5c5463ade9fc5201f476944f6953bfb889397f` |
| `pruefung/LECKPRUEFUNG.json` | `5b1915c04345b467e0b25a7234e3c6cbf0e567f156b74896a635b7301407b20c` |
| `zuordnung/HERKUNFT-PROTOKOLLE.tsv` | `55caf4a2168399b800517658c1808f10f71d55568c444c532ebd5bd8c7fb81b5` |
| `isolation/sperre.sb` | `2364687eb78451e5625989ae813c2eea01f136281c7e463262e2e010b4337caf` |
| `isolation/starten.sh` | `558b99c4d311defbd5fc3c7d7e79511e0d940e5155c07fabe851322517822011` |
| `isolation/pruefe_protokoll.py` | `eb4d76373ddf8c34fdf9008349ac96dfd1cb63f61b412d793c1eee11aab1572e` |
| `isolation/TEST-ERGEBNIS.md` | `0b32c6f76838005c37e18bf9a010ffb88e9a5f99c7b31f0dc0e344f548385fbb` |
| `werkzeuge/aktualisiere_bindungen.py` | `e84e64e2f3ee1fdcf8ece5a612b82f830a118a31ef92a88eed3e31bddaaa869c` |
| `isolation/sichern.sh` | `7b7c2e11217335b9882d630ef8c0e856d7004af5a0016fea7dfc004874e61f7a` |
| `isolation/TEST-v3-AUDIT.md` | `a0368cb3cd8125ce88a1d8b1c5d822055b89e4fdc182c2baedfa95e07f1e2614` |
| `isolation/TEST-v3-lauf.log` | `fcbd0697686c31537b4cd827daf56671f9f20563efcb06e245251c8ff520f1e9` |
| `GEGENPRUEFUNG-CODEX.md` | `4b8598a35342dc36e1049c484699dbc8cdd65478687a357b2357669d1d8c6661` |
| `GEGENPRUEFUNG-CODEX-2.md` | `611c078cc23fed8ad5b631aae2e32c2c2ddc640ddff0ec5899344209bbbee615` |
| `GEGENPRUEFUNG-CODEX-3.md` | `78f1005e18cf9a8cf8b402aed0efa4a2afeb7ac91fdbd8c543ca65e5dfd8faf1` |
| `GEGENPRUEFUNG-CODEX-4.md` | `6df4ce8ad7048d37699bfd30285a79ee805ce9491b46340e6de6af116180b0e9` |
| Sollwert `communication-pruning-framework/ergebnisse/hauptvergleich/P-ROWS.json` (Commit 3ca3c6a) | `f22b12017abe4f93a89fcb29dd55728e78c31392bcc8895ebbcf47672c00fcd0` |
| Sollwert `communication-pruning-framework/ergebnisse/hauptvergleich/P-ANALYSIS.json` (Commit 3ca3c6a) | `fc4be29676749d7611d7c3f0d11e912193e4588609acb5d4734a15c387dcba65` |
| Z56 `pruefroutine-studienlaeufe/MANIFEST.json` | `9e98bba5ee626ea6d31087c529c2cbaa531d9bffd1948fdce9266ce8c3b87367` |
| Zahlen der Arbeit: `thesis-rev25-bereinigt.md` | `023df612bfde1e7a9d54bf7191cf155674342d25178cc3e7ff74082bb11b68db` |
