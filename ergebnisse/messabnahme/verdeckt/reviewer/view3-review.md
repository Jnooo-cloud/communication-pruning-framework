# Z37 – endgültige Bewertung vor Offenlegung des Sollschlüssels

Die getrennte innere Clientspur klärt jetzt Aufrufzahl, tatsächliche Nachrichten und künstliche Preise. Beträge wurden je Aufruf mit Dezimalarithmetik aus deklarierter Usage und Tarif berechnet; ausdrücklich freigestellte Aufrufe bleiben bekannte Nullpreise. Quelle und sämtliche freigegebenen Eingaben wurden vor jeder entscheidenden Ausführung vollständig archiviert. Keine private Zuordnung oder Instrumentausgabe wurde gelesen.

| Fall | Innere Starts / Rückgaben | Bekannte Teilsumme USD | Gesamtkosten USD | Konkretes Urteil |
|---|---:|---:|---:|---|
| p-6dzsyfwuh | 7 / 7 | 0.0025612 | 0.0025612 | Konsistenter äußerer Falschpreis: behauptete Summe um 0.0003700 zu hoch. |
| p-83xhvpk79 | 8 / 8 | 0.0031085 | 0.0031085 | Verborgener zusätzlicher linking-Aufruf; außen fehlen ein Aufruf und 0.0003656 USD. |
| p-b7dnq6awc | 3 / 3 | 0.0006945 | 0.0006945 | Unterdrückung und eine Runde auch innerlich korrekt, keine versteckte Ausführung. |
| p-f9gwrjdba | 7 / 7 | 0.0025697 | 0.0025697 | Verbotene draft→linking-Nachricht tatsächlich übertragen; Messung vollständig. |
| p-kbqchj34v | 3 / 3 | 0.0006930 | 0.0006930 | Korrekt bezahlter F-01-Modellmisserfolg mit anschließendem Stopp. |
| p-p73vgcqax | 3 / 2 | 0.0003274 | unbekannt | Technischer Fehler ohne Abrechnungsbeleg; korrekt offener Prefix. |
| p-r82sckbw4 | 7 / 7 | 0.0025612 | 0.0025612 | Sieben echte Rückgaben, acht Journalabschlüsse: Doppelbuchung bei bekanntem Nullpreis. |
| p-rbdtj357g | 7 / 7 | 0.0025612 | 0.0025612 | Äußere Preisversionsangabe widerspricht innerem Beleg; Journalhash bleibt gebrochen. |
| p-vktaj3qn2 | 7 / 7 | 0.0025612 | 0.0025612 | Vollständiger regulärer Messbeleg einschließlich innerer Preisprüfung. |
| p-vz3eq4smw | 7 / 7 | 0.0025612 | 0.0025612 | Echte evidence-Rückgabe außen einem nie gestarteten checking-Versuch zugeordnet. |
| p-w5t6ckxzm | 7 / 7 | 0.0025612 | 0.0025612 | Innere linking-Rückgabe belegt fehlendes äußeres Abschlussereignis und dessen Betrag. |
| p-yx4wuqhtd | 3 / 2 | 0.0003274 | unbekannt | Ungeklärte innere Abrechnung widerlegt behaupteten erfolgreichen Vollabschluss und bekannte Gesamtkosten. |

Bei den beiden technischen Fehlern sind nur zwei Rückgaben abgeschlossen; die dritte Ausführung bleibt abrechnungsseitig offen. Ein zufällig richtiger Gesamtbetrag oder eine richtige physische Aufrufzahl repariert kein doppeltes, falsch zugeordnetes oder fehlendes Journalereignis. Die vollständige JSON-Bewertung trennt tatsächlichen Ausgang, ursprünglichen Messbeleg und jede behauptete Messgröße.

Das Kostenblatt ergibt 0.0001701 USD für Input/Output, 0.0001747 USD für den bezahlten Fehlversuch, nochmals 0.0001701 USD für die frische Wiederholung, einen bekannten Nullpreis und den künstlichen Anbieter-Gesamtbetrag 0.00009 USD. Bekannte Summe: **0.0006049 USD**. Cachekosten lassen sich daraus nicht separat zuordnen. Der lokale Controller hat keine Modellaufrufe; seine tatsächliche CPU-Zeit fehlt. Automatische Retries sind verboten und erhalten keinen erfundenen Preis. Separate Reasoningkosten sind nicht unterstützt.

Die erste eigene S3-Routine behandelte die Zusatzrückgabe fälschlich als reguläre Vorgängernachricht und erzeugte dadurch weitere Herkunftshinweise. Diese Fehlannahme wurde dokumentiert und eng korrigiert. Beide Prüfstände bleiben erhalten; tatsächliche Nachrichten, Aufrufzahlen, Tokenwerte und sämtliche Beträge waren unverändert. Die früheren Sichtberichte wurden nicht überschrieben.

Dies ist eine separate Agentenprüfung kontrolliert künstlicher Belege. Sie belegt weder reale Tarifgültigkeit noch statistische Eignung oder Qualitätswirkung. Der Vergleich mit dem bestehenden Instrument und dem vorher gebundenen Sollschlüssel liegt weiterhin beim Koordinator.
