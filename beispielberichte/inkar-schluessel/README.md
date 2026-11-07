# INKAR-Schlüssel: Gesamtanalyse (05.11.2026)

Beleg zu E40 in [`docs/entscheidungen.md`](../../docs/entscheidungen.md) und zu den Befunden B1, A2 und B5 der Prüfung vom
05.11.2026. Die Frage ist, wie oft der fünfteilige Quellschlüssel aus den Antworten 31 und 62 (Kennziffer, Bereich,
Kürzel, Indikator, Zeitbezug) in `dashboard_data_de` auf denselben Schlüssel fällt, und mit welchen Werten. Dort gibt
es nur `kennziffer, indikator, zeitbezug`, und das Schema bleibt unverändert (Antworten 27, 29).

- `analyse.py` ist die Abfrage. Sie liest die INKAR-Gesamtdatei 2025 (`inkar_2025.zip` des BBSR, Stand der Datei
  13.08.2025) als Datenstrom über `unzip -p`, mit Raumbezug Gemeinden und achtstelliger Kennziffer. Sie braucht nur
  die Standardbibliothek. Aufruf aus dem Repository:
  `python3 -I beispielberichte/inkar-schluessel/analyse.py cache/inkar_2025.zip`.
- `ergebnis-2026-11-05.txt` ist die Ausgabe des Laufs vom 05.11.2026. Sie enthält nur Zählungen, Kürzel, Bereiche und
  Indikatornamen, keine Werte je Gebiet (Antwort 69). Die letzte Zeile („# Messung des Aufrufs …“) stammt nicht von
  `analyse.py`, sondern vom Aufrufskript, das nicht beiliegt: Wandzeit 92 s einschließlich des Kindprozesses `unzip`
  (`analyse.py` selbst nennt 80 s) und dessen größter Speicher (`maxrss` 2 837 116 KiB, rund 2,7 GiB).
- `zom_kurznamen.py` und `zom-kurznamen-2026-11-05.txt` (seit E42): Kurznamen im Blatt ZOM der Indikatorenübersicht
  (liegt in derselben ZIP-Datei) gegen die Langtexte der ZOM-Reihen, für die fünf Kürzel der Konfiguration. Darauf
  beruht `ausser: [ZOM]` (E40). Ergebnis: xbev, q_bev_fl, e5_bev und q_pendlersaldo gleich, `alo` ohne ZOM-Reihe.

| Auswahl | Zeilen | doppelte Schlüssel nur über `kennziffer, indikator, zeitbezug` | davon mit verschiedenem Wert | Zielschlüssel nach der Regel aus E40 |
|---|---|---|---|---|
| Brandenburg, alle 264 Kürzel (Gesamtanalyse) | 1 285 774 | 35 819 | **826** (je 413 Gemeinden für „Bevölkerung“ und „Arbeitslosigkeit“, nur 2023) | 1 285 774, keiner doppelt |
| Brandenburg, die fünf Kürzel der Konfiguration (Beispiellauf) | 62 929 | 5 670 | **0** (alle wertgleich) | 62 929, keiner doppelt |
| Deutschland, dieselben fünf Kürzel | 1 640 420 | 142 678 | 0 | 1 640 420, keiner doppelt |

Katalog über alle Gemeinden Deutschlands:

- 355 Reihen (Bereich, Kürzel, Indikator) in 5 Bereichen, mit 264 Kürzeln und 333 Langtexten.
- Kürzel und Langtext bestimmen eine Reihe nicht allein: 21 Kürzel tragen mehr als einen Langtext, und 20 Paare aus
  Kürzel und Langtext stehen in mehr als einem Bereich.
- Im selben Bereich hat kein Langtext zwei Kürzel.
- Die Regel aus E40 (Langtext, außer im Bereich ZOM mit dem Bereich in Klammern) ergibt 355 verschiedene Namen für
  355 Reihen.

Frühere Angaben: E27 nannte 413 Fälle mit verschiedenem Wert. 413 ist die Zahl je Langtext; Schlüssel mit
verschiedenem Wert sind es 826. E37 ordnete die 413 dem Beispiellauf mit 5 670 Doppelungen zu, dort ist aber kein
Wert verschieden. Beides ist in E27 und E37 vermerkt.
