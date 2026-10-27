<!-- status: Vergleich N, maschinell | 2026-10-27T22:36:15Z -->

# Vergleich der getrennten Nachrechnung N

| Eingabe | SHA-256 |
|---|---|
| AUSGABE.sha256 | `1c467a83784cecc738e9e36d107b3853b8999721820cb4d456def9dd31b62b8d` |
| eingang/MANIFEST.sha256 | `4a7ef3f82031fc0d04bdb0f80b4cb1ca8ade16b4dfbb8bcb778de83f06b2f19f` |
| P-ROWS.json | `f22b12017abe4f93a89fcb29dd55728e78c31392bcc8895ebbcf47672c00fcd0` |
| P-ANALYSIS.json | `fc4be29676749d7611d7c3f0d11e912193e4588609acb5d4734a15c387dcba65` |
| vergleich.py | `aaeb2cf80b1ff94cbe3255b516b4216925d671d6f022291c8d4dbb151a6a00bf` |

Meldungen gesamt: **4**

- lauf: 0
- plausibilitaet: 0
- vollstaendigkeit: 0
- intern: 2
- p-analysis: 0
- arbeit: 2

Läufe mit Meldung: 0

Größte Abweichung der Bootstrapgrenzen über beide Seeds (Originaleinheit):

- differenz.untere: 8.609819988887601e-05
- differenz.obere: 2.643042508580079e-05
- verhaeltnis.untere: 5.6746220173264916e-05
- verhaeltnis.obere: 0.00017913166953253956

## Gedruckte Werte gegen Arbeit 6.3

Die Toleranzprüfung der Bootstrapgrenzen und der exakte Vergleich ihrer kaufmännischen Rundung sind getrennt.

| Größe | Sollwert | Nachrechnung ungerundet | Kaufmännisch gerundet | Toleranz | Rundung | Quelle |
|---|---:|---:|---:|---|---|---|
| arme.Q.anteil_exakt_richtig | 31.99 | 31.9911504424778800 | 31.99 | nicht festgelegt | bestanden | [N1006] |
| arme.F.anteil_exakt_richtig | 36.21 | 36.2057522123893800 | 36.21 | nicht festgelegt | bestanden | [N1006] |
| qualitaetsdifferenz.schaetzer | -4.21 | -4.214601769911504500 | -4.21 | nicht festgelegt | bestanden | [N1006], [N1011] |
| kostenverhaeltnis.schaetzer | 1.169 | 1.1692640311394336 | 1.169 | nicht festgelegt | bestanden | [N1013] |
| arme.Q.kosten_summe_usd | 14.44 | 14.43511769 | 14.44 | nicht festgelegt | bestanden | [N1013] |
| arme.F.kosten_summe_usd | 12.35 | 12.34547314 | 12.35 | nicht festgelegt | bestanden | [N1013] |
| arme.Q.f1_mittel | 0.436 | 0.4359280383754858 | 0.436 | nicht festgelegt | bestanden | [N1015] |
| arme.F.f1_mittel | 0.481 | 0.48077504695132584 | 0.481 | nicht festgelegt | bestanden | [N1015] |
| bootstrap.S1.differenz.untere | -4.90 | -4.898773697542700 | -4.90 | bestanden | bestanden | [N1011] |
| bootstrap.S1.differenz.obere | -3.54 | -3.541100865762044500 | -3.54 | bestanden | bestanden | [N1011] |
| bootstrap.S1.verhaeltnis.untere | 1.162 | 1.1620463507363719 | 1.162 | bestanden | bestanden | [N1013] |
| bootstrap.S1.verhaeltnis.obere | 1.176 | 1.1765393418022732 | 1.177 | bestanden | nicht bestanden | [N1013] |
| bootstrap.S2.differenz.untere | -4.90 | -4.89293344682147300 | -4.89 | bestanden | nicht bestanden | [N1011] |
| bootstrap.S2.differenz.obere | -3.54 | -3.54241849747942300 | -3.54 | bestanden | bestanden | [N1011] |
| bootstrap.S2.verhaeltnis.untere | 1.162 | 1.1621153949054066 | 1.162 | bestanden | bestanden | [N1013] |
| bootstrap.S2.verhaeltnis.obere | 1.176 | 1.1763650321327872 | 1.176 | bestanden | bestanden | [N1013] |

## Meldungen

| Ebene | Lauf | Größe | Feld | Wert N | Sollwert | Quelle | Regel |
|---|---|---|---|---|---|---|---|
| intern | None | bootstrap.S1 | zeilen_tabelle_4_5 | ['N0560', 'N0562', 'N0564', 'N0566'] | ['[N0560]', '[N0562]', '[N0564]', '[N0566]'] | eigene Grenzen, AUFTRAG 4.6 | identisch |
| intern | None | bootstrap.S2 | zeilen_tabelle_4_5 | ['N0560', 'N0562', 'N0564', 'N0566'] | ['[N0560]', '[N0562]', '[N0564]', '[N0566]'] | eigene Grenzen, AUFTRAG 4.6 | identisch |
| arbeit | None | bootstrap.S1.verhaeltnis.obere | rundung | {'ungerundet': '1.1765393418022732', 'gerundet': '1.177'} | 1.176 | Arbeit rev25, 6.3 [N1013] | kaufmännisch auf 3 Stellen gerundet, dann exakt verglichen |
| arbeit | None | bootstrap.S2.differenz.untere | rundung | {'ungerundet': '-4.89293344682147300', 'gerundet': '-4.89'} | -4.90 | Arbeit rev25, 6.3 [N1011] | kaufmännisch auf 2 Stellen gerundet, dann exakt verglichen |
