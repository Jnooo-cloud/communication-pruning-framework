<!-- status: entwurf | quellen: 04_ergebnisse/daten/collected/rows-{R,T,F}.json, 04_ergebnisse/belege/RTF/ANALYSIS-{R,T,F}.json, RTF/DESIGN.md, RTF/log.md, Rohantworten Z53 live/blocks im alten Repo (nur lesend) | codex: GO Runde 3 (Runden 1 und 2 NO-GO) | 2026-10-04 -->

# K-Fenster-Auswertung der Z53-Nebenpanels

**Kurzbefund.** Bei K = 4 (tatsächlich gewählt) gibt es im parallel gelaufenen Z53-Abschnitt 0 Paare in R-Rest, 3 in T und 3 in F; bei K = 6 (ursprünglich vorgesehen) 1, 5 und 4. Ohne die betroffenen Blöcke ändern sich alle Kostenquotienten um höchstens 0,06 % ihres Werts (größte relative Änderung: R02 bei K = 6, 1,980224 zu 1,979188; bei K = 4 höchstens 0,02 %, F02 0,576763 zu 0,576657). Die mittleren Kostenänderungen F03 bis F05 verschieben sich um höchstens 0,00000062 USD. Die Auflage aus dem Z53-Design ist damit offline erfüllt; keine Kostenaussage ändert sich.

Skript: `k_fenster.py` (reproduzierbar, 0 USD, keine API-Aufrufe). Rohwerte: `K-FENSTER-ERGEBNIS.json`.

## Auflage und Definition

Das Z53-Design verlangt: „Paare gleicher task_id innerhalb eines Fensters von K aufeinanderfolgenden Blöcken (R-Rest 1, T 5, F 4 bei K=6) mit Kostenquotienten mit/ohne diese Paare“ (`04_ergebnisse/belege/RTF/DESIGN.md`, letzter Absatz). Gestartet wurde mit K = 4 statt 6 (`RTF/log.md`, 01.10., 19:20).

Festgelegt wie in der Nachrechnung von Codex (`08_kanon/beitragsanalyse/runde3/CODEX.md`):

- Betrachtet wird nur der parallel gelaufene Abschnitt: R draw_index 2183 bis 2951 („R-Rest“), T und F vollständig.
- Paar = zwei Blöcke i < j mit gleicher `task_id` und Indexabstand j − i < K.
- Sensitivität: Jeder Block, der in einem Paar vorkommt, entfällt mit allen Armen. Neu gerechnet wird auf dem ganzen Panel ohne diese Blöcke, beim R-Panel also einschließlich des sequenziellen Teils 0 bis 2182.
- Quotient wie in `ANALYSIS-*.json`: Verhältnis der Kostenmittel, Decimal mit 50 Stellen. Für F03 bis F05 (mittlere gepaarte Kostenänderung) entsprechend der Mittelwert der Änderung.

Prüfung vorab: SHA256 der drei `rows`-Dateien stimmt mit `MANIFEST.tsv` überein; alle Vollpanel-Werte reproduzieren die `estimate`-Felder der `ANALYSIS`-Dateien auf 40 Stellen.

## Paare

| Panel | K = 4 | K = 6 | betroffene Blöcke (K = 4 / 6) |
|---|---:|---:|---:|
| R-Rest (769 Blöcke) | 0 | 1 | 0 / 2 |
| T (2.952) | 3 | 5 | 6 / 10 |
| F (2.952) | 3 | 4 | 6 / 8 |

Jedes Paar besteht aus genau zwei Blöcken; kein Block liegt in zwei Paaren. Die Zahlen bei K = 6 stimmen mit den im Design angekündigten (1/5/4) überein.

Paare im Einzelnen (draw_index):

- R, nur K = 6: 2245/2249.
- T: 1290/1292, 1531/1534, 2463/2466; zusätzlich bei K = 6: 2262/2266, 2321/2326.
- F: 750/753, 2180/2181, 2663/2664; zusätzlich bei K = 6: 2382/2387.

## Kostenquotienten mit und ohne betroffene Blöcke

R-Panel (Z53-Ziehung mit dem alten S-k-Arm; die Z54-Korrektur von S-k ist hier nicht eingerechnet). Bei K = 4 sind alle neun Quotienten unverändert.

| Endpunkt | Arme | vollständig | ohne, K = 6 |
|---|---|---:|---:|
| R01 | Q/S | 7,741757 | 7,739147 |
| R02 | Q/S-k | 1,980224 | 1,979188 |
| R03 | Q/D | 0,619404 | 0,619143 |
| R04 | Q/Z | 0,954396 | 0,954234 |
| R05 | Q/F | 1,162766 | 1,162577 |
| R06 | F/S | 6,658050 | 6,656890 |
| R07 | F/S-k | 1,703028 | 1,702414 |
| R08 | F/D | 0,532699 | 0,532560 |
| R09 | F/Z | 0,820798 | 0,820792 |

T- und F-Panel:

| Endpunkt | Arme | vollständig | ohne, K = 4 | ohne, K = 6 |
|---|---|---:|---:|---:|
| T01 | Q-ST/Q-TF | 1,397403 | 1,397312 | 1,397210 |
| F01 | Qf/Qc | 0,631746 | 0,631699 | 0,631774 |
| F02 | Ff/Fc | 0,576763 | 0,576657 | 0,576548 |
| F03 | H_Q, mittlere Änderung in USD | −0,00055514 | −0,00055540 | −0,00055538 |
| F04 | H_F, mittlere Änderung in USD | −0,00055014 | −0,00055048 | −0,00055075 |
| F05 | H_Q − H_F in USD | −0,00000500 | −0,00000492 | −0,00000462 |

Ergänzend beschreibend: Die EM-Differenzen der Quotienten-Endpunkte verschieben sich um höchstens rund 0,07 Prozentpunkte (F02 bei K = 6: −1,457 zu −1,529 pp; R06/R07 bei K = 6: +0,271 zu +0,339 pp). Werte je Endpunkt in der JSON-Datei. Die Qualitätsauswertung von R/T/F (marginale Hoeffding-Intervalle) wurde nicht neu gerechnet.

## Tatsächliche Zeitlage und Cache (beschreibend)

Die Indexprüfung allein belegt keine zeitliche Überlappung (Codex). Deshalb zusätzlich aus dem alten Repo, nur lesend: Bearbeitungsintervall je Block aus `live/events.jsonl` (letzter `complete`-Eintrag, Intervall [t − seconds, t]); Cache-Anteil = Summe `cached_tokens` / Summe `prompt_tokens` über alle gewerteten Calls des Blocks, einschließlich übernommener Antworten in `provider-*.a1`. Alle Paarblöcke liefen im ersten Versuch ohne Fortsetzung. Die protokollierten Dauern sind auf Zehntelsekunden gerundet; Abstände unter 0,1 s bedeuten deshalb nur „unmittelbar aufeinander“.

- **Überlappung:** 6 der 10 Paare überlappen zeitlich (F 750/753, 2180/2181, 2663/2664 mit 6,7 bis 14,4 s; T 1531/1534, 2463/2466, 2262/2266 mit 0,5 bis 4,7 s). Bei K = 4 sind das alle drei F-Paare und zwei der drei T-Paare.
- **Ohne Überlappung:** R 2245/2249, T 1290/1292 und T 2321/2326 folgen mit weniger als 0,1 s Abstand aufeinander; F 2382/2387 mit 3,8 s.
- **Cache:** Im Block mit dem höheren Index liegt der Cache-Anteil in 9 von 10 Paaren höher als im früheren (Ausnahme F 2663/2664, 39,2 % zu 22,5 %, die mit 14,4 s am stärksten überlappen) und in 9 von 10 über dem Mittel des jeweiligen Z53-Abschnitts (R 19,8 %, T 18,1 %, F 14,6 %; Ausnahme F 750/753 mit 10,5 %). Beispiele: T 2463/2466 21,8 % zu 87,4 %, F 2180/2181 22,4 % zu 50,6 %.

Das ist mit Cache-Wiederverwendung zwischen nahen Wiederholungen derselben Aufgabe vereinbar, aber kein Nachweis: Der Anbieter meldet nur Mengen, nicht die Herkunft des Cache-Eintrags, und Cache tritt auch ohne Wiederholung in rund 78 bis 85 % der Blöcke auf. Belegt ist nur, dass das Entfernen der betroffenen Blöcke die ausgewiesenen Kostenwerte kaum ändert (siehe Tabellen); über die Größe eines Cache-Effekts insgesamt und über die Qualitätsintervalle sagt das nichts.

## Grenzen

- Indexabstand ist ein Ersatzmaß für Gleichzeitigkeit; die Worker vergaben Blöcke in Planreihenfolge, aber Blockdauern schwanken. Die Intervallprüfung ergänzt das nur für die gefundenen Paare, nicht für weiter auseinanderliegende Wiederholungen. Das Intervall aus `events.jsonl` misst die Bearbeitung durch den Worker, nicht die Rechenzeit beim Anbieter.
- Fortgesetzte Blöcke (z. B. F 515 bis 519, R 2185/2186): Cache-Anteile über alle gewerteten Antworten je `attempt_id` (frischer Ordner vor übernommenem, wie `z53_fast._pick`); das Bearbeitungsintervall erfasst nur den letzten Versuch. Kein Paarblock ist betroffen.
- Wiederholungen außerhalb des Fensters (über das ganze Panel verteilt) sind nicht Gegenstand dieser Auflage.
- Beschreibende Sensitivität, kein Test; die vorab gebundene Auswertung bleibt unverändert.

## Folgerung für die Arbeit

Die im Z53-Design verlangte Offenlegung kann wörtlich erfolgen: Bei tatsächlich gewähltem K = 4 betreffen nahe Wiederholungen 0 (R-Rest), 3 (T) und 3 (F) Paare; ohne sie verändern sich die Kostenquotienten um höchstens 0,02 % (T01 1,397403 zu 1,397312; F01 0,631746 zu 0,631699; F02 0,576763 zu 0,576657). Bei K = 6 bleibt das Bild gleich.
