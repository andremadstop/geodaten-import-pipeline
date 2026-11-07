# Projektsteckbrief: Geodaten-Import-Pipeline

Vorlage für Berichte, Anträge und Vorträge. Eine Seite; die Zahlen in eckigen Klammern liefert `--kennzahlen` für den Berichtszeitraum.

**Was:** Eine quelloffene Pipeline holt Geodaten aus amtlichen Diensten (OGC WFS, OGC API - Features) und Statistiktabellen (u. a. INKAR des BBSR) automatisch in die Datenbank der Plattform, rechnet sie in ein einheitliches Koordinatensystem um und dokumentiert jeden Lauf.

**Wozu:** Aktuelle, verlässliche und nachvollziehbare Daten für die Praxispartner, ohne wiederkehrenden Handimport.

**Stand [Datum]:**

- angebundene Quellen: [Anzahl], davon [n] Webdienste und [n] Tabellen
- Objekte im Bestand: [Anzahl]
- Läufe im Berichtszeitraum: [Anzahl], übernommene Änderungen: [neu / geändert / gelöscht]
- abgefangene Störungen der Quellen (der bisherige Stand blieb erhalten): [Anzahl]
- vorbereitete Rückmeldungen an Datenanbieter: [Anzahl]

**Wie es Vertrauen schafft:** Herkunft und Lizenz an jedem Objekt; Bericht je Lauf; Störungen und Schemaänderungen der Quellen werden erkannt, bevor sie den Bestand verändern; Datenbankrollen nach geringsten Rechten, geprüfte Abhängigkeiten, Bedrohungsmodell.

**Nachnutzung:** Code offen unter [Lizenz] im Repository [Adresse], zitierbar [DOI]. Andere Einrichtungen tragen ihre eigenen Quellen in eine Konfigurationsdatei ein, ohne den Code zu ändern.

**Bild:** Die Änderungskarte eines Laufs zeigt, was sich bei den Quellen seit dem letzten Abruf geändert hat (Bildschirmfoto aus `berichte/<lauf>-karte.html`).
