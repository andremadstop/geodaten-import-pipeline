# Für Anträge und Berichte

Für die Projektleitung: was die Pipeline zu Förderanträgen, Zwischenberichten und Verwendungsnachweisen beiträgt, und Sätze, die sich übernehmen lassen.

## FAIR

Die FAIR-Prinzipien gelten den Daten, nicht der Software. Die Pipeline macht die Daten in der Plattform nicht allein FAIR (dafür braucht es etwa einen Katalog und dauerhafte Kennungen je Datensatz), sie liefert aber die Grundlage dafür:

| Prinzip | Was die Pipeline beiträgt |
|---|---|
| **Auffindbar** (Findable) | Jedes Objekt trägt Quelle, Objekt-ID der Quelle und Lauf. Das Quellenverzeichnis führt je Quelle Anbieter, Kontakt, Lizenz, letzten erfolgreichen Abruf und Anzahl und hält sich nach jedem Lauf selbst aktuell |
| **Zugänglich** (Accessible) | Quellen über offene Standards (OGC WFS 2.0, CSV) und https; Ergebnisse in PostgreSQL/PostGIS, für die Plattform über eine eigene Leserolle |
| **Interoperabel** (Interoperable) | Einheitliches Koordinatensystem EPSG:4326, Geometrien in PostGIS, Kennzahlen in Langform mit Zeitbezug (`dashboard_data_de` der Plattform), Metadaten nach DCAT-AP in `table_metadata`, Berichte als JSON; amtliche Statistik ohne Koordinaten wird über Gebietsschlüssel (AGS) mit Flächen verknüpft |
| **Nachnutzbar** (Reusable) | Lizenz der Quelle an jedem Objekt (z. B. dl-de/by-2-0), Herkunft und Zeitpunkt des Imports, Bericht je Lauf mit allen Änderungen; der Code selbst offen lizenziert, dokumentiert und getestet |

## Zitieren

Das Repository enthält eine Datei `CITATION.cff`. GitHub zeigt dafür den Knopf „Cite this repository“ mit fertigen Angaben (APA, BibTeX).

Eine DOI je Version gibt es über [Zenodo](https://help.zenodo.org/docs/github/): bei Zenodo mit GitHub anmelden, das Repository im GitHub-Bereich von Zenodo einschalten, danach erzeugt jedes GitHub-Release ein Archiv mit eigener DOI. Die Angaben übernimmt Zenodo aus `CITATION.cff`. Die DOI danach in `CITATION.cff` unter `identifiers` nachtragen.

## Kennzahlen für Berichte

Für einen Berichtszeitraum, als Markdown zum Übernehmen in Zwischenberichte und Verwendungsnachweise:

    docker compose run --rm --no-deps pipeline --kennzahlen --von 2026-01-01 --bis 2027-01-01

Ausgabe: Zahl der Läufe und Quellen, Objekte im Bestand, übernommene Änderungen (neu, geändert, gelöscht), abgefangene Störungen der Quellen (der alte Stand blieb jeweils erhalten), vorbereitete Meldungen an Anbieter, dazu eine Tabelle je Quelle. Die Grundlage sind die Laufberichte in `berichte/`; den aktuellen Stand je Quelle zeigt `berichte/quellenverzeichnis.md`.

## Welcher Datenstand lag einer Auswertung zugrunde?

Die Tabellen der Plattform haben keine Versionen; ein Import gleicht den Stand einer Quelle ab, was neu, geändert oder entfernt ist, steht im Protokoll je Lauf (`pipeline_meta.aenderung`). Für reproduzierbare Auswertungen (gute wissenschaftliche Praxis) legt die Pipeline auf Wunsch (`archiv: true`) den neuen Stand jeder geänderten Quelle als GeoJSON-Datei ab, mit Lizenz und Lauf an jedem Objekt. Wer eine Auswertung veröffentlicht, nennt die Lauf-ID; der zugehörige Stand liegt unter `berichte/archiv/<lauf>/`.

## Nachnutzung durch andere Einrichtungen

Code und Dokumentation sind offen, die Konfiguration ist von der Plattform getrennt: Eine andere Hochschule oder Kommune trägt ihre eigenen Quellen in `config/quellen.yaml` ein und braucht keine Änderung am Code.

Die Veröffentlichung zusätzlich auf [Open CoDE](https://opencode.de), der Plattform der öffentlichen Verwaltung für offenen Code, wäre der Ort, an dem Kommunen suchen. Die Nutzungsbedingungen verlangen dort „einen Träger der öffentlichen Verwaltung als Rechtsinhaber oder Auftraggeber“; Hochschulen werden nicht ausdrücklich genannt. Ob das für die Einrichtung zutrifft, vorher mit Open CoDE klären.

## Sätze zum Übernehmen

> Die Plattform bezieht ihre Geodaten automatisiert aus amtlichen Diensten (OGC WFS) und Statistiktabellen. Jeder Import ist über einen maschinenlesbaren Bericht nachvollziehbar; Herkunft und Lizenz werden je Objekt mitgeführt.

> Störungen und Schemaänderungen der Datenquellen werden erkannt, bevor sie den Datenbestand verändern. Der bisherige Stand bleibt erhalten, und eine Rückmeldung an den Anbieter wird vorbereitet.

> Die Import-Pipeline ist quelloffen, dokumentiert und zitierbar und kann von anderen Einrichtungen nachgenutzt werden: Tabellen- und Feldzuordnungen eigener Quellen sind konfigurierbar; abweichende fachliche Schlüssel oder Metadatenstrukturen können eine Adapteranpassung erfordern.
