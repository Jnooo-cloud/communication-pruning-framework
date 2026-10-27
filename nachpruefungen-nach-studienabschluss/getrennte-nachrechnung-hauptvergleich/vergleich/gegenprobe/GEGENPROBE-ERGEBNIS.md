<!-- status: Gegenprobe zu vergleich.py, maschinell | 2026-10-27 -->

# Gegenprobe des Vergleichsskripts

Gesamt: **bestanden**

- vergleich.py SHA-256 `aaeb2cf80b1ff94cbe3255b516b4216925d671d6f022291c8d4dbb151a6a00bf`
- gegenprobe.py SHA-256 `ee746cd8be3518bdc6a46715e98bbc1913f9068a2bfdf2e073a761160a7046c4`
- P-ROWS.json SHA-256 `f22b12017abe4f93a89fcb29dd55728e78c31392bcc8895ebbcf47672c00fcd0`, P-ANALYSIS.json SHA-256 `fc4be29676749d7611d7c3f0d11e912193e4588609acb5d4734a15c387dcba65`
- eingang/MANIFEST.sha256 SHA-256 `4a7ef3f82031fc0d04bdb0f80b4cb1ca8ade16b4dfbb8bcb778de83f06b2f19f`

| Probe | erwartet | Ergebnis |
|---|---|---|
| A Nullprobe | keine Meldung, Exit 0 | Exit 0, 0 Meldungen, bestanden |
| B Reihenfolgeprobe | keine Meldung, Exit 0 | Exit 0, 0 Meldungen, bestanden |
| C Änderungsprobe | genau die 5 Änderungen auf Laufebene (6 Läufe), Kontrolle ungemeldet | Exit 1, 5 Änderungen in 6 Läufen gemeldet, Kontrolle ungemeldet, bestanden |
| D Feldprobe | Status, run_id, paarindex, arm, unbekannte Beträge, beide Endantwortfehler, Duplikat und Lücke gemeldet | Exit 1, erwartete Meldungen 9/9, bestanden |
| E Festschreibungsregeln | fehlender Hash, Zusatzdatei, doppelter und unsicherer Manifestpfad blockieren | Exit 2/2/2/2, bestanden |
| F Änderung nach Festschreibung | falsche Prüfsumme und geänderte Datei: Exit 2 | Exit 2/2, bestanden |

## Änderungsprobe im Einzelnen

| Nr. | Art | Lauf | Feld | alt | neu |
|---|---|---|---|---|---|
| 1 | EM gedreht | Z50-STUDY-v1:P:07431:F | exact_match | 0.0 | 1.0 |
| 2 | F1 verändert (+1e-8, Toleranz 1e-9) | Z50-STUDY-v1:P:07045:F | f1 | 0.07692307692307693 | 0.07692308692307692 |
| 3 | Aufrufzahl +1 | Z50-STUDY-v1:P:00689:F | gestartete_aufrufe | 5 | 6 |
| 4 | Betrag +0,0000001 US-Dollar | Z50-STUDY-v1:P:01624:F | bekannte_kosten_usd | 0.00076828 | 0.00076838 |
| 5 | Werte zweier Zeilen vertauscht | Z50-STUDY-v1:P:00858:F | ['f1', 'bekannte_kosten_usd'] | {'f1': 0.6666666666666666, 'cost_usd': '0.0013892'} | {'f1': 0.0, 'cost_usd': '0.0016352'} |
| 5 | Werte zweier Zeilen vertauscht | Z50-STUDY-v1:P:08567:F | ['f1', 'bekannte_kosten_usd'] | {'f1': 0.0, 'cost_usd': '0.0016352'} | {'f1': 0.6666666666666666, 'cost_usd': '0.0013892'} |

Kontrolle: Kontrolle: F1 um 1e-10 verändert (unter der Toleranz), keine Meldung erwartet; Lauf Z50-STUDY-v1:P:03566:F.

Gemeldet auf Laufebene (Lauf, Feld):

- Z50-STUDY-v1:P:00689:F, gestartete_aufrufe
- Z50-STUDY-v1:P:00858:F, bekannte_kosten_usd
- Z50-STUDY-v1:P:00858:F, f1
- Z50-STUDY-v1:P:01624:F, bekannte_kosten_usd
- Z50-STUDY-v1:P:07045:F, f1
- Z50-STUDY-v1:P:07431:F, exact_match
- Z50-STUDY-v1:P:08567:F, bekannte_kosten_usd
- Z50-STUDY-v1:P:08567:F, f1

## Feldprobe und erwartete Meldungen

| Mutation | Lauf | Erwartete Meldung | Ergebnis |
|---|---|---|---|
| status | Z50-STUDY-v1:P:05511:Q | lauf/status | gemeldet |
| run_id | Z50-STUDY-v1:P:00049:F | lauf/run_id | gemeldet |
| paarindex | Z50-STUDY-v1:P:07011:Q | lauf/paarindex | gemeldet |
| arm | Z50-STUDY-v1:P:01733:Q | lauf/arm | gemeldet |
| unbekannte_betraege | Z50-STUDY-v1:P:06827:F | plausibilitaet/unbekannte_betraege | gemeldet |
| endantwort_geaendert | Z50-STUDY-v1:P:04794:Q | lauf/endantwort | gemeldet |
| endantwort_fehlt | Z50-STUDY-v1:P:05499:F | lauf/endantwort | gemeldet |
| doppelter_lauf | Z50-STUDY-v1:P:04811:Q | lauf/lauf_kennung | gemeldet |
| fehlender_lauf | Z50-STUDY-v1:P:08694:F | lauf/vorhanden | gemeldet |

## Festschreibungsregeln

- ohne_ausgabe_sha: Exit 2, erwartet 2; vergleich.py: error: the following arguments are required: --ausgabe-sha
- extra_datei: Exit 2, erwartet 2; VORBEDINGUNG VERLETZT: nicht festgeschriebene Datei(en) in der Ausgabe: nicht-gelistet.txt
- doppelter_manifestpfad: Exit 2, erwartet 2; VORBEDINGUNG VERLETZT: doppelter Manifestpfad in AUSGABE.sha256: ZUGRIFFSPROTOKOLL.md
- unsicherer_manifestpfad: Exit 2, erwartet 2; VORBEDINGUNG VERLETZT: unsicherer Manifestpfad: '../unsicher.txt'

Folgemeldungen in abhängigen Kennzahlen (zulässig, weil die Pseudoausgabe ihre Punktwerte aus den veränderten Zeilen rechnet):

- p-analysis: arme.F.anteil_exakt_richtig (wert): 0.3621681415929204 statt 0.3620575221238938
- p-analysis: arme.F.kosten_summe_usd (wert): 12.34547324 statt 12.34547314
- p-analysis: arme.F.kosten_mittel_usd (wert): 0.00136564969469026548672566371681415929203539823008849557522124 statt 0.0013656496836283185840707964601769911504424778761062
- p-analysis: qualitaetsdifferenz.schaetzer (wert): -0.04225663716814159 statt -0.042146017699115045
- p-analysis: qualitaetsdifferenz.se (wert): 0.00346993863459671 statt 0.0034683236626088486
- p-analysis: kostenverhaeltnis.schaetzer (wert): 1.169264021668237 statt 1.1692640311394327
- p-analysis: kostenverhaeltnis.se (wert): 0.0036742541146988967 statt 0.003674363475411334
- arbeit: paarzahlen.gleich (wert): 8040 statt 8041
- arbeit: paarzahlen.nur_f (wert): 691 statt 690
- arbeit: saldo_zugunsten_f (wert): 382 statt 381
- arbeit: arme.F.anteil_exakt_richtig (rundung): {'ungerundet': '36.2168141592920400', 'gerundet': '36.22'} statt 36.21
- arbeit: qualitaetsdifferenz.schaetzer (rundung): {'ungerundet': '-4.22566371681415900', 'gerundet': '-4.23'} statt -4.21

Unzulässige Folgemeldungen: 0; fehlende Pflichtfolgemeldungen: keine; Siegel unverändert: True.
