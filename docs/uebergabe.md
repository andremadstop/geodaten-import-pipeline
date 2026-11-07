# Übergabesitzung als Schulung

Die Leistungsbeschreibung verlangt die Übergabe mit einer kurzen Einweisung für den weiteren Betrieb durch die TH (LB 3 und 9); sie kann per Videokonferenz stattfinden (Antworten 39 und 55). Wir legen sie als Schulung an: Die Teilnehmenden führen die Schritte selbst aus, wir erklären, was passiert und warum es so gebaut ist. Bei MOSIDI wechseln die Pflegenden; die Sitzung soll deshalb nicht zeigen, was die Pipeline kann, sondern was die TH danach ohne uns kann.

Dauer: ein halber Tag mit Pause, aufgeteilt in sieben Blöcke. Die Zeiten sind Planwerte. Grundlage sind die vorhandenen Dokumente; die Sitzung ersetzt sie nicht, sie zeigt, wo was steht.

## Vorbereitung

**Durch die TH, vor der Sitzung** (etwa eine Stunde, Hilfe per Mail):

1. Repository klonen (bis zur Übergabe aus dem Repository des Auftragnehmers, danach aus MOSIDI-ORG, Antwort 40).
2. Docker und Docker Compose auf einem Rechner, der `isk.geobasis-bb.de` und `download.statistik-berlin-brandenburg.de` erreicht (Liste: `docker compose run --rm --no-deps pipeline --ziele`).
3. `.env` aus `.env.beispiel` mit drei eigenen Passwörtern (`chmod 600`).
4. Wer den Vollumfang von INKAR nachstellen will: die Gesamtdatei unter `cache/` ablegen und `PIPELINE_INKAR_DATEI` setzen (README, „Start“). Für die Sitzung reicht die Schulungskonfiguration (unten, „Durch uns“) ohne INKAR. Die Prüfkonfiguration selbst enthält INKAR aktiv; ohne abgelegte Datei riefe `--alle` mit ihr den Rechner `www.bbr-server.de` ab, dessen robots.txt automatische Abrufe sperrt.
5. Einen Blick in den Lageplan (`docs/lageplan.svg`) und die ersten drei Schritte des [`rundgang.md`](rundgang.md).

**Durch uns:** Testdatenbank mit dem öffentlichen Schema bereit, eine Schulungskonfiguration (Kopie von `config/pruefkonfiguration.yaml` mit `aktiv: false` bei `inkar_gemeinden`, eingehängt wie eine eigene Prüfkonfiguration), ein vorbereiteter Fehlerfall (eine Quelle mit falscher Adresse in einer Kopie der Konfiguration), die Berichte des letzten Prüfstands zum Vergleich.

**Teilnehmende:** wer die Pipeline betreibt (Rechenzentrum oder Administration), wer Quellen pflegt (Entwicklungsteam MOSIDI), nach Möglichkeit wer die Daten nutzt (Forschende); die Projektleitung für die Abnahme.

## Agenda

| Block | Zeit | Inhalt | Wer macht was | Dokument |
|---|---|---|---|---|
| 1 | 20 min | **Worum es geht.** Die drei Tabellen von MOSIDI, was die Pipeline schreibt und was nie (Schema, fremde Zeilen, Raumdaten), die Grundhaltung: eine Transaktion je Quelle, gelöscht nur nach belegt vollständigem Abruf, Nullmenge und Rückgang halten an. Der Lageplan als Karte für den Rest der Sitzung | wir erklären, Fragen | README, `docs/lageplan.svg`, [`rundgang.md`](rundgang.md) 1 |
| 2 | 45 min | **Ein Lauf von Anfang bis Ende.** `docker compose up -d db`, `einrichten` als Administrator (was es anlegt: Schema, zwei Rollen, Rechte bis auf die Spalte, Katalogfunktion), dann `--probelauf --alle` mit der Schulungskonfiguration (Vorbereitung 4), danach ein echter Lauf. Gemeinsam den Textbericht und das JSON lesen: Status je Quelle, Zähler, Hinweise, Laufzeit; die Änderungskarte öffnen; das Quellenverzeichnis; `pipeline_meta.lauf`, `quellenlauf` und `aenderung` per SQL ansehen. Zweiter Lauf: alles unverändert, dritter Lauf: nicht fällig | Teilnehmende tippen, wir kommentieren | README „Start“, [`rundgang.md`](rundgang.md) 2 bis 8, `sql/pipeline_meta.sql` |
| 3 | 45 min | **Eine neue Quelle anbinden.** Eine weitere Objektart der LGB oder eine zweite Tabelle des Amts als Eintrag in `config/quellen.yaml`: Typ, Adresse, Schlüssel, `felder`, `ziel`, Rhythmus, Lizenz, Kontakt. Dann die drei Schritte: Eintrag, `einrichten` (Rechte auf neue Spalten), `--probelauf --nur NEU`. Fehler absichtlich einbauen (Tippfehler im Rhythmus, `zeitbudget_min: 0`) und sehen, wie die Pipeline vor der ersten Verbindung abbricht; dazu eine Datenzeile ohne Pflichtwert (`ziel.pflicht`), die mit Warnung ausgelassen wird, während ihr bisheriger Wert bleibt. Was eine Anpassung im Adapter bräuchte und was nicht (Antwort 64) | Teilnehmende schreiben den Eintrag | Kopf von `config/quellen.yaml`, [`betrieb.md`](betrieb.md) „Neue Quelle“, [`rundgang.md`](rundgang.md) 3 bis 5 |
| | 15 min | Pause | | |
| 4 | 40 min | **Ein Fehlerfall.** Vorbereitete Konfiguration mit unerreichbarer Quelle: der Lauf endet mit Rückgabe 1, die anderen Quellen sind geladen, der Bericht nennt die Ursache, der Meldungsentwurf an den Anbieter liegt bereit und wird nicht versendet. Dann der Rückgang-Schutz (eine BBOX verkleinern): alter Stand bleibt, Warnung, `--leerlieferung` nur mit Grund für einen Lauf. Dann eine Umfangsänderung (E52): Quelle hält an, Bestätigung mit `--umfang-bestaetigen`. Zuletzt `--status` als Zeile für die Überwachung und die Rückgabewerte 0, 1, 2 | Teilnehmende führen aus, wir deuten den Bericht | [`betrieb.md`](betrieb.md) „Störungen“ und „Überwachung“, [`entscheidungen.md`](entscheidungen.md) E4, E8, E34, E52 |
| 5 | 30 min | **Betrieb im Compose von MOSIDI.** `deploy/mosidi/docker-compose.pipeline.yml` neben `brandenburg_db`, `pipeline-einrichten` zuerst als Eigentümer der View oder Superuser (Katalogfunktion), systemd-Timer und `OnFailure`, `TimeoutStartSec` über der Summe der Zeitbudgets, Platz und Laufzeit des INKAR-Vollumfangs (24 GB nach dem Lauf, mindestens 66 GB währenddessen, 130 bis 160 min auf unserem Rechner), was `--probelauf` im Vollumfang bedeutet, Updates über Dependabot und `--probelauf`, Passwörter wechseln, Sicherung von `pipeline_meta` und `berichte/` | wir zeigen, TH entscheidet Weg der Compose-Korrektur (AP 6) | [`../deploy/mosidi/README.md`](../deploy/mosidi/README.md), [`betrieb.md`](betrieb.md), [`sicherheit.md`](sicherheit.md) |
| 6 | 20 min | **Für Forschung und Berichte.** Laufkennung als zitierbarer Datenstand, `pipeline_meta.aenderung` als Protokoll seit einem Lauf, `--kennzahlen` für Zwischenberichte, `CITATION.cff`, Herkunft und Lizenz je Quelle in `table_metadata` und im Quellenverzeichnis, Stand-Archiv (`archiv: true`) | wir zeigen | [`forschung.md`](forschung.md), [`vorlagen/projektsteckbrief.md`](vorlagen/projektsteckbrief.md) |
| 7 | 25 min | **Grenzen, offene Punkte, Abnahme.** Was die Pipeline nicht sieht (beschädigter Ziffern-Schlüssel, Zählprüfung beim Überspringen, Änderungskarte unvollständig), die fünf Klärungspunkte und ihr Stand, der Abnahmelauf (LB 11), das Abnahmeprotokoll ausfüllen, Nachbetreuung (30 Kalendertage per Mail) | gemeinsam | [`anforderungen.md`](anforderungen.md), [`vorlagen/abnahmeprotokoll.md`](vorlagen/abnahmeprotokoll.md), [`entscheidungen.md`](entscheidungen.md) |

Aufzeichnung der Sitzung: nur mit Einverständnis aller; Zugangsdaten werden während der Sitzung nicht gezeigt (Bildschirm teilen erst nach dem Anlegen der `.env`).

## Was die TH danach selbst kann

Abhaken am Ende der Sitzung; was offen bleibt, klären wir in der Nachbetreuung.

- [ ] Die Pipeline von Hand starten (`--alle`, `--nur`, `--probelauf`) und den Bericht lesen: Status, Zähler, Hinweise, Warnungen, Laufzeit.
- [ ] Eine neue Quelle eines vorhandenen Typs anbinden: Eintrag, `einrichten`, Probelauf, erster Lauf.
- [ ] Eine Zuordnung ändern (`ziel`, `felder`) und wissen, dass danach `einrichten` und ein Probelauf fällig sind.
- [ ] Einen Fehlerfall einordnen: Rückgabe 1 oder 2, Status FEHLER, ANGEHALTEN, unvollständig; wissen, wann nichts gelöscht wurde und warum.
- [ ] Den Meldungsentwurf an einen Anbieter finden, prüfen und entscheiden, ob er versendet wird.
- [ ] Eine bestätigte Leerlieferung (`--leerlieferung`) und eine bestätigte Umfangsänderung (`--umfang-bestaetigen`) freigeben, und wissen, dass beides nur für einen Lauf bzw. einen Umfang gilt.
- [ ] `--status` in die vorhandene Überwachung einhängen und die Rückgabewerte deuten.
- [ ] Den Timer prüfen (`systemctl list-timers`), das Journal lesen (`journalctl -u geodaten-import.service`), einen Lauf nachholen.
- [ ] Ein Update einspielen: Pull Request lesen, bauen, Probelauf, bei Bedarf zurück auf den vorigen Stand.
- [ ] Nach einem Update, das `pipeline_meta` erweitert, `einrichten` ausführen (der Lauf meldet es).
- [ ] Passwörter der drei Rollen wechseln.
- [ ] `pipeline_meta` und `berichte/` sichern und wissen, was beim Verlust jeder der beiden passiert.
- [ ] Aus `pipeline_meta.aenderung` abfragen, was sich seit einem Lauf je Quelle geändert hat; eine Laufkennung als Datenstand angeben.
- [ ] Die Entscheidungen (`entscheidungen.md`) als Nachschlagewerk nutzen: warum etwas so gebaut ist und wann es neu zu prüfen ist.

## Checkliste Betrieb

Für die erste Woche nach der Übergabe, aus [`betrieb.md`](betrieb.md) und [`sicherheit.md`](sicherheit.md) zusammengezogen.

**Einmal, beim Einrichten**

- [ ] `.env` mit eigenen, zufälligen Passwörtern je Rolle, `chmod 600`; nicht im Repository.
- [ ] `pipeline-einrichten` zuerst als Eigentümer der View `source_granularities` oder als Superuser ausgeführt (legt den Eigentümer der Katalogfunktion fest); Meldung über fremd vergebene Rechte gelesen.
- [ ] Vorhandene direkte `TRUNCATE`-Rechte und Rechte über PUBLIC oder Standardrechte geprüft (`einrichten` erfasst sie nicht; `sicherheit.md`).
- [ ] Platz auf dem Rechner von `brandenburg_db`: mit INKAR im Vollumfang rund 24 GB nach dem Lauf, mindestens 66 GB währenddessen, Reserve darüber.
- [ ] Ausgehende Verbindungen auf die Rechner aus `--ziele` begrenzt, wo die Umgebung das erlaubt; Proxy in `.env`, falls nötig.
- [ ] Freigabe für `www.bbr-server.de` (`robots_freigabe`) bewusst getroffen; Anfrage an das BBSR gestellt oder entschieden.
- [ ] `PIPELINE_KENNUNG` mit eigenem Kontakt gesetzt, damit Anbieter sich melden können.
- [ ] systemd-Timer aktiv, `TimeoutStartSec` über der Summe der Zeitbudgets (`test_gesamtabbruch_liegt_ueber_den_zeitbudgets_der_lieferkonfiguration` prüft das für die ausgelieferte Konfiguration).
- [ ] `geodaten-import-fehler.service` mit eigener Benachrichtigung (Mail, Chat, Ticket) ergänzt.
- [ ] `--status --max-alter-h` in die Überwachung eingehängt.
- [ ] `aufbewahrung_tage` gesetzt oder bewusst offen gelassen (nicht kürzer als der längste Rhythmus).

**Nach jedem Lauf, bis es Routine ist**

- [ ] Rückgabewert und `--status` gesehen.
- [ ] Textbericht gelesen: Warnungen, Hinweise, unvollständige Quellen, Katalog aktualisiert oder ausstehend.
- [ ] Meldungsentwürfe in `berichte/` geprüft.
- [ ] Laufzeit je Quelle gegen `zeitbudget_min` verglichen; bei INKAR gegen 240 min.

**Regelmäßig**

- [ ] Dependabot-Pull-Requests prüfen und zusammenführen; `pruefen.sh` läuft darauf.
- [ ] Nach einem Update: `docker compose build pipeline`, `--probelauf`, bei Bedarf `einrichten`.
- [ ] Hauptversion von PostgreSQL/PostGIS nie automatisch; vorher sichern, `pg_upgrade` oder Sicherung und Wiederherstellung.
- [ ] Sicherung von `pipeline_meta` (Register, Protokoll, Quellenstand) und `berichte/` im Sicherungsplan der Datenbank.
- [ ] Passwörter nach dem Plan der TH wechseln (`betrieb.md`, „Passwörter wechseln“).

## Nach der Sitzung

Protokoll der Sitzung mit den offenen Fragen an die TH, Stand der Klärungspunkte K1 bis K5 ([`anforderungen.md`](anforderungen.md)) und den Punkten aus der Liste „Was die TH danach selbst kann“, die noch nicht abgehakt sind. Nachbetreuung 30 Kalendertage per Mail, wie im Angebot.
