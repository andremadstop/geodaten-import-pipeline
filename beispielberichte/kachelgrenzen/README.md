# Grenzfall: Gebäude auf Kachelgrenzen (Abruf 02.11.2026)

Der WFS „ALKIS vereinfacht“ der LGB meldet `ImplementsResultPaging=FALSE`. Die Pipeline fragt den Ausschnitt um den Campus der TH (`alkis_gebaeude_thb` in `config/quellen.yaml`, 1,2 × 1,0 km) deshalb in 9 Kacheln zu 400 m ab. Ein Gebäude, dessen Umriss über eine Kachelgrenze reicht, liefert der Dienst in jeder berührten Kachel.

| | Anzahl |
|---|---|
| Objekte geliefert, über alle Kacheln | 940 |
| Gebäude (verschiedene Objekt-IDs), übernommen | 882 |
| davon in mehreren Kacheln geliefert | 53 |
| davon in drei oder vier Kacheln | 3 |

Ohne Entdopplung stünden 940 Objekte in der Tabelle. Die Pipeline übernimmt jede Objekt-ID genau einmal (`pipeline/quellen.py`, Funktion `wfs`).

Nachzählen: `python beispielberichte/kachelgrenzen/zaehlen.py ergebnis.json` (fragt den Dienst live ab; die JSON-Datei enthält die Geometrien und bleibt deshalb außerhalb des Repositorys). Nur die Zählungen, mit Zeitpunkt und Kachel-BBOX je Abfrage: `python beispielberichte/kachelgrenzen/pruefen.py`. Ausgabe vom 05.11.2026, 09:22 UTC: [`pruefausgabe-2026-11-05.txt`](pruefausgabe-2026-11-05.txt) (9 Kacheln, 882 Gebäude, 940 geliefert, 53 in mehreren Kacheln: 50 in zwei, 1 in drei, 2 in vier). Grafik: `kachelgrenzen.png`. © GeoBasis-DE/LGB, dl-de/by-2-0.
