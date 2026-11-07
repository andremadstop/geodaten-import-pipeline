"""Geodaten-Import-Pipeline: holt Geodaten und Kennzahlen aus öffentlichen
Quellen (WFS, OGC API - Features, CSV, XLSX, GeoJSON, INKAR) in PostgreSQL/PostGIS (EPSG:4326) und
gleicht sie mit den Bestandstabellen der Plattform MOSIDI ab, ohne deren Schema zu verändern.

Ablauf eines Laufs: laden → quellen → ziel.

- laden: Einstieg (`python -m pipeline.laden`); steuert den Lauf mit Sperren, Rhythmus je Quelle, einer
  Transaktion je Quelle, Berichten und Rückgabewerten für die Überwachung.
- quellen: ein Adapter je Quelltyp (ADAPTER), liefert Datensätze als dict; prüft vor jeder Verbindung
  URL-Schema und die Sperrliste nach robots.txt (ROBOTS_GESPERRT).
- ziel: Zuordnung Quelle → Zieltabelle aus der Konfiguration, temporäre Zwischentabellen, Vergleich mit
  dem Bestandsregister pipeline_meta.bestand, Schreiben, Metadaten in table_metadata.
- waechter: Schemavergleich, Rückgang-Schutz, Löschfreigabe und Meldungsentwürfe an die Anbieter.
- verzeichnis: Quellenverzeichnis und atomares Schreiben der Berichtsdateien.
- karte: Änderungskarte je Lauf als eine HTML-Datei (Leaflet eingebettet aus vendor/).
- betrieb: --status, --kennzahlen, Aufbewahrung, Stand-Archiv.
- sprache: Ausgaben auf Deutsch oder Englisch aus sprachen/<code>.json.
- signatur: Ausgabe von --version.
- einrichten: Schema pipeline_meta, Rollen und Rechte (`python -m pipeline.einrichten`, als
  Administrator der Datenbank).

Entscheidungen mit Anlass und Begründung: docs/entscheidungen.md (E1 bis E49); Betrieb: docs/betrieb.md.
"""
