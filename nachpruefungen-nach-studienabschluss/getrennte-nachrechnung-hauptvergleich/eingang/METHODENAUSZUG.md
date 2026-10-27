<!-- status: Methodenauszug für die getrennte Nachrechnung N | 2026-10-27 -->

# Methodenauszug: Abschnitt 4.4 und Anhang D der Arbeit

Quelle: Masterarbeit, Fassung rev25 (Sauberfassung, alle Änderungen angenommen), Datei `thesis-rev25-bereinigt.md`, SHA-256 `023df612bfde1e7a9d54bf7191cf155674342d25178cc3e7ff74082bb11b68db`. Wortlaut unverändert. Kennungen in eckigen Klammern sind Absatzkennungen der Word-Datei; Tabellenzellen sind mit „·“ eingerückt; ⟦Q⟧, ⟦F*⟧ und andere Ausdrücke in ⟦ ⟧ sind Formelobjekte der Arbeit (⟦Q⟧ = aufgabenabhängige Auswahl, Arm Q; ⟦F*⟧ = feste Referenz, Arm F).

Ausgelassen, ohne Ersatz:
- [N4004]: betrifft nur Referenz-, Runden- und Ausfallvergleich (Hoeffding-Intervalle)
- [N4005]: betrifft nur die Kosten der ergänzenden Vergleiche
- [N4006]: betrifft nachträgliche Auswertungen außerhalb des vorab festgelegten Hauptvergleichs
- [X0570]: nimmt auf Ergebnisse aus Kapitel 6 und auf Entwicklungswerte Bezug
- [X1695]: betrifft nur die Kosten der ergänzenden Vergleiche

Verweise auf andere Abschnitte der Arbeit (zum Beispiel 2.4, 6.1, 7.4) sind nicht Teil dieses Auszugs.

---

## 4.4 Zielgrößen und Entscheidungsregel [N0542]

[N0543] Für die beiden Zahlen des Hauptvergleichs, Qualitätsdifferenz und Kostenverhältnis, wurden Berechnung und Unsicherheitsverfahren vor der Hauptstudie festgelegt, ebenso die Entscheidungsregel, die beide zugleich prüft, und die Lesart jedes möglichen Ergebnisses. Einzige inhaltliche Ausnahme für den Hauptvergleich ist die Kostenannahme im übernächsten Absatz.
[N0544] Die Hauptstudie umfasst 9.040 Paare aus dem Dev-Bestand. Antwortet in einem Paar nur ⟦Q⟧ exakt richtig, zählt das Paar ⟦+1⟧. Antwortet nur ⟦F*⟧ richtig, zählt es ⟦-1⟧. Sonst zählt es ⟦0⟧. Der Mittelwert dieser Werte über alle Paare, mal 100, ist die Qualitätsdifferenz in Prozentpunkten. Für die Kosten teilt die Auswertung die mittleren bekannten Modellkosten von ⟦Q⟧ durch die von ⟦F*⟧. Das entspricht dem Verhältnis der Gesamtkosten, nicht einem Mittel der Verhältnisse einzelner Paare.
[X0542] Die Auswertung zählt eine unbekannte Abrechnung nicht als gemessene Null. Sie bleibt als unbekannt ausgewiesen, und das Verhältnis beruht auf den bekannten Kosten. Für die tatsächlichen Kosten gelten das Verhältnis und die Kostenbedingung der Entscheidungsregel deshalb nur unter der Annahme, dass unbekannte Abrechnungen keine zusätzlichen Kosten verursachten. Im Auswertungsplan war diese Annahme nicht vorgesehen. Sie kam während der Hauptstudie hinzu, am 21. September 2026 nach den ersten 100 Paaren, als ein Aufruf ohne Antwort und ohne Abrechnung endete. Begründet wurde sie mit früheren abgebrochenen Aufrufen, die nicht in Rechnung gestellt worden waren. Das Laufregister vermerkt bis dahin keine Einsicht in die Qualitätsergebnisse. Abschnitt 6.1 berichtet, wie oft die Annahme nötig war. Ob die Armreihenfolge die Kosten beeinflusst, wurde für den Hauptvergleich nicht geprüft (Abschnitt 7.4).
[N0545] Geschätzt wird damit, wie die beiden eingefrorenen Regeln im Mittel über genau diesen Bestand abschneiden, wenn jede Aufgabe gleich wahrscheinlich gezogen und neu beantwortet wird. Ein Mittel über alle denkbaren Mehrschrittfragen ist das nicht. Weil mit Zurücklegen gezogen wird, kommen Aufgaben mehrfach vor. Für diese Zielgröße bleiben die Ziehungen trotzdem unabhängig, auch wenn Wiederholungen bei Temperatur 0 fast gleich ausfallen. Die Sensitivitätsanalyse am Ende des Abschnitts prüft eine gebündelte Behandlung mehrfach gezogener Aufgaben.
[N0546] Die Unsicherheit beider Zahlen wird mit einem Verfahren bestimmt, das der Auswertungsplan vorab festlegt, nämlich einem studentisierten Bootstrap über ganze Paare. Nach dem Plan zieht er 19.999-mal 9.040 Paare mit Zurücklegen, mit denselben Ziehungsindizes für Qualität und beide Kostenreihen, und bildet die Grenzen aus den studentisierten Abständen. Die untere Qualitätsgrenze nutzt das 97,5-%-Quantil, die obere Kostengrenze das 2,5-%-Quantil. Der Auswertungsplan legt Standardfehler und die Regeln für nicht berechenbare Grenzen fest (Anhang D). Der Plan setzt voraus, dass der Anbieter über die ganze Laufzeit gleich antwortet und kein gemeinsames Ereignis mehrere Ziehungen zugleich trifft. Zufällige Ziehung und getrennte Gesprächskontexte beweisen das nicht. In Abschnitt 7.4 wird bewertet, was daraus für die Belastbarkeit folgt.
[N0547] Die Entscheidungsregel verbindet beide Zahlen. ⟦Q⟧ gilt als lohnend, wenn beides zugleich gilt: Die untere einseitige 97,5-%-Grenze der Qualitätsdifferenz liegt über ⟦-3⟧ Prozentpunkten, und die obere einseitige 97,5-%-Grenze des Kostenverhältnisses liegt unter 0,90. Gleichheit mit einer Schwelle reicht nicht. Die Qualitätsbedingung folgt der Logik eines Nachweises der Nichtunterlegenheit (Abschnitt 2.4). Die dort zitierte Leitlinie gibt keinen Wert für die Schwelle vor (European Medicines Agency, 2005, S. 3). Die drei Prozentpunkte sind daher eine eigene normative Festlegung für diesen Benchmark. Ein kleiner, begrenzter Qualitätsverlust gilt damit als hinnehmbar, wenn dafür die Kosten deutlich sinken. Für die Kosten gilt eine Überlegenheitsbedingung. ⟦Q⟧ muss nachweislich mehr als zehn Prozent günstiger sein, auch das eine eigene Festlegung und kein aus der Literatur abgeleitetes Optimum. Die Regel braucht keine Korrektur für zwei Prüfungen. Lohnt sich ⟦Q⟧ in Wahrheit nicht, ist mindestens eine der beiden Bedingungen verletzt. Ein falsches „lohnt sich“ entsteht dann nur, wenn die Intervallgrenze gerade dieser Bedingung trotzdem auf der günstigen Seite ihrer Schwelle liegt, nominal in höchstens 2,5 % der Fälle (eigenes Argument, nicht aus der Leitlinie).
[N0552] Tabelle 4.5 legt fest, was jedes mögliche Ergebnis des Hauptvergleichs bedeutet, auch ein negatives oder unklares.
[N0553] Tabelle 4.5: Lesart möglicher Ergebnisse des Hauptvergleichs, vor der Hauptstudie festgelegt
  · [N0554] Lage der Grenzen (einseitig 97,5 %)
  · [N0555] Zulässige Aussage
  · [N0556] untere Qualitätsgrenze über ⟦-3⟧ Prozentpunkten und obere Kostengrenze unter 0,90
  · [N0557] ⟦Q⟧ lohnt sich gegenüber ⟦F*⟧ auf dem Dev-Bestand; die Entscheidungsregel ist erfüllt
  · [N0558] mindestens eine der beiden Bedingungen verfehlt, ohne dass eine Grenze einen Nachteil belegt
  · [N0559] kein Nachweis, dass sich ⟦Q⟧ lohnt; die Entscheidung bleibt offen, weder Gleichwertigkeit noch Nachteil folgt
  · [N0560] obere Qualitätsgrenze unter 0
  · [N0561] Qualitätsverlust belegt
  · [N0562] obere Qualitätsgrenze unter ⟦-3⟧
  · [N0563] Verlust über die Schwelle von drei Prozentpunkten hinaus belegt
  · [N0564] untere Kostengrenze über 0,90
  · [N0565] Ersparnis von zehn Prozent ausgeschlossen
  · [N0566] untere Kostengrenze über 1
  · [N0567] Mehrkosten belegt
  · [N0568] Grenze nicht berechenbar oder Messung ungültig
  · [N0569] Nachweis offen; kein Nullergebnis
  · [N0570] Kostenunterschied in einem ergänzenden Vergleich
  · [N0571] Beschreibung der erhobenen Blöcke, keine abgesicherte Kostenrichtung
[N0572] Anmerkung. Kostengrenzen nur aus bekannten Kosten, gültig unter der während der Hauptstudie ergänzten Kostenannahme.
[N4003] Wie viele Paare und Blöcke erhoben wurden, ergab sich aus den Präzisionszielen. Das Budget bestimmte die Schwellen nicht. Auch für eine kleine Studie darf die Schwelle nicht großzügiger ausfallen, denn sie ist unabhängig vom Stichprobenumfang festzulegen (European Medicines Agency, 2005, S. 5). Die Zahl von 9.040 Paaren beruht auf einer Pilotstudie mit 120 Aufgaben außerhalb des Dev-Bestands. Nach dem vorab festgelegten Rechenweg sollte die Intervallgrenze der Qualitätsdifferenz rund 1,5 Prozentpunkte vom Schätzwert entfernt liegen, halb so weit wie die Drei-Punkte-Schwelle (Anhang D). Diese Rechnung diente nur der Planung des Umfangs, nicht der Auswertung. Für das Kostenverhältnis lag das Ziel bei 0,05, der Hälfte der geforderten Ersparnis. Die Qualität verlangte mehr Paare und bestimmte den Umfang. Die 2.952 Blöcke der ergänzenden Vergleiche folgen aus der Hoeffding-Ungleichung (nächster Absatz). Beide Umfänge sind eigene Planungsfestlegungen nach dem Ansatz, einen Umfang aus der gewünschten Intervallbreite abzuleiten (Lakens, 2022, S. 7 f.). Sie liefern keinen Nachweis der Teststärke und bestimmen nicht, wie oft ein vorhandener Nutzen so unerkannt bliebe.
[N0574] Die vorab festgelegten Schlüsse gelten für die beiden eingefrorenen Regeln auf dem Dev-Bestand von MuSiQue, mit einem Sprachmodell bei einem festen Anbieter und festen Prompts, im Hauptvergleich mit zwei Runden. Ein Ergebnis zu ⟦Q⟧ betrifft diese eine Auswahlregel und ist kein Urteil über aufgabenabhängige Auswahl im Allgemeinen.


# Anhang D Planungsrechnungen [X1692]

[X1693] Die Unsicherheit von Qualitätsdifferenz und Kostenverhältnis im Hauptvergleich bestimmt ein studentisierter Bootstrap über ganze Paare (Abschnitt 4.4). Nach dem Plan zieht er aus den 9.040 beobachteten Paaren 19.999-mal erneut 9.040 Paare mit Zurücklegen und rechnet jedes Mal Qualitätsdifferenz, Kostenverhältnis und deren Standardfehler neu, mit denselben Ziehungsindizes für Qualität und beide Kostenreihen. Die Intervallgrenzen bildet der Plan aus der Verteilung der Abstände zwischen neu gerechnetem und beobachtetem Wert, je geteilt durch den neu gerechneten Standardfehler. Als Standardfehler der Qualitätsdifferenz dient die Standardabweichung der Paarwerte geteilt durch die Wurzel der Paarzahl, für das Kostenverhältnis die entsprechende Größe aus dessen linearer Näherung. Die untere Qualitätsgrenze nutzt das 97,5-%-Quantil, die obere Kostengrenze das 2,5-%-Quantil dieser Verteilung. Ohne Streuung, bei undefinierten studentisierten Werten oder bei instabilem Kostennenner gilt die betroffene Grenze als nicht aussagekräftig. Die untere Qualitätsgrenze wird dann auf ⟦-100⟧ Prozentpunkte gesetzt, die obere Kostengrenze auf unendlich. Keine Wiederholung wird dabei verworfen. Das Verfahren wird auch in diesen Fällen nicht ersetzt.
[N129727829] Die Zahl von 9.040 Paaren beruht auf einer Pilotstudie mit 120 Aufgaben außerhalb des Dev-Bestands (Abschnitt 4.4). Die je drei Paare derselben Aufgabe zählen nicht als unabhängige Aufgaben. Unter den vorab festgelegten Teilsichten nach Schrittzahl war der Anteil der Paare, in denen nur eine der beiden Regeln exakt richtig antwortete, bei den Zweischrittfragen am höchsten. Er lag bei 9/34 der 204 Paare aus 68 Zweischrittaufgaben. Wie vorab festgelegt, wurde dieser Anteil verdoppelt. Eine Normalnäherung berechnete daraus, wie viele Paare nötig sind, damit die Intervallgrenze rund 1,5 Prozentpunkte vom Schätzwert liegt, halb so weit wie die Drei-Punkte-Schwelle: ⟦1,962⋅2⋅934/0,0152⟧, aufgerundet 9.040.
