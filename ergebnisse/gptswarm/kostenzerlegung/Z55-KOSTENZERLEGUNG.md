<!-- status: entwurf | quellen: Rohantworten Z55 (runs/Z55-GPTSWARM-DEMO-001/live/blocks) und Z53 (runs/Z53-SCHNELLFORTSETZUNG-001/live/blocks) im alten Repo (nur lesend), runs/Z55-GPTSWARM-DEMO-001/ANALYSIS-001.json, 04_ergebnisse/dsr/Z55-GPTSWARM-DEMO-ERGEBNIS.md, runde3/CODEX.md | codex: GO Runde 2 (Runde 1 NO-GO; niedriger Befund Z. 14 danach wörtlich nach Codex-Vorschlag umgesetzt) | 2026-10-04 -->

# Z55: Zerlegung der Kostendifferenz gegenüber Z53

**Kurzbefund.** Die Mehrkosten von F\* in der GPTSwarm-Demo (+0,02376036 USD, +18,90 %) gehen rechnerisch vollständig auf weniger gecachte Prompt-Tokens zurück. In den 90 Blöcken mit identischen Anfragen und Antworten sind Prompt-, Completion- und Reasoning-Tokens Call für Call gleich; der einzige Unterschied sind 255.737 gecachte Tokens weniger (Z53 267.954, Z55 12.217), und das ergibt genau die Differenz von 0,02301633 USD. Modell, angeforderte Providerroute, Preis, Reasoning-Tokens und zusätzliche abgerechnete Versuche scheiden als direkte Abrechnungskomponenten aus. Warum der Anbieter in Z55 weniger aus dem Cache bediente, ist ungeklärt; die Daten passen zu einer Erklärung über den Laufaufbau (in Z53 gingen dieselben Anfragen oft wenige Sekunden vorher von anderen Armen raus, in Z55 lief F\* in jedem Block zuerst).

Skript: `z55_kostenzerlegung.py` (0 USD, keine API-Aufrufe). Rohwerte: `Z55-KOSTENZERLEGUNG.json`.

## Vorgehen

- Je Call aus den Rohantworten beider Läufe: `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `cached_tokens`, `cache_write_tokens`, `provider`, `model`, `usage.cost`. Z53-Calls über die `attempt_id` des jeweiligen Arms zugeordnet, bei mehreren Provider-Ordnern gilt der frische (gleiche Regel wie die Paritätsprüfung in Z55).
- Zuordnung Z55 zu Z53 über (Runde, Rolle). Gruppierung „identisch“ = Block mit identischen Requests und Antworten laut `ANALYSIS-001.json` (`per_block`).
- Preisformel aus den Daten abgeleitet und **für jeden Call exakt geprüft**: `cost = 1e-7 · (prompt − cached) + 1e-8 · cached + 4e-7 · completion` (USD je Token).
- Zerlegung der Differenz Z55 − Z53: Prompt-Volumen zum vollen Satz, entgangener Cache-Rabatt (9e-8 USD je gecachtem Token weniger), Completion, weitere abgerechnete Versuche, Rest. Algebraisch gleich der Preisformel; da die Formel für jeden Call einzeln stimmt, ist auch der Rest 0.
- Beschreibend: ob vor einem Call im selben Block schon ein byteidentischer Request (gleiche `request_sha256`) gesendet worden war, von welchem Arm und wie viele Sekunden vorher (`created`).

## Vorabprüfungen

| Prüfung | F\* | D |
|---|---|---|
| Armkosten je Block = Summe der Callkosten, Z55 | 100/100 | 100/100 |
| dasselbe, Z53 | 100/100 | 100/100 |
| Preisformel exakt, Z55 / Z53 | 488/488, 491/491 | 863/863, 869/869 |
| `provider` / `model` | überall „Google“ / `google/gemini-2.5-flash-lite` | ebenso |
| Reasoning-Tokens | 0 in allen Calls | 0 in allen Calls |
| weitere abgerechnete Versuche neben der finalen Antwort | keine | keine |

## Zerlegung F\*

Z53 0,12570271 USD, Z55 0,14946307 USD, Differenz +0,02376036 USD (+18,90 %).

| Komponente (USD) | 90 identische Blöcke | 10 übrige Blöcke | alle 100 |
|---|---:|---:|---:|
| Prompt-Volumen | 0 | −0,00087590 | −0,00087590 |
| entgangener Cache-Rabatt | +0,02301633 | +0,00165033 | +0,02466666 |
| Completion | 0 | −0,00003040 | −0,00003040 |
| weitere Versuche, Rest | 0 | 0 | 0 |
| **Summe** | **+0,02301633** | **+0,00074403** | **+0,02376036** |

Token in den identischen Blöcken (441 Calls je Lauf): Prompt 1.192.868 und Completion 39.700 in beiden Läufen gleich, Antworttexte Call für Call gleich; gecacht Z53 267.954, Z55 12.217. Über alle 100 Blöcke: gecacht Z53 286.291 von 1.330.221 Prompt-Tokens (21,5 %), Z55 12.217 von 1.321.462 (0,9 %).

Die zehn abweichenden Blöcke tragen netto 0,00074403 USD (3,1 % der Differenz): 0,00165033 USD weniger Cache-Rabatt, abzüglich 0,00090630 USD durch geringeres Prompt- und Completion-Volumen. Ein eigener Effekt der abweichenden Antworten ist darin nicht abgegrenzt.

Der Cache-Effekt allein ist mit 0,02466666 USD etwas größer als die Gesamtdifferenz (103,8 %); die drei Calls weniger in den abweichenden Blöcken senken die Kosten leicht. Mit dem Cache-Stand von Z53 hätte F\* in der Demo rechnerisch 0,12479641 USD gekostet, 0,7 % weniger als in Z53.

Verteilung auf die Calls der identischen Blöcke: 1:evidence +0,00843489, 1:linking +0,00687519, 2:linking +0,00394380, 2:evidence +0,00201942, 3:aggregator +0,00174303 USD.

## Zerlegung D

Z53 0,24139318 USD, Z55 0,25059007 USD, Differenz +0,00919689 USD (+3,81 %).

| Komponente (USD) | 96 identische Blöcke | 4 übrige Blöcke | alle 100 |
|---|---:|---:|---:|
| Prompt-Volumen | 0 | −0,00280580 | −0,00280580 |
| entgangener Cache-Rabatt | +0,01201176 | +0,00018333 | +0,01219509 |
| Completion | 0 | −0,00019240 | −0,00019240 |
| **Summe** | **+0,01201176** | **−0,00281487** | **+0,00919689** |

Auch bei D sind in den identischen Blöcken alle Tokenmengen außer `cached_tokens` gleich (gecacht Z53 317.828, Z55 184.364). In den übrigen Blöcken liegen sechs Calls weniger vor (Z55 863, Z53 869), was die Differenz teilweise ausgleicht.

## Warum weniger Cache? (beschreibend, nicht belegt)

| | F\* Z53 | F\* Z55 | D Z53 | D Z55 |
|---|---:|---:|---:|---:|
| Calls mit früherem byteidentischem Request im selben Block | 183 von 491 | 0 von 488 | 208 von 869 | 200 von 863 |
| Cache-Anteil dieser Calls | 56,9 % | – | 52,3 % | 31,4 % |
| Cache-Anteil der übrigen Calls | 0,7 % | 0,9 % | 2,4 % | 1,6 % |
| Abstand zum früheren Request, Median (Spanne) | 8 s (2 bis 34) | – | 5 s (2 bis 23) | 3 s (2 bis 6) |

- In Z53 liefen je Block sechs Arme (D, S-k, S, F, Z, Q) in blockweise gebundener Reihenfolge; D kam in 55 von 100 Blöcken vor F. Die früheren identischen Requests für F\* stammten von D, Q und Z.
- In Z55 liefen nur F\* und D, F\* in jedem Block zuerst (`ARMS = ("F", "D")`). F\* hatte daher nie einen Vorläufer; D konnte nur auf die F\*-Requests der Runde 1 folgen.
- Bei Calls mit identischem Vorläufer beträgt der Anteil gecachter Prompt-Tokens je Gruppe 31,4 bis 56,9 %, ohne solchen Vorläufer 0,7 bis 2,4 %. Das passt zu einem anbieterseitigen Cache, der wiederholte Eingaben in kurzem Abstand billiger abrechnet, beweist ihn aber nicht.

Belegt ist damit: Die Mehrkosten werden rechnerisch durch geringere Cache-Rabatte getragen; in den identischen Blöcken ist das die einzige Abweichung. Nicht belegt ist, warum weniger gecacht wurde. Die Armreihenfolge ist ein Indiz, kein kausaler Nachweis. Die Antwort meldet nur die Menge gecachter Tokens, nicht, welcher frühere Request den Cache-Eintrag erzeugt hat. Ob der Anbieter auch teilweise übereinstimmende Requests aus dem Cache bedient, ist hier nicht geprüft; die geringen Cache-Anteile ohne identischen Vorläufer (0,7 bis 2,4 %) zeigen nur, dass Cache auch ohne ihn vorkommt. Die Zuordnung über „früherer identischer Request“ ist deshalb ein Indiz.

## Ausgeschlossene direkte Abrechnungskomponenten

| Kandidat | Befund |
|---|---|
| Providerroute | Alle 2.711 Calls „Google“, gleiches Modell. Die angeforderte Route war in beiden Läufen gleich gebunden; die tatsächlich ausgeführte feinere Route steht nicht im Antwortobjekt und ist damit nicht direkt geprüft. |
| Preisänderung | Preisformel für jeden Call beider Läufe exakt erfüllt, Rest 0. |
| Reasoning-Tokens | 0 in allen Calls. |
| zusätzliche abgerechnete Versuche | keine; jeder Call hat genau eine abgerechnete Antwort. |
| mehr oder längere Antworten | in den identischen Blöcken gleiche Prompt- und Completion-Tokens; insgesamt hat Z55 sogar etwas weniger Calls und Tokens. |

## Folgerung für die Arbeit

Die Mehrkosten werden rechnerisch durch geringere Cache-Rabatte getragen. Ein isolierter Kosteneffekt der GPTSwarm-Ausführung lässt sich aus diesem Vergleich nicht bestimmen. Das stützt die bisherige Einordnung, dass Z55 keine Kostenaussage trägt. Zugleich zeigt der Befund, dass Cache-Bedingungen die Modellkosten eines Arms spürbar verschieben können: In den 90 identischen Blöcken, bei gleichen Prompt- und Completion-Tokens, entsprechen die Mehrkosten rund 21 % der Z53-Kosten dieser Blöcke (0,02301633 von 0,11105094 USD). Für die Studienpanels betrifft das die Armreihenfolge innerhalb eines Blocks; in Z53 war sie je Block gebunden, und der Cache-Anteil wurde in den Post-Checks berichtet (R 19,5 % zu 21,0 %, `RTF/log.md`). Ob die Armreihenfolge in P oder R/T/F die Kostenquotienten systematisch verschiebt, ist hier nicht geprüft.
