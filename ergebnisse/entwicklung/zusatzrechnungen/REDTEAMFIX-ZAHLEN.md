<!-- status: Rechenergebnis | Skript 06_thesis/review/redteamfix_zahlen.py | Eingaben hashgeprüft | 0 USD -->
# Zusatzrechnungen Red-Team-Fix

## Entwicklungsmatrix je Konfiguration (300 Entwicklungsaufgaben, zwei Runden)

| Konfiguration | exakt richtig (%) | richtig von 300 | Abstand zur besten (Pp.) | mittlere bekannte Kosten (USD) | Kosten relativ zu C01 | im Spielraum 1 Pp. | Wahl von Q (abschließend gelernt, 300) |
|---|---:|---:|---:|---:|---:|---|---:|
| C01 | 40,33 | 121 | 0,00 | 0,00111262 | 1,000 | ja | 49 |
| C02 | 29,33 | 88 | -11,00 | 0,00101557 | 0,913 | nein | 27 |
| C03 | 22,00 | 66 | -18,33 | 0,00103594 | 0,931 | nein | 13 |
| C04 | 38,33 | 115 | -2,00 | 0,00109934 | 0,988 | nein | 31 |
| C05 | 37,00 | 111 | -3,33 | 0,00106295 | 0,955 | nein | 26 |
| C06 | 28,67 | 86 | -11,67 | 0,00101743 | 0,914 | nein | 22 |
| C07 | 35,67 | 107 | -4,67 | 0,00139172 | 1,251 | nein | 19 |
| C08 | 36,33 | 109 | -4,00 | 0,00160195 | 1,440 | nein | 14 |
| C09 | 37,67 | 113 | -2,67 | 0,00142748 | 1,283 | nein | 25 |
| C10 | 34,33 | 103 | -6,00 | 0,00159982 | 1,438 | nein | 19 |
| C11 | 28,33 | 85 | -12,00 | 0,00136808 | 1,230 | nein | 13 |
| C12 | 24,67 | 74 | -15,67 | 0,00151239 | 1,359 | nein | 7 |
| C13 | 36,67 | 110 | -3,67 | 0,00139534 | 1,254 | nein | 22 |
| C14 | 36,00 | 108 | -4,33 | 0,00158353 | 1,423 | nein | 13 |

Feste Referenz nach der Regel: C01. Q nutzt 14 Konfigurationen, C01 49-mal von 300.

## Obergrenze: beste Konfiguration je Aufgabe (in der Stichprobe)

- mindestens eine Konfiguration exakt richtig: 152 von 300 Aufgaben (50,67 %)
- Abstand zu F* (40,33 %): 10,33 Prozentpunkte
- keine der 14 Konfigurationen richtig: 148 Aufgaben; alle 14 richtig: 33 Aufgaben
- C01 falsch, aber mindestens eine andere Konfiguration richtig: 31 Aufgaben
- mittlere Kosten der je Aufgabe günstigsten besten Konfiguration: 0,00087531 USD (0,787-fach C01)
- alle 300 Aufgabenmittel binär (0 oder 1): True

## Hauptstudie: Kosten der Läufe mit Modellausfall

- Q: 228 von 9040 Läufen, 0,30277739 von 14,43511769 USD, 2,10 %
- F: 224 von 9040 Läufen, 0,25788151 von 12,34547314 USD, 2,09 %
- alle: 452 von 18080 Läufen, 0,56065890 von 26,78059083 USD, 2,09 %

## Z55 F*: Tokens mal Tarif ohne Cache-Rabatt gegen gemeldete Beträge

- identical: Z53 Tarif 0,13516680 / gemeldet 0,11105094 (17,8 % darunter); Z55 Tarif 0,13516680 / gemeldet 0,13406727 (0,8 % darunter); gemeldet Z55 über Z53: 20,7 %; Tarifwerte gleich: True
- all: Z53 Tarif 0,15146890 / gemeldet 0,12570271 (17,0 % darunter); Z55 Tarif 0,15056260 / gemeldet 0,14946307 (0,7 % darunter); gemeldet Z55 über Z53: 18,9 %; Tarifwerte gleich: False

## Rundenvergleich nach Wahl der Rundenregel

- regel_1_runden: 1649 Blöcke; richtig mit Regel 575, mit einer Runde 577; nur Regel richtig 1, nur eine Runde richtig 3; Differenz -0,12 Pp.
- regel_2_runden: 1303 Blöcke; richtig mit Regel 422, mit einer Runde 425; nur Regel richtig 61, nur eine Runde richtig 64; Differenz -0,23 Pp.
