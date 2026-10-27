"""Schreibt eingang/METHODENAUSZUG.md: Abschnitt 4.4 und Anhang D der Arbeit (rev25, bereinigt),
wörtlich, ohne die Absätze zu den ergänzenden Vergleichen, zu nachträglichen Auswertungen und
ohne Bezug auf Ergebnisse aus Kapitel 6."""
import hashlib
from pathlib import Path

ARBEIT = Path(__file__).resolve().parent.parent
QUELLE = Path("/Users/jannikhiller/Desktop/ai operations/Studium OS/Masterarbeit/output/council-feedback-rev25-2026-10-27/quellen/thesis-rev25-bereinigt.md")
SOLL_SHA = "023df612bfde1e7a9d54bf7191cf155674342d25178cc3e7ff74082bb11b68db"

AUSGELASSEN = {
    "[N4004]": "betrifft nur Referenz-, Runden- und Ausfallvergleich (Hoeffding-Intervalle)",
    "[N4005]": "betrifft nur die Kosten der ergänzenden Vergleiche",
    "[X0570]": "nimmt auf Ergebnisse aus Kapitel 6 und auf Entwicklungswerte Bezug",
    "[N4006]": "betrifft nachträgliche Auswertungen außerhalb des vorab festgelegten Hauptvergleichs",
    "[X1695]": "betrifft nur die Kosten der ergänzenden Vergleiche",
}

text = QUELLE.read_bytes()
assert hashlib.sha256(text).hexdigest() == SOLL_SHA
zeilen = text.decode("utf-8").split("\n")


def abschnitt(start_marker, ende_praefix):
    i = next(k for k, z in enumerate(zeilen) if z.startswith(start_marker))
    j = next(k for k in range(i + 1, len(zeilen)) if zeilen[k].startswith(ende_praefix))
    return zeilen[i:j]


teil44 = abschnitt("## 4.4 Zielgrößen und Entscheidungsregel [N0542]", "# 5 ")
teilD = abschnitt("# Anhang D Planungsrechnungen [X1692]", "# Literaturverzeichnis")

behalten, weg = [], []
for z in teil44 + [""] + teilD:
    kennung = z.split("]")[0] + "]" if z.startswith("[") else None
    if kennung in AUSGELASSEN:
        weg.append(kennung)
        continue
    behalten.append(z)
assert sorted(weg) == sorted(AUSGELASSEN), weg

kopf = [
    "<!-- status: Methodenauszug für die getrennte Nachrechnung N | 2026-10-27 -->",
    "",
    "# Methodenauszug: Abschnitt 4.4 und Anhang D der Arbeit",
    "",
    "Quelle: Masterarbeit, Fassung rev25 (Sauberfassung, alle Änderungen angenommen), Datei `thesis-rev25-bereinigt.md`, "
    f"SHA-256 `{SOLL_SHA}`. Wortlaut unverändert. Kennungen in eckigen Klammern sind Absatzkennungen der Word-Datei; "
    "Tabellenzellen sind mit „·“ eingerückt; ⟦Q⟧, ⟦F*⟧ und andere Ausdrücke in ⟦ ⟧ sind Formelobjekte der Arbeit "
    "(⟦Q⟧ = aufgabenabhängige Auswahl, Arm Q; ⟦F*⟧ = feste Referenz, Arm F).",
    "",
    "Ausgelassen, ohne Ersatz:",
]
for k in sorted(AUSGELASSEN):
    kopf.append(f"- {k}: {AUSGELASSEN[k]}")
kopf += ["", "Verweise auf andere Abschnitte der Arbeit (zum Beispiel 2.4, 6.1, 7.4) sind nicht Teil dieses Auszugs.", "", "---", ""]

ziel = ARBEIT / "eingang" / "METHODENAUSZUG.md"
ziel.write_text("\n".join(kopf + behalten).rstrip("\n") + "\n", encoding="utf-8")
print(ziel, len(behalten), "Zeilen;", "ausgelassen:", ", ".join(sorted(weg)))
