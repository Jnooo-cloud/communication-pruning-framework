# Methoden- und Informationsvertrag: konkreter Entwurf

16. September 2026; FF2a–c / RQ-6, gemeinsames Paket `A-20260916T080520Z-ea309d`, Ausgangsrevision `eab751efc932d4218c7a60d9958043787ecd2e55`. **Planung, keine Methodenabnahme.** V4/V5 werden konkretisiert; Datenweg und Ressourcen stehen in den benachbarten Unterlagen. Alle nachfolgend mit **M** bezeichneten Festlegungen sind eigene neue Vorschläge, weder Literaturvorgaben noch durch D-059 bereits angenommen. Keine Simulation, Codeänderung, neue Datenrechnung oder Inhaltsexposition durchgeführt.

## 1. Bestehender Vertrag und neuer Entscheidungsgegenstand

D-049/D-050/D-052/D-059 bleiben gültig: feste Regeln im bereinigten Dev-Bestand; primär höchstens 3 Prozentpunkte Qualitätsverlust und mindestens 10 % Kostensenkung; bekannte F01-Fehler mit tatsächlichen Kosten; `h_D=0,015`, `h_rho=0,05`, K3*, `B=19.999`, `N=10.000`. Z33 bleibt negativ; Z34 belegt ausschließlich begrenzte numerische Stabilität. Bedingte Planung: `m=9.040`, `n_R=n_T=n_F=2.952`; SV-1 bis SV-3 sind noch nicht angenommen.

**Zur Entscheidung M:** die folgenden endlichen Stressverteilungen, Informationskriterien und Kontrollfolgen als Grundlage des einmaligen Schlusschecks annehmen. Sie benötigen keine neue reale Informationsstichprobe. Alternative: diesen begrenzten Annahmebereich ablehnen und einmalig den konkret nicht abgedeckten Kostenmechanismus samt erforderlicher Beobachtung benennen; daraus folgt ein eigener Daten-/Kostenplan, keine automatische Panelerweiterung. Ein bestandenes künstliches Raster beweist keine universelle Gültigkeit.

## 2. Vollständige Endpunktmatrix

`E` bezeichnet das Erwartungsmittel; `L/U` die untere/obere Grenze. Q/F bedeuten die eingefrorenen räumlichen Regeln; `f/c` gestört/sauber. Jede Zeile wird vollständig berichtet, einschließlich offener oder ungünstiger Befunde.

| ID | Zielgröße | Richtungen und erlaubte Aussage |
|---|---|---|
| P-D | `delta=E(EM_Q−EM_F)` | `L_D>−0,03`: Qualität ausreichend erhalten; `U_D<0`: Verlust; `U_D<−0,03`: Verlust jenseits der Marge |
| P-C | `rho=E(C_Q)/E(C_F)` | `U_rho<0,90`: mindestens 10 % Einsparung; `L_rho>0,90`: weniger Einsparung; `L_rho>1`: Mehrkosten |
| R01 | `E(C_Q)/E(C_S)` | L und U |
| R02 | `E(C_Q)/E(C_S-k)` | L und U |
| R03 | `E(C_Q)/E(C_D)` | L und U |
| R04 | `E(C_Q)/E(C_Z)` | L und U |
| R05 | `E(C_Q)/E(C_F)` im Referenzpanel | L und U; ergänzende Wiederholung, kein Ersatz für P-C |
| R06 | `E(C_F)/E(C_S)` | L und U |
| R07 | `E(C_F)/E(C_S-k)` | L und U |
| R08 | `E(C_F)/E(C_D)` | L und U |
| R09 | `E(C_F)/E(C_Z)` | L und U |
| T01 | `E(C_Q-ST)/E(C_Q-TF)` | L und U |
| F01 | `E(C_Qf)/E(C_Qc)` | L und U; ID nicht mit Modellfehler F-01 verwechseln |
| F02 | `E(C_Ff)/E(C_Fc)` | L und U |
| F03 | `H_Q=E(C_Qf−C_Qc)` | L und U, USD pro Block |
| F04 | `H_F=E(C_Ff−C_Fc)` | L und U, USD pro Block |
| F05 | `H_diff=H_Q−H_F` | L und U, USD pro Block |

Für Nebenquotienten bedeutet `U<1` niedrigere, `L>1` höhere Kosten; für absolute Änderungen `U<0` Senkung, `L>0` Erhöhung. Dazwischen bleibt die Richtung offen. **Der primäre 3-pp-/10-%-Vertrag wird nicht auf Nebenarme übertragen.** Die positive Hauptaussage verlangt beide primären Bedingungen strikt; Gegenrichtungen sind einzelne Aussagen, kein zusätzlicher globaler Negativtest.

Nebenqualität: dieselben neun Referenzpaare, Q-ST/Q-TF sowie `d_Q=E(EM_Qf−EM_Qc)`, `d_F` und `d_Q−d_F`: **13 Kontraste**, jeweils beide Richtungen. Der bestehende Hoeffding-Vorschlag verwendet Bereiche [−1,1], beim Änderungsunterschied [−2,2]; bei 2.952 Blöcken höchstens ±5 bzw. ±10 pp. F1 ergänzt dieselbe Blocklogik. Marginale Bereiche begründen keinen Gesamtgewinner; ihre analytische Gültigkeit wird nicht durch Monte-Carlo-Erfolg ersetzt.

## 3. M-I: brauchbare Information zusätzlich zur Kalibrierung

Pro Endpunkt und regulärem Fall: `a_L=|Schätzer−L|`, `a_U=|U−Schätzer|`; gesperrte/uninformative Ausgaben erhalten unendliche Abstände. Keine Entfernung solcher Datensätze. Gemeinsamer Vorschlag: obere zweiseitige 95-%-Wilson-Grenze ihres Anteils **höchstens 1 %**; in jeder Richtung 90-%-Quantil **≤1,25h**. Quantile: Ordnungsrang `ceil(pN)`. Dies begrenzt häufige Ausreißer; eine seltene unendliche Ausgabe bleibt sichtbar. Die 1-%-/90-%-/1,25-Werte sind technische Autorenwahl, keine bewiesenen Optimalwerte.

**Genau eine Medianregel vor Ausführung wählen:** M-Ia verlangt Medianabstand **≤h**. Die koordinierend empfohlene Alternative **M-Ib** behält h als Ziel und akzeptiert eine feste Mediantoleranz bis **1,01h**. Anlass aus der Originalplanung, nicht aus neuen Rechenergebnissen: Bei m=9.040 ist der normal angenäherte Qualitätsabstand mit rund 0,014999 nur minimal kleiner als 0,015. Bootstrapbreiten und ihre Monte-Carlo-Quantile können davon abweichen. M-Ib verringert die unmittelbare Empfindlichkeit an dieser Planungsgrenze; die 1 % sind eine eigene pragmatische Wahl, **keine bewiesene Monte-Carlo-Fehlergrenze**. Ein Überschreiten von h kann auch eine echte endliche Bootstrapbreite widerspiegeln und wird stets berichtet. M-Ib akzeptiert damit beim primären Median höchstens **1,515 pp statt 1,5 pp** beziehungsweise **0,0505 statt 0,05**, bei Nebenquotienten **10,1 % statt 10 %** relativen Abstand. Gleiche Abnahmepräzision wird nicht behauptet. K3*, 90-%-Quantil, Uninformativitätsgrenze, n/B/Seeds und normative 3-pp-/10-%-Grenzen bleiben in beiden Varianten identisch. Kein Wechsel von M-Ia zu M-Ib nach Ausführung; keine Bestehensgarantie durch die kleine Toleranz.

| Endpunkte | Vorgeschlagenes h im künstlichen Check | Zweck und Einheit |
|---|---|---|
| P-D / P-C | bestehend 0,015 / 0,05 | absolute Qualitäts- bzw. Quotienteneinheiten, beide Richtungen |
| R01–R09, T01, F01/F02 | `0,10*rho_wahr` | 10 % **relativer Grenzabstand**, z. B. bei Verhältnis 4 ein Abstand 0,4; kein neues Einsparziel |
| F03 | `0,10*E(C_Qc)` | absolute USD, bezogen auf saubere Q-Kosten |
| F04 | `0,10*E(C_Fc)` | absolute USD, bezogen auf saubere F-Kosten |
| F05 | `0,10*[E(C_Qc)+E(C_Fc)]` | absolute USD; doppelte Auflösung gegenüber 10 % des mittleren sauberen Arms |

Damit wird keine relative Genauigkeit an einem möglicherweise nullnahen H verlangt. Reale Grenzen werden in Originaleinheiten berichtet, zusätzlich relativ zu den beobachteten Referenzkosten; diese Beschreibung erzeugt kein Ersatzintervall. Die Kostenauflösung ist bewusst grob: kleinere Unterschiede können offenbleiben. Wer bei Nebenquotienten ±0,05 **absolute** Quotienteneinheiten benötigt, muss diese einmalige alternative Informationsanforderung vor Ausführung ausdrücklich wählen; sie ist nicht durch die Qualitätsplanung finanziert oder erfüllt.

M-I gilt für sämtliche regulären Nebenfälle und primär R1–R8/P1/P2. P3 bleibt eine ausdrücklich außerhalb des gewählten Qualitäts-Varianzszenarios liegende Sensitivität: Nur sein Qualitäts-Median und Qualitäts-90-%-Quantil werden ohne Breiten-Bestehensquote berichtet; das 1,5-pp-Ziel wird dort nicht behauptet. P3-Kosten-M-I, die Uninformativitätsgrenze beider Endpunkte und sämtliche K3*-Ereignisse bleiben verpflichtend. Kein nachträgliches Umbenennen weiterer ungünstiger Fälle in Sensitivitäten. Verfehlt ein beanspruchter Fall M-I, ist die entsprechende Auflösung nicht abgenommen, auch bei bestandenem K3*.

## 4. M-S: endliche Verteilungen und bekannte Wahrheiten

### Primär: Originale plus drei begründete Ergänzungen

R1–R8 aus Z32 §6 bleiben bytegebunden erhalten, beim angenommenen m. P1–P3 nutzen dieselbe Kostenformel `B=bZ`, `A=rho*bZV(1+0,3D)/(1+0,3delta)`, `b=0,0012 USD`, ursprüngliches Z und schiefes V aus R5. Für `q=P(D≠0)` gilt `P(D=±1)=(q±delta)/2`. Z42 §2 nennt als größte Pilot-Hop-Sicht `q_Hop2=9/34`; Z40 §4 verdoppelt dies zur Planungsvarianz `v_D=9/17`. **Das ist nicht die beobachtete gesamte Pilot-Unterschiedsquote.** Weil `Var(D)=q−delta²`, setzen P1/P2 künstlich `q=9/17+delta²`, sodass ihre Varianz genau dem vorsichtigen Planungsszenario entspricht.

| Fall | q | delta | rho | Grund |
|---|---:|---:|---:|---|
| P1 | `9/17+0,03²` | −0,03 | 0,90 | vorsichtige Planungsvarianz, mit R5-Kostenschiefe |
| P2 | `9/17+0,06²` | −0,06 | 1,10 | informativer Nachteil; zusätzlich zufällige Paarreihenfolge und Kostenfaktor 1 erster / 0,5 zweiter Arm |
| P3 | 1 | 0 | 0,90 | erhaltene harte Qualitätssensitivität `Var(D)=1` |

Die Reihenfolge in P2 ist unabhängig von D/Z/V; beide Kostenmittel erhalten denselben erwarteten Faktor 0,75, daher bleibt rho exakt. Das halbierte Kostenniveau ist ein eigener Stresswert, keine Schätzung der beobachteten Cachewirkung.

### Nebenarme: vollständige Vektoren, keine erfundenen Pilotvarianzen

Grundform `C_j=(b/5)*K_j*Z*U_j*T_j*M_j*e_j`. **b ist ein fünf Aufrufe umfassender Armanker**, kein Aufrufpreis. Die Skalierung stammt aus dem künstlichen Z32-Fall; absolute USD sind keine Kostenprognose. Bern(p) ist eine 0/1-Ziehung mit Wahrscheinlichkeit p. Soweit nicht ausdrücklich gekoppelt, sind alle Zufallsgrößen unabhängig; pro neuem Block wird frisch gezogen.

| Template / Armreihenfolge | K: reguläre Aufrufzahlen und Kopplung |
|---|---|
| R: S, S-k, D, Z, Q, F | `(1,5,9,5+2Bern(4/7),5+2Bern(1/2),5)`; Q-Häufigkeit reine Stressannahme |
| T1/T2: Q-ST, Q-TF | gemeinsames `k=2+Bern(1/2)`; `(k[1+Bern(1/2)]+1, k*t+1)`, festes t=1 bzw.2. Beide Templates bleiben erhalten; Q-TF wird nicht zufällig zur adaptiven Regel. |
| F: Qc,Qf,Fc,Ff | gemeinsames `k=2+Bern(1/2)`; `(2k+1,2k−1,5,3)` |

Je Template genau S1–S7, insgesamt 28 Nebengruppen. Standard: Z=0,75/1,25, U_j=0,8/1,2, jeweils gleichwahrscheinlich, T=M=e=1.

| Regime | Vollständige Abweichung vom Standard | Risiko |
|---|---|---|
| S1 | keine | gewöhnliche gekoppelte Kosten |
| S2 | je Arm T∈{1;16}, P(T=16)=0,01, anschließend durch E(T) normiert; F zusätzlich e_Qc=1, e_Qf=1,5, e_Fc=1, e_Ff=0,75 | selten hohe Kosten; unterschiedliche absolute Ausfalländerungen |
| S3 | je Arm T∈{1;64}, P(T=64)=0,001, anschließend durch E(T) normiert; F: e_Qc=1, e_Qf=0,75, e_Fc=1, e_Ff=1,5 | noch seltenere Extreme; Gegenrichtung des Änderungsunterschieds |
| S4 | U_j=0,05/1,95 gleichwahrscheinlich | kleine, stark variable Referenzkosten |
| S5 | Z=0,1/1,9; U_j=0,99/1,01, jeweils gleichwahrscheinlich | starke gemeinsame Schwankung innerhalb des Blocks |
| S6 | je Arm unabhängig mit Wahrscheinlichkeit 0,10 K_j durch 1 ersetzen | früher bezahlter F01-Abbruch; Kosten bleiben erhalten, keine Nullkostenimputation |
| S7 | uniforme zufällige Permutation aller Arme; M=1 für erste, sonst 0,5 | positionsabhängiger Cache-/Rabatteffekt innerhalb des Blocks |

Alle Kosten sind nichtnegativ; sämtliche Atome und Wahrscheinlichkeiten folgen aus diesen endlichen Produkten. Vor Monte Carlo werden sie rational abgeleitet und separat geprüft. Exakte Wahrheiten: `mu_j=sum_s p_s C_js`; Quotienten `mu_a/mu_b`; H aus denselben vier Mitteln. Z/U/normiertes T haben Mittel eins; S6 verändert E(K) zu `0,9E(K)+0,1`; S7 multipliziert jedes Mittel bei a Armen mit `(a+1)/(2a)`. Kein empirisches Mittel wird zum vermeintlich bekannten Wahrheitswert.

## 5. M-F: Fallliste, Kalibrierung und Kontrollen

K3* unverändert: für jede reguläre Fehlrate obere zweiseitige 95-%-Wilson-Grenze ≤0,04; exakter einseitiger Binomial-p-Wert gegen 0,025; eine Holm-Familie bei 0,025. Fehlereignisse je Endpunkt `L>wahr` und `U<wahr`; keine simultane Absicherung realer Nebenresultate daraus ableiten.

| Familie | Vollständige Ereignislogik | Anzahl |
|---|---|---:|
| Primär R1–R8/P1–P3 | 11×4 Richtungen; gemeinsame falsche Effizienzkonjunktion für R1–R7 und P1–P3 | 54 |
| R-S1…S7 | 7×9×2 | 126 |
| T1/T2-S1…S7 | 2×7×1×2 | 28 |
| F-S1…S7 | 7×5×2 | 70 |
| **Gesamt** | **39 reguläre Gruppen, je N=10.000; B=19.999** | **278** |

Vor Ausführung: lexikografische IDs `Template/Regime/Endpunkt/L|U|Joint`, vollständig ausgeschriebene Ereignisliste; gleiche p-Werte nach dieser ID ordnen. Seedbasis-Vorschlag `SV-METHODEN-2026-09-16-v1`; SHA256 über UTF-8 `Basis|Fall|n|Wiederholung|data` bzw. `bootstrap`, erste 16 Bytes als Little-Endian-Ganzzahl für PCG64, Wiederholungen 0–9.999. Implementierung/Runtime, unabhängige Datenströme, Quantilrang `ceil(pB)`, Sperren und wiederherstellbare Quellen werden vor Rechnung gebunden.

Kontrollen getrennt, je n=20 direkte Zeilen: D durchgehend 0 → Qualität gesperrt; B durchgehend 0 → Quotient undefiniert; B=(1,0,…,0), A durchgehend 1 → Nennersperre; B abwechselnd 1/2, A=2B → Nullstreuung des Quotienten; Viererzeilen durchgehend (1,2,3,4) → Nullstreuung sämtlicher H. Zusätzlich je Schätzertyp eine vorgegebene Bootstrapreplikation nur aus Zeile1 → undefinierter Pivot muss erhalten bleiben und sperren. Hierfür D/H abwechselnd −1/+1, beim Quotienten A=1 und B abwechselnd 1/2: gültige Originalstreuung, entartete Replikation. Kostenwerte in USD; keine empirischen Kostenannahmen. Uninformative Bereiche bleiben Qualität [−1,1], Quotient [0,∞], H ohne harte Schranke (−∞,∞).

Zusätzlich genau fünf Abhängigkeitskontrollen à 2.000 Datensätze: erhaltene globale Qualitätsstörung G1 aus Z32 beim angenommenen m; R/T1/T2/F mit S1 und einem **datensatzweit gemeinsamen** S=±1 (je 1/2), Kostenmultiplikator je Arm `1+0,5*S*(−1)^j`, j=1…Armzahl. Fall-IDs `G-Q`, `G-R`, `G-T1`, `G-T2`, `G-F`, dieselbe SHA256-/PCG64-Regel, getrennte data/bootstrap-Ströme, Wiederholungen 0–1.999 und B=19.999; n=m für G-Q, sonst jeweiliges Neben-n. Die n=20-Sollfälle davor sind vollständig deterministisch und verwenden keinen Zufallsstrom. Diese bekannten Annahmeverletzungen sind keine regulären iid-Fälle, nicht Teil der 278 Warnungen und kein positiver Eignungsnachweis. Berichtet werden wahre unbedingte Mittel, Fehlüberdeckung und Informationsstatus; kein verlangtes „Bestehen“ und kein beanspruchter universeller Detektor.

## 6. Endliche Folge und konkrete Grenze

1. Umfang/Finanzierung und **M** ausdrücklich entscheiden; Zeitregeln und Nebenarmsemantik fertigstellen. Danach Quellen, Wahrheiten, Ereignisse, Ressourcenlimit und Kontroll-Sollwerte prospektiv sichern; neue gebundene Aufgaben-ID erforderlich.
2. Begrenzte Implementierungs-/Referenzprüfung, dann genau ein vollständiger Schlusscheck. Ein Nichtautor prüft Wahrheiten, Ereigniszählung, Kalibrierung und M-I; Selbstprüfung ist davon getrennt.
3. Technischer Fehler: abhängigen Lauf stoppen, Fehlerfassung erhalten; eng begründete Korrektur vor erneutem Lauf sichern. Fachliches Nichtbestehen: betreffende Analysefreigabe endet. Keine Seed-/B-/n-Suche, kein Hoeffding-Kostenersatz, keine Umdeutung eines Präfixes als vollständiger Lauf. Eine andere Methode oder schwächere Aussage erfordert eine neue konkrete Entscheidung.
4. Reale Kosten gelten für den gebundenen randomisierten Vergleichsablauf. Cache im zweiten Arm ist innerhalb eines Blocks erlaubt. Vollpreissensitivität ist keine Rekonstruktion isolierter Produktionskosten. Anbieter-/Versionswechsel, bekannte blockübergreifende gemeinsame Störung, ungeklärter Kosten-/Paarstatus oder eine konkret belegte, ungeklärte relevante Abhängigkeit sperren den betroffenen iid-Schluss. Ein p-Wert über 0,05 beweist keine Unabhängigkeit; vollständiger empirischer Unabhängigkeitsbeweis wird nicht verlangt.

**Offen bleiben echte Ausführungsnachweise:** passende endliche Ressourcenbindung für 390.000 reguläre und 10.000 Kontroll-Datensätze, technische Referenzprüfung, tatsächliche Kalibrierung/M-I, endgültige Regeln und begründeter Anbieter-Anwendungsbereich. Die geprüfte Planung schließt die zuvor unbestimmte Wahl von Stressparametern und Informationskriterien als Vorschlag; sie schließt RQ-6 noch nicht. Nächster Schritt ist die konkrete Annahme und anschließende gebundene Umsetzung, kein weiterer allgemeiner Review und kein Q-Sieg als Abschlussbedingung.

## Quellen und tatsächlich erfolgte Prüfung

Gezielte lokale Lektüre von Projektregeln, Hauptdesign §§7–9/Anhang §§11–15, D-049/050/052/059, Z32 §6, Z33/Z34-Ergebnissen, E6 §4, Z40 §§2a/4/6/7/10, Nebenplan §§2–7, aktuellem Z42-Abschluss und Postmortem A1/A2/A5. Keine neue Literaturbehauptung und keine Wiederholung einer empirischen Prüfung. Mehrere große Leseausgaben waren gekürzt; benötigte Abschnitte wurden gezielt nachgelesen. History-check meldete ausschließlich das bekannte gemeinsame Paket und die neue Auftragsdatei; Koordination schließt es ab.

| Quelle | SHA256 der gelesenen Fassung |
|---|---|
| Hauptdesign / Anhang | `35a23e908ce817199264242394afbeb70c6ce8ab0a8304f649b0863684bd5213` / `866858b287a28867c1a8c5e6db7897e9f2612b589870067eeb9af362a55748e5` |
| Entscheidungslog | `00fabbef1fd63eb39bc13978895bf3d328764568047aaf7bbb44a9f880932284` |
| Z32-Hauptvergleichsplan | `927aa7ee09d9c842c61709a923db8f0cd2b0b184ead86f871e2b9345694cf9ce` |
| Z33-Ergebnis / Z34-Numerik | `764336c97d41a292138a067b23163a82251415dfe8c0998669615f4f279a4edd` / `a0fa4b701f114cb174bfd7f4f132ba341bffb89495d6a1fda61355b2514e5ebf` |
| E6 / Z40-Analyseplan | `302bf4a2ce1a32295007d67e7073d9a685fa02f2110bd4780fba85f8fc2db7d5` / `d27cc9a813ed222312fcd9c335313acef8ae4cd5ead0a3df360eecbf6a84df40` |
| Nebenvergleichsplan | `c0299735af0af51691d6c0bb69ed17a4a7a6796730b0e9e002ec0590401f8f1e` |
| Z42-Pilotergebnis | `3c2dd878553647cec51dfa84d4dc7fb58aace1e11bc3f80be152b1f78a5844c1` |
| Studienentscheidungsvorlage | `2981e0e5cc1676e5c423c5ed816688930934b9eb79b2f792cca5651135a174eb` |
