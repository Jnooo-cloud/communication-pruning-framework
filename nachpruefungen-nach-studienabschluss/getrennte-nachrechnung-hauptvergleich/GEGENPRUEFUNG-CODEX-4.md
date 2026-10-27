# Vierte Gegenprüfung der Vorabfestlegung N

Stand: 27.10.2026

## Urteil

**freigabefähig: nein (vorbehaltlich der Autorenfreigabe von F4 und F11).** Die Isolation der bisherigen drei Muss-Punkte ist im aktuellen Profil und Startskript umgesetzt. Die Hashwerte und die drei angeforderten Skriptprüfungen stimmen. Vor einem gebundenen Commit ist die Belegbindung aber noch nicht geschlossen: Der Auditbericht zur Isolation ist nicht einzeln gehasht, und diese vierte Gegenprüfung steht naturgemäß noch nicht in der Commit- und Prüfsummenliste. Ein aktueller erneuter Probelauf konnte in dieser Ausführungsumgebung die Sandbox nicht starten. F4 und F11 sind weiterhin Vorschläge; eine Freigabe durch Jannik liegt nicht vor.

## Status der dritten Gegenprüfung

| Punkt | Status | Beleg |
|---|---|---|
| **Muss 1: frühere Sitzungen** | **Im Profil und Startskript erfüllt; aktuelle erneute Funktionsprobe nicht möglich.** `starten.sh:13-14` erzeugt pro Start mit `mktemp -d` einen neuen Ordner und legt dessen drei Unterordner mit `mkdir` ohne Wiederverwendung an. `sperre.sb:4-10` sperrt `/private/tmp` und gibt nur den aktuellen Parameter `LAUF` frei. Der gespeicherte v3-Probelauf zeigt die Verweigerung von `ls /private/tmp` und `ls /private/tmp/n-isoliert-2026-10-27` (`isolation/TEST-v3-lauf.log`, `isolation/TEST-ERGEBNIS.md`). Ein gesonderter Zugriff auf einen älteren Geschwisterordner `/private/tmp/n-lauf-*` ist dort nicht protokolliert; er liegt nach der Profilregel ebenfalls unter dem gesperrten Unterbaum. Der von mir einmal gestartete neue Probelauf scheiterte, bevor Codex startete; siehe Prüfgrenze unten. |
| **Muss 2: Anmeldedatei** | **Erfüllt, mit begrenztem Testnachweis.** `sperre.sb:12` erlaubt `auth.json` nur lesend; `starten.sh:37` verknüpft sie in das neue CODEX_HOME. Der v3-Probelauf protokolliert einen gescheiterten Schreibversuch auf diese Datei (`isolation/TEST-v3-lauf.log`). Die aktuelle Beschreibung benennt auch das mögliche Weitergeben des lesbaren Tokens über das Netz (`VORAB-N.md:304(b)`). Der Authentifizierungsinhalt wurde in dieser Gegenprüfung nicht geöffnet. |
| **Muss 3: Versionsbindung** | **Teilweise erfüllt.** `VORAB-N.md:239` nimmt Sandbox, Startskript, Protokollprüfer und Testergebnis in die geplante Commitliste auf. Die Tabelle in `VORAB-N.md:315-338` hasht diese vier Dateien. `isolation/TEST-v3-AUDIT.md` und `isolation/TEST-v3-lauf.log` haben dort keinen eigenen Hash; „Probeprotokolle“ in Zeile 239 benennt die konkreten Dateien nicht. Der jetzt vorliegende Bericht `GEGENPRUEFUNG-CODEX-4.md` fehlt ebenfalls noch in der Liste und Tabelle. |
| **Muss 4: veraltete Aussagen** | **Inhaltlich erfüllt; Statuszähler nach dieser Gegenprüfung veraltet.** `VORAB-N.md:48` nennt technische Lese- und Schreibsperren und sagt ausdrücklich, dass Befehls-Netzwerkzugriffe nicht technisch gesperrt sind. `README.md:22-24` lässt F4/F11 offen und unterscheidet den Modellkanal von Netzwerkzugriffen der Befehle. Die dort genannten drei Gegenprüfungen und die ausstehende vierte Prüfung müssen jetzt aktualisiert werden. |
| **Soll: Nachlaufprüfung, Netzwerk und Anmeldedatei** | **Teilweise erfüllt.** `VORAB-N.md:303-304` beschreibt die Prüfung der Sitzungsdateien, die erkannten Muster, abgeschaltete Zusatzdienste und das Tokenrisiko. `pruefe_protokoll.py:13-39` liest Codex-Sitzungsdateien und schreibt Auditdateien. Die Vorabfestlegung sagt, Protokoll und Audit würden „mit der Ausgabe“ festgeschrieben (`VORAB-N.md:303`); `README.md:24-25` nennt aber keinen genauen Ablagepfad und keinen Schritt, der diese Dateien in die gesicherte Ausgabe übernimmt. |
| **Soll: Laufzeitpfade** | **Erfüllt.** `starten.sh:8-12` legt Node, Codex und Python als absolute Pfade fest und prüft die Dateien sowie den aufgelösten Codex-Pfad vor dem Start. Die aktuellen Node- und Codex-Pfade liegen unter der erlaubten Version `v25.2.1`. |

## Verbleibende Befunde

### Muss

1. **Isolationstest und vierte Gegenprüfung noch nicht vollständig in der Bindungsliste.** Der Hash der Eingangsdatei allein bindet die Isolation nicht; zwar sind die zentralen Programmdateien und `TEST-ERGEBNIS.md` erfasst, aber Auditbeleg und Laufprotokoll fehlen in der Prüfsummentabelle. Nach Ablage dieses Berichts ist auch er nicht mehr von der Formulierung „drei Codex-Gegenprüfungen“ umfasst. **Fix:** In `VORAB-N.md:239` `GEGENPRUEFUNG-CODEX-4.md`, `isolation/TEST-v3-AUDIT.md` und `isolation/TEST-v3-lauf.log` ausdrücklich nennen. Für diese Dateien die SHA-256 in Abschnitt 14 ergänzen und anschließend die Tabelle erneut vollständig prüfen. Den Commit erst nach den ausdrücklich festgehaltenen Autorenentscheidungen zu F4 und F11 erstellen.

### Soll

1. **Das Profil ist keine vollständige Allowlist.** `isolation/sperre.sb:2` beginnt mit `(allow default)`; gesperrt werden anschließend nur `/Users`, `/private/tmp`, `/private/var/folders` und `/Volumes` (Zeilen 4-8). Die bekannten Projekt-, Studiencode- und Ergebnisdateien unter `/Users` sowie frühere temporäre Sitzungen unter `/private/tmp` sind von diesen Regeln erfasst. Ich habe keinen direkten Freigabepfad zu diesen bekannten Dateien gefunden. **Hypothese:** Eine Kopie sensibler Dateien an einem anderen, nicht gesperrten Ort wäre nach dem Profil lesbar und grundsätzlich auch beschreibbar. **Fix:** Wenn „geschlossene Sandbox“ eine Beschränkung auf die benötigten Ressourcen meint, auf eine Sperre als Standard umstellen und nur Laufordner sowie nachgewiesene Laufzeitdateien gezielt freigeben. Danach die benötigten Systempfade testen und die Isolationsbeschreibung an den tatsächlichen Umfang anpassen.

2. **Die Protokollprüfung vergleicht Pfade als Zeichenfolgenpräfixe.** `isolation/pruefe_protokoll.py:10` trägt den Laufpfad ohne abschließende Pfadgrenze als erlaubt ein; Zeile 30 prüft mit `startswith`. Ein Pfad wie `<LAUF>-kopie/...` würde dadurch als innerhalb des Laufordners gewertet, obwohl er ein Geschwisterpfad ist. Das Sandboxprofil sperrt diesen Geschwisterpfad weiterhin, der Auditbericht könnte ihn aber übersehen. **Fix:** Pfade mit einer Komponentenprüfung wie `Path.relative_to(LAUF)` oder gleichwertig vergleichen und einen Geschwisterpfad als Gegenprobe ergänzen.

3. **Der Sicherungsort des vollständigen Laufprotokolls bleibt unbestimmt.** Die Nachlaufprüfung erzeugt `AUDIT.json` und `AUDIT.md` im Laufordner; die vollständigen Codex-Sitzungsdateien liegen unter dessen CODEX_HOME. Die Vorabfestlegung sagt nur, sie würden „mit der Ausgabe“ festgeschrieben, während die README den konkreten Schritt auslässt. **Fix:** In `README.md` und `VORAB-N.md` den genauen Zielpfad und den Sicherungsschritt für Sitzungsdateien, `lauf.log`, `AUDIT.json` und `AUDIT.md` festlegen; die Dateien vor dem Vergleich gemeinsam mit der Ausgabe hashen und sichern.

4. **Der dokumentierte Prüfstand ist nach dieser Ablage veraltet.** `VORAB-N.md:5` und `README.md:1,22` nennen noch drei abgeschlossene Gegenprüfungen und eine vierte als ausstehend. **Fix:** Die Statusangaben auf vier vorliegende Gegenprüfungen setzen und F4/F11 ausdrücklich weiter als freigabeoffen kennzeichnen.

### Kann

- Für einen neuen Lauf sollte die Probe einmal in einer Umgebung wiederholt werden, die das Anwenden des macOS-Sandboxprofils zulässt. Erst ein gestarteter Codex-Prozess kann die konkreten Leseversuche protokollieren. In dieser Gegenprüfung wurde der erlaubte Probestart einmal verwendet und nicht wiederholt.
- Diese Prüfung bewertet nicht die fachliche Richtigkeit der Rechenregeln oder der Zuordnung. Die Nachrechnung selbst wurde nicht ausgeführt. F4 und F11 bleiben Autorenentscheidungen.

## Prüfungen und Grenzen

- In der vorgegebenen Scratchpad-Kopie liefen `vergleich/gegenprobe.py`, `werkzeuge/leckpruefung.py` und `werkzeuge/pruefe_wortgleichheit.py` mit `/opt/anaconda3/bin/python -I` jeweils mit Exit 0. Die Gegenprobe bestand alle sechs Gruppen. Die Leckprüfung meldete 18.092 Dateien einschließlich Manifest, 18.080 Protokolle, 120 Ergebniszahlen und 2.474 Textformen; sie fand keinen Befund. Die Wortgleichheitsprüfung meldete `wortgleich`.
- Alle 18.091 Einträge im Eingangsmanifest stimmen mit den Dateien überein; es fehlen keine Dateien und es gibt keine zusätzlichen oder abweichenden Dateien. Die Manifestprüfsumme ist `4a7ef3f82031fc0d04bdb0f80b4cb1ca8ade16b4dfbb8bcb778de83f06b2f19f`. Die Paketgröße einschließlich Manifest beträgt 448.900.017 Bytes.
- Ich prüfte 34 SHA-256-Verweise aus den Tabellen in `VORAB-N.md` gegen die jeweils gebundenen Dateien und Quellen. Alle stimmten überein.
- `isolation/starten.sh --probe` erzeugte `/private/tmp/n-lauf-6ypmmeJf`, aber `sandbox-exec` meldete `sandbox_apply: Operation not permitted` und der Runner protokollierte `Codex-Exit: 71`. Es entstand keine Codex-Sitzungsdatei. `pruefe_protokoll.py` meldete deshalb null Sitzungsdateien und null Werkzeugaufrufe. Diese Ausführungsumgebung hat die Isolation also nicht erneut bestätigt; der Fehler belegt keine erfolgreiche oder fehlgeschlagene Lesesperre des Probeprozesses.
