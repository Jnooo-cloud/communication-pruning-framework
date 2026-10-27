# Dritte Gegenprüfung der Vorabfestlegung N

Stand: 27.10.2026

## Urteil

**freigabefähig: nein (vorbehaltlich der Autorenfreigabe von F4 und F11).** Die Hashbindungen der Eingaben und Vergleichswerkzeuge sowie die Gegenproben sind jetzt stimmig. Die Isolierung lässt aber Zugriff auf frühere Probesitzungen zu, und die Beschreibung sowie die geplante Versionsbindung sind noch widersprüchlich. F4 und F11 stehen korrekt als Vorschläge mit ausstehender Autorenfreigabe. Vor deren Freigabe und dem gebundenen Zeitnachweis darf die getrennte Implementierung nicht starten.

## Muss

### 1. Der freigegebene Arbeitsbaum enthält frühere Sitzungen

`isolation/sperre.sb:4-12` sperrt `/Users`, `/private/tmp`, `/private/var/folders` und `/Volumes`, erlaubt aber den gesamten Unterbaum `/private/tmp/n-isoliert-2026-10-27` zum Lesen und Schreiben. `isolation/starten.sh:6-10` verwendet diesen Unterbaum für den normalen Lauf und dessen `probe`-Unterordner; es prüft nur, ob `W/arbeit` existiert. `mkdir -p` erhält vorhandene Inhalte in `codex-home` und `tmp`.

Der Probeordner war bei dieser Prüfung bereits vorhanden. Darin lagen `probe/lauf.log`, `probe/letzte-antwort.txt` sowie frühere Codex-Dateien wie `probe/codex-home/thread_history_1.sqlite`, `logs_2.sqlite` und `memories_1.sqlite`. Da derselbe Profilgrant den ganzen Elternordner freigibt, kann ein normal gestarteter Prozess diese Probesitzung lesen. Das ist aus Profil und Dateipfaden ableitbar; ein zusätzlicher Leseversuch innerhalb der Sandbox wurde nicht ausgeführt. Ebenfalls möglich ist, dass ein früher abgebrochener Lauf `W/codex-home` oder `W/tmp` hinterlässt und ein späterer Start diese Verzeichnisse wiederverwendet.

Der direkte Zugriff auf die Thesis, den Framework- und Studiencode sowie `P-ROWS.json` und `P-ANALYSIS.json` unter `/Users` ist durch das Profil gesperrt; die dokumentierten Fehler beim Lesen von `/Users` und des Frameworkpfads stützen das (`TEST-ERGEBNIS.md:10-15`). Bereitgestellt werden aber bewusst die Rohprotokolle mit Antworten, Status und Beträgen sowie Methodik-, Plan- und Bewertungsdateien (`VORAB-N.md:28-41, 303(c)`).

**Fix:** Einen neuen, zufälligen Laufordner verwenden und ausschließlich dessen konkrete Arbeits-, `CODEX_HOME`- und temporäre Pfade freigeben. Vor dem Start alle drei auf Nichtexistenz prüfen. Für `--probe` ein getrenntes Profil verwenden, das den normalen Laufordner nicht freigibt. So kann die Bezeichnung „ohne frühere Sitzungen“ technisch eingehalten werden.

### 2. Die Sandbox erlaubt auch Schreibzugriff auf die Host-Anmeldedatei

`isolation/sperre.sb:12` erlaubt auf `~/.codex/auth.json` ausdrücklich sowohl `file-read*` als auch `file-write*`. `isolation/starten.sh:31` verlinkt diese Hostdatei in das freigegebene `CODEX_HOME`. `VORAB-N.md:303(b)` beschreibt dagegen nur, dass die Datei lesbar ist; der Probelauf testet keinen Schreibversuch auf diese Ausnahme.

**Fix:** Die Ausnahme für die Hostdatei auf Lesen beschränken, sofern Codex damit starten kann. Falls Schreibzugriff benötigt wird, eine kurzlebige, für diesen Zweck begrenzte Anmeldedatei statt der Hostdatei bereitstellen und dies als eigenes Risiko ausweisen. Lesen und Schreiben getrennt testen.

### 3. Die Versionsbindung erfasst die neue Isolation nicht

`VORAB-N.md:239` listet für den geplanten gezielten Commit `VORAB-N.md`, `README.md`, Eingabedateien, `werkzeuge/`, `pruefung/` und `vergleich/` auf. `isolation/starten.sh`, `isolation/sperre.sb` und die neuen Testbelege fehlen. Sie stehen auch nicht in der Prüfsummentabelle `VORAB-N.md:316-332`. Der neue Hash des Eingangsmanifests bindet diese Dateien nicht. Damit würde der vorgesehene Commit den geprüften Startweg und die Sandbox nicht festschreiben.

**Fix:** `starten.sh`, `sperre.sb` und die maßgeblichen Isolationstestbelege in die Commitliste und Prüfsummentabelle aufnehmen. Den Commit als Zeitanker erst nach den Autorenentscheidungen zu F4/F11 erstellen und seine Kennung dokumentieren. `VORAB-N.md:5` nennt diesen Zeitanker weiterhin als offen.

### 4. Veraltete Aussagen widersprechen dem aktuellen Stand

`VORAB-N.md:48` sagt noch, es gebe keine technische Lesesperre und die Arbeit erfolge „ohne Netz“. Das widerspricht der neuen Erläuterung `VORAB-N.md:297-304`: Dort sind bestimmte Pfade technisch gesperrt, der Netzwerkzugriff von Befehlen aber ausdrücklich nicht. `README.md:21-24` sagt weiterhin, O1 bis O5 seien entschieden, obwohl F4/F11 in `VORAB-N.md:286, 293, 308-309` als Vorschläge mit ausstehender Freigabe markiert sind. Außerdem unterscheidet README Zeile 24 den Modellkanal nicht von Netzwerkzugriffen durch ausgeführte Befehle.

**Fix:** Die alten Sätze in `VORAB-N.md:48` und `README.md:21-24` an den aktuellen Stand anpassen. Die Sperre auf die tatsächlich gesperrten Pfade begrenzen, Netzwerkzugriffe von Befehlen als nicht technisch blockiert kennzeichnen und F4/F11 weiterhin als freigabeoffen ausweisen.

Nach Ablage dieser dritten Gegenprüfung sind außerdem `VORAB-N.md:5` und `README.md:1,22` mit „zwei Gegenprüfungen“ beziehungsweise „dritte Gegenprüfung ausstehend“ zu aktualisieren. Das ist ein Statushinweis, keine Freigabe.

## Soll

### Netzwerkprüfung und Anmeldedatei enger behandeln

`VORAB-N.md:303(a)` kündigt eine Prüfung des vollständigen Sitzungsprotokolls an. `starten.sh:35-39` schreibt aber nur `lauf.log` und `letzte-antwort.txt`; eine Protokollsuche oder deren Sicherung ist dort nicht eingebaut. Außerdem enthält `isolation/TEST-v2-lauf.log:1` einen `rmcp::transport::worker`-Fehler mit Verweis auf `mcp.firecrawl.dev` und `invalid_token`. Das belegt einen Authentifizierungsfehler eines Firecrawl-Connectors, nicht einen erfolgreichen Abruf. Die angekündigte Suche nach Befehlsnamen nennt MCP-Connectoren nicht ausdrücklich. Weil das Profil Netzwerk nicht sperrt und `auth.json` lesbar ist, kann ein Prozess die Anmeldedatei möglicherweise über einen Netzwerkweg offenlegen; das ist eine Folgerung aus den eingeräumten Rechten, kein im Probelauf belegtes Ereignis.

**Fix:** Den Umfang der Nachlaufprüfung festlegen und die vollständigen Codex- und Connector-Ereignisse sichern. Nicht benötigte MCP-Connectoren abschalten oder ausdrücklich als zulässige Netzwerkverbindungen aufführen. Die mögliche Nutzung oder Weitergabe des Anmeldetokens als Risiko benennen, statt sie nur als lokale Kontosicherheit einzuordnen.

### Laufzeitpfade vor dem Start festlegen

`isolation/starten.sh:33` löst `node` und `codex` über den geerbten `PATH` auf, bevor `env -i` angewandt wird. In der hier geprüften Umgebung zeigen beide Pfade auf `~/.nvm/versions/node/v25.2.1/bin`; das Skript erzwingt diese Herkunft aber nicht.

**Fix:** Die erwarteten absoluten Pfade fest eintragen oder die aufgelösten Pfade vor dem Start gegen die erlaubte Laufzeit prüfen. So kann ein anderer aufrufender `PATH` die verwendeten Programme nicht ändern.

## Prüfungsergebnisse

- In einer temporären Kopie liefen `/opt/anaconda3/bin/python -I vergleich/gegenprobe.py`, `werkzeuge/leckpruefung.py` und `werkzeuge/pruefe_wortgleichheit.py` jeweils mit Exit 0. Die Gegenprobe bestand alle sechs Gruppen; die Leckprüfung meldete 18.092 Dateien, 18.080 Protokolle, 120 Ergebniszahlen und 2.474 Textformen; die Wortgleichheitsprüfung meldete `wortgleich`.
- Alle 18.091 Einträge aus `eingang/MANIFEST.sha256` stimmen mit den Dateien überein; keine Datei fehlt, ist zusätzlich oder weicht ab. Der Manifesthash ist `4a7ef3f82031fc0d04bdb0f80b4cb1ca8ade16b4dfbb8bcb778de83f06b2f19f`.
- Die SHA-256-Werte der Eingabetabelle und der Prüfsummentabelle in `VORAB-N.md` stimmen mit den Eingabedateien, den gebundenen Quellbelegen und den aufgeführten Dateien überein. Die Paketgröße von 448.900.017 Bytes stimmt ebenfalls.
- Der vorhandene Probelauf wurde nicht wiederholt, weil `/private/tmp/n-isoliert-2026-10-27/probe` bereits existierte. `starten.sh` wurde nicht ohne `--probe` ausgeführt. Es gab keine Netzwerkzugriffe in dieser Gegenprüfung.

## Noch offene Grenze

Die Gegenprüfung bestätigt nicht die vollständige Wirksamkeit aller Sandboxregeln durch einen neuen Lauf. Sie bestätigt auch nicht die unabhängige Richtigkeit des verwendeten Studienplans oder der Paarzuordnung. Der optionale künstliche Überlappungsfall für die Deduplizierung unbekannter Beträge aus Gegenprüfung 2 wurde nicht erneut ausgeführt; die Deduplizierung ist im Auftrag festgelegt.
