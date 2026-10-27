<!-- status: Auftrag an die getrennte Implementierung N, Teil der Vorabfestlegung N | 2026-10-27 -->

# Auftrag: getrennte Nachrechnung des Hauptvergleichs

## 1 Worum es geht

Eine abgeschlossene Studie hat zwei Auswahlregeln für ein LLM-Multi-Agenten-System auf dem Dev-Bestand von MuSiQue verglichen: die aufgabenabhängige Auswahl, Arm `Q` (in der Arbeit ⟦Q⟧), und die feste Referenz, Arm `F` (in der Arbeit ⟦F*⟧). Jede der 9.040 Aufgabenziehungen (Paare) wurde mit beiden Armen je einmal ausgeführt, zusammen 18.080 Läufe. Jeder Lauf hat ein Laufprotokoll.

Deine Aufgabe: Rechne allein aus den Unterlagen in diesem Ordner nach, was der Hauptvergleich aus diesen Protokollen ergibt. Pro Lauf Status, Endantwort, Exact Match, F1, gestartete Modellaufrufe und bekannte Kosten; daraus Paarzahlen, Anteile, Qualitätsdifferenz, Kostensummen, Kostenverhältnis, die Grenzen des studentisierten Bootstraps für zwei Seeds, das Urteil der Entscheidungsregel und die Lesart nach Tabelle 4.5. Schreibe dafür eigenen Code. Sollwerte bekommst du nicht. Verglichen wird später von einer anderen Instanz, erst nachdem deine Ausgabe mit Prüfsumme festgeschrieben ist.

## 2 Was du lesen darfst und was nicht

Erlaubt sind ausschließlich die Dateien in diesem Ordner (Liste in Abschnitt 6), dazu die Standardbibliothek von Python und NumPy aus der lokalen Installation. Python mit NumPy: `/opt/anaconda3/bin/python`; das System-Python (`python3`) hat kein NumPy.

Nicht erlaubt, auch nicht zum Nachschlagen oder Gegenprüfen:

- alles außerhalb dieses Ordners im Projekt `Masterarbeit` und im Repository `communication-pruning-framework`, insbesondere `eval-harness/eval` mit `communication_pruning`, `study_preparation` (darin `intervals.py`, `final_analysis.py`) und `runs/` (darin `result.json`, `reference.json`, `selection.json`, `STATE.json`), `studiencode-ad152f2`, `nachrechnen/`, `nachpruefungen-nach-studienabschluss/` (darin `audit_v2.py`, `RESULTS.jsonl`, Manifeste), `ergebnisse/` (darin `P-ROWS.json`, `P-ANALYSIS.json`, `ANALYSIS-*.json`), die Arbeit außer `METHODENAUSZUG.md`, alle Pläne, Positionen und Gegenprüfungen unter `output/` und im Ordner `output/nachrechnung-n-2026-10-27/` alles außer `eingang/`;
- Netzzugriffe und Modellaufrufe aus den Befehlen und Programmen, die du ausführst, auch keine Paketinstallation. Die Verbindung, über die du selbst als Modell arbeitest, ist davon nicht betroffen.

Die Pfade in `plan/ANALYSIS-BINDING.json` und die Funktionsnamen in `format/contract.md` sind Verweise, keine Leseerlaubnis.

Arbeite in einer Kopie dieses Ordners in einem neuen, leeren Arbeitsordner. Führe ein Zugriffsprotokoll (`ausgabe/ZUGRIFFSPROTOKOLL.md`): Beginn und Ende, Python- und NumPy-Version, jeder ausgeführte Befehl, jede gelesene Datei außerhalb dieses Ordners (Soll: keine außer Python und NumPy). Hast du versehentlich etwas Verbotenes geöffnet, steht das im Protokoll, und du rechnest trotzdem weiter.

<!-- REGELN-ANFANG -->
## 3 Rechenregeln pro Lauf

**3.1 Zuordnung.** `laufliste.tsv` nennt pro Lauf `paarindex` (0 bis 9.039), `arm` (`Q` oder `F`), `block_id`, `musique_id`, `lauf_kennung` und `pfad` des Protokolls. Die Zuordnung wird übernommen, nicht neu hergeleitet. Geprüft wird nur auf Plausibilität: Die `run_id` im Protokollkopf endet auf `:` plus `lauf_kennung`, und die Frage im Protokollkopf (`trace.task.question`) ist gleich dem Feld `question` des MuSiQue-Eintrags mit `id` = `musique_id`. Jeder Verstoß wird als Plausibilitätsbefund des Laufs ausgegeben und ändert nichts an der Rechnung.

**3.2 Format.** Maßgeblich ist `format/contract.md`, Abschnitte „Ausführungs- und Nachrichtenvertrag“, „Journal und bestehendes Instrument“ (nur das Format; die dort genannten Funktionen sind nicht Teil dieses Pakets und werden nicht verwendet) und „Zählung und Kosten“. Ergänzung für die Studienprotokolle: Die Beträge stammen aus der Abrechnung des Anbieters (`cost_source` = `provider`, `price_version` = null), nicht aus einer künstlichen Preistabelle; die Sichten 1 bis 3 der Messabnahme und deren Dateien gibt es hier nicht.

**3.3 Status.** Steht im Protokoll eine `finished`-Nutzlast mit `status` = `completed`, ist der Status `ok`; mit `status` = `model_failed` ist er `model_failure`. Fehlt die `finished`-Nutzlast oder hat sie einen anderen Wert, ist der Status `nicht_nachrechenbar`, mit Grund. Ein solcher Lauf wird gezählt und gemeldet, nicht still ausgelassen.

**3.4 Endantwort.** Das Feld `answer` der `finished`-Nutzlast (bei `model_failure` null).

**3.5 Bewertung.** Zulässige Goldantworten eines Laufs sind `answer` und alle `answer_aliases` des MuSiQue-Eintrags mit `id` = `musique_id` in `daten/musique_ans_v1.0_dev.jsonl` (Regel aus `bewertung/evaluate_v1.0.py`, Zeilen 44 bis 46). Exact Match ist `metric_max_over_ground_truths(compute_exact, endantwort, goldantworten)`, F1 ist `metric_max_over_ground_truths(compute_f1, endantwort, goldantworten)`, jeweils mit den unveränderten Funktionen aus `bewertung/metrics/answer.py` (importierbar mit `bewertung/` im Suchpfad; `bewertung/metrics/metric.py` ist nur ein Platzhalter für die im Original vorhandene Basisklasse, die Funktionen hängen nicht davon ab). Vorab festgelegte Ausnahme ([N0212], [N0596] der Arbeit): Ist der Status nicht `ok` oder ist die Endantwort null, kein String oder nach Entfernen von Leerraum leer (`endantwort.strip() == ""`), sind Exact Match 0 und F1 0. Exact Match wird als Ganzzahl 0 oder 1 ausgegeben, F1 als Gleitkommazahl.

**3.6 Gestartete Modellaufrufe.** Zahl der `event`-Nutzlasten mit `event.kind` = `started`.

**3.7 Bekannte Kosten.** Summe aller Beträge `usage.cost_usd`, die nicht null sind, über alle Ereignisse mit `usage`, exakt mit `decimal.Decimal` aus den Zeichenketten gerechnet (keine Gleitkommazahl), ausgegeben als Dezimalzeichenkette ohne Exponent (`format(summe, "f")`). Unbekannte Beträge werden je eindeutiger `attempt_id` höchstens einmal gezählt: Ein Versuch zählt, wenn mindestens ein Ereignis dieses Versuchs `usage.cost_usd` = null enthält oder ein zugehöriges `started`-Ereignis kein abschließendes `completed` oder `model_failed` mit derselben `attempt_id` hat. Ereignisse ohne `attempt_id` werden jeweils einzeln gezählt, wenn sie eine dieser Bedingungen erfüllen. Wenn beide Bedingungen denselben Versuch betreffen, zählt er einmal. Ein unbekannter Betrag geht nicht als gemessene Null ein und wird nicht geschätzt; die Kostenrechnung beruht auf den bekannten Kosten ([X0542] im Methodenauszug).

## 4 Rechenregeln für Paare und Hauptvergleich

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

## 5 Ausgabeformat

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

## 6 Inhalt dieses Ordners

| Pfad | Inhalt |
|---|---|
| `AUFTRAG.md` | dieser Auftrag |
| `METHODENAUSZUG.md` | Abschnitt 4.4 und Anhang D der Arbeit, wörtlich, ohne Absätze zu ergänzenden Vergleichen und Ergebnissen |
| `laufliste.tsv` | 18.080 Läufe: Paarindex, Arm, Block, MuSiQue-ID, Lauf-Kennung, Pfad |
| `protokolle/Q/*.jsonl`, `protokolle/F/*.jsonl` | die 18.080 Laufprotokolle, unverändert kopiert, Dateiname = Paarindex |
| `daten/musique_ans_v1.0_dev.jsonl` | MuSiQue-Ans v1.0, Dev-Bestand, unverändert |
| `bewertung/metrics/answer.py` | Bewertungsskript von MuSiQue (StonyBrookNLP, Commit 922ac98f19a201998dbdae6d7f2887a5258dbdeb, Datei `metrics/answer.py`), unverändert |
| `bewertung/metrics/metric.py` | Platzhalter für die fehlende Basisklasse, nur für den Import |
| `bewertung/evaluate_v1.0.py` | Auswertungsskript von MuSiQue, gleicher Commit, unverändert; nur Beleg der Aliasregel (Zeilen 44 bis 46), nicht ausführen |
| `plan/PLAN.json` | Studienplan: Blöcke, Ziehung, Armreihenfolge, Seedbasis |
| `plan/ANALYSIS-BINDING.json` | Bindung der Auswertung: B, Seed, Schwellen, Seedregel |
| `plan/METHODEN-UND-INFORMATION.md` | Methoden- und Informationsvertrag (Formeln, PCG64, Quantilrang) |
| `format/contract.md` | Schnittstellenvertrag der Messabnahme, hier als Formatbeschreibung des Laufprotokolls |
| `MANIFEST.sha256` | SHA-256 aller Dateien dieses Ordners außer sich selbst |

## 7 Ablauf und Unklarheiten

1. Prüfe `MANIFEST.sha256` gegen die Dateien, bevor du rechnest, und halte das Ergebnis im Zugriffsprotokoll fest.
2. Schreibe den Code, plausibilisiere ihn an wenigen Läufen von Hand (ohne Sollwerte), dann die volle Rechnung mit beiden Seeds.
3. Schreibe `AUSGABE.sha256` und schließe das Zugriffsprotokoll ab. Gib an die koordinierende Instanz nur den Pfad von `ausgabe/` und die SHA-256 von `AUSGABE.sha256` zurück.
4. Vergleiche nichts und fordere keine Sollwerte an.

Ist eine Regel hier nicht eindeutig: nicht raten und nicht anderswo nachlesen. Wähle die naheliegendste Lesart von Auftrag, Methodenauszug und Plandateien, halte sie in `festlegungen_ohne_plantext` mit Begründung fest und rechne weiter.

Korrekturrunde: höchstens eine, und nur, wenn die einordnende Instanz eine Abweichung als Fehler der Implementierung einordnet. Sie nennt dann die verletzte Regel aus diesem Auftrag oder dem Plantext, nicht den Sollwert. Die erste Ausgabe bleibt unverändert erhalten; die korrigierte kommt nach `ausgabe-korrektur-1/` mit eigener `AUSGABE.sha256`.
