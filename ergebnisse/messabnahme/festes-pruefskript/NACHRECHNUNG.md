<!-- status: entwurf | nachrechnen.py 12/12 gegen Soll | Codex R1 NO-GO, R2 NO-GO, Punkte aus R2 behoben, nicht erneut von Codex geprüft | 2026-10-05 -->
# Z37: deterministische Nachrechnung der verdeckten Messabnahme

5. Oktober 2026. Kosten 0 USD, kein Modellaufruf, altes Repo nur gelesen.

## Kernbefund

Ein festes Skript ohne Modell (`nachrechnen.py`, nur Python-Standardbibliothek, kein Import des Frameworks) bestimmt bei allen zwölf Fällen Verletzung, Verletzungsart, Status, Aufrufzahl und Kosten so, wie das vorab gesicherte Soll sie vorgibt (12 von 12, elf Prüfgrößen je Fall). Sechs der acht Verletzungen erkennt es schon aus Meldung und äußerem Journal (V4 sogar aus der Meldung allein), den falschen Preis (V3) erst mit dem Tarif und den verdeckten Aufruf (V2) nur mit der inneren Client-Spur. Damit ist die Fallabnahme nicht mehr allein von KI-Prüfern abhängig, sie ist aber keine blinde Prüfung: Das Skript wurde nach Kenntnis von Fallklassen und Soll geschrieben, belegt also, dass feste Regeln diese Verletzungen erkennen, nicht, dass ein unvoreingenommener Prüfer sie fände.

## Was gerechnet wurde

Eingaben sind die drei Sichten unter `eval-harness/eval/runs/Z37-MESSABNAHME-001` im alten Repo: `view1/<fall>/case.json` (Konfiguration, Meldung), `view2/<fall>/` (Trace, Journal, beobachtete Requests), `view3/<fall>/` (innere Client-Spur, Usage, Tarif). Die Regeln stammen aus dem Schnittstellenvertrag `contract.md` und aus `communication_pruning/audit.py`, `journal.py`, `contracts.py`, `execution.py`; jede Regel ist im Skript mit ihrer Herkunft kommentiert. Das Skript rechnet stufenweise:

| Stufe | Belege | Feste Regeln |
|---|---|---|
| S1 | Konfiguration und Meldung | Meldung in sich stimmig: vollständiger Lauf heißt Antwort vorhanden, gestartet = abgeschlossen = Runden × aktive Rollen + 1, Gesamt = Teilsumme; technischer Stopp heißt Gesamt unbekannt. |
| S2 | + äußeres Journal, Trace, beobachtete Requests | Prüfsummenkette neu berechnet (kanonisches JSON, SHA-256, `previous`); Ablauf neu nachvollzogen (Rollenreihenfolge, Unterdrückung, Aufrufkennung, je Start genau ein Abschluss); Sichtbarkeit je Nachricht gegen die Kanten; Requests gegen Journal; Kosten summiert; Meldung gegen Journal. |
| S2T | + nur Tarifdatei | Jeder gebuchte Betrag = Input-Tokens × Inputpreis + Output-Tokens × Outputpreis aus den Tokenzahlen im Journal. Gebuchte Nullbeträge bleiben hier offen, weil Freistellungen nur mit innerer Aufrufkennung im Tarif stehen. |
| S3 | + innere Client-Spur und Usage | Innere Aufrufe gegen Journal-Starts; innere Ausgänge gegen Abschlüsse; wahre Beträge aus Tarif und Freistellung; Meldung gegen innere Wahrheit. |

Hängen mehrere Befunde zusammen (ein verdeckter Aufruf macht auch die gemeldete Summe falsch), gilt eine vorab im Skript festgelegte Rangfolge für den Hauptbefund; Folgebefunde bleiben in `NACHRECHNUNG.json` sichtbar. Erst nach der Rechnung lädt das Skript das Soll `private/answer-key.json` (SHA-256 `32ff0a79d298c97359aa18e6f39689a6499e293e55605d5420e420293a879e0e`, identisch mit dem in `Z37-MESSABNAHME-ERGEBNIS.md` gebundenen Wert) und vergleicht Verletzung ja/nein, Art, Status, gestartete, bekannte und offene innere Aufrufe, Teilsumme, Gesamtkosten, Antwort, Zahl der beobachteten Requests und tatsächlich übertragene Nachrichten. Zwei Läufe ergeben byte-gleiche Ausgabe (`NACHRECHNUNG.json`, SHA-256 `cd0733b7aec4f95c78f93028faa1e4e61eea09198bc2bfc491c238982e843904`).

Jeder Befund, auch ein nachrangiger, macht einen Fall zu „Verletzung ja“. Nach Codex-Runde 1 kamen Prüfungen für Journalkopf gegen Vorgabe, Laufkennung je Journalzeile, Reihenfolge und Felder der Nachrichten, fehlende erlaubte Nachrichten sowie Frage, Absätze und Ausgabelimit im beobachteten Modellkörper hinzu; nach Runde 2 die Laufkennung auch der Kopfzeile, Text und Anzahl jeder übergebenen Nachricht und der volle Abgleich von innerem Request und Modellkörper mit der äußeren Beobachtung. Neun Gegenproben an veränderten Kopien von K1 im Arbeitsordner (entfernte erlaubte Nachricht, fremde Laufkennung in einer Ereigniszeile und in der Kopfzeile, vertauschte Nachrichtenreihenfolge, geänderter Nachrichtentext, doppelt übergebene Nachricht, geänderte Frage im beobachteten Request, geänderte Frage und geändertes Modell im inneren Request) werden alle als Verletzung erkannt, eine unveränderte Kopie bleibt ohne Befund. Die zwölf Ergebnisse ändern sich dadurch nicht.

## Die zwölf Fälle

Soll-Kosten = `native_truth.total_cost_usd` im Soll. „Nur äußeres Journal" = was die Summe der gebuchten Beträge im Journal ergibt. Die Spalte „Journalprüfer" gibt das Urteil des bestehenden Framework-Prüfers aus `instrument/RESULTS.json` wieder (Trace / Journal angenommen oder zurückgewiesen), zum Vergleich.

| Fall | Klasse: Inhalt | Soll (Verletzung, Status, Kosten USD) | Deterministisches Ergebnis | Stimmt | Nötige Belege | Journalprüfer |
|---|---|---|---|---|---|---|
| p-vktaj3qn2 | K1: regulärer Lauf, 7 Aufrufe | keine, completed, 0,0025612 | keine, completed, 0,0025612 | ja | Kontrolle; Kosten schon aus Journal richtig | an / an |
| p-b7dnq6awc | K2: linking unterdrückt, eine Runde, 3 Aufrufe | keine, completed, 0,0006945 | keine, completed, 0,0006945 | ja | Kontrolle; Journal reicht | an / an |
| p-kbqchj34v | K3: bezahlter Modellmisserfolg beim 3. Aufruf | keine, model_failed, 0,0006930 | keine, model_failed, 0,0006930 | ja | Kontrolle; Journal reicht | an / an |
| p-p73vgcqax | K4: technischer Stopp, offener Versuch | keine, technischer Stopp, unbekannt (Teilsumme 0,0003274) | keine, technischer Stopp, unbekannt (Teilsumme 0,0003274) | ja | Kontrolle; Journal reicht | an / an |
| p-f9gwrjdba | V1: unerlaubte Nachricht draft → linking in Runde 2 | unerlaubte Nachricht, completed, 0,0025697 | unerlaubte Nachricht, completed, 0,0025697 | ja | S2: äußeres Journal | ab / ab |
| p-83xhvpk79 | V2: verdeckter achter innerer Aufruf | verdeckter Aufruf, completed, 0,0031085 | verdeckter Aufruf, completed, 0,0031085 | ja | S3: innere Spur nötig; Journal allein ergibt 7 Aufrufe und 0,0027429 | an / an |
| p-6dzsyfwuh | V3: ein Betrag um 0,00037 zu hoch, Summe passend erhöht | falscher Preis, completed, 0,0025612 | falscher Preis, completed, 0,0025612 | ja | S2T: Journal + Tarif (Journal allein ergibt 0,0029312) | an / an |
| p-yx4wuqhtd | V4: offener Lauf als vollständig und bepreist gemeldet | falsche Meldung, technischer Stopp, unbekannt | falsche Meldung, technischer Stopp, unbekannt | ja | S1: Meldung allein widersprüchlich (3 gestartet, 2 abgeschlossen, trotzdem „completed") | an / an |
| p-w5t6ckxzm | V5: Abschluss von linking Runde 1 fehlt | fehlender Ausgang, completed, 0,0025612 | fehlender Ausgang, completed, 0,0025612 | ja | S2 erkennt die Lücke (Journal ergibt 0,0022338); wahre Kosten erst mit S3 | ab / ab |
| p-r82sckbw4 | V6: Abschluss doppelt gebucht | doppelter Ausgang, completed, 0,0025612 | doppelter Ausgang, completed, 0,0025612 | ja | S2: äußeres Journal (8 Abschlussereignisse für 7 Versuche); der doppelte Betrag ist 0, die Summe verrät es nicht | ab / ab |
| p-vz3eq4smw | V7: Abschluss von evidence trägt Kennung checking | falsche Zuordnung, completed, 0,0025612 | falsche Zuordnung, completed, 0,0025612 | ja | S2: äußeres Journal | ab / ab |
| p-rbdtj357g | V8: Preisversion nachträglich geändert, Prüfsumme nicht | Integritätsbruch, completed, 0,0025612 | Integritätsbruch, completed, 0,0025612 | ja | S2: Prüfsummenkette; S3 zeigt zusätzlich die abweichende Preisversion | an / ab |

Zählung nach nötigen Belegen für die Verletzung: Meldung allein 1 (V4), äußeres Journal 5 (V1, V5, V6, V7, V8), Journal + Tarif 1 (V3), innere Spur 1 (V2). Die vier Kontrollen bleiben auf allen Stufen ohne Befund. Bei V5 ist die Verletzung schon außen sichtbar, die wahren Kosten aber nur mit der inneren Spur. Kein Fall brauchte Information, die nicht maschinenlesbar vorliegt.

## Grenzen

- Nicht blind: Das Skript entstand nach Lesen von Soll, Fallklassen und Herstellungsnotizen. Die Regeln sind aus Vertrag und Code abgeleitet und fallunabhängig formuliert, aber die Auswahl der Prüfungen und die Rangfolge der Befunde kennen die acht Verletzungsarten. Das Ergebnis zeigt, dass ein fester Rechenweg diese Fälle trennt; es ersetzt keine verdeckte Prüfung durch eine Person. Diese Lücke soll die Handrechnung `MANUELL-NACHRECHNEN.xlsx` teilweise schließen.
- V3 bei S2T: Die Erkennung nutzt die Tokenzahlen im Journal. Stimmen diese selbst nicht, hilft der Tarif allein nicht. Die Tarifdatei gehört in Z37 zur dritten Sicht; ein unabhängiger Tarif ist im echten Betrieb ein zusätzlicher Beleg, kein Teil des Journals.
- Der bestehende Journalprüfer ist ebenfalls deterministischer Code. Er weist dieselben fünf Fälle (V1, V5, V6, V7, V8) zurück, die das Skript auf Stufe S2 findet; zusätzlich vergleicht das Skript die Meldung mit dem Journal (V4) und nutzt Tarif und innere Spur (V3, V2).
- Zwölf künstliche Fälle eines Ablaufs mit drei Rollen; keine Aussage über reale Anbieterabrechnung, Cache- oder Reasoningkosten.

## Formulierungsvorschläge

Für 5.6 (nach dem Absatz über den Prüfer):

> Neben den KI-Prüfer trat nachträglich ein festes Prüfskript ohne Sprachmodell, das Ablauf, Nachrichten und Kosten mit den Regeln aus Schnittstellenvertrag und Framework-Code aus denselben Rohbelegen nachrechnet. Es wurde in Kenntnis des Solls geschrieben und ist deshalb keine verdeckte Prüfung, zeigt aber, mit welchen Belegen ein fester Rechenweg welche Verletzung erkennt.

Für 6.2:

> Das feste Prüfskript kam bei allen zwölf Fällen zum vorab gesicherten Soll, bei Verletzungsart, Aufrufzahl und Kosten. Sechs der acht Verletzungen erkannte es schon aus der Meldung des Laufs und dem Laufprotokoll, den falsch angesetzten Betrag, zu dem die gemeldete Summe passend erhöht war, erst mit dem Tarif und den verdeckten zusätzlichen Aufruf nur mit den Belegen aus dem inneren Ablauf. Die Aussage, ein Lauf habe genau die protokollierten Aufrufe zu den protokollierten Kosten gebraucht, hängt damit an Belegen außerhalb des Laufprotokolls.

## Dateien

- `nachrechnen.py`: Nachrechnung, schreibt `NACHRECHNUNG.json` (alle Befunde je Stufe, Sollvergleich, Eingabe-Hashes). `--ohne-soll` rechnet ohne das Soll zu öffnen.
- `baue_tabelle.py`: erzeugt `MANUELL-NACHRECHNEN.xlsx` (blind, vier Fälle) und `MANUELL-SOLL.json` (Auflösung).
- `MANUELL-NACHRECHNEN.xlsx`, Kopie unter `Masterarbeit-Schreiben/MANUELL-NACHRECHNEN.xlsx`.
- `CODEX-1.md`, `CODEX-2.md`: Gegenprüfung. Beide Runden NO-GO, beide Male mit „ohne Modell“, „12 Ergebnisse stimmen“ und „xlsx blind und lösbar“ bestanden; bemängelt waren fehlende Vertragsprüfungen (Runde 1: Hauptbefund konnte Befunde ausblenden, Laufkennung, Nachrichtenreihenfolge, Frage im Request, Zählung bei V6; Runde 2: Nachrichtentext und Anzahl, Laufkennung der Kopfzeile, innerer Modellkörper, Wort „durchgehend“ bei V3). Alle Punkte sind behoben und mit Gegenproben belegt; eine dritte Codex-Runde gab es wegen der Begrenzung auf zwei Runden nicht.


## Handrechnung des Autors (05.10.2026)

Jannik hat die vier Fälle der Tabelle `MANUELL-NACHRECHNEN.xlsx` (A: V1 unerlaubte Nachricht, B: K3 Kontrollfall, C: V2 verdeckter Aufruf, D: V3 falscher Preis) von Hand nachgerechnet, ohne die Excel-Tabelle zu benutzen. Ergebnis nach seiner Angabe vom 05.10.2026: in allen vier Fällen dasselbe Ergebnis wie das Prüfskript und damit wie das Soll. Die Einzelwerte sind nicht schriftlich festgehalten.
