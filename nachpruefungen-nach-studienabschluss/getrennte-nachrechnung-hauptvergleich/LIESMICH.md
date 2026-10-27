# Getrennte Nachrechnung des Hauptvergleichs

Nach Abschluss der Studie wurde der Hauptvergleich ohne neue Modellaufrufe aus den gespeicherten Laufprotokollen aller 18.080 Läufe nachgerechnet (Abschnitt 6.2 der Arbeit). Die Implementierung ist eigens dafür geschrieben (`ausgabe-1/code/nachrechnung.py`). Sie erhielt weder den Code von Framework und Auswertung noch die ausgewerteten Zeilen und lief in einer macOS-Sandbox, die den Lesezugriff darauf sperrte (`isolation/`).

Ablauf:
1. Die Vorabfestlegung mit Rechenregeln, Toleranzen und Abweichungsklassen (`VORAB-N.md`, `eingang/AUFTRAG.md`) wurde vor der Implementierung im privaten Projekt-Repository festgeschrieben, Commit `268c0ddb8`.
2. Die Ausgabe der Implementierung wurde vor jedem Vergleich mit Prüfsumme gesichert und dort festgeschrieben, Commit `053c6d10d`.
3. Erst danach verglich `vergleich/vergleich.py` die Ausgabe mit den ausgewerteten Zeilen und der Arbeit (`vergleich/bericht-1/`). Die Meldungen ordnete eine weitere getrennte Instanz ein (`EINORDNUNG-1.md`).

Ergebnis: Alle Einzelwerte der 18.080 Läufe stimmten im Rahmen der vorab festgelegten Toleranzen überein. Die Bootstrapgrenzen wichen um höchstens 0,009 Prozentpunkte beziehungsweise 0,0002 ab, und die Entscheidungsregel ergab dasselbe Urteil. Die vier Meldungen des Vergleichs gehören alle zur Klasse (c) der Vorabfestlegung.

Nicht enthalten:
- die 18.080 Laufprotokolle wegen ihres Umfangs; `eingang/MANIFEST.sha256` bindet sie mit Prüfsumme
- der Dev-Bestand von MuSiQue, das Bewertungsskript von MuSiQue sowie Plan- und Formatdateien, die schon an anderer Stelle dieses Repositorys oder bei MuSiQue liegen
- die vollständigen Sitzungsprotokolle der Implementierung

`lauf-1/SICHERUNG.sha256` führt deshalb auch Dateien auf, die hier fehlen. Pfadangaben in den Dateien beziehen sich auf den Entwicklungsrechner.
