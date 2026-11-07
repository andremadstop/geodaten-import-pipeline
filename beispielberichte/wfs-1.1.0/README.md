# WFS 1.1.0 gegen WFS 2.0.0 am selben Dienst (04.11.2026)

Antwort 67 der TH: Unterstützt werden sollen WFS 2.0.0 und 1.1.0 mit den Ausgabeformaten des Dienstes.
Gegenprobe mit der Quelle `kreise_lgb` aus `config/quellen.yaml` (Verwaltungsgrenzen der LGB, Kreise),
einmal mit `version: 2.0.0`, einmal mit `version: 1.1.0`, sonst gleiche Konfiguration.

| | WFS 2.0.0 | WFS 1.1.0 |
|---|---|---|
| Objekte | 18, vollständig | 18, vollständig |
| Geometrie im GML | `gml:MultiSurface` (GML 3.2) | `gml:MultiPolygon` (GML 3.1.1) |
| Objekt-IDs und Sachdaten | gleich | gleich |
| Geometrien, in PostGIS 3.6 verglichen (EPSG:25833) | | größte Flächendifferenz 0 m², größter Hausdorff-Abstand 0 m |
| Koordinaten, Zahl für Zahl verglichen (Nachprüfung 05.11.2026) | 169 598 Punkte | 18 von 18 Geometrien identisch |

Nachprüfbar: `python beispielberichte/wfs-1.1.0/vergleichen.py` holt beide Fassungen mit dem Adapter der Pipeline und
zählt; Ausgabe mit Zeitpunkt und Abfragen vom 05.11.2026, 09:22 UTC: [`pruefausgabe-2026-11-05.txt`](pruefausgabe-2026-11-05.txt). Der
Vergleich in PostGIS vom 04.11. ist nicht als Datei aufbewahrt.

Der Adapter fragt bei 1.1.0 mit `TYPENAME` und `MAXFEATURES`, liest `gml:featureMember` und
`gml:featureMembers` und kachelt immer, weil 1.1.0 kein Paging und keine Gesamtzahl kennt; eine Kachel,
die die Höchstzahl erreicht, gilt als unvollständig (E34). Test: `tests/test_quellen.py`,
`test_wfs_1_1_0_mit_featuremember_und_eigenen_parametern`.
