# Einordnung der Vergleichsmeldungen

**Grundlage:** `VORAB-N.md` Abschnitte 7, 8 und 12; `eingang/AUFTRAG.md` Abschnitte 4.4 bis 4.7 und 5.2; `vergleich/bericht-1/VERGLEICH-ERGEBNIS.md` und `.json`; `ausgabe-1/aggregat.json`. Die vier Meldungen werden nach den vorab festgelegten Regeln eingeordnet.

## Einordnung je Meldung

### 1. Meldung „intern“, Bootstrap S1: `zeilen_tabelle_4_5`

**Klasse (c): Mehrdeutigkeit der Ausgabevorgabe.** `AUFTRAG.md` 4.6, Zeile 81, sagt: „Dazu `zeilen_tabelle_4_5`: die Kennungen aller zutreffenden Zeilen aus der rechten Spalte, ohne Doppelungen, in der Reihenfolge der Tabelle.“ In der rechten Spalte stehen die Verweise als `[N0560]`, `[N0562]`, `[N0564]`, `[N0566]`; das Ausgabeschema 5.2, Zeile 137, weist ein Array aus, legt aber die Schreibweise der einzelnen Kennungen nicht fest. N gibt `N0560`, `N0562`, `N0564`, `N0566` aus. Die Kennungen, ihre Reihenfolge und ihre Zuordnung zu den vier Zeilen sind identisch; abweichend sind nur die Klammerzeichen.

`VORAB-N.md` Abschnitt 8, Zeile 225, nennt als Klasse (c) eine „dokumentierte, vorab nummerierte Regel oder Mehrdeutigkeit der Spezifikation“; die Folge ist: „nur mit Zitat des konkreten Regelpunkts; beide Werte und die rechnerische Folge werden berichtet.“ Beide Schreibweisen sind oben angegeben; die rechnerische Folge ist null. **Keine Änderung** eines Zahlenwerts, der Lesart in Tabelle 4.5 oder der Entscheidung: die vier Zeilen bleiben dieselben, und `regel_erfuellt` bleibt `false`.

### 2. Meldung „intern“, Bootstrap S2: `zeilen_tabelle_4_5`

**Klasse (c): dieselbe Mehrdeutigkeit der Ausgabevorgabe wie bei S1.** Maßgeblich ist `AUFTRAG.md` 4.6, Zeile 81: „die Kennungen aller zutreffenden Zeilen aus der rechten Spalte, ohne Doppelungen, in der Reihenfolge der Tabelle.“ N gibt dieselben vier Kennungen `N0560`, `N0562`, `N0564`, `N0566` in derselben Reihenfolge aus; gegenüber der Darstellung der rechten Tabellenspalte fehlen nur die Klammern. Das Arrayformat in 5.2, Zeile 137, bestimmt nicht, ob die Klammern Bestandteil der auszugebenden Kennung sind.

Nach `VORAB-N.md` Abschnitt 8, Zeile 225, werden für Klasse (c) beide Werte und ihre rechnerische Folge berichtet. **Keine Änderung** eines Zahlenwerts, der Lesart in Tabelle 4.5 oder der Entscheidung: dieselben vier Zeilen treffen zu, und `regel_erfuellt` bleibt `false`.

### 3. Meldung „arbeit“, Bootstrap S1: obere Grenze des Kostenverhältnisses

**Klasse (c): vorab geregelte Abweichung bei der getrennten Prüfung von Toleranz und Rundung.** `VORAB-N.md` F2, Zeile 284, legt fest: „Ziehung je Wiederholung mit genau einem Aufruf `rng.integers(0, 9040, size=9040)`.“ F10, Zeile 292, lautet: „Grenzen gegen die gedruckten Werte der Arbeit: numerische Toleranz und kaufmännische Rundung getrennt prüfen; undefinierte Wiederholungen nur null gegen nicht null“. Abschnitt 7, Zeile 208, legt für den Vergleich mit der Arbeit fest: „numerische Toleranz allein: ±0,0005 für Δ als Anteil, ±0,001 für ρ; zusätzlich kaufmännische Rundung auf die gedruckten Stellen und exakter Vergleich mit dem Druckwert.“ Die Obergrenze von N ist ungerundet `1.1765393418022732`; auf drei Stellen kaufmännisch gerundet ist sie `1.177`, während in der Arbeit `1.176` steht. Die Differenz zum Druckwert beträgt `0.0005393418022732` Verhältnis-Einheiten und liegt innerhalb der Toleranz von `±0.001`.

`VORAB-N.md` Abschnitt 8, Zeile 225, verlangt für Klasse (c): „beide Werte und die rechnerische Folge werden berichtet.“ Der Druckwert der Arbeit wird durch diese Einordnung nicht geändert; würde man den gerundeten N-Wert einsetzen, änderte sich die angezeigte Zahl von `1.176` zu `1.177`. Die Lesart in Tabelle 4.5 und die Entscheidung ändern sich nicht: die obere Grenze liegt weit über `0.90`, die Ersparnisregel ist nicht erfüllt, und `regel_erfuellt` bleibt `false`.

### 4. Meldung „arbeit“, Bootstrap S2: untere Grenze der Qualitätsdifferenz

**Klasse (c): vorab geregelte Abweichung bei der getrennten Prüfung von Toleranz und Rundung.** Es gelten dieselben zitierten Regeln F2 (`VORAB-N.md` Abschnitt 12, Zeile 284), F10 (Zeile 292) und Abschnitt 7 (Zeile 208). Die untere Grenze von N ist ungerundet `-4.892933446821473` Prozentpunkte; auf zwei Stellen kaufmännisch gerundet ist sie `-4.89`, während in der Arbeit `-4.90` steht. Der Abstand zum Druckwert beträgt `0.007066553178527` Prozentpunkte. Das entspricht `0.00007066553178527` als Anteil und liegt innerhalb der Toleranz von `±0.0005` als Anteil, also `±0.05` Prozentpunkten.

Nach `VORAB-N.md` Abschnitt 8, Zeile 225, werden für Klasse (c) beide Werte und die rechnerische Folge berichtet. Der Druckwert der Arbeit wird durch diese Einordnung nicht geändert; würde man den gerundeten N-Wert einsetzen, änderte sich die angezeigte Zahl von `-4.90` zu `-4.89`. Die Lesart in Tabelle 4.5 und die Entscheidung ändern sich nicht: auch die N-Untergrenze liegt unter der Schwelle von `-3` Prozentpunkten, und `regel_erfuellt` bleibt `false`.

## Vollständigkeit und weitere Regeln aus Abschnitt 8

**Ja, die anwendbaren Bedingungen aus „Weitere Regeln“ sind erfüllt.** `ausgabe-1/aggregat.json` weist `n_paare = 9040`, `n_laeufe = 18080`, `vollstaendig = true`, null nicht nachrechenbare Läufe und null ausgelassene Paare aus. Damit ist die Vorgabe aus `VORAB-N.md` Abschnitt 8, Zeile 232, erfüllt: „Kein Lauf wird still ausgeschlossen. Nicht nachrechenbare Läufe werden gezählt; Grenzen, Urteil und Lesart gelten nur als nachgerechnet, wenn alle 18.080 Läufe nachgerechnet sind.“ Die zwei Seeds enthalten jeweils 19.999 Wiederholungen; die Grenzen haben den Status `ok` und jeweils null undefinierte Wiederholungen. Grenzen, Entscheidungsregel und Lesart wurden somit für beide Seeds nachgerechnet. Das Urteil ist bei beiden Seeds `false`; die Lesart nennt jeweils die Zeilen N0560, N0562, N0564 und N0566.

Die Zusatzprüfung eines bekannten kleinen Falls nach `VORAB-N.md` Abschnitt 8, Zeile 230, ist nicht ausgelöst: keine Bootstrapgrenze liegt außerhalb der vorab festgelegten numerischen Toleranz. Der Vergleich weist null Laufmeldungen und null Meldungen gegen P-ANALYSIS aus; damit gibt es in diesem Ergebnis keinen gemeldeten Lauf- oder Analysebefund, auch keinen protokollgebundenen Kostenbefund zu ersetzten Sendeversuchen. Die vier Meldungen werden nach den vorab festgelegten Regeln und ohne Richtungsfilter eingeordnet. `VORAB-N.md` Abschnitt 8, Zeile 233, sagt dazu: „Toleranzen, Regeln und Klassen werden nach Sicht auf Ergebnisse nicht geändert.“ Es gibt keinen Anhaltspunkt, dass Toleranzen oder Regeln nach Sichtung der Ergebnisse geändert wurden.

## Formulierung für die Arbeit

Die getrennte Nachrechnung N über 9.040 Paare ergab eine Qualitätsdifferenz von `-4.2146` Prozentpunkten und ein Kostenverhältnis von `1.1693`. Die Grenzen der Qualitätsdifferenz lagen bei S1 zwischen `-4.8988` und `-3.5411` Prozentpunkten und bei S2 zwischen `-4.8929` und `-3.5424`; die Grenzen des Kostenverhältnisses lagen bei S1 zwischen `1.162046` und `1.176539` sowie bei S2 zwischen `1.162115` und `1.176365`. Die größten Abweichungen der Bootstrapgrenzen zwischen N und P-ANALYSIS betrugen bei der Qualitätsdifferenz `0.00860982` Prozentpunkte an der unteren Grenze und `0.00264304` Prozentpunkte an der oberen Grenze; beim Kostenverhältnis betrugen sie `0.0000567462` und `0.000179132` Verhältnis-Einheiten an der unteren und oberen Grenze. Die Entscheidungsregel war für beide Seeds nicht erfüllt, und die Lesart umfasste jeweils die Tabellenzeilen [N0560], [N0562], [N0564] und [N0566]; die Abstände der beiden Werte zum Druckwert liegen innerhalb der vorab gesetzten Toleranz, obwohl N sie auf `1.177` statt `1.176` beziehungsweise `-4.89` statt `-4.90` rundet.
