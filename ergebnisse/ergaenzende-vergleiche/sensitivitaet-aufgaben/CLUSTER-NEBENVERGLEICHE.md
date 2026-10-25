<!-- status: entwurf | vorab: VORAB.md (SHA256 bcc2ccd8…, VORAB.md.sha256) | quellen: rows-{R,T,F}.json, ANALYSIS-{R,T,F}.json, intervals.py, final_analysis.py, final_plan.py | codex: GO Runde 2 (Runde 1 NO-GO: Formulierung 4.4/7.4 auf EM begrenzt) | 2026-10-06 -->

# Explorative Cluster-Sensitivität der ergänzenden Vergleiche

**Explorativ und nachträglich.** Nicht Teil der vorab gebundenen Auswertung; ändert sie nicht und ersetzt sie nicht. Ablauf und Ablesung standen vor der Rechnung fest (`VORAB.md`, SHA256 `bcc2ccd8b5210ba5bc63218bb6ea980e3c90d63008894354bc057b48fee2fe5c`, festgehalten 06.10.2026 10:56 MESZ). Gerechnet mit `cluster_nebenvergleiche.py` (Python 3.12.14, numpy 1.26.4 aus `runs/Z38-QSEM-001/provision/python`), Laufzeit rund 3 Minuten, Rohwerte `CLUSTER-NEBENVERGLEICHE.json`. 0 USD, keine Modellaufrufe.

## Kernbefund

Zieht man im Bootstrap ganze Aufgaben oder ganze Fragenfamilien statt einzelner Blöcke, werden die Intervalle gegenüber einem Blockbootstrap 1,3- bis 2,0-mal so breit, bleiben aber bei allen EM-Kennzahlen deutlich schmaler als die Hoeffding-Intervalle der Hauptauswertung (21 bis 69 % ihrer Breite); keine EM-Aussage kippt: F\* liegt über der dichten Gruppe, Q unter F\*, und Runden- wie Ausfallvergleich schließen die Null weiter ein. Nur wenn man die Hoeffding-Ungleichung selbst mit Aufgaben statt Blöcken als unabhängigen Einheiten rechnet, wächst der Radius von 5 auf rund 7,5 Prozentpunkte (Familien rund 23,5), und dann schließen auch F\* gegen dichte Gruppe (−0,79 bis 14,20) und Q gegen F\* im Referenzvergleich (−12,51 bis 2,48) die Null ein. Wiederholungen derselben Aufgabe liefern fast immer dasselbe Ergebnis (Qualitätsunterschied gleich bei 98,6 % der mehrfach gezogenen Aufgaben im Referenzvergleich, 99,4 % im Rundenvergleich, 86 % im Ausfallvergleich mit seiner zufälligen Ausfallrolle).

## 1. Reproduktion (Schritt 1 und 2)

- Zeilendateien: SHA256 gleich `MANIFEST.tsv` und `rows_sha256` in `ANALYSIS-{R,T,F}.json`; je 2.952 Blöcke, Arme vollständig, `task_id` und `family_id` je Block über alle Arme gleich. Code-SHA256 von `intervals.py`, `final_analysis.py`, `final_plan.py` wie in `VORAB.md` §3.
- **Bitgleich reproduziert:** EM- und F1-Mittel aller Arme der drei Panels gegen `report.estimates`; alle Hoeffding-Einträge (Schätzer, Grenzen, Radius, n) aller 13 Qualitätsendpunkte für EM und F1 gegen `report.secondary_quality`; Kostenquotienten R05, R06, R08, T01, F01, F02 als Dezimalzeichenkette gegen `report.descriptive_costs`. Gerundet gegen `08_kanon/GLIEDERUNG.md`: R08 +6,71 (1,71 bis 11,71) bei 0,53; R06 +0,27 (−4,73 bis 5,27) bei 6,66; T01 −0,17 (−5,17 bis 4,83) bei 1,40; Ausfall Q −0,34, F\* −1,46, Differenz +1,12 (−8,88 bis 11,12), Kosten 0,63 und 0,58; F1-Werte ebenso. Alle gleich.
- Einzelcluster-Prüfung gegen direkte Blockatome, gleicher Seed: größte Abweichung 1,7 · 10⁻¹⁵ (R), 8,7 · 10⁻¹⁶ (T), 1,9 · 10⁻¹⁵ (F).
- Seed-Ableitung wie P-Cluster, Prüfung gegen den Primärseed bestanden. Monte-Carlo-Kontrolle mit Primärseed: Grenzen (EM und F1) weichen höchstens 0,055 Prozentpunkte von den abgeleiteten Seeds ab, keine Ablesung ändert sich. Alle Endpunkte Status `ok`, null undefinierte Ziehungen.

## 2. Ergebnisse

Clusterzahlen: Aufgaben 1.663 (R), 1.654 (T), 1.654 (F), Größe Median 2, höchstens 6 bzw. 7; Familien 459, 471, 453, Median 3 bis 4, größte 78, 74, 85 Blöcke, die 1 % größten Familien enthalten 9 bis 10 % der Blöcke. Σm²/n: Aufgaben 2,25 / 2,29 / 2,30, Familien 22,3 / 21,9 / 22,1.

### 2.1 EM-Differenz (Prozentpunkte, 95 %)

| Kennzahl | Punkt | Hoeffding (Hauptauswertung) | Cluster-Bootstrap Aufgabe | Cluster-Bootstrap Familie | Blockbootstrap (Referenz) | Hoeffding über Aufgaben | 0 enthalten (H / A / B / Block / H-Aufg.) |
|---|---:|---:|---:|---:|---:|---:|---|
| R08 F\* − dichte Gruppe | +6,71 | 1,71 bis 11,71 | 4,70 bis 8,76 | 4,45 bis 9,20 | 5,38 bis 8,06 | −0,79 bis 14,20 | nein / nein / nein / nein / **ja** |
| R06 F\* − Einzelaufruf | +0,27 | −4,73 bis 5,27 | −2,28 bis 2,81 | −3,33 bis 3,60 | −1,43 bis 1,98 | −7,22 bis 7,77 | ja / ja / ja / ja / ja |
| R05 Q − F\* (ergänzend) | −5,01 | −10,01 bis −0,01 | −6,79 bis −3,31 | −6,85 bis −3,30 | −6,21 bis −3,85 | −12,51 bis 2,48 | nein / nein / nein / nein / **ja** |
| T01 Rundenwahl − eine Runde | −0,17 | −5,17 bis 4,83 | −1,34 bis 0,98 | −1,28 bis 1,02 | −0,91 bis 0,58 | −7,73 bis 7,39 | ja / ja / ja / ja / ja |
| d_Q (Ausfall bei Q) | −0,34 | −5,34 bis 4,66 | −2,05 bis 1,37 | −2,38 bis 1,58 | −1,64 bis 0,98 | −7,93 bis 7,25 | ja / ja / ja / ja / ja |
| d_F (Ausfall bei F\*) | −1,46 | −6,46 bis 3,54 | −3,36 bis 0,53 | −3,63 bis 0,69 | −2,81 bis −0,11 | −9,05 bis 6,13 | ja / ja / ja / **nein** / ja |
| d_Q − d_F | +1,12 | −8,88 bis 11,12 | −1,05 bis 3,28 | −1,05 bis 3,21 | −0,40 bis 2,68 | −14,06 bis 16,30 | ja / ja / ja / ja / ja |

Breite im Verhältnis: Aufgabencluster zu Hoeffding 0,22 bis 0,51, Familiencluster zu Hoeffding 0,21 bis 0,69; Aufgabencluster zu Blockbootstrap 1,31 bis 1,56, Familiencluster zu Blockbootstrap 1,39 bis 2,03. Hoeffding über Familien (Radius 23,4 bis 23,6, bei d_Q − d_F 47,0 Prozentpunkte) schließt bei jeder Kennzahl die Null ein und ist praktisch uninformativ.

### 2.2 F1-Differenz (nachrangig, Skala 0 bis 1)

| Kennzahl | Punkt | Hoeffding | Aufgabe | Familie | Block | Hoeffding über Aufgaben |
|---|---:|---:|---:|---:|---:|---:|
| R08 | 0,063 | 0,013 bis 0,112 | 0,045 bis 0,080 | 0,043 bis 0,084 | 0,051 bis 0,074 | −0,012 bis 0,137 |
| R06 | 0,016 | −0,034 bis 0,066 | −0,008 bis 0,041 | −0,017 bis 0,051 | 0,000 bis 0,033 (untere Grenze 0,0000168) | −0,058 bis 0,091 |
| R05 | −0,048 | −0,098 bis 0,002 | −0,063 bis −0,032 | −0,066 bis −0,030 | −0,058 bis −0,037 | −0,122 bis 0,027 |
| T01 | −0,002 | −0,052 bis 0,048 | −0,011 bis 0,008 | −0,011 bis 0,008 | −0,008 bis 0,004 | −0,078 bis 0,074 |
| d_Q | −0,004 | −0,054 bis 0,046 | −0,020 bis 0,011 | −0,025 bis 0,014 | −0,016 bis 0,008 | −0,080 bis 0,072 |
| d_F | −0,021 | −0,071 bis 0,029 | −0,038 bis −0,004 | −0,042 bis −0,002 | −0,034 bis −0,009 | −0,097 bis 0,055 |
| d_Q − d_F | 0,017 | −0,083 bis 0,117 | −0,002 bis 0,036 | −0,003 bis 0,038 | 0,003 bis 0,031 | −0,135 bis 0,169 |

### 2.3 Kostenquotienten (nur Einordnung; die Hauptauswertung beschreibt Kosten ohne Intervall)

| Kennzahl | Punkt | Hoeffding | Aufgabe | Familie | Block | 1 enthalten |
|---|---:|---|---:|---:|---:|---|
| R08 F\* / dichte Gruppe | 0,5327 | keins (beschreibend) | 0,5274 bis 0,5380 | 0,5274 bis 0,5380 | 0,5280 bis 0,5374 | nein |
| R06 F\* / Einzelaufruf | 6,6581 | keins | 6,5345 bis 6,7874 | 6,5174 bis 6,8053 | 6,5368 bis 6,7852 | nein |
| R05 Q / F\* | 1,1628 | keins | 1,1460 bis 1,1798 | 1,1428 bis 1,1827 | 1,1485 bis 1,1768 | nein |
| T01 Rundenwahl / eine Runde | 1,3974 | keins | 1,3660 bis 1,4286 | 1,3488 bis 1,4535 | 1,3717 bis 1,4239 | nein |
| F01 Q gestört / sauber | 0,6317 | keins | 0,6244 bis 0,6390 | 0,6239 bis 0,6402 | 0,6249 bis 0,6387 | nein |
| F02 F\* gestört / sauber | 0,5768 | keins | 0,5708 bis 0,5827 | 0,5704 bis 0,5840 | 0,5710 bis 0,5826 | nein |

Breite gegenüber Blockbootstrap: Aufgaben 1,01 bis 1,20, Familien 1,13 bis 2,00 (T01 Familie).

### 2.4 Wiederholungsstruktur (beschreibend)

| | Referenz (R) | Runden (T) | Ausfall (F) |
|---|---:|---:|---:|
| Aufgaben / davon mehrfach gezogen | 1.663 / 868 | 1.654 / 853 | 1.654 / 855 |
| Blöcke in mehrfach gezogenen Aufgaben | 2.157 von 2.952 | 2.151 | 2.153 |
| EM-Kontrast über alle Wiederholungen gleich | R08 98,6 %, R06 99,7 %, R05 99,4 % | T01 99,4 % | d_Q 85,7 %, d_F 87,8 %, Differenz 85,8 % |
| dasselbe, über alle Wiederholungspaare | 98,9 %, 99,8 %, 99,6 % | 99,5 % | 88,3 %, 90,6 %, 87,7 % |
| EM eines Arms über alle Wiederholungen gleich | S, S-k 100 %; F 99,7 %; Q 99,5 %; D 99,0 %; Z 84,8 % | Q-TF 99,9 %; Q-ST 99,5 % | Fc 99,8 %; Qc 99,3 %; Ff 88,1 %; Qf 85,7 % |

Lesart: Arme bei Temperatur 0 ohne Zufallselement wiederholen sich fast exakt. Niedriger liegen nur Arme mit Zufall je Ziehung: Z (Zufallsauswahl) und die gestörten Arme Qf und Ff (zufällige Ausfallrolle).

## 3. Was sich an den Aussagen ändert

- **EM, Cluster-Bootstrap über Aufgaben oder Familien:** keine Änderung gegenüber den Hoeffding-Intervallen. R08 und R05 schließen die Null weiter aus, R06, T01, d_Q, d_F und d_Q − d_F schließen sie weiter ein. Nach der Vorab-Regel (§7) ist das robust gegenüber dieser Abhängigkeitsannahme.
- **EM, Hoeffding über Aufgaben (analytisch):** Zwei Aussagen kippen. Der Vorsprung von F\* vor der dichten Gruppe (R08) und der Rückstand von Q hinter F\* im Referenzvergleich (R05) sind dann nicht mehr abgesichert. Über Familien kippen dieselben zwei, alle Intervalle sind dort zwischen rund 47 und 94 Prozentpunkten breit.
- **EM, Blockbootstrap (Referenz):** d_F schließt dort die Null aus (−2,81 bis −0,11); mit Aufgaben- oder Familienclustern nicht mehr. Das ist ein Methodeneffekt des Bootstraps, kein Befund der Hauptauswertung.
- **F1:** Unter beiden Cluster-Bootstraps schließen R05 und d_F die Null aus, anders als unter Hoeffding (dort enthalten). R08 bleibt ausgeschlossen; Hoeffding über Aufgaben kippt R08 auch bei F1.
- **Drei-Punkte-Marke:** Die Cluster-Bootstrap-Intervalle von T01, d_Q und R06 (Aufgaben) enthalten weder −3 noch +3 Prozentpunkte. Das ist kein vorab festgelegtes Verfahren dieser Vergleiche, und die Arbeit entscheidet sie nicht nach der Drei-Punkte-Schwelle. Daraus folgt kein Gleichheitsnachweis.
- **Kosten:** Kein Intervall enthält 1; Richtung und Größenordnung der beschriebenen Quotienten bleiben unter Clusterung gleich. Weil Kostenintervalle für diese Vergleiche vor der abschließenden Bewertung wegen zu geringer Genauigkeit verworfen wurden, begründet das keine abgesicherte Kostenrichtung.
- **Lesart insgesamt:** Die Hoeffding-Intervalle sind breiter als jedes Bootstrapintervall, weil sie nur den Wertebereich und nicht die Streuung nutzen. Ihre Überdeckung setzt aber unabhängige Blöcke voraus. Der Clusterbootstrap stützt die Aussagen, ist aber selbst ein Näherungsverfahren; die verteilungsfreie Grenze mit Aufgaben als Einheiten stützt R08 und R05 nicht. Die Aussagen R08 und R05 hängen damit an einer von zwei Annahmen: unabhängige Blöcke oder ein Bootstrap, der die Unsicherheit bei Aufgabenclustern trifft.

## 4. Grenzen

- Nachträglich und explorativ; die Hauptauswertung (Hoeffding, unabhängige Blöcke) bleibt maßgeblich.
- Clusterung über Aufgaben bzw. Familien erfasst keine zeitlich gemeinsamen Anbieterzustände und nicht den Wechsel von sequenzieller zu paralleler Erhebung im Referenzvergleich (dazu `04_ergebnisse/nacharbeit-2026-10-04/K-FENSTER-ERGEBNIS.md`).
- Die Bootstrapintervalle sind studentisierte Näherungen; ihre Überdeckung bei diesen diskreten Kontrasten ist nicht geprüft. Für die Kostenendpunkte der ergänzenden Vergleiche hatte die Simulation vor der abschließenden Bewertung zu geringe Genauigkeit gezeigt.
- Hoeffding über Cluster ist bedingt auf die beobachteten Clustergrößen und setzt unabhängige Cluster voraus.
- Familien sind über gemeinsame Teilfragen definiert; andere gemeinsame Kontexte sind nicht berücksichtigt. Die 1 % größten Familien tragen rund 10 % der Blöcke, das schwächt die Studentisierung bei Familien.
- Weder Clusterbootstrap noch Hoeffding über Cluster begründen eine Aussage über Aufgaben außerhalb des Dev-Bestands.
- R01 bis R04, R07 und R09 wurden nicht gerechnet.

## 5. Formulierungsvorschläge

**4.4 (ersetzt in R-02 den Satz „Eine Sensitivität mit gebündelten Aufgaben gibt es nur für den Hauptvergleich“):**
„Eine nachträgliche, explorative Sensitivitätsanalyse zieht im Bootstrap ganze Aufgaben oder Fragenfamilien; ihre Intervalle sind bei allen drei Vergleichen schmaler als die Hoeffding-Intervalle und ändern keine Aussage zum Exact Match. Beim ergänzenden F1 schließen sie in zwei Fällen die Null aus, die das Hoeffding-Intervall einschließt (Q gegen F\* im Referenzvergleich, Ausfalländerung von F\*); als Befund wertet die Arbeit das nicht, weil dieses Verfahren nicht vorab festgelegt war. Wendet man die Hoeffding-Ungleichung dagegen auf Aufgaben statt auf Blöcke an, wächst der Radius auf rund 7,5 Prozentpunkte, und was daraus folgt, bewertet Abschnitt~\ref{sec:7-4}.“

**6.4 (nach den Zahlen zu R08 und R06):**
„Zieht der Bootstrap ganze Aufgaben statt einzelner Blöcke, liegt der Vorsprung von F\* vor der dichten Gruppe zwischen 4,70 und 8,76 Prozentpunkten, mit ganzen Fragenfamilien zwischen 4,45 und 9,20; gegenüber dem Einzelaufruf bleibt die Null im Intervall. Diese Rechnung kam nach der Erhebung hinzu und ersetzt die Hoeffding-Intervalle nicht.“

**6.5 (nach dem Intervall −5,17 bis 4,83):**
„Auch wenn ganze Aufgaben oder Familien gezogen werden, enthält das Intervall die Null (−1,34 bis 0,98 bzw. −1,28 bis 1,02 Prozentpunkte); als Nachweis gleicher Qualität liest die Arbeit das nicht, weil dieses Verfahren für den Rundenvergleich nicht vorab festgelegt war.“

**6.6 (nach dem Intervall −8,88 bis 11,12):**
„Mit Aufgaben oder Familien als Ziehungseinheit liegt die Differenz zwischen −1,05 und 3,28 bzw. −1,05 und 3,21 Prozentpunkten und schließt die Null weiterhin ein. Wiederholungen derselben Aufgabe fallen hier seltener gleich aus als in den anderen Vergleichen (rund 86 %), weil die ausfallende Rolle je Ziehung zufällig bestimmt wird.“

**7.4 (Absatz zur Analyseeinheit, ergänzend):**
„Auch die Hoeffding-Intervalle der ergänzenden Vergleiche setzen unabhängige Blöcke voraus. Dort kommen Aufgaben im Mittel 1,8-mal vor, und bei 98,6 % (Referenz) bzw. 99,4 % (Runden) der mehrfach gezogenen Aufgaben fällt der Exact-Match-Unterschied bei jeder Wiederholung gleich aus. Ein Bootstrap über ganze Aufgaben oder Familien verbreitert die Intervalle gegenüber einem Bootstrap über Blöcke um das 1,3- bis 2,0-Fache, bleibt aber innerhalb der Hoeffding-Intervalle und ändert keine Aussage zum Exact Match; beim ergänzenden F1 schließt es für Q gegen F\* im Referenzvergleich und für die Ausfalländerung von F\* die Null aus, die Hoeffding einschließt. Rechnet man die Hoeffding-Ungleichung selbst mit Aufgaben als Einheiten, sichern die Intervalle weder den Vorsprung von F\* vor der dichten Gruppe noch den Rückstand von Q hinter F\* im Referenzvergleich ab. Diese beiden Aussagen gelten deshalb nur unter einer von zwei Annahmen: Die Blöcke sind unabhängig, oder der Bootstrap bildet die Unsicherheit bei gebündelten Aufgaben richtig ab; geprüft ist keine von beiden.“
