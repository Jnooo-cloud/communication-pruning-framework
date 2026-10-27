# Gegenprüfung der Vorregistrierung N

Stand: 27.10.2026

## Urteil

**Freigabefähig: nein.** Die Rechenvorschrift ist für die regulären Laufwerte und die Hauptkennzahlen weitgehend ausführbar. Vor Beginn der getrennten Implementierung müssen aber der tatsächliche Dateizugriff begrenzt und die Lücken im Vergleichswerkzeug geschlossen werden. O1 bis O5 sind unten entschieden.

## Befunde

### Muss: Implementierung technisch auf das Eingangspaket begrenzen

`AUFTRAG.md` Abschnitt 2 und `VORAB-N.md` Abschnitte 4 und 11 beschreiben die Trennung ausdrücklich als organisatorisch, ohne technische Lesesperre. Ein Arbeitsordner außerhalb der beiden Repositories verhindert nicht, dass dieselbe lokale Sitzung Dateien aus `Masterarbeit` oder `communication-pruning-framework` liest. Das reicht für die Anforderung „der spätere Implementierer darf den Originalcode nie sehen“ nicht.

**Änderung:** Die Implementierung in einem Container oder separaten Konto ausführen, in dem ausschließlich eine Kopie von `eingang/` und die benötigte Python-/NumPy-Laufzeit verfügbar sind. Die Studienrepositorys und der übrige Masterarbeitsordner dürfen dort nicht eingehängt sein; Netzwerk bleibt gesperrt. Den Zugriff auf diesen Arbeitsbereich protokollieren.

### Muss: Vergleich an eine vollständige Festschreibung binden

`vergleich.py` macht `--ausgabe-sha` optional (`vergleich.py:586`, `601-602`); ohne Angabe kann der Lauf trotz Hinweis mit Exit 0 enden. Nicht in `AUSGABE.sha256` gelistete Dateien werden ebenfalls nur als Information gemeldet (`599-600`). Das widerspricht dem Ablauf in `VORAB-N.md` 9.5-6, der einen Vergleich erst nach Festschreibung verlangt, und dem Auftrag 5.5, der alle Ausgabedateien binden lässt.

**Änderung:** `--ausgabe-sha` verpflichtend machen und bei fehlendem Wert abbrechen. Jede nicht gelistete Datei sowie unsichere oder doppelte Manifestpfade müssen den Vergleich blockieren. Die Gegenprobe muss fehlenden Hash und eine zusätzliche, nicht gelistete Datei als Fehler testen.

### Muss: Endantwort prüfbar machen

Der Auftrag verlangt `endantwort` je Lauf (`AUFTRAG.md` 5.1). `P-ROWS.json` enthält dieses Feld nicht; `vergleich.py` prüft es daher nicht und berechnet EM/F1 nicht aus der ausgegebenen Antwort neu. `gegenprobe.py` setzt die Antwort in der Pseudoausgabe sogar für alle Zeilen auf `null` (`gegenprobe.py:123-127`) und mutiert sie nie. Eine falsche oder fehlende Antwort bleibt unentdeckt, wenn EM und F1 zufällig gleich bleiben.

**Änderung:** Nach Festschreibung jede ausgegebene Antwort gegen `finished.answer` im durch die gebundene Laufliste bezeichneten Rohprotokoll prüfen. Zusätzlich eine Probe mit veränderter und eine mit fehlender Antwort aufnehmen. Die Antwort bleibt ein Zwischenwert ohne Sollwert in `P-ROWS`, aber ihre Herkunft und Übertragung werden so geprüft.

### Muss: Gegenprobe um nicht abgedeckte Felder erweitern

Die vier Proben liefen in einer temporären Kopie erfolgreich. Die Änderungsprobe deckt EM, F1, Aufrufzahl, Kosten und Zeilentausch ab. Sie deckt den Statusvergleich jedoch nicht ab: beide für den Tausch ausgewählten Zeilen haben laut Auswahlregel `status == "ok"` (`gegenprobe.py:163-172`). Auch `run_id`, `paarindex`, `arm`, unbekannte Beträge und die Antwort werden nicht gezielt verfälscht.

**Änderung:** Je Feld mindestens eine kontrollierte Veränderung mit erwarteter Meldung ergänzen, insbesondere `ok` gegen `model_failure`, falsche Lauf-ID/Paar-/Armzuordnung sowie `endantwort`. Zusätzlich Duplikat, fehlenden Lauf und die oben genannten Festschreibungsfälle testen.

### Muss: O1 und O2 vor der Rechnung ausdrücklich schließen

O1 ist als Lücke benannt, aber weiterhin zur Entscheidung offen (`VORAB-N.md:285`). Die aktuelle N-Regel F4 setzt einen Kostennenner nur bei `mittel(C_F) <= 0` auf nicht aussagekräftig. Der Originalcode enthält zusätzlich den Status `denominator_weak`, wenn der Nenner höchstens `1,95996 * SE(mittel(C_F))` beträgt (`intervals.py:105-109`). Das ist eine codeinformierte Vergleichsdifferenz, keine Vorgabe des Plantexts. O2 lässt offen, ob reguläre Grenzen zusätzlich auf `[-1,1]` beziehungsweise `[0, unendlich]` begrenzt werden; der Auftrag nennt nur die Formel, während der Originalcode reguläre Grenzen begrenzt (`intervals.py:133-139`).

**Änderung:** O1 zugunsten der bereits dokumentierten F4 schließen: bei `mittel(C_F) <= 0` sperren, keinen später übernommenen Codegrenzwert ergänzen und einen dadurch abweichenden Grenzstatus nach der vorab genannten Klasse (c) berichten. O2 zugunsten der wörtlichen Formel schließen: reguläre Grenzen nicht zusätzlich kappen; nur die ausdrücklich festgelegten nicht aussagekräftigen Grenzen auf die uninformativen Bereiche setzen. Beide Entscheidungen mit genauer Formel in `AUFTRAG.md` spiegeln. So bleibt die Implementierung am dokumentierten Plan und nicht am Originalcode gebunden.

### Soll: Toleranz und Rundungsbericht auseinanderhalten

Die Bootstrap-Toleranzen sind numerisch festgelegt: 0,0005 für die Qualitätsdifferenz und 0,001 für das Kostenverhältnis. Die Begründung im Einarbeitungsplan vergleicht sie mit dem Monte-Carlo-Fehler bei 19.999 Wiederholungen; die Größenordnung ist plausibel. Der Vergleich zur gedruckten Arbeit erlaubt zusätzlich eine halbe letzte Stelle (`VORAB-N.md` 7; `vergleich.py`, `ARBEIT_GRENZEN`). Dadurch kann ein Wert die numerische Toleranz bestehen, obwohl seine Rundung auf den gedruckten Stellen abweicht.

**Änderung:** Im Vorabtext klar sagen, dass die numerische Toleranz den Bootstrapvergleich steuert, die Rundungszugabe aber keine Behauptung gleicher gedruckter Werte erlaubt. Im Bericht jeweils Sollwert, ungerundeten Nachrechnungswert und dessen kaufmännische Rundung nebeneinander ausgeben. Schwellenurteil und Tabellenlesart bleiben separat exakt zu vergleichen.

### Soll: Klasse (c) gegen nachträgliche Ausweitung absichern

Abschnitt 8 ordnet eine breite Gruppe dokumentierter Mehrdeutigkeiten als Klasse (c) ein und verlangt nur, sie „als erklärt“ zu berichten. Obwohl Regeländerungen nach Ergebnissicht untersagt sind (Abschnitt 8), bleibt damit Raum, einen neuen Grund nachträglich unter „Mehrdeutigkeit“ zu fassen.

**Änderung:** Für jede Klasse-(c)-Meldung den vorab nummerierten Regelpunkt zitieren und beide Werte sowie die rechnerische Folge ausweisen. Neue oder nicht vorab erfasste Erklärungen bleiben Klasse (d); keine neue Klasse-(c)-Grundlage nach Ergebnissicht ergänzen.

## Rechenregeln und Vergleich

Status, zulässige Goldantworten samt Aliassen, MuSiQue-Funktionen für EM/F1, gestartete Aufrufe und bekannte Kosten sind in `AUFTRAG.md` 3.3-3.7 konkret beschrieben. Paarwert, Kennzahlen, Standardfehler, Bootstrapziehungen, Quantilränge, zwei Seeds, Entscheidungsregel und Wahrheitsbedingungen für Tabelle 4.5 stehen in 4.1-4.7. Die noch fehlenden numerischen Nenner- und Kappungsregeln sind oben benannt. **Kann:** Die Zählung unbekannter Beträge addiert Ereignisse mit `cost_usd = null` und nicht abgeschlossene Starts; falls beides dieselbe `attempt_id` betrifft, ist nicht gesagt, ob einmal oder zweimal gezählt wird. Ergänze eine Deduplizierung nach Versuch, falls das Protokollformat diese Überschneidung zulässt.

`vergleich.py` vergleicht die in `P-ROWS` tatsächlich verfügbaren Identitäts-, Status-, EM-, F1-, Aufruf- und Kostenfelder. Ich habe die gestarteten Ereignisse in allen 18.080 Eingangsläufen gegen `P-ROWS.call_count` gezählt: 18.080 Übereinstimmungen; auch `run_id` und Laufkennung stimmen in 18.080 Fällen. Gegen `P-ANALYSIS` prüft der Vergleich die Punktwerte, Standardfehler, Grenzen, Grenzstatus, Aussagen und gemeinsame Entscheidungsregel. Die Hauptlücke ist die nicht geprüfte Endantwort; außerdem ist die vorhandene Gegenprobe für die genannten Feld- und Festschreibungsfehler unvollständig.

## O1 bis O5

- **O1:** F4 beibehalten und vor Commit als abgeschlossene Wahl markieren. Nicht den zusätzlichen Codegrenzwert übernehmen. Ein abweichender Grenzstatus wird als Klasse (c) mit Zahlenfolge berichtet.
- **O2:** Für reguläre Grenzen die Formel ohne Kappung festlegen. Damit wird die dokumentierte Rechenvorschrift umgesetzt; jede Abweichung zur codebedingten Kappung bleibt sichtbar.
- **O3:** Nur den vorgesehenen, gezielten Commit der in `VORAB-N.md` 9.3 aufgelisteten Prüf- und Steuerdateien verwenden; keine zweite Kopie unter `project/` anlegen. `output/` liegt außerhalb des History-Scopes. Der Commit-/Push-Schritt bleibt der dort genannten Ansage vorbehalten.
- **O4:** `VORAB-N.md` nicht in `eingang/` aufnehmen. Die Implementierung braucht die Regeln daraus über den wortgleichen Auftrag; die Vorabdatei enthält Vergleichs- und Ergebniswissen. Die Leck- und Wortgleichheitsprüfungen stützen diese Trennung.
- **O5:** Vor späterer Textübernahme E28, E32 und E39 um `AUFTRAG.md` als tatsächlich bereitgestellte Grundlage ergänzen. In E32/E39 auch offenlegen, dass der Auftrag N-spezifische, teils codeinformierte Festlegungen enthält und die Formatbeschreibung in Kenntnis des Codes erstellt wurde.

## Ergebnis der Prüfungen und Grenzen

- `eingang/MANIFEST.sha256`: 18.091 Prüfsummeneinträge geprüft, keine Abweichung. Das Paket enthält 18.092 Dateien einschließlich Manifest und 18.080 Laufprotokolle.
- `leckpruefung.py` aus einer temporären Kopie ausgeführt: bestanden; 120 Ergebniszahlen in 2.474 Textformen gesucht. Außerhalb der ausdrücklich unveränderten Rohdaten fanden sich keine P-ANALYSIS- oder Abschnitt-6.3-Ergebniszahlen, keine Ergebnisdateien und kein Framework-/Auswertungscode. Vorhanden sind die für die Bewertung nötigen MuSiQue-Skripte sowie Plan-, Pfad- und Prüfsummenmetadaten, nicht der Studiencode.
- `pruefe_wortgleichheit.py` aus temporärer Kopie: bestanden. `gegenprobe.py` aus temporärer Kopie: bestanden, alle vier enthaltenen Proben.
- Quellen gelesen: die genannten Vorab-, Auftrags-, README- und Vergleichsdateien, Planabschnitt 4, Planentwurf 1.3, K3/NEU-1 bis NEU-5 sowie für diese Gegenprüfung die Originaldateien `intervals.py`, `final_analysis.py`, `evaluation.py` und `P-ROWS.json`/`P-ANALYSIS.json`. Keine Netzwerkzugriffe. Alle Skriptausgaben lagen in einem temporären Verzeichnis; keine anderen Projektdateien wurden geändert.
- Die getrennte Rechnung selbst ist noch nicht ausgeführt. Es fand keine unabhängige zweite Implementierung statt. Der verwendete Protokollbestand und Auswertungsplan sind dieselben wie in der Studie; die Zuordnung zu den Paaren wird aus der früheren Z56-Prüfung übernommen. Die Nachrechnung kann daher diese Eingaben und die Paarzuordnung nicht unabhängig bestätigen.
