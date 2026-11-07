# Testdaten

`statistiktabelle-csv-auszug.csv` (bis E48 `regionalstatistik-12411-B-auszug.csv`): **Die Zahlen sind erfunden.** Aufbau, Kopfzeilen, Fußblock (mit
Urhebervermerk, Lizenz und Abrufzeitpunkt), Gebietsschlüssel und Namen sind wie in der Tabelle 12411-01-01-5-B
der Regionaldatenbank Deutschland, damit der Test den echten Aufbau der Datei prüft (Kopfprüfung, Stichtag aus
Zeile 7, Fußblock, `-` für aufgelöste Gemeinden). Die Bevölkerungszahlen darin sind keine amtlichen Werte und
dürfen nicht als solche verwendet werden; die letzte Zeile der Datei sagt das auch dort. Erfunden sind sie seit
E38 (05.11.2026), nach Antwort 69 der TH: Quelldaten werden nicht mit dem Code veröffentlicht.

Alle anderen Testdaten entstehen in den Tests selbst (erfundene Objekte, Schlüssel und Koordinaten).

Seit E48 (06.11.2026) lädt keine mitgelieferte Konfiguration aus der Regionaldatenbank: Deren robots.txt sperrt
automatische Abrufe ganz (`Disallow: /`). Die Datei sichert weiter den CSV-Typ für Statistiktabellen mit Kopf- und
Fußblock (E19, E47). Die Berichte des Amts für Statistik Berlin-Brandenburg als XLSX (Typ `xlsx`) erzeugen die
Tests selbst, mit erfundenen Zahlen (`tests/conftest.py`).
