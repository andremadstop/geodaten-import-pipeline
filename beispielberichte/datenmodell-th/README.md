# Zieldatenmodell der TH und die drei Quellenarten, Läufe vom 02.11.2026

Zwei Läufe mit `config/quellen.yaml` gegen eine frische Datenbank:

- `20261102T100512Z.txt`: erster Lauf. WFS der LGB (882 Gebäude), Gemeinden der LGB über OGC API (413), Bevölkerung und Gebietsfläche je Gemeinde aus der Regionaldatenbank, Daten des Amts für Statistik Berlin-Brandenburg (je 413; sieben aufgelöste Gemeinden, die die Statistik noch mit „-“ führt, ausgelassen und im Bericht genannt). Die absichtlich unerreichbare Beispielquelle endet als Fehler mit Meldungsentwurf.
- `20261102T100542Z.txt`: zweiter Lauf ohne Änderung an den Quellen. Jede Quelle meldet 0 neu, 0 geändert, 0 gelöscht: Der Vergleich erkennt Zahlen und Zeit-Referenzen exakt wieder.
- `datenbank-auszug.txt`: Metadaten je Quelle nach dem Lauf; die Datensätze am Beispiel Brandenburg an der Havel sind seit 05.11.2026 entfernt (Antwort 69, E38). Die Statistik hat keine eigene Geometrie, sondern zeigt mit ihrer Geo-Referenz auf die Gemeindefläche der LGB. Gegenprobe über alle 413 Gemeinden: Die aus den LGB-Polygonen berechnete Fläche weicht im Median 0,005 % und höchstens 0,161 % (gerundet 0,16 %) von der Gebietsfläche der Statistik ab, bei 389 Gemeinden gar nicht (auf 0,01 km² genau).

Die Änderungskarten der Läufe sind hier weggelassen (je 7,5 MB, mit den importierten Datensätzen); ein Beispiel mit erfundenen Daten liegt unter `../aenderungskarte/`.

INKAR mit demselben Modell (`config/beispiel-inkar.yaml`, Berichte in `inkar/`): 413 Gemeinden, zweiter Lauf ohne Änderung.

Quellenvermerke: © GeoBasis-DE/LGB, dl-de/by-2-0 · © BKG (2026) dl-de/by-2-0 · © Statistische Ämter des Bundes und der Länder, Deutschland, 2026, dl-de/by-2-0.
