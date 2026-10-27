"""Prüft (oder setzt mit --einfuegen einmalig ein), dass VORAB-N.md die Abschnitte 3 bis 5 aus
eingang/AUFTRAG.md wortgleich enthält; einziger Unterschied: Überschriften eine Ebene tiefer."""
import sys
from pathlib import Path

ARBEIT = Path(__file__).resolve().parent.parent
A, E = "<!-- REGELN-ANFANG -->", "<!-- REGELN-ENDE -->"
MARKE = "<!-- REGELN AUS AUFTRAG -->"


def block(text):
    i, j = text.index(A), text.index(E)
    return text[i:j + len(E)]


def tiefer(b):
    return "\n".join(("#" + z) if z.startswith("## ") else z for z in b.split("\n"))


auftrag = (ARBEIT / "eingang/AUFTRAG.md").read_text(encoding="utf-8")
vorab_pfad = ARBEIT / "VORAB-N.md"
vorab = vorab_pfad.read_text(encoding="utf-8")
soll = tiefer(block(auftrag))
if "--einfuegen" in sys.argv:
    if vorab.count(MARKE) != 1 or A in vorab:
        sys.exit("Marke fehlt oder Block schon eingesetzt")
    vorab_pfad.write_text(vorab.replace(MARKE, soll), encoding="utf-8")
    vorab = vorab_pfad.read_text(encoding="utf-8")
ok = block(vorab) == soll
print("wortgleich" if ok else "NICHT wortgleich")
sys.exit(0 if ok else 1)
