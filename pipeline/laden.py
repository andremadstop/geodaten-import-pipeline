"""Import-Lauf: alle konfigurierten Quellen einlesen, je Quelle mit ihrer Zieltabelle in
PostgreSQL/PostGIS abgleichen, Bericht als JSON (und kurz als Text) ablegen.

Aufruf:  python -m pipeline.laden --config config/quellen.yaml [--nur QUELLE] [--probelauf] [--alle]
                                   [--vollabgleich]
         python -m pipeline.laden --ziele | --status [--max-alter-h 26] | --kennzahlen [--von --bis]
Jede Quelle läuft in einer eigenen Transaktion. Fällt eine Quelle aus, wird sie
zurückgerollt und im Bericht als fehlgeschlagen geführt; die anderen laufen weiter.
Bricht die Objektzahl einer Quelle stark ein, bleibt ihr alter Stand stehen (angehalten).
War der Abruf unvollständig, wird eingefügt und aktualisiert, aber nichts gelöscht.
Für fehlgeschlagene und angehaltene Quellen legt der Lauf einen Meldungsentwurf an den
Anbieter ab (siehe waechter.py). Danach schreibt er den Bericht, erst dann die Änderungskarte
(<lauf>-karte.html, zeigt, was der Lauf je Quelle verändert hat; karte.py), und aktualisiert
das Quellenverzeichnis (Reihenfolge seit E50).

Ziele sind die Bestandstabellen der Plattform MOSIDI (z. B. "Gebäude (ALKIS)",
dashboard_data_de, table_metadata); die Zuordnung steht je Quelle unter `ziel` in der
Konfiguration (ziel.py). Protokoll je Lauf und Quelle, Bestandsregister und Quellenstand liegen
im eigenen Schema pipeline_meta (sql/pipeline_meta.sql, angelegt von pipeline.einrichten).
Quellen mit `rhythmus` (taeglich, woechentlich, monatlich, vierteljaehrlich, jaehrlich) laden
nur, wenn ihr Takt seit dem letzten Erfolg abgelaufen ist; --alle oder --nur laden trotzdem.
Dateiquellen (csv, xlsx, inkar) mit `unveraendert_ueberspringen: true` werden bei byte-gleicher Datei
übersprungen, solange Konfiguration, Code und Zählprüfung passen und der letzte Vollabgleich jünger als
`vollabgleich_tage` (Standard 7) ist; --vollabgleich schaltet das für einen Lauf ab (E52, unveraendert.py).

Mit --probelauf wird alles gelesen, geprüft und verglichen (eine als unverändert übersprungene Quelle nicht,
E52; vollständig mit --probelauf --vollabgleich --alle bzw. --nur QUELLE), ohne dauerhafte Änderungen an den
Fachdaten:
Jede Transaktion wird am Ende zurückgerollt, auch das Protokoll in pipeline_meta entfällt (nur eine
Sequenz, die eine Zieltabelle für neue Zeilen nutzt, zählt trotzdem weiter; PostgreSQL rollt nextval
nicht zurück).
Geschrieben werden Prüfberichte (<lauf>-probelauf.json, .txt, Karte) und, wo eine Quelle ihn nutzt,
der Zwischenspeicher der Downloads (cache); Quellenverzeichnis und Meldungsentwürfe nicht. So lässt
sich eine neue Quelle testen, bevor sie in den Betrieb geht. Der Bericht zählt nicht als
Vergleichsstand.

Nach einem Lauf mit Änderungen aktualisiert die Pipeline den Katalog von MOSIDI (Materialized View
public.source_granularities, Antwort 75) über pipeline_meta.katalog_aktualisieren(); fehlt die View,
steht nur ein Hinweis im Bericht (E46). Scheitert das oder bricht der Lauf vorher ab, holt der nächste
Lauf es nach, auch ohne eigene Änderungen (pipeline_meta.katalog_offen, Nachprüfung zu E46). Seit E52
gleichzeitig (CONCURRENTLY), wenn die View einen eindeutigen Index hat, mit eigenem Zeitlimit
(katalog_zeitlimit_min, katalog_sperre_max_s oben in der Konfiguration) und nach einem Bericht vorab mit dem
Katalog „ausstehend“.

Datenbankzugang über die libpq-Variablen PGHOST, PGUSER, PGPASSWORD, PGDATABASE
(oder DATABASE_URL), im Betrieb mit der Rolle pipeline_import (Rechte: pipeline.einrichten).

Mit --ziele gibt die Pipeline nur aus, welche Rechner sie erreichen muss (host:port je aktiver
Quelle), und beendet sich ohne Datenbank. Daraus entstehen die Freigaben für die Firewall.
--status gibt den Zustand des letzten Laufs für die Überwachung aus (Nagios-Konvention),
--kennzahlen fasst die Läufe eines Zeitraums für Berichte zusammen (beide ohne Datenbank).

Optional in der Konfiguration: aufbewahrung_tage (alte Laufdateien löschen, der jüngste
Bericht bleibt immer), archiv: true (Stand jeder geänderten Quelle als GeoJSON ablegen) und karte
(false: keine Änderungskarte; {hintergrund: [basemap, luftbild]}: Hintergrundkarten Dritter, karte.py).

Nur ein Lauf je Datenbank gleichzeitig: Sperre im Berichtsordner und datenbankweit (pg_advisory_lock,
E46). Rückgabe: 0 alles gut; 1 eine Quelle fehlgeschlagen, angehalten oder unvollständig, der Katalog
nicht aktualisiert, eine optionale Ausgabe (Karte, Aufräumen) gescheitert (E50), oder ein anderer Lauf hält
eine der Sperren; 2 technischer Abbruch. Ein technischer Abbruch hinterlässt einen Bericht mit
`abbruch` (--status: CRITICAL) und den bis dahin bearbeiteten Quellen (E50), soweit der Berichtsordner
bekannt und beschreibbar ist (E34, E38).

Stellung im Ablauf (laden → quellen → ziel): Dieses Modul ist der Einstieg und steuert den Lauf. main()
wertet die Aufrufoptionen aus, lauf() nimmt die Sperre im Berichtsordner und vergibt die Laufkennung,
_lauf() verbindet sich mit der Datenbank, prüft pipeline_meta (meta_pruefen) und nimmt die datenbankweite
Sperre (db_sperre). Je aktiver Quelle folgen Fälligkeit (faelligkeit), Laden (quelle_laden) und Nachlauf
(_nachlauf: Meldungsentwurf, Stand-Archiv, Protokoll). quelle_laden holt die Datensätze über den Adapter
des Quelltyps (quellen.ADAPTER) und überlässt Zwischentabellen, Vergleich und Schreiben dem Modul ziel;
Schemavergleich, Rückgang-Schutz und Löschfreigabe kommen aus waechter. Danach folgen Katalog,
Laufprotokoll (pipeline_meta.lauf), der Pflichtbericht (JSON und Text), Aufräumen und Änderungskarte mit
eigenem Fehlerpfad, der Bericht mit deren Ergebnis und das Quellenverzeichnis (E50).

Wichtigste Entscheidungen (docs/entscheidungen.md): Rückgang-Schutz und Anhalten bei fehlenden Feldern
(E4), eine Transaktion je Quelle (E7), Meldungen an Anbieter nur als Entwurf (E8), Bestandsregister und
Löschen nur bei vollständigem Abruf (E23), Rhythmus je Quelle (E24), ein unvollständiger Abruf ist kein
Erfolg (E32), Sperre und Abbruchbericht (E34), Raumdaten werden nicht gelöscht (E35), Rhythmus vorab
prüfen und Abriss der Verbindung (E44, E45), Katalog, Metadatenkonflikt und datenbankweite Sperre (E46),
robots.txt je Rechner, auch für --ziele (E48); benannte Freigabe eines gesperrten Rechners je Quelle, auch in
--ziele, Pflichtbericht vor den optionalen Ausgaben und bei jedem Abbruch mit den bisherigen Quellen,
Zeitbudget je Quelle (zeitbudget_min), bestätigte Leerlieferung für genau einen Lauf (--leerlieferung) (E50);
Zeitgrenzen der Datenbank je Quelle (E51); unveränderte Lieferung überspringen, Katalog gleichzeitig mit
eigenem Zeitlimit und Bericht vorab (E52).
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import logging
import math
import os
import signal
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from psycopg import errors as pg_fehler

from . import betrieb, karte, quellen, signatur, sprache, umfang, unveraendert, verzeichnis, waechter, ziel
from .einrichten import verbinden
from .quellen import ADAPTER, Protokoll, freigabe_fuer, robots_gesperrt

log = logging.getLogger("pipeline")


# Rhythmus je Quelle (Antwort 37): Ein Zeitgeber startet die Pipeline z. B. täglich, jede Quelle
# lädt aber nur, wenn ihr Rhythmus seit dem letzten Erfolg abgelaufen ist. Eine Stunde Spielraum,
# damit ein Zeitgeber, der ein paar Minuten früher feuert, nicht einen ganzen Takt verliert.
RHYTHMUS_TAGE = {"taeglich": 1, "woechentlich": 7}
RHYTHMUS_MONATE = {"monatlich": 1, "vierteljaehrlich": 3, "jaehrlich": 12}
SPIELRAUM = timedelta(hours=1)


def _plus_monate(t: datetime, n: int) -> datetime:
    """Addiert n Kalendermonate zu t, ohne Zusatzbibliothek.

    Fehlt der Tag im Zielmonat, gilt dessen letzter Tag (31.01. plus ein Monat ergibt den 28.02., im
    Schaltjahr nach gregorianischer Regel den 29.02.). Uhrzeit und Zeitzone bleiben.

    Args:
        t: Ausgangszeitpunkt.
        n: Zahl der Monate (aus RHYTHMUS_MONATE: 1, 3 oder 12).

    Returns:
        Der um n Monate verschobene Zeitpunkt.
    """
    # Monate nullbasiert rechnen, damit divmod den Jahresübertrag liefert
    j, m = divmod(t.month - 1 + n, 12)
    jahr, monat = t.year + j, m + 1
    tage = [31, 29 if jahr % 4 == 0 and (jahr % 100 or jahr % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][monat - 1]
    return t.replace(year=jahr, month=monat, day=min(t.day, tage))


def naechster_termin(rhythmus: str | None, letzter_erfolg: datetime | None) -> datetime | None:
    """Ab wann die Quelle wieder fällig ist; None heißt: bei jedem Lauf.

    Termin = Basis plus Takt minus SPIELRAUM (eine Stunde). Tägliche und wöchentliche Rhythmen rechnen
    in festen Tagen, die übrigen in Kalendermonaten (_plus_monate).

    Args:
        rhythmus: Wert von `rhythmus` aus der Konfiguration; None oder leer heißt kein Rhythmus.
        letzter_erfolg: Zeitpunkt, ab dem der Rhythmus zählt (siehe rhythmus_basis); None, solange die
            Quelle noch keinen gültigen Erfolg hat.

    Returns:
        Zeitpunkt, ab dem die Quelle wieder lädt, oder None (bei jedem Lauf laden).

    Raises:
        ValueError: unbekannter Rhythmus. Im Lauf meldet rhythmen_pruefen das schon vor dem Laden.
    """
    if not rhythmus or letzter_erfolg is None:
        return None
    if rhythmus in RHYTHMUS_TAGE:
        return letzter_erfolg + timedelta(days=RHYTHMUS_TAGE[rhythmus]) - SPIELRAUM
    if rhythmus in RHYTHMUS_MONATE:
        return _plus_monate(letzter_erfolg, RHYTHMUS_MONATE[rhythmus]) - SPIELRAUM
    raise ValueError(f"Unbekannter Rhythmus '{rhythmus}' (erlaubt: "
                     f"{', '.join([*RHYTHMUS_TAGE, *RHYTHMUS_MONATE])})")


def rhythmen_pruefen(cfg: dict) -> None:
    """Rhythmus aller Quellen vor dem Laden prüfen, auch abgeschalteter und mit --nur nicht gewählter.
    naechster_termin() sieht einen Tippfehler erst nach dem ersten Erfolg der Quelle; bis dahin lädt sie
    bei jedem Lauf, danach brach der ganze Lauf ab (Code-Review 05.11., F1, E44). Nur ein fehlender oder
    leerer Eintrag (`rhythmus:` ohne Wert, None) heißt „bei jedem Lauf“; false, 0, '' oder [] sind Tippfehler
    und fielen bis E45 ohne Meldung durch (Pre-existing).

    Args:
        cfg: ganze Konfiguration; geprüft werden alle Einträge unter `quellen`, die ein dict sind.

    Raises:
        KonfigFehler: mindestens ein unbekannter Rhythmus; die Meldung nennt alle mit ihrer Quelle.
    """
    erlaubt = [*RHYTHMUS_TAGE, *RHYTHMUS_MONATE]
    # `is not None` statt Wahrheitswert: sonst gälten false, 0 und '' still als „kein Rhythmus“
    falsch = [f"'{q['rhythmus']}' ({name})" for name, q in cfg["quellen"].items()
              if isinstance(q, dict) and q.get("rhythmus") is not None and q["rhythmus"] not in erlaubt]
    if falsch:
        raise KonfigFehler(f"Unbekannter Rhythmus {', '.join(falsch)}; erlaubt: {', '.join(erlaubt)}")


# Zeitbudget je Quelle in Minuten (E50, Befund W6), wenn weder die Quelle noch die Konfiguration oben
# `zeitbudget_min` setzt. Bemessen an Läufen mit abgelegter Datei: INKAR mit fünf Kürzeln bundesweit brauchte
# im Deutschland-Lauf rund 5 min. Ein Download zählt zum Budget der Quelle (Nachprüfung zu E50). Die
# ausgelieferte INKAR-Quelle im Vollumfang setzt seit E51 (Befund W2) ein eigenes zeitbudget_min von 240
# (gemessen 146,5 min, Begründung in config/quellen.yaml); systemd beendet den ganzen Lauf nach 7 h
# (TimeoutStartSec, über der Summe der Budgets der Lieferkonfiguration)
ZEITBUDGET_STANDARD_MIN = 30

# Wartegrenze für Sperren je Quelle in Sekunden (E51, Befund K1), wenn weder die Quelle noch die
# Konfiguration oben `db_sperre_max_s` setzt. Die Pipeline wartet auf eine Sperre nur, wenn eine andere
# Sitzung die Zieltabelle sperrt (Wartung, Schemaänderung, eine lange Transaktion von MOSIDI); Lesen in MOSIDI
# sperrt sie nicht. Fünf Minuten lassen eine kurze Wartung durch und halten die übrigen Quellen nicht lange
# auf; die blockierte Quelle ist beim nächsten Lauf wieder dran (kein Erfolg, also fällig)
DB_SPERRE_STANDARD_S = 300

# Rest des Zeitbudgets in Sekunden, unter dem ein QueryCanceled als Abbruch durch statement_timeout gilt
# (db_zeitgrenze_melden, Nachprüfung zu E51). Bricht PostgreSQL am statement_timeout ab, ist der Rest auf der
# Uhr der Pipeline 0 (Begründung dort); 1 s lässt Raum für Rückrollen und Übertragung der Ausnahme
STATEMENT_TIMEOUT_SCHWELLE_S = 1.0

# Höchster Wert, den PostgreSQL für statement_timeout und lock_timeout annimmt: 2^31 - 1 Millisekunden (int),
# rund 35 791 min oder 24,8 Tage. Nachprüfung zu E51: zeitbudget_pruefen nahm jede endliche Zahl über 0 an;
# ein größeres zeitbudget_min (etwa 40 000) bestand die Prüfung vor dem Lauf, dann lehnte set_config in
# db_grenzen den Wert zu Beginn der Quelle ab (InvalidParameterValue, „exceeds integer range“), und _nachlauf
# schrieb einen Meldungsentwurf an den Anbieter, obwohl der Fehler in der eigenen Konfiguration lag. Jetzt
# prüft zeitbudget_pruefen auch die Obergrenze, und db_grenzen kappt zur Sicherheit auf diesen Wert
PG_ZEITGRENZE_MAX_MS = 2**31 - 1

# Obergrenze je Schlüssel in seiner Einheit (Minuten bzw. Sekunden), abgeleitet aus PG_ZEITGRENZE_MAX_MS.
# Verglichen wird der Wert mit dieser Grenze, nicht der in Millisekunden umgerechnete Wert: 1e306 * 60 000
# wäre unendlich (und math.ceil darauf ein OverflowError)
ZEITGRENZE_HOECHST = {"zeitbudget_min": PG_ZEITGRENZE_MAX_MS / 60_000,
                      "db_sperre_max_s": PG_ZEITGRENZE_MAX_MS / 1_000,
                      # Katalogaktualisierung (E52), nur oben in der Konfiguration
                      "katalog_zeitlimit_min": PG_ZEITGRENZE_MAX_MS / 60_000,
                      "katalog_sperre_max_s": PG_ZEITGRENZE_MAX_MS / 1_000}


def _budget_gueltig(wert, hoechst: float = math.inf) -> bool:
    """Ist `wert` ein gültiges zeitbudget_min oder db_sperre_max_s: endliche Zahl über 0, kein Wahrheitswert
    und höchstens `hoechst` (ZEITGRENZE_HOECHST, Nachprüfung zu E51)?"""
    return (isinstance(wert, (int, float)) and not isinstance(wert, bool) and math.isfinite(wert)
            and 0 < wert <= hoechst)


def zeitbudget(cfg: dict, qcfg: dict) -> float:
    """Zeitbudget einer Quelle in Minuten: `zeitbudget_min` der Quelle, sonst oben in der Konfiguration, sonst
    ZEITBUDGET_STANDARD_MIN (E50). Gültigkeit prüft zeitbudget_pruefen vor dem Lauf."""
    return qcfg.get("zeitbudget_min", cfg.get("zeitbudget_min", ZEITBUDGET_STANDARD_MIN))


def db_sperre_max(cfg: dict, qcfg: dict) -> float:
    """Wartegrenze für Sperren einer Quelle in Sekunden: `db_sperre_max_s` der Quelle, sonst oben in der
    Konfiguration, sonst DB_SPERRE_STANDARD_S (E51). Gültigkeit prüft zeitbudget_pruefen vor dem Lauf."""
    return qcfg.get("db_sperre_max_s", cfg.get("db_sperre_max_s", DB_SPERRE_STANDARD_S))


def zeitbudget_pruefen(cfg: dict) -> None:
    """Vor dem ersten Abruf: jedes `zeitbudget_min` und jedes `db_sperre_max_s` (E51; oben und je Quelle, auch
    abgeschaltete) ist eine endliche Zahl über 0 und höchstens so groß, wie PostgreSQL es für
    statement_timeout bzw. lock_timeout annimmt (ZEITGRENZE_HOECHST: 35 791 min bzw. 2 147 483 s;
    Nachprüfung zu E51). Wie rhythmen_pruefen: ein Tippfehler bricht den Lauf ab, bevor eine Quelle lädt,
    statt erst mitten im Lauf oder gar nicht aufzufallen.

    Seit E52 ebenso `katalog_zeitlimit_min` und `katalog_sperre_max_s` (Zeitgrenzen der
    Katalogaktualisierung); die beiden gelten nur oben, in einer Quelle wären sie wirkungslos und gelten als
    Fehler (ein Tippfehler in der Einrückung soll nicht still den Standard lassen).

    Raises:
        KonfigFehler: mindestens ein ungültiger Wert; die Meldung nennt alle mit ihrem Ort."""
    for schluessel, einheit in (("katalog_zeitlimit_min", "Minuten"), ("katalog_sperre_max_s", "Sekunden")):
        falsch = [f"oben: {cfg[schluessel]!r}"] if schluessel in cfg and not _budget_gueltig(
            cfg[schluessel], ZEITGRENZE_HOECHST[schluessel]) else []
        falsch += [f"{n}: nur oben in der Konfiguration, nicht je Quelle" for n, q in cfg["quellen"].items()
                   if isinstance(q, dict) and schluessel in q]
        if falsch:
            raise KonfigFehler(f"{schluessel} muss oben in der Konfiguration stehen und eine Zahl über 0 und "
                               f"höchstens {int(ZEITGRENZE_HOECHST[schluessel])} sein ({einheit}; "
                               f"Katalogaktualisierung, E52): {', '.join(falsch)}")
    for schluessel, einheit in (("zeitbudget_min", "Minuten"), ("db_sperre_max_s", "Sekunden")):
        hoechst = ZEITGRENZE_HOECHST[schluessel]
        falsch = [f"oben: {cfg[schluessel]!r}"] if schluessel in cfg and not _budget_gueltig(
            cfg[schluessel], hoechst) else []
        falsch += [f"{n}: {q[schluessel]!r}" for n, q in cfg["quellen"].items()
                   if isinstance(q, dict) and schluessel in q and not _budget_gueltig(q[schluessel], hoechst)]
        if falsch:
            # Die Grenze abgerundet nennen (35 791, 2 147 483): ein Wert bis dahin ist sicher erlaubt
            raise KonfigFehler(f"{schluessel} muss eine Zahl über 0 und höchstens {int(hoechst)} sein "
                               f"({einheit}; Höchstwert der Zeitgrenzen in PostgreSQL): {', '.join(falsch)}")


def db_grenzen(cur, prot: Protokoll, sperre_max_s: float) -> tuple[int, int]:
    """Prüfpunkt des Zeitbudgets und Zeitgrenzen der Datenbank für den nächsten Schritt einer Quelle (E51,
    Befund K1 des Prüfberichts vom 07.11.2026).

    Bis E51 prüfte die Pipeline das Zeitbudget nur zwischen den Anweisungen (Protokoll.zeit_pruefen). Eine
    Anweisung, die auf eine Sperre wartete oder sehr lange rechnete, lief ohne Grenze weiter und hielt alle
    folgenden Quellen bis zum Abbruch des ganzen Laufs auf; nur die Katalogaktualisierung hatte eine
    Wartegrenze. Jetzt begrenzt PostgreSQL selbst:
      statement_timeout  Rest des Zeitbudgets der Quelle (Protokoll.rest_s). Kein kleinerer fester Wert: Die
                         Einleseanweisung (COPY in die Eingangstabelle) bleibt offen, solange der Adapter
                         liest, bei INKAR samt Download; sie würde sonst mitten im Abruf abgebrochen.
      lock_timeout       kleinerer Wert aus Rest und `sperre_max_s` (db_sperre_max_s, Standard 300 s): Eine
                         gesperrte Zieltabelle hält die Quelle nur so lange auf, dann ist die nächste dran.
    Beide mit set_config(…, true), also nur bis zum Ende der Transaktion der Quelle (wie SET LOCAL); danach
    gelten wieder die Einstellungen der Sitzung. Nie 0, denn 0 hieße in PostgreSQL „ohne Grenze“: aufgerundet
    auf mindestens 1 ms.

    Aufgerufen zu Beginn der Transaktion und an jedem Prüfpunkt zwischen den Schreibschritten (quelle_laden),
    so beginnt jeder Schritt mit dem aktuellen Rest. Grenze: Ein Schritt aus mehreren Anweisungen (etwa
    ziel.neu_bilden) setzt nicht vor jeder Anweisung neu; jede einzelne darf bis zum Rest am letzten
    Prüfpunkt laufen, zusammen also länger. transaction_timeout, das die ganze Transaktion begrenzen würde,
    gibt es erst ab PostgreSQL 17; unterstützt wird auch 16.

    Args:
        cur: Cursor in der Transaktion der Quelle.
        prot: Protokoll der Quelle mit gesetzter Frist (frist_setzen).
        sperre_max_s: Wartegrenze für Sperren in Sekunden (db_sperre_max).

    Returns:
        (statement_timeout, lock_timeout) in Millisekunden, wie gesetzt.

    Raises:
        quellen.ZeitbudgetUeberschritten: Das Budget ist schon um (Protokoll.zeit_pruefen); dann wird nichts
            gesetzt.
    """
    prot.zeit_pruefen()
    rest = prot.rest_s()
    rest = float("inf") if rest is None else rest
    # Gekappt vor dem Aufrunden (Nachprüfung zu E51): höchstens PG_ZEITGRENZE_MAX_MS, sonst lehnt PostgreSQL
    # den Wert ab; zeitbudget_pruefen hält die Konfiguration schon darunter, aufgerundet könnte der Rest aber
    # um 1 ms darüber liegen, und ein direkter Aufruf mit einem sehr großen Budget soll nicht überlaufen
    anweisung_ms = 0 if math.isinf(rest) else max(1, math.ceil(min(rest * 1000, PG_ZEITGRENZE_MAX_MS)))
    sperre_ms = max(1, math.ceil(min(rest * 1000, sperre_max_s * 1000, PG_ZEITGRENZE_MAX_MS)))
    cur.execute("SELECT set_config('statement_timeout', %s, true), set_config('lock_timeout', %s, true)",
                (f"{anweisung_ms}ms", f"{sperre_ms}ms"))
    return anweisung_ms, sperre_ms


@contextlib.contextmanager
def db_zeitgrenze_melden(sperre_max_s: float, prot: Protokoll | None = None):
    """Übersetzt den Abbruch einer Anweisung durch die Zeitgrenzen aus db_grenzen in
    quellen.ZeitbudgetUeberschritten (E51, Befund K1). Als äußerster Kontext um die Transaktion der Quelle:
    Wenn die Ausnahme hier ankommt, ist die Transaktion schon zurückgerollt.

    Text „Zeitbudget/Datenbank-Zeitgrenze überschritten (…)“: Er beginnt wie die Meldung des Zeitbudgets,
    deshalb schreibt _nachlauf keinen Meldungsentwurf an den Anbieter (waechter.meldung_noetig; die Ursache
    liegt in der eigenen Datenbank), und der Bericht führt die Quelle als FEHLER. Übersetzt werden:
      LockNotAvailable  lock_timeout, erkannt an der Ausnahmeklasse (SQLSTATE 55P03); NOWAIT nutzt die
                        Pipeline in den Quellen nicht.
      QueryCanceled     statement_timeout, wenn das Zeitbudget der Quelle beim Eintreffen der Ausnahme
                        praktisch aufgebraucht ist (prot.rest_s() unter STATEMENT_TIMEOUT_SCHWELLE_S), sonst
                        nur mit „statement timeout“ im Text der Servermeldung (Rückfall).
    Warum nach der Zeit (Nachprüfung zu E51): statement_timeout und ein Abbruch von Hand (pg_cancel_backend)
    haben denselben SQLSTATE 57014. Bis zur Nachprüfung entschied nur der Text, und der folgt lc_messages des
    Servers; ein Server mit deutscher Locale meldet „storniere Anfrage wegen Zeitüberschreitung der
    Anweisung“, und ein echter Abbruch am Budget lief als gewöhnlicher Fehler hinaus, mit Meldungsentwurf an
    den Anbieter. lc_messages setzen darf die Importrolle nicht (nur Superuser). Die Zeit trägt: db_grenzen
    setzt statement_timeout auf den aufgerundeten Rest am Prüfpunkt, die Anweisung beginnt danach, also
    bricht PostgreSQL sie frühestens am Ende des Budgets ab; die Uhr der Pipeline steht dann auf 0 Rest.
    Grenze: Ein Abbruch von Hand in der letzten Sekunde des Budgets zählt als Zeitbudget. Ohne Budget (rest_s
    None) ist statement_timeout 0, also kann der Abbruch nicht von dort kommen; dann gilt nur der Text.

    Args:
        sperre_max_s: Wartegrenze für Sperren, nur für den Text der Meldung.
        prot: Protokoll der Quelle (frist_setzen aufgerufen) für den Vergleich nach der Zeit; None nur in
            Tests, dann entscheidet allein der Text."""
    try:
        yield
    except pg_fehler.LockNotAvailable as e:
        raise quellen.ZeitbudgetUeberschritten(
            f"Zeitbudget/Datenbank-Zeitgrenze überschritten (lock_timeout, Wartegrenze für Sperren "
            f"{sperre_max_s:g} s oder Rest des Zeitbudgets): Zieltabelle von einer anderen Sitzung gesperrt; "
            "Quelle abgebrochen, ihre Transaktion zurückgerollt, alter Stand bleibt") from e
    except pg_fehler.QueryCanceled as e:
        rest = prot.rest_s() if prot is not None else None
        budget_um = rest is not None and rest < STATEMENT_TIMEOUT_SCHWELLE_S
        if not budget_um and "statement timeout" not in (getattr(e.diag, "message_primary", None) or str(e)):
            raise
        raise quellen.ZeitbudgetUeberschritten(
            "Zeitbudget/Datenbank-Zeitgrenze überschritten (statement_timeout, Rest des Zeitbudgets): eine "
            "Datenbankanweisung lief bis zum Ende des Zeitbudgets; Quelle abgebrochen, ihre Transaktion "
            "zurückgerollt, alter Stand bleibt") from e


def freigaben_pruefen(cfg: dict) -> None:
    """Vor dem ersten Abruf und vor --ziele: jede robots_freigabe ist ohne Steuerzeichen und Zeilentrenner
    (Nachprüfung zu E50). Ein Grund mit Zeilenumbruch ergab in --ziele eine zweite Zeile ohne „#“, die ein
    Skript, das die Kommentarzeilen überspringt, als Ziel für die Firewall läse. Geprüft werden alle Quellen,
    auch abgeschaltete, wie bei zeitbudget_pruefen.

    Raises:
        KonfigFehler: mindestens eine ungültige Freigabe; die Meldung nennt alle Quellen."""
    falsch = []
    for name, q in cfg["quellen"].items():
        if not isinstance(q, dict):
            continue
        try:
            quellen.robots_freigabe(q)
        except quellen.QuellenFehler as e:
            falsch.append(f"{name}: {e}")
    if falsch:
        raise KonfigFehler(f"robots_freigabe ungültig: {'; '.join(falsch)}")


def ueberspringen_pruefen(cfg: dict) -> None:
    """Vor dem ersten Abruf: `unveraendert_ueberspringen` und `vollabgleich_tage` in allen Quellen (E52;
    Regeln in unveraendert.konfig_fehler). Wie zeitbudget_pruefen bricht ein Tippfehler den Lauf ab, bevor
    eine Quelle lädt.

    Raises:
        KonfigFehler: mindestens ein ungültiger Wert; die Meldung nennt alle mit ihrer Quelle."""
    fehler = unveraendert.konfig_fehler(cfg)
    if fehler:
        raise KonfigFehler("Unveränderte Lieferung (E52): " + "; ".join(fehler))


def umfang_pruefen(cfg: dict, bestaetigen: set[str] | None) -> None:
    """Vor dem ersten Abruf (E52, Umfangsänderung): `umfang_bestaetigt` in allen Quellen ist eine Kennung aus
    dem Bericht (umfang.konfig_fehler), und jede Quelle unter --umfang-bestaetigen ist eine aktive Quelle der
    Konfiguration (wie bei leerlieferung_pruefen; ein Tippfehler im Namen verfiele sonst still).

    Raises:
        KonfigFehler: mindestens ein ungültiger Eintrag; die Meldung nennt alle."""
    fehler = umfang.konfig_fehler(cfg)
    for name in sorted(bestaetigen or ()):
        q = cfg["quellen"].get(name)
        if not isinstance(q, dict) or not q.get("aktiv", True):
            fehler.append(f"--umfang-bestaetigen {name}: keine aktive Quelle")
    if fehler:
        raise KonfigFehler("Umfangsänderung (E52): " + "; ".join(fehler))


def leerlieferung_pruefen(cfg: dict, leer: dict[str, str] | None) -> None:
    """Vor dem ersten Abruf: Jede Freigabe einer Leerlieferung (--leerlieferung QUELLE GRUND, E50, Befund W7)
    nennt eine aktive Quelle der Konfiguration und einen Grund, der nicht leer ist.

    Raises:
        KonfigFehler: unbekannte oder abgeschaltete Quelle oder leerer Grund; die Meldung nennt alle."""
    falsch = []
    for name, grund in (leer or {}).items():
        q = cfg["quellen"].get(name)
        if not isinstance(q, dict) or not q.get("aktiv", True):
            falsch.append(f"{name}: keine aktive Quelle")
        elif not str(grund or "").strip():
            falsch.append(f"{name}: Grund fehlt")
    if falsch:
        raise KonfigFehler(f"--leerlieferung: {'; '.join(falsch)}")


def quelle_laden(conn, name: str, cfg: dict, lauf_id: str, jetzt: datetime,
                 prot: Protokoll, vorher: dict | None = None, probelauf: bool = False,
                 kartenobjekte: dict | None = None, leer_grund: str | None = None,
                 budget_min: float = ZEITBUDGET_STANDARD_MIN,
                 sperre_max_s: float = DB_SPERRE_STANDARD_S, vollabgleich: bool = False,
                 umfang_bestaetigen: bool = False) -> dict:
    """Liest eine Quelle vollständig und gleicht sie in einer Transaktion mit der Zieltabelle ab.

    Vor dem Schreiben wird der neue Stand mit dem Bestandsregister verglichen; daraus kommen die
    Zahlen neu / geändert / gelöscht / unverändert für Bericht und Protokoll. Liefert die Quelle
    0 Objekte oder deutlich weniger als bisher, bleibt der alte Stand stehen. War der Abruf nicht
    vollständig, wird eingefügt und aktualisiert, aber nichts gelöscht.

    Reihenfolge: Datensätze des Adapters per COPY in die temporäre Tabelle `eingang`; Schemavergleich
    mit dem letzten Stand (nur Hinweise); fehlende Felder (hält an); daraus `neu` (ziel.neu_bilden),
    zusammengelegte Schlüssel (hält an); Gebiet und Fläche prüfen (Hinweis oder Warnung, halten nicht an;
    mit ohne_flaeche: auslassen fallen Zeilen ohne Fläche aus `neu`); 0 Objekte, Rückgang und
    belegte Namen in table_metadata (je hält an). Jede Prüfung, die anhält, greift, bevor außer temporären
    Tabellen (ON COMMIT DROP) etwas geschrieben ist. Erst danach Vergleich mit dem Register,
    Löschentscheidung, Kartenobjekte, Schreiben, Metadaten und Quellenstand.

    Args:
        conn: psycopg-Verbindung ohne offene Transaktion (siehe _verbindung).
        name: Name der Quelle (Schlüssel unter `quellen` in der Konfiguration).
        cfg: Konfiguration dieser einen Quelle.
        lauf_id: Laufkennung (JJJJMMTTTHHMMSSZ); landet im Register und in quellenstand.letzter_lauf.
        jetzt: Startzeit des Laufs (UTC); wird letzter_erfolg, wenn der Abruf vollständig war.
        prot: Protokoll der Quelle; Adapter und diese Funktion tragen Warnungen, Hinweise und `info` ein.
        vorher: Eintrag der Quelle aus dem letzten Bericht, in dem sie geladen wurde (für den
            Schemavergleich); None beim ersten Lauf.
        probelauf: True rollt die Transaktion am Ende in jedem Fall zurück.
        kartenobjekte: Sammlung für die Änderungskarte, die Objekte dieser Quelle kommen unter `name`
            hinein; None, wenn keine Karte geschrieben wird.
        leer_grund: Grund einer bestätigten Leerlieferung für genau diesen Lauf (--leerlieferung, E50, W7)
            oder None. Liefert die Quelle 0 Objekte, vollständig und ohne fehlende Felder, wird sie dann
            nicht angehalten, sondern abgeglichen (alle bisherigen Zeilen gelöscht, soweit das Ziel löschen
            darf). Ohne Freigabe hält eine Nullmenge die Quelle an, auch mit abgeschaltetem Rückgang-Schutz.
        budget_min: Zeitbudget der Quelle in Minuten (zeitbudget, E50, W6). Geprüft wird je Datensatz des
            Adapters, in den Adaptern vor jeder Anfrage und je Block, und zwischen den Schreibschritten; dort
            setzt db_grenzen seit E51 auch die Zeitgrenzen der Datenbank (statement_timeout = Rest des
            Budgets).
        sperre_max_s: Wartegrenze für Sperren in Sekunden (db_sperre_max, E51, Befund K1): lock_timeout ist
            der kleinere Wert aus ihr und dem Rest des Budgets.
        vollabgleich: True (--vollabgleich, E52): nie überspringen, auch bei byte-gleicher Datei.
        umfang_bestaetigen: True (--umfang-bestaetigen QUELLE, E52): eine Umfangsänderung dieser Quelle ist
            für diesen Lauf bestätigt (Modul umfang).

    Umfangsänderung (E52, Ablauf und Freigabe im Modul umfang): nach der Löschentscheidung geprüft
    (_umfang_pruefen); angehalten, wenn der Lauf unter geändertem Umfang ohne Bestätigung Zeilen löschen oder
    Quellschlüssel ersetzen würde.

    Unveränderte Lieferung (E52, Modul unveraendert): Mit `unveraendert_ueberspringen: true` (csv, xlsx,
    inkar) prüft quelle_laden vor dem Einlesen, ob die Quelle bei byte-gleicher Datei übersprungen werden darf
    (unveraendert.vorpruefen). Dann endet der Adapter mit quellen.DateiUnveraendert, bevor er die Datei
    liest, und _uebersprungen schreibt nur den Quellenstand. Den Vergleichsstand schreibt nur ein
    vollständiger Lauf mit Prüfsumme, jeder andere leert ihn. Der Probelauf entscheidet wie der reguläre Lauf.

    Returns:
        {"status": "ok" oder "angehalten", "zaehler": {...}} mit den Zählern gelesen, neu, geaendert,
        unveraendert, geloescht, uebernommen, uebernommen_geaendert und zurueckgehalten; bei einer genutzten
        Freigabe der Leerlieferung zusätzlich "leerlieferung" (der Grund); bei einer übersprungenen Quelle
        (E52) zusätzlich "uebersprungen" ({sha256, vollabgleich}), gelesen 0 und unveraendert = Zeilen im
        Register.

    Raises:
        Exception: jeder Fehler des Adapters oder der Datenbank (etwa quellen.QuellenFehler,
            ziel.ZielFehler, psycopg.Error, quellen.ZeitbudgetUeberschritten). Die Transaktion der Quelle ist
            dann zurückgerollt; _lauf führt die Quelle als fehlgeschlagen und macht mit der nächsten weiter.

    Seiteneffekte:
        Netzabruf über den Adapter (je nach Quelltyp auch der Download-Zwischenspeicher). Bei Status
        ok und ohne Probelauf: Zieltabelle, pipeline_meta.bestand und pipeline_meta.aenderung
        (ziel.anwenden), table_metadata (ziel.metadaten_schreiben), pipeline_meta.quellenstand und bei
        Änderungen pipeline_meta.katalog_offen, alles in derselben Transaktion.
    """
    zaehler = {"gelesen": 0, "neu": 0, "geaendert": 0, "unveraendert": 0, "geloescht": 0,
               "uebernommen": 0, "uebernommen_geaendert": 0, "zurueckgehalten": 0}
    adapter = ADAPTER[cfg["typ"]]
    z = ziel.aus_konfiguration(name, cfg)
    # Zeitbudget ab hier (E50, W6): Prüfpunkte statt Signal, damit Verbindung und Cache in klarem Zustand
    # bleiben (Protokoll.zeit_pruefen)
    prot.frist_setzen(budget_min)
    # Unveränderte Lieferung (E52): nur mit Schalter und nur für Dateiquellen; sonst wie vor E52
    prot.datei_pruefen = unveraendert.aktiv(cfg)
    try:
        return _quelle_abgleichen(conn, name, cfg, lauf_id, jetzt, prot, vorher, probelauf, kartenobjekte,
                                  leer_grund, sperre_max_s, vollabgleich, adapter, z, zaehler,
                                  umfang_bestaetigen)
    except quellen.DateiUnveraendert as u:
        # Außerhalb der Transaktion der Quelle: Sie ist zurückgerollt, geschrieben war nur die temporäre
        # Eingangstabelle (ON COMMIT DROP)
        return _uebersprungen(conn, name, cfg, lauf_id, jetzt, prot, probelauf, sperre_max_s, z, zaehler, u)


def _quelle_abgleichen(conn, name: str, cfg: dict, lauf_id: str, jetzt: datetime, prot: Protokoll,
                       vorher: dict | None, probelauf: bool, kartenobjekte: dict | None,
                       leer_grund: str | None, sperre_max_s: float, vollabgleich: bool, adapter, z,
                       zaehler: dict, umfang_bestaetigen: bool) -> dict:
    """Die Transaktion der Quelle aus quelle_laden (Ablauf und Parameter dort; seit E52 eigene Funktion, damit
    quelle_laden quellen.DateiUnveraendert nach dem Zurückrollen abfangen kann).

    Zusätzlich: adapter (Funktion aus ADAPTER), z (Ziel aus der Konfiguration), zaehler (die Zähler, werden
    hier fortgeschrieben), umfang_bestaetigen (--umfang-bestaetigen für diese Quelle, E52). Ob die Prüfsumme
    der Datei gebildet wird, steht in prot.datei_pruefen (unveraendert.aktiv, gesetzt von quelle_laden).

    Raises:
        quellen.DateiUnveraendert: Datei byte-gleich mit dem letzten Vollabgleich (nur mit Prüfsumme); die
            Transaktion ist dann zurückgerollt. Sonst wie quelle_laden."""
    pruefsumme = prot.datei_pruefen

    def grenzen(cur) -> None:
        """Prüfpunkt zwischen den Schreibschritten: Zeitbudget prüfen und die Zeitgrenzen der Datenbank auf
        den Rest setzen (db_grenzen, E51, Befund K1)."""
        db_grenzen(cur, prot, sperre_max_s)

    # Eine Transaktion je Quelle (E7): Ein Fehler rollt nur diese Quelle zurück, die anderen laufen
    # weiter. force_rollback rollt im Probelauf auch einen Erfolg zurück. db_zeitgrenze_melden steht außen:
    # Bricht PostgreSQL eine Anweisung an einer Zeitgrenze ab, ist die Transaktion zurückgerollt, und die
    # Quelle endet als „Zeitbudget/Datenbank-Zeitgrenze“ (E51)
    with (db_zeitgrenze_melden(sperre_max_s, prot), conn.transaction(force_rollback=probelauf),
          conn.cursor() as cur):
        # Zeitgrenzen gleich zu Beginn der Transaktion. Sie begrenzen vor allem die Einleseanweisung (COPY in
        # die Eingangstabelle), die offen bleibt, solange der Adapter liest. ziel.pruefen liest nur den
        # Katalog (to_regclass, pg_attribute, geometry_columns) und nimmt keine Sperre auf der Zieltabelle;
        # die erste Anweisung, die auf eine solche Sperre warten kann, kommt erst nach dem nächsten Prüfpunkt
        # (vor ziel.neu_bilden). Bis zur Nachprüfung zu E51 stand hier, ziel.pruefen lese die Zieltabelle
        grenzen(cur)
        ziel.planer_einstellen(cur)
        ziel.pruefen(cur, z)
        prot.info["ziel"] = z.name
        if pruefsumme:
            # Vor dem Einlesen (E52): Hier ist noch kein COPY offen, Quellenstand und Zählung sind abfragbar.
            # Mit Prüfsumme meldet der Adapter eine byte-gleiche Datei über DateiUnveraendert
            prot.datei_erwartet, grund = unveraendert.vorpruefen(cur, name, z, cfg, jetzt, vollabgleich,
                                                                 leer_grund)
            if grund:
                prot.hinweise.append(f"Vollabgleich: {grund}")
        cur.execute(ziel.EINGANG_TABELLE)
        # Laufende Nummer je Zielzeile: ziel.neu_bilden unterscheidet damit doppelt gelieferte Zeilen
        nr = 0
        # COPY schreibt jede Zeile gleich weiter, statt erst alle Datensätze zu sammeln (INKAR bundesweit
        # rund 1,5 Mio. Zeilen, gemessen im Deutschland-Lauf zu E29)
        with ziel.eingang_kopie(cur) as kopie:
            for ds in adapter(cfg, prot):
                prot.zeit_pruefen()
                zaehler["gelesen"] += 1
                # Ein Datensatz kann null, eine oder (mit je_wert) mehrere Zielzeilen ergeben
                for werte, geom, gebiet in ziel.zeilen(ds, z):
                    nr += 1
                    ziel.eingang_zeile(kopie, nr, ds["objekt_id"], werte, geom, gebiet,
                                       bool(ds.get("leer")))

        # Veränderungen an der Quelle selbst (Feldliste u. a.) gegenüber ihrem letzten geladenen Stand
        prot.hinweise += waechter.schema_vergleichen(vorher, prot.info)
        if prot.info.get("fehlende_felder"):
            # Sonst verschwände ein Attribut still bei allen Objekten der Quelle
            prot.warnungen.append("Felder fehlen in der Quelle, alter Stand bleibt unverändert")
            return {"status": "angehalten", "zaehler": zaehler}

        # Prüfpunkte zwischen den Schreibschritten (E50), seit E51 mit Zeitgrenzen der Datenbank
        grenzen(cur)
        grund = ziel.neu_bilden(cur, z, prot)
        if grund:
            # Gekürzte Schlüssel oder mehrdeutige Abbildung (E40) legten verschiedene Datensätze
            # zusammen; das wäre ein Datenverlust
            prot.warnungen.append(grund)
            return {"status": "angehalten", "zaehler": zaehler}
        ziel.gebiet_pruefen(cur, z, prot)
        ziel.flaeche_pruefen(cur, z, prot)
        cur.execute("SELECT count(*) FROM neu")
        n_neu = cur.fetchone()[0]
        # Vergleichsgröße für den Rückgang-Schutz: Zeilen dieser Quelle laut Bestandsregister
        n_bisher = ziel.bisher(cur, name, z)
        prot.info["objekte"] = n_neu
        leer_bestaetigt = False
        if n_neu == 0:
            if not leer_grund:
                prot.warnungen.append("Quelle lieferte 0 Objekte, alter Stand bleibt unverändert")
                return {"status": "angehalten", "zaehler": zaehler}
            if prot.unvollstaendig:
                # Eine Lücke im Abruf ist keine bestätigte Leerlieferung: Was fehlt, ist dann unbekannt (E50)
                prot.warnungen.append(f"Quelle lieferte 0 Objekte und der Abruf war unvollständig; die "
                                      f"Freigabe der Leerlieferung ({leer_grund}) gilt nur für einen "
                                      "vollständigen Abruf, alter Stand bleibt unverändert")
                return {"status": "angehalten", "zaehler": zaehler}
            # Bestätigte Leerlieferung für genau diesen Lauf (E50, W7): Abgleich statt Anhalten, sichtbar
            leer_bestaetigt = True
            prot.warnungen.append(f"Quelle lieferte 0 Objekte; Leerlieferung für diesen Lauf bestätigt "
                                  f"(--leerlieferung: {leer_grund}); die {n_bisher} bisherigen Zeilen werden "
                                  "abgeglichen und gelöscht, soweit das Ziel löschen darf")
        elif leer_grund:
            prot.hinweise.append(f"Freigabe der Leerlieferung ohne Wirkung: Quelle lieferte {n_neu} Objekte")
        # Steht max_rueckgang ohne Wert (None) in der Quelle, ist der Rückgang-Schutz für sie abgeschaltet
        max_rueckgang = cfg.get("max_rueckgang", waechter.MAX_RUECKGANG_STANDARD)
        if not leer_bestaetigt and waechter.rueckgang_zu_gross(n_bisher, n_neu, max_rueckgang):
            prot.warnungen.append(f"Quelle lieferte {n_neu} statt bisher {n_bisher} Objekte "
                                  f"(Rückgang über {max_rueckgang:.0%}), alter Stand bleibt unverändert")
            return {"status": "angehalten", "zaehler": zaehler}
        belegt = ziel.metadaten_belegt(cur, name, cfg, z, prot)
        if belegt:
            # Keine Fachdaten ohne ihren Metadatensatz (Antwort 75, Prüfbericht 05.11., F2, E46). Bis E45
            # wurden die Daten trotzdem geladen, mit einer Warnung. Vor dem Schreiben geprüft: Bis hierher
            # gibt es nur temporäre Tabellen, die Transaktion endet ohne Änderung
            prot.info["metadaten_belegt"] = belegt
            prot.warnungen.append(
                f"{ziel.META_TABELLE}: {len(belegt)} Zeile{'n' if len(belegt) != 1 else ''} nicht anlegbar, "
                "der Name ist schon für eine andere Quelle oder Raumebene eingetragen und wird nicht "
                f"überschrieben: "
                f"{', '.join(belegt[:10])}{' …' if len(belegt) > 10 else ''}; Quelle angehalten, alter Stand "
                "bleibt (Name in AP 1 klären oder fremde Zeile als Administrator prüfen, docs/betrieb.md)")
            return {"status": "angehalten", "zaehler": zaehler}

        grenzen(cur)
        zaehler.update(ziel.vergleichen(cur, name, z))
        # Quellschlüssel gewechselt, Zielschlüssel gleich (E42): Der bisherige Datensatz ist nicht mehr in
        # der Quelle (Antwort 62: gelöscht), seine Zeile trägt jetzt den neuen (neu). Das zählt auch bei
        # unvollständigem Abruf als gelöscht, die Zeile wird ja überschrieben; deshalb erst nach der Sperre
        ersetzt = zaehler.pop("ersetzt", 0)
        doppelt = ziel.doppelte_im_ziel(cur, z)
        if doppelt:
            prot.hinweise.append(f"{doppelt} Schlüssel stehen in {z.name} mehrfach; die Pipeline "
                                 "aktualisiert jeweils alle diese Zeilen")
        loeschen = waechter.loeschen_erlaubt(prot)
        raumdaten_behalten = not z.loeschen
        if zaehler["geloescht"] and loeschen and raumdaten_behalten:
            # Antwort 74: Raumdaten (Geometrien) bleiben, andere Quellen hängen über den AGS daran
            zaehler["zurueckgehalten"] += zaehler["geloescht"]
            prot.hinweise.append(f"{zaehler['geloescht']} Objekte nicht mehr in der Quelle, bleiben stehen "
                                 "(Ziel mit loeschen: false, Raumdaten werden nicht gelöscht)")
            zaehler["geloescht"] = 0
            loeschen = False
        elif zaehler["geloescht"] and not loeschen:
            zaehler["zurueckgehalten"] += zaehler["geloescht"]
            prot.warnungen.append(f"{zaehler['geloescht']} Zeilen nicht gelöscht: Abruf war nicht "
                                  "vollständig, Löschen nur bei vollständigem Abruf")
            zaehler["geloescht"] = 0
        # Umfangsänderung (E52): erst hier, weil erst jetzt feststeht, was der Lauf tatsächlich löschen würde
        # (nach Löschsperre bei Lücken und `loeschen: false`). Bis hierher gibt es nur temporäre Tabellen
        umfang_neu = _umfang_pruefen(cur, name, cfg, prot, zaehler, ersetzt, umfang_bestaetigen)
        if umfang_neu is _ANHALTEN:
            return {"status": "angehalten", "zaehler": zaehler}
        if not loeschen:
            # Im Vergleich heißen die Löschkandidaten ab hier `zurueckgehalten`, damit Karte und
            # Änderungsprotokoll zeigen, was wirklich geschieht
            ziel.zurueckhalten(cur)
        if ersetzt:
            zaehler["geloescht"] += ersetzt
            prot.hinweise.append(f"{ersetzt} Zeilen kommen aus einem anderen Quellschlüssel als bisher "
                                 "(etwa ein umbenanntes Kürzel): bisheriger Quellschlüssel als gelöscht, "
                                 "neuer als neu gezählt, die Zeile in der Zieltabelle wird aktualisiert")
        # Die Karte erst jetzt: sie zeigt, was wirklich geschieht, nicht den Vergleich davor
        if kartenobjekte is not None and cfg.get("karte", True) is not False:
            kartenobjekte[name] = karte.objekte_lesen(
                cur, ziel.karte_sql(z), cfg.get("karte_max_objekte", karte.MAX_OBJEKTE_STANDARD))
        grenzen(cur)
        ziel.anwenden(cur, name, z, lauf_id, loeschen)
        if zaehler["uebernommen"]:
            # Fachlich gezählt (Antwort 62, E46): abweichende Werte unter geändert, sonst unverändert
            n_ue, n_ug = zaehler["uebernommen"], zaehler["uebernommen_geaendert"]
            prot.hinweise.append(f"{n_ue} Zeilen gab es in {z.name} schon (nicht von der Pipeline "
                                 f"geschrieben); sie werden ab jetzt von dieser Quelle gepflegt: {n_ug} mit "
                                 f"abweichenden Werten (unter geändert gezählt), {n_ue - n_ug} unverändert")
        # Übernommene Zeilen zählen mit: Sie kommen in diesem Lauf neu ins Bestandsregister
        geaendert = any(zaehler[k] for k in ("neu", "geaendert", "geloescht", "uebernommen"))
        grenzen(cur)
        prot.info["metadaten"] = ziel.metadaten_schreiben(cur, name, cfg, z, prot, jetzt, geaendert)
        # Vergleichsstand für das Überspringen (E52): nur nach einem vollständigen Vollabgleich mit Prüfsumme
        # einer Datei, die beim Lesen dieselbe blieb, und nicht nach einer bestätigten Leerlieferung (die gilt
        # für genau einen Lauf). Jeder andere Lauf, der hier schreibt, leert ihn: Hat ein unvollständiger Lauf
        # mit Datei B eingefügt und aktualisiert, darf eine spätere Datei A nicht gegen den Stand von A
        # übersprungen werden, die Datenbank hält ja Werte aus B
        stand = (None,) * len(unveraendert.SPALTEN)
        if pruefsumme and not prot.unvollstaendig and not leer_bestaetigt and prot.datei_noch_gleich():
            grenzen(cur)
            stand = (prot.datei_sha256, unveraendert.fingerabdruck(cfg), jetzt,
                     *unveraendert.zaehlen(cur, name, z))
        elif pruefsumme and prot.datei_sha256 and not prot.datei_noch_gleich():
            prot.hinweise.append("Datei während des Laufs ersetzt oder geändert; keine Prüfsumme als "
                                 "Vergleichsstand gespeichert, nächster Lauf ist ein Vollabgleich")
        cur.execute("""INSERT INTO pipeline_meta.quellenstand
                           (quelle, tabelle, rhythmus, letzter_lauf, letzter_erfolg, objekte,
                            datei_sha256, konfig_sha256, vollabgleich, register_zeilen, ziel_zeilen, umfang)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (quelle) DO UPDATE SET tabelle = EXCLUDED.tabelle,
                           rhythmus = EXCLUDED.rhythmus, letzter_lauf = EXCLUDED.letzter_lauf,
                           letzter_erfolg = COALESCE(EXCLUDED.letzter_erfolg,
                                                     pipeline_meta.quellenstand.letzter_erfolg),
                           objekte = EXCLUDED.objekte, datei_sha256 = EXCLUDED.datei_sha256,
                           konfig_sha256 = EXCLUDED.konfig_sha256, vollabgleich = EXCLUDED.vollabgleich,
                           register_zeilen = EXCLUDED.register_zeilen, ziel_zeilen = EXCLUDED.ziel_zeilen,
                           umfang = EXCLUDED.umfang""",
                    # Ein unvollständiger Abruf zählt nicht als Erfolg: sonst hielte der Rhythmus
                    # (INKAR monatlich) die Quelle bis zum nächsten Termin auf dem lückenhaften Stand
                    (name, z.name, cfg.get("rhythmus"), lauf_id,
                     None if prot.unvollstaendig else jetzt, n_neu, *stand,
                     # Gemerkter Umfang (E52): neu oder der bisherige (_umfang_pruefen), als JSON
                     json.dumps(umfang_neu)))
        if geaendert:
            # Katalog offen, bis ein Aufruf von katalog_aktualisieren gelingt; mit den Daten in derselben
            # Transaktion, damit es auch ein Abbruch vor dem Aufruf nicht verliert (Nachprüfung zu E46)
            cur.execute("INSERT INTO pipeline_meta.katalog_offen (lauf_id) VALUES (%s) "
                        "ON CONFLICT DO NOTHING", (lauf_id,))
        # Letzter Prüfpunkt vor dem Abschluss der Transaktion: auch hier noch zurückrollen statt übernehmen
        grenzen(cur)

    return {"status": "ok", "zaehler": zaehler, **({"leerlieferung": leer_grund} if leer_bestaetigt else {})}


# Rückgabe von _umfang_pruefen, wenn die Quelle wegen einer Umfangsänderung anhält (E52)
_ANHALTEN = object()


def _umfang_pruefen(cur, name: str, cfg: dict, prot: Protokoll, zaehler: dict, ersetzt: int,
                    bestaetigen: bool):
    """Umfangsänderung der Quelle (E52, Modul umfang) nach der Löschentscheidung in _quelle_abgleichen.

    Liest den gemerkten Umfang (umfang.lesen), vergleicht ihn mit dem jetzt (umfang.teile) und entscheidet
    (umfang.entscheiden). Gezählt als Löschung werden die Zeilen, die tatsächlich gelöscht würden
    (zaehler["geloescht"] nach Löschsperre und `loeschen: false`), und die ersetzten Quellschlüssel (ersetzt;
    ein geänderter `schluessel` ersetzt die Quellschlüssel der Zeilen, die Zieltabelle behält sie).

    Hält die Quelle an: Warnung mit den geänderten Schlüsseln, beiden Kennungen und der Freigabe;
    info["umfang"] mit angehalten, Kennungen, geänderten Schlüsseln und den Zahlen, die der Lauf geschrieben
    hätte; die Zähler außer gelesen auf 0 (in pipeline_meta.quellenlauf soll kein Löschen stehen, das nicht
    stattfand). Waechter.meldung_noetig schreibt dafür keinen Meldungsentwurf an den Anbieter.

    Returns:
        _ANHALTEN, oder der Umfang, der in den Quellenstand kommt (der neue oder der bisherige, nie None)."""
    alt = umfang.lesen(cur, name)
    neu = umfang.teile(cfg)
    abdruck = umfang.fingerabdruck(neu)
    loeschungen = zaehler["geloescht"] + ersetzt
    durch = umfang.bestaetigung(cfg, abdruck, bestaetigen)
    anhalten, merken = umfang.entscheiden(alt, neu, loeschungen, not prot.unvollstaendig, durch)
    if alt is None or alt == neu:
        if bestaetigen:
            prot.hinweise.append("--umfang-bestaetigen ohne Wirkung: " + (
                "Umfang der Quelle unverändert" if alt is not None
                else "noch kein Umfang gemerkt (erster Lauf seit E52), er wird jetzt gemerkt"))
        return neu
    schluessel = umfang.geaendert(alt, neu)
    alt_kennung, neu_kennung = umfang.kennung(umfang.fingerabdruck(alt)), umfang.kennung(abdruck)
    info = {"alt": alt_kennung, "neu": neu_kennung, "geaendert": schluessel, "loeschungen": loeschungen}
    liste = ", ".join(schluessel[:20]) + (" …" if len(schluessel) > 20 else "")
    # Gemeinsamer Anfang aller Meldungen unten, und die Zahl der Löschungen mit Wort
    kopf = f"Umfang der Quelle geändert ({liste}; Kennung {alt_kennung} → {neu_kennung})"
    zeilen = f"{loeschungen} Zeile{'n' if loeschungen != 1 else ''}"
    if anhalten:
        info.update(angehalten=True, zaehler={k: v for k, v in zaehler.items() if k != "gelesen"})
        prot.info["umfang"] = info
        prot.warnungen.append(
            f"{kopf}, und der Lauf würde {zeilen} löschen bzw. ihren Quellschlüssel ersetzen; Quelle "
            f"angehalten, alter Stand bleibt. Freigeben einmal mit --umfang-bestaetigen {name} oder in der "
            f"Quelle mit {umfang.SCHLUESSEL}: \"{neu_kennung}\" (gilt nur für diesen Umfang)")
        for k in zaehler:
            if k != "gelesen":
                zaehler[k] = 0
        return _ANHALTEN
    info.update(angehalten=False, bestaetigt=durch, gemerkt=merken)
    prot.info["umfang"] = info
    if durch and loeschungen:
        # Die Bestätigung steht als Warnung im Bericht und in pipeline_meta.quellenlauf (Prüfpfad)
        prot.warnungen.append(f"{kopf}, bestätigt durch {durch}: {zeilen} werden gelöscht bzw. ihr "
                              "Quellschlüssel ersetzt")
    elif merken:
        prot.hinweise.append(f"{kopf}, ohne Löschung übernommen; ab jetzt gilt der neue Umfang")
    else:
        prot.hinweise.append(
            f"{kopf}; Abruf unvollständig, nichts gelöscht, der bisherige Umfang bleibt gemerkt: Sobald ein "
            "vollständiger Lauf löschen würde, hält die Quelle an, bis der neue Umfang bestätigt ist"
            + (f" (Bestätigung durch {durch} in diesem Lauf ohne Wirkung)" if durch else ""))
    return neu if merken else alt


def _uebersprungen(conn, name: str, cfg: dict, lauf_id: str, jetzt: datetime, prot: Protokoll,
                   probelauf: bool, sperre_max_s: float, z, zaehler: dict,
                   u: quellen.DateiUnveraendert) -> dict:
    """Unveränderte Lieferung (E52): Quellenstand fortschreiben, Ergebnis der übersprungenen Quelle bilden.

    In eigener Transaktion (im Probelauf zurückgerollt): letzter_lauf und letzter_erfolg auf diesen Lauf,
    damit der Rhythmus ab hier zählt; ein Lauf ohne Abgleich ist hier ein belegt vollständiger Abruf ohne
    Änderung (Datei byte-gleich mit einem vollständigen Vollabgleich, Zählprüfung bestanden). Der
    Vergleichsstand selbst (Prüfsumme, Zeitpunkt des Vollabgleichs, Zählung) bleibt, so zählt
    vollabgleich_tage vom letzten echten Vollabgleich. Nur, wenn im Quellenstand noch dieselbe Prüfsumme
    steht; sonst (nur denkbar, wenn zwischen Vorprüfung und hier jemand den Quellenstand geändert hat)
    scheitert die Quelle, statt etwas zu behaupten.

    Keine Schreibvorgänge in Zieltabelle, Register, Änderungsprotokoll, table_metadata (imported bleibt beim
    letzten Vollabgleich) und katalog_offen; keine Kartenobjekte.

    Returns:
        Ergebnis wie quelle_laden: status ok, zaehler mit gelesen 0 und unveraendert = Zeilen im Register laut
        Vergleichsstand, "uebersprungen" mit Prüfsumme und Zeitpunkt des letzten Vollabgleichs.

    Raises:
        RuntimeError: Quellenstand passt nicht mehr zur Prüfsumme. psycopg.Error, ZeitbudgetUeberschritten wie
            in quelle_laden."""
    with (db_zeitgrenze_melden(sperre_max_s, prot), conn.transaction(force_rollback=probelauf),
          conn.cursor() as cur):
        db_grenzen(cur, prot, sperre_max_s)
        cur.execute("""UPDATE pipeline_meta.quellenstand
                       SET letzter_lauf = %s, letzter_erfolg = %s, rhythmus = %s
                       WHERE quelle = %s AND tabelle = %s AND datei_sha256 = %s
                       RETURNING vollabgleich, register_zeilen, objekte""",
                    (lauf_id, jetzt, cfg.get("rhythmus"), name, z.name, u.sha256))
        zeile = cur.fetchone()
        if zeile is None:
            raise RuntimeError("Quellenstand passt nicht mehr zur Prüfsumme der Datei; Quelle nicht "
                               "übersprungen, nächster Lauf ist ein Vollabgleich")
    vollabgleich, register, objekte = zeile
    zaehler["unveraendert"] = register
    prot.info["objekte"] = objekte
    seit = vollabgleich.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    prot.hinweise.append(
        f"unverändert (Datei byte-gleich, sha256 {u.sha256[:16]}…): Quelle übersprungen, nicht eingelesen "
        f"und nicht verglichen, keine Schreibvorgänge in {z.name}, Register und table_metadata; letzter "
        f"Vollabgleich {seit}, {register} Zeilen im Register (Vollabgleich beim ersten Lauf der Quelle ab "
        f"{unveraendert.tage(cfg):g} Tagen danach, sofort mit --vollabgleich)"
        + ("; Probelauf: ein regulärer Lauf überspränge die Quelle ebenso" if probelauf else ""))
    return {"status": "ok", "zaehler": zaehler, "uebersprungen": {"sha256": u.sha256, "vollabgleich": seit}}


def rhythmus_basis(erfolg: datetime | None, letzter_lauf: str | None) -> datetime | None:
    """Ab welchem Erfolg der Rhythmus zählt. Lief die Quelle nach ihrem letzten Erfolg noch einmal
    und war dabei unvollständig (dann bleibt letzter_erfolg alt, letzter_lauf ist jünger), ist sie
    sofort wieder fällig: Sonst hielte ein junger Erfolg vor einem erzwungenen, lückenhaften Lauf
    (--alle, --nur) die Quelle bis zum nächsten Termin auf dem lückenhaften Stand (Codex B6).

    Args:
        erfolg: pipeline_meta.quellenstand.letzter_erfolg (Startzeit des letzten vollständigen Laufs).
        letzter_lauf: pipeline_meta.quellenstand.letzter_lauf (Laufkennung JJJJMMTTTHHMMSSZ).

    Returns:
        erfolg, oder None (sofort fällig), wenn nach dem Erfolg ein weiterer Lauf geschrieben hat. Eine
        unlesbare Laufkennung ändert nichts.
    """
    if erfolg is None or not letzter_lauf:
        return erfolg
    try:
        lauf_zeit = datetime.strptime(letzter_lauf, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return erfolg
    # Vergleich auf die Sekunde wie die Laufkennung: Der Lauf, der den Erfolg selbst gesetzt hat, ergibt
    # Gleichheit und gilt nicht als späterer Lauf
    return None if lauf_zeit > erfolg.replace(microsecond=0) else erfolg


def faelligkeit(conn, name: str, qcfg: dict, jetzt: datetime) -> tuple[datetime | None, bool]:
    """Nächster Termin der Quelle (None: bei jedem Lauf) und ob sie nur wegen einer Wiederholung nach
    einem unvollständigen Lauf schon vorher fällig ist.

    Args:
        conn: Verbindung; gelesen wird pipeline_meta.quellenstand (danach rollback).
        name: Name der Quelle.
        qcfg: Konfiguration der Quelle (`rhythmus`).
        jetzt: Startzeit des Laufs.

    Returns:
        (Termin oder None, Wiederholung ja/nein); die Quelle lädt, wenn kein Termin oder jetzt >= Termin.

    Raises:
        psycopg.Error: quellenstand nicht lesbar; _lauf führt dann nur diese Quelle als fehlgeschlagen.
    """
    basis, erfolg = letzter_erfolg(conn, name)
    return (naechster_termin(qcfg.get("rhythmus"), basis),
            nur_wegen_wiederholung(qcfg.get("rhythmus"), basis, erfolg, jetzt))


def letzter_erfolg(conn, name: str) -> tuple[datetime | None, datetime | None]:
    """Ab welchem Erfolg der Rhythmus zählt (rhythmus_basis) und der letzte Erfolg selbst.

    Returns:
        (Basis, letzter_erfolg); (None, None), wenn die Quelle noch nie geladen wurde.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT letzter_erfolg, letzter_lauf FROM pipeline_meta.quellenstand WHERE quelle = %s",
                    (name,))
        zeile = cur.fetchone()
    # Lesetransaktion beenden: Bei offener Transaktion wäre conn.transaction() in quelle_laden nur ein
    # Sicherungspunkt darin, und ihre Änderungen würden am Blockende nicht festgeschrieben
    conn.rollback()
    if not zeile:
        return None, None
    return rhythmus_basis(zeile[0], zeile[1]), zeile[0]


def nur_wegen_wiederholung(rhythmus: str | None, basis: datetime | None, erfolg: datetime | None,
                           jetzt: datetime) -> bool:
    """Ist die Quelle nur deshalb fällig, weil ihr letzter Lauf unvollständig war? Nur dann gehört
    der Hinweis „Wiederholung“ in den Bericht; ohne Rhythmus oder mit abgelaufenem Termin wäre sie
    ohnehin geladen worden.

    Args:
        rhythmus: Rhythmus der Quelle aus der Konfiguration.
        basis: Ergebnis von rhythmus_basis; None bei einer Wiederholung nach unvollständigem Lauf.
        erfolg: letzter_erfolg selbst.
        jetzt: Startzeit des Laufs.

    Returns:
        True nur, wenn der reguläre Termin ab `erfolg` noch nicht erreicht ist.
    """
    if basis is not None or erfolg is None or not rhythmus:
        return False
    try:
        # Termin so, als wäre der lückenhafte Lauf nicht gewesen
        termin = naechster_termin(rhythmus, erfolg)
    except ValueError:
        return False
    return termin is not None and jetzt < termin


def protokollieren(conn, lauf_id: str, eintrag: dict) -> None:
    """Protokoll je Lauf und Quelle in pipeline_meta (eigene Transaktion, auch bei Fehlern).

    Schreibt eine Zeile in pipeline_meta.quellenlauf. Eigene Transaktion, damit auch eine
    fehlgeschlagene Quelle, deren Transaktion zurückgerollt wurde, im Protokoll steht. Die Spalte
    `entfernt` trägt den Zähler `geloescht`.

    Args:
        conn: Verbindung ohne offene Transaktion.
        lauf_id: Laufkennung.
        eintrag: Berichtseintrag der Quelle (status, zaehler, info, warnungen, fehler, laufzeit_s).

    Raises:
        psycopg.Error: Schreiben gescheitert; _protokoll_sicher fängt das ab.
    """
    # Fehlgeschlagene oder nicht fällige Quellen haben keine Zähler: dann NULL in allen Zählspalten
    z = eintrag.get("zaehler") or {}
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("""INSERT INTO pipeline_meta.quellenlauf (lauf_id, quelle, tabelle, status, gelesen, neu,
                           geaendert, entfernt, unveraendert, uebernommen, zurueckgehalten, dauer_s,
                           warnungen, fehler)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    # Derselbe Erfolgsstatus wie im Quellenverzeichnis (Codex-Prüfung 05.11., B3)
                    (lauf_id, eintrag["quelle"], (eintrag.get("info") or {}).get("ziel"),
                     verzeichnis.ergebnis(eintrag),
                     z.get("gelesen"), z.get("neu"), z.get("geaendert"), z.get("geloescht"),
                     z.get("unveraendert"), z.get("uebernommen"), z.get("zurueckgehalten"),
                     eintrag.get("laufzeit_s"),
                     json.dumps(eintrag.get("warnungen") or [], ensure_ascii=False),
                     eintrag.get("fehler")))


# Obergrenze für einen einzelnen Verbindungsversuch (libpq connect_timeout). Ohne sie hängt ein Versuch
# bei einem Netz, das Pakete still verwirft, bis zum TCP-Timeout des Betriebssystems (E45)
VERBINDUNG_TIMEOUT_S = 10


class DatenbankWeg(RuntimeError):
    """Verbindung abgerissen und nicht wieder aufzubauen. Die Fehlerbehandlung je Quelle lässt sie
    durch: Der Lauf endet als technischer Abbruch, statt jede weitere Quelle als fehlgeschlagen zu
    führen (Code-Review 05.11. nach E44, E45)."""


# Schlüssel der datenbankweiten Sperre (pg_advisory_lock, Prüfbericht 05.11., F10, E46): fest, damit alle
# Fassungen und Konfigurationen der Pipeline dieselbe Sperre nehmen. 0x67656F6461746E = „geodatn“ (ASCII)
DB_SPERRE = 0x67656F6461746E


def db_sperre(conn) -> None:
    """Nur ein Lauf je Datenbank gleichzeitig, auch aus verschiedenen Berichtsordnern, Rechnern oder
    Containern; die Dateisperre gilt nur je Berichtsordner (Prüfbericht 05.11., F10, E46). Sitzungssperre:
    Sie hält bis zum Ende der Verbindung, auch über die Transaktionen der Quellen und deren Rollback
    hinweg, und PostgreSQL löst sie, wenn die Verbindung abreißt. Wartet nicht.

    Raises:
        LaufLaeuftNoch: Eine andere Sitzung hält den Schlüssel DB_SPERRE; die Meldung nennt ihre
            Prozessnummer, soweit pg_locks sie zeigt.
    """
    with conn.cursor() as cur:
        # pg_try_ statt pg_advisory_lock: ein zweiter Start soll abbrechen, nicht hinter dem ersten warten
        cur.execute("SELECT pg_try_advisory_lock(%s)", (DB_SPERRE,))
        frei = cur.fetchone()[0]
    conn.rollback()
    if not frei:
        # Den Schlüssel kann jede Sitzung mit Zugang zur Datenbank nehmen, auch eine andere Rolle oder die
        # eigene alte Sitzung nach einem halboffenen Abriss: deshalb neutral, mit der Sitzung, die ihn hält
        # (Nachprüfung zu E46). pg_locks führt einen bigint-Schlüssel als classid (obere 32 Bit), objid
        # (untere 32 Bit) und objsubid 1
        try:
            with conn.cursor() as cur:
                cur.execute("""SELECT string_agg(pid::text, ', ' ORDER BY pid) FROM pg_locks
                               WHERE locktype = 'advisory' AND granted AND objsubid = 1
                               AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
                               AND classid::bigint = %s AND objid::bigint = %s""",
                            (DB_SPERRE >> 32, DB_SPERRE & 0xFFFFFFFF))
                pid = cur.fetchone()[0]
            conn.rollback()
        except Exception:
            # Die Prozessnummer ist nur eine Hilfe für die Meldung; ohne sie bleibt es beim Abbruch
            pid = None
        raise LaufLaeuftNoch(f"Die Sperre der Pipeline auf derselben Datenbank (pg_advisory_lock "
                             f"{DB_SPERRE}) hält Sitzung {pid or 'unbekannt'}: ein anderer Lauf oder eine "
                             "andere Sitzung mit diesem Schlüssel (pg_stat_activity); dieser Start bricht ab")


KATALOG_VIEW = "public.source_granularities"
# Wartegrenze für die Sperre der View (lock_timeout), wenn die Konfiguration oben kein
# `katalog_sperre_max_s` setzt. REFRESH ohne CONCURRENTLY braucht ACCESS EXCLUSIVE; solange die Anforderung
# wartet, stehen auch neue Leser der View hinter ihr an. Deshalb kurz: Scheitert es, holt der nächste Lauf
# es nach (Nachprüfung zu E46; bis dahin 60 s). Als Text für set_config; die Tests setzen ihn herunter
KATALOG_WARTEN = "10s"

# Zeitlimit der Katalogaktualisierung in Minuten (statement_timeout, E52), wenn die Konfiguration oben kein
# `katalog_zeitlimit_min` setzt. Bis E52 lief sie ohne eigene Grenze (Prüfbericht 07.11., K1); die
# Nachprüfung zu E51 hatte eine Grenze abgelehnt, weil eine Grenze unter der unbekannten Dauer den Katalog
# nach jedem Vollumfang dauerhaft offen ließe. Deshalb großzügig und aus dem Betrieb abgeleitet, nicht aus
# einer Messung: Die Summe der Zeitbudgets der Lieferkonfiguration (390 min) liegt 30 min unter
# TimeoutStartSec (7 h, E51); 20 min davon für den Katalog lassen 10 min für Bericht, Karte und
# Quellenverzeichnis. Überschritten heißt: Warnung, katalog_offen bleibt, der nächste Lauf holt es nach,
# statt dass systemd den ganzen Lauf mit SIGTERM beendet (technischer Abbruch, CRITICAL)
KATALOG_ZEITLIMIT_STANDARD_MIN = 20

# Rückgabe von pipeline_meta.katalog_aktualisieren() -> (ergebnis, verfahren) im Bericht (E52). Seit E52
# meldet die Funktion, ob sie gleichzeitig (CONCURRENTLY, Leser laufen weiter) oder exklusiv aktualisiert
# hat; im Bericht bleibt `ergebnis` beim bisherigen Wort (Textbericht, --status, Auswertungen), `verfahren`
# kommt dazu. 'aktualisiert' liefert auch eine Fassung der Funktion von vor E52; sie aktualisierte immer
# exklusiv. Nach einem Update ohne einrichten kommt es nicht so weit (meta_pruefen hält wegen der neuen
# Spalten von pipeline_meta an); die Zuordnung ist nur Vorsicht, etwa bei einer von Hand zurückgesetzten
# Funktion
KATALOG_ERGEBNIS = {"aktualisiert_gleichzeitig": ("aktualisiert", "gleichzeitig"),
                    "aktualisiert": ("aktualisiert", "exklusiv")}


def katalog_grenzen(cfg: dict) -> tuple[float, float | None]:
    """Zeitgrenzen der Katalogaktualisierung aus der Konfiguration oben (E52): (Zeitlimit in Minuten,
    Wartegrenze für die Sperre in Sekunden oder None). Ohne Angabe KATALOG_ZEITLIMIT_STANDARD_MIN bzw. None,
    dann gilt KATALOG_WARTEN (in katalog_aktualisieren zur Laufzeit gelesen). Gültigkeit prüft
    zeitbudget_pruefen vor dem Lauf."""
    return cfg.get("katalog_zeitlimit_min", KATALOG_ZEITLIMIT_STANDARD_MIN), cfg.get("katalog_sperre_max_s")


def katalog_aktualisieren(conn, lauf_id: str = "", aenderung: bool = True, *,
                          zeitlimit_min: float = KATALOG_ZEITLIMIT_STANDARD_MIN,
                          sperre_max_s: float | None = None, vorab=None) -> dict | None:
    """Katalog von MOSIDI nach einem Lauf mit Änderungen (Antwort 75, Prüfbericht 05.11., F2, E46): die
    Materialized View über pipeline_meta.katalog_aktualisieren(), die einrichten als Administrator anlegt;
    die Importrolle darf nur sie ausführen. Eigene Transaktion nach den Quellen. Scheitert es, ist das eine
    Warnung (Rückgabe 1, --status WARNING), kein Abbruch: Die Daten der Quellen sind schon übernommen.

    Auch ohne Änderung in diesem Lauf, wenn ein früherer Lauf den Katalog offen gelassen hat
    (pipeline_meta.katalog_offen: Aufruf gescheitert oder Lauf vorher abgebrochen); bis dahin blieb der
    Katalog alt, und --status sprang nach einem Lauf ohne Änderung auf OK (Nachprüfung zu E46). Gelingt
    der Aufruf oder fehlt die View, wird die Liste in derselben Transaktion geleert. Rückgabe: Eintrag für
    den Bericht, mit `nachgeholt` (frühere Läufe), oder None, wenn nichts zu tun war.

    Seit E52 (Mitbewerber-Sichtung 08.11.2026; Prüfbericht 07.11., K1) in zwei Transaktionen:
      1. katalog_offen lesen (schon mit den Grenzen aus 3.); ist nichts zu tun, Ende ohne weitere Anweisung.
      2. `vorab` mit dem Eintrag „ausstehend“ aufrufen (laden._lauf schreibt damit den Bericht, bevor die
         Berechnung beginnt; scheitert der Prozess währenddessen, steht der Bericht mit allen Quellen da und
         --status meldet WARNING statt nichts). Ein Fehler in `vorab` wird nur protokolliert.
      3. Mit eigenem Zeitlimit (statement_timeout = `zeitlimit_min`) und Wartegrenze für die Sperre
         (lock_timeout = `sperre_max_s`, Standard KATALOG_WARTEN), beide nur für diese Transaktion, die
         Funktion aufrufen und katalog_offen leeren. Die Funktion aktualisiert gleichzeitig (CONCURRENTLY),
         wenn die View einen dafür nutzbaren eindeutigen Index hat, sonst exklusiv (sql/pipeline_meta.sql);
         der Bericht nennt es unter `verfahren`.
    Zwischen 1 und 3 kann kein anderer Lauf katalog_offen ändern: Beide halten die datenbankweite Sperre
    (db_sperre), solange ihre Verbindung steht.

    Args:
        conn: Verbindung ohne offene Transaktion.
        lauf_id: Kennung dieses Laufs; sie zählt in katalog_offen nicht als früherer Lauf.
        aenderung: Hat dieser Lauf Daten einer Quelle geändert (_mit_aenderung)?
        zeitlimit_min: statement_timeout für den Aufruf in Minuten (katalog_zeitlimit_min, E52).
        sperre_max_s: lock_timeout in Sekunden (katalog_sperre_max_s, E52); None = KATALOG_WARTEN.
        vorab: Funktion, die den Eintrag „ausstehend“ bekommt, bevor die Berechnung beginnt, oder None.

    Returns:
        {"view", "ergebnis", ggf. "verfahren", "fehler", "zeitgrenze", "nachgeholt"} oder None. `ergebnis`:
        aktualisiert (mit `verfahren` gleichzeitig oder exklusiv), fehlt, keine_materialized_view oder
        "fehler". `zeitgrenze` (statement_timeout oder lock_timeout) nur, wenn der Fehler eine der beiden
        Grenzen ist, erkannt an der Ausnahmeklasse und bei statement_timeout an der verstrichenen Zeit (wie
        db_zeitgrenze_melden, Nachprüfung zu E51: der Text folgt lc_messages des Servers). `nachgeholt` nennt
        die früheren Läufe aus katalog_offen, auch wenn der Aufruf scheiterte (dann bleiben sie offen).

    Jede Exception fängt die Funktion selbst ab (Log und Eintrag mit "fehler"); nur BaseException wie
    Beendet geht durch.
    """
    frueher: list[str] = []
    # Wie db_grenzen: nie 0 (hieße „ohne Grenze“), höchstens PG_ZEITGRENZE_MAX_MS
    anweisung_ms = max(1, math.ceil(min(zeitlimit_min * 60_000, PG_ZEITGRENZE_MAX_MS)))
    warten = f"{max(1, math.ceil(min(sperre_max_s * 1000, PG_ZEITGRENZE_MAX_MS)))}ms" \
        if sperre_max_s is not None else KATALOG_WARTEN
    t0 = time.monotonic()
    grenzen = ("SELECT set_config('lock_timeout', %s, true), "
               "set_config('statement_timeout', %s, true)")
    try:
        with conn.transaction(), conn.cursor() as cur:
            # Dieselben Grenzen schon für das Lesen (Codex-Prüfung E52): sonst hielte eine Sperre auf
            # katalog_offen den Lauf hier unbegrenzt auf
            cur.execute(grenzen, (warten, f"{anweisung_ms}ms"))
            cur.execute("SELECT array_agg(lauf_id ORDER BY lauf_id) FROM pipeline_meta.katalog_offen")
            frueher = [x for x in (cur.fetchone()[0] or []) if x != lauf_id]
        if not (aenderung or frueher):
            return None
        if vorab is not None:
            ausstehend = {"view": KATALOG_VIEW, "ergebnis": "ausstehend"}
            try:
                vorab({**ausstehend, "nachgeholt": frueher} if frueher else ausstehend)
            except Exception as e:
                # Der Bericht folgt nach dem Katalog ohnehin; scheitert er dann auch, ist das ein Abbruch
                log.warning("Bericht vor der Katalogaktualisierung nicht geschrieben", exc_info=e)
        t0 = time.monotonic()
        with conn.transaction(), conn.cursor() as cur:
            # Dritter Parameter true: beide Grenzen gelten nur bis zum Ende dieser Transaktion (wie SET
            # LOCAL); statement_timeout misst die eine Anweisung unten samt Warten auf die Sperre
            cur.execute(grenzen, (warten, f"{anweisung_ms}ms"))
            cur.execute("SELECT pipeline_meta.katalog_aktualisieren()")
            roh = cur.fetchone()[0]
            # Erst nach einem gelungenen Aufruf: Scheitert er, kommt die Ausnahme vorher, nichts wird
            # geleert, und der nächste Lauf holt die Aktualisierung nach
            cur.execute("DELETE FROM pipeline_meta.katalog_offen")
    except Exception as e:
        log.error("Katalog %s nicht aktualisiert", KATALOG_VIEW, exc_info=e)
        aus = {"view": KATALOG_VIEW, "ergebnis": "fehler",
               "fehler": betrieb.einzeilig(f"{type(e).__name__}: {e}")[:500]}
        # Zeitgrenze nach der Ausnahmeklasse, nie nach dem Text (Nachprüfung zu E51). QueryCanceled hat auch
        # ein Abbruch von Hand; als Zeitlimit zählt er nur, wenn das Limit bis auf die Schwelle verstrichen
        # ist. Die Schwelle höchstens das halbe Limit (Codex-Prüfung E52): Bei einem Limit unter 1 s wäre sie
        # sonst negativ, und jeder sofortige Abbruch von Hand zählte als Zeitlimit
        limit_s = anweisung_ms / 1000
        if isinstance(e, pg_fehler.LockNotAvailable):
            aus["zeitgrenze"] = "lock_timeout"
        elif isinstance(e, pg_fehler.QueryCanceled) and \
                time.monotonic() - t0 >= limit_s - min(STATEMENT_TIMEOUT_SCHWELLE_S, limit_s / 2):
            aus["zeitgrenze"] = "statement_timeout"
    else:
        ergebnis, verfahren = KATALOG_ERGEBNIS.get(roh, (roh, None))
        aus = {"view": KATALOG_VIEW, "ergebnis": ergebnis}
        if verfahren:
            aus["verfahren"] = verfahren
    return {**aus, "nachgeholt": frueher} if frueher else aus


def _mit_aenderung(q: dict) -> bool:
    """Hat die Quelle laut Berichtseintrag Daten geändert (Status ok und neu, geändert, gelöscht oder
    übernommen)? Dieselben Zähler wie `geaendert` in quelle_laden; entscheidet über den Katalog."""
    z = q.get("zaehler") or {}
    return q.get("status") == "ok" and any(z.get(k) for k in ("neu", "geaendert", "geloescht", "uebernommen"))


def _tot(conn) -> bool:
    """Ist die Verbindung laut psycopg geschlossen (`closed`) oder kaputt (`broken`)? Ein Objekt ohne
    diese Attribute gilt als lebendig. `broken` setzt psycopg erst nach einem gescheiterten Zugriff,
    `closed` auch nach einem ausdrücklichen close() (siehe _verbindung)."""
    return bool(getattr(conn, "closed", False) or getattr(conn, "broken", False))


def _verbindung(conn, stapel: contextlib.ExitStack):
    """Die Verbindung, oder eine neue, wenn sie abgerissen ist (Server neu gestartet, Netz, Sitzung
    beendet). Ohne das liefen Protokoll und alle weiteren Quellen auf der toten Verbindung, und der Lauf
    endete ohne regulären Bericht (Code-Review 05.11., F5, E44).

    Einen Abriss vermerkt psycopg in `closed` und `broken` erst nach einem gescheiterten Zugriff (`closed`
    steht außerdem nach einem ausdrücklichen close()). Eine Verbindung, die im
    Leerlauf gestorben ist (etwa beim Neustart des Servers während eines langen Downloads), sähe noch
    gesund aus, und die nächste Abfrage einer Quelle, die selbst in Ordnung ist, scheiterte an ihr. Deshalb
    vorher ein Lebenstest mit `SELECT 1`, danach rollback, damit keine offene Transaktion in die Quelle
    reicht (E45). Scheitert er, ohne dass die Verbindung tot ist, geht der Fehler an die Quelle.

    Neuaufbau einmal mit kurzer Wartezeit: bei verweigerter Verbindung rund 6 s (Versuche alle 2 s, Ende
    nach mehr als 5 s), bei still verworfenen Paketen höchstens rund 10 s (`VERBINDUNG_TIMEOUT_S`).
    Scheitert er, wirft er DatenbankWeg, und der Lauf versucht es nicht weiter (E45). Die datenbankweite
    Sperre endet mit der alten Verbindung; die neue nimmt sie wieder. Hat inzwischen ein anderer Lauf sie,
    ist das ebenfalls DatenbankWeg (E46).

    Args:
        conn: bisherige Verbindung.
        stapel: ExitStack von _lauf; eine neue Verbindung kommt hinein, damit sie am Ende des Laufs
            geschlossen wird.

    Returns:
        Eine lebende Verbindung ohne offene Transaktion: die bisherige oder eine neue.

    Raises:
        DatenbankWeg: Neuaufbau oder erneute Sperre gescheitert.
        Exception: Lebenstest gescheitert, die Verbindung ist aber nicht tot (geht an die Quelle).
    """
    if not _tot(conn):
        try:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.rollback()
            return conn
        except Exception:
            if not _tot(conn):
                raise
    log.warning("Datenbankverbindung abgerissen, wird neu aufgebaut")
    # Die alte Verbindung kann schon halb geschlossen sein; ein Fehler beim Schließen ändert nichts
    with contextlib.suppress(Exception):
        conn.close()
    try:
        # Dieselbe Quelle für die Zugangsdaten wie in _lauf: DATABASE_URL oder die PG*-Variablen
        neu = stapel.enter_context(verbinden(os.environ.get("DATABASE_URL", ""), warten_s=5,
                                             connect_timeout=VERBINDUNG_TIMEOUT_S))
        db_sperre(neu)
        return neu
    except Exception as e:
        raise DatenbankWeg(f"Datenbankverbindung abgerissen, Neuaufbau gescheitert: "
                           f"{type(e).__name__}: {e}"[:500]) from e


def _warnung(eintrag: dict, was: str, e: Exception) -> None:
    """Fehler eines Nachlaufschritts als Warnung der Quelle: ins Log (mit Traceback) und in
    eintrag["warnungen"], auf 500 Zeichen begrenzt. Der Status der Quelle bleibt unverändert."""
    log.error("%s (Quelle %s)", was, eintrag["quelle"], exc_info=e)
    eintrag.setdefault("warnungen", []).append(f"{was}: {type(e).__name__}: {e}"[:500])


def _protokoll_sicher(conn, stapel: contextlib.ExitStack, lauf_id: str, eintrag: dict):
    """protokollieren() je Quelle abgefangen. Scheitert es, sind die Daten einer erfolgreichen Quelle
    schon übernommen (eigene Transaktion, quellenstand gesetzt); ihr Status bleibt deshalb, der Bericht
    bekommt eine Warnung. Gibt die (womöglich neue) Verbindung zurück. DatenbankWeg geht nach der
    Warnung durch.

    Args:
        conn: bisherige Verbindung (wird vorher mit _verbindung geprüft).
        stapel: ExitStack von _lauf für eine neu aufgebaute Verbindung.
        lauf_id: Laufkennung.
        eintrag: Berichtseintrag der Quelle; bekommt im Fehlerfall eine Warnung.

    Raises:
        DatenbankWeg: Die Datenbank ist nicht mehr erreichbar; _lauf bricht dann den Lauf ab.
    """
    try:
        conn = _verbindung(conn, stapel)
        protokollieren(conn, lauf_id, eintrag)
    except Exception as e:
        _warnung(eintrag, "Protokoll in pipeline_meta.quellenlauf nicht geschrieben", e)
        if isinstance(e, DatenbankWeg):
            raise
    return conn


def _nachlauf(conn, stapel: contextlib.ExitStack, ordner: Path, lauf_id: str, name: str, qcfg: dict,
              cfg: dict, eintrag: dict, spr: str):
    """Meldungsentwurf, Stand-Archiv und Protokoll einer Quelle nach dem Laden, jeder Schritt abgefangen.
    Meldung und Archiv standen bis E45 außerhalb der Fehlerbehandlung je Quelle: Scheiterte einer der
    beiden (etwa Platte voll), endete der Lauf mit einem Abbruchbericht ohne Quellen, und die übrigen
    Quellen liefen nicht, obwohl die Daten dieser Quelle schon übernommen waren (Code-Review 05.11. nach
    E44). Jetzt wird ein Fehler zur Warnung, der Status bleibt. Das Protokoll kommt zuletzt, damit es
    diese Warnungen enthält. Gibt die (womöglich neue) Verbindung zurück.

    Nur im regulären Lauf aufgerufen; der Probelauf schreibt weder Meldungen noch Archiv noch Protokoll.

    Args:
        conn: bisherige Verbindung.
        stapel: ExitStack von _lauf für eine neu aufgebaute Verbindung.
        ordner: Berichtsordner; dorthin kommen Meldungsentwurf und Archiv.
        lauf_id: Laufkennung, Präfix der Dateinamen.
        name: Name der Quelle.
        qcfg: Konfiguration der Quelle.
        cfg: ganze Konfiguration (Schalter `archiv`).
        eintrag: Berichtseintrag der Quelle; bekommt `meldung`, `archiv` oder Warnungen.
        spr: Sprache des Meldungsentwurfs.

    Raises:
        DatenbankWeg: aus Archiv oder Protokoll; die Warnung steht dann schon im Eintrag.
    """
    # Meldungsentwurf (E8): nur eine Datei für einen Menschen, die Pipeline schickt nichts ab
    if waechter.meldung_noetig(eintrag):
        try:
            datei = ordner / f"{lauf_id}-meldung-{name}.txt"
            verzeichnis.schreiben(datei, waechter.meldung_text(name, qcfg, eintrag, lauf_id, spr))
            eintrag["meldung"] = datei.name
        except Exception as e:
            _warnung(eintrag, "Meldungsentwurf nicht geschrieben", e)
    z = eintrag.get("zaehler") or {}
    # Stand-Archiv (E17) nur, wenn es eingeschaltet ist und die Quelle Werte geändert hat
    if (cfg.get("archiv") and eintrag["status"] == "ok"
            and (z.get("neu") or z.get("geaendert") or z.get("geloescht"))):
        try:
            conn = _verbindung(conn, stapel)
            # Lesen in einer eigenen Transaktion, die danach endet und nichts offen lässt
            with conn.transaction():
                eintrag["archiv"] = str(betrieb.archiv_schreiben(
                    conn, ordner, lauf_id, name, ziel.aus_konfiguration(name, qcfg)).relative_to(ordner))
        except Exception as e:
            _warnung(eintrag, "Stand-Archiv nicht geschrieben", e)
            if isinstance(e, DatenbankWeg):
                raise
    return _protokoll_sicher(conn, stapel, lauf_id, eintrag)


class LaufLaeuftNoch(RuntimeError):
    """Ein anderer Lauf hält die Sperre im Berichtsordner (sperre) oder eine andere Sitzung die
    datenbankweite Sperre (db_sperre, E46). Rückgabe 1, kein Abbruchbericht (siehe lauf)."""


class KonfigFehler(RuntimeError):
    """Konfiguration nicht lesbar (dann ist auch der Berichtsordner unbekannt) oder ungültig."""


class MetaFehlt(RuntimeError):
    """Schema pipeline_meta fehlt: `python -m pipeline.einrichten` wurde nicht ausgeführt."""


def konfiguration_lesen(pfad: str) -> dict:
    """Konfiguration als YAML lesen und grob prüfen (Abschnitt `quellen` als Zuordnung).

    yaml.safe_load: Die Konfiguration kann keine Python-Objekte erzeugen. Die Prüfung der einzelnen
    Quellen folgt später (rhythmen_pruefen, ziel.aus_konfiguration, die Adapter).

    Args:
        pfad: Pfad der YAML-Datei.

    Returns:
        Die Konfiguration als dict.

    Raises:
        KonfigFehler: Datei nicht lesbar, kein gültiges UTF-8 oder YAML, oder `quellen` fehlt, steht
            ohne Wert da oder ist keine Zuordnung.
    """
    try:
        cfg = yaml.safe_load(Path(pfad).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise KonfigFehler(f"Konfiguration {pfad} nicht lesbar: {type(e).__name__}: {e}"[:500]) from e
    if not isinstance(cfg, dict) or not isinstance(cfg.get("quellen"), dict):
        raise KonfigFehler(f"Konfiguration {pfad}: Abschnitt `quellen` fehlt oder ist leer")
    return cfg


@contextlib.contextmanager
def sperre(ordner: Path):
    """Nur ein Lauf je Berichtsordner gleichzeitig (Timer und Handstart überschneiden sich sonst und
    schreiben dieselben Quellen doppelt). Die Sperre löst das Betriebssystem auch nach einem Absturz.

    Args:
        ordner: Berichtsordner; die Sperrdatei .lauf.sperre bleibt dort liegen.

    Raises:
        LaufLaeuftNoch: Die Sperre ist schon vergeben; es wird nicht gewartet.
        OSError: Sperrdatei nicht anlegbar.
    """
    # "a+": legt die Datei an, falls sie fehlt, ohne eine vorhandene zu leeren
    with open(ordner / ".lauf.sperre", "a+", encoding="utf-8") as f:
        try:
            # LOCK_NB: ein zweiter Start bricht sofort ab, statt hinter dem ersten zu warten (E34)
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LaufLaeuftNoch(f"Ein anderer Lauf nutzt {ordner} noch, dieser Start bricht ab") from None
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def startzeit(ordner: Path) -> datetime:
    """Startzeit mit einer Laufkennung, die es im Berichtsordner noch nicht gibt (Kennung auf die
    Sekunde; zwei sehr kurze Läufe hintereinander bekämen sonst dieselbe).

    Nur unter der Sperre des Berichtsordners aufrufen: Erst dann kann kein anderer Lauf dieselbe Kennung
    gleichzeitig vergeben. Geprüft werden regulärer Bericht und Probelauf-Bericht.

    Args:
        ordner: Berichtsordner.

    Returns:
        Startzeit (UTC); ihre Sekunde ergibt die Laufkennung.
    """
    while True:
        jetzt = datetime.now(UTC)
        lid = jetzt.strftime("%Y%m%dT%H%M%SZ")
        if not any((ordner / f"{lid}{e}.json").exists() for e in ("", "-probelauf")):
            return jetzt
        time.sleep(0.2)


def abbruch_melden(ordner: Path, jetzt: datetime, probelauf: bool, fehler: BaseException,
                   nachtragen: bool = True, teilbericht: dict | None = None) -> Path | None:
    """Auch ein technischer Abbruch (Datenbank nicht erreichbar, Platte voll, pipeline_meta fehlt,
    Sperre nicht anlegbar, Signal) hinterlässt einen Bericht, damit --status ihn sieht und nicht den
    letzten guten Lauf meldet. Steht der Bericht des Laufs schon da (Abbruch erst danach, etwa beim
    Quellenverzeichnis), bekommt er den Abbruch nachgetragen, aber nur mit nachtragen=True: Das darf
    nur der Lauf selbst, dessen Kennung aus startzeit() eindeutig ist. Vor der Sperre ist die Zeit
    nicht eindeutig, ein Bericht derselben Sekunde gehört dann einem anderen Lauf und bleibt
    unberührt. Rückgabe: Datei, oder None, wenn nichts schreibbar war (dann bleibt nur die Meldung
    auf stderr und der Rückgabewert).

    Seit E50 (Befund K2): Steht noch kein Bericht da, aber der Lauf hat schon Quellen bearbeitet
    (`teilbericht`, der Bericht im Aufbau aus _lauf), enthält der Abbruchbericht deren Ergebnisse statt
    `quellen: []`. Seit E52 gilt der Bericht im Aufbau auch, wenn die Datei schon da ist (sie ist ein älterer
    Stand desselben Berichts, etwa der Bericht vor dem Katalog mit „ausstehend“); ohne ihn wird die Datei
    ergänzt. Neben dem JSON entsteht auch der Textbericht mit dem Abbruch (zusammenfassung); scheitert
    er, bleibt das JSON.

    Args:
        ordner: Berichtsordner.
        jetzt: Startzeit; ihre Sekunde ergibt den Dateinamen.
        probelauf: Bericht mit Endung -probelauf.json.
        fehler: Ursache des Abbruchs; `abbruch` bekommt Typ und Text (höchstens 500 Zeichen).
        nachtragen: Darf ein vorhandener Bericht derselben Kennung ergänzt werden?
        teilbericht: Bericht im Aufbau mit den bisher bearbeiteten Quellen, oder None (Abbruch vor dem Lauf).

    Returns:
        Pfad des geschriebenen Berichts oder None.
    """
    lid = jetzt.strftime("%Y%m%dT%H%M%SZ")
    datei = ordner / f"{lid}{'-probelauf' if probelauf else ''}.json"
    bericht = {"lauf_id": lid, "start": jetzt.isoformat(), "probelauf": probelauf, "quellen": []}
    if teilbericht and nachtragen:
        # Kopie, damit der Bericht im Aufbau unverändert bleibt; die Listen der Ergebnisse wie in _lauf
        bericht = _abschliessen(dict(teilbericht), None)
    # Unlesbarer vorhandener Bericht (OSError, kaputtes JSON als ValueError): dann gilt der leere Bericht
    # von oben und ersetzt ihn
    with contextlib.suppress(OSError, ValueError):
        if datei.exists():
            if not nachtragen:
                return None
            # Die Datei nur ohne Bericht im Aufbau (Codex-Prüfung E52, Muss 2): Sie ist immer ein älterer
            # Stand desselben Objekts. Seit dem Bericht vor dem Katalog (E52) stand dort „ausstehend“, während
            # der Bericht im Aufbau schon das Ergebnis hatte; ein Abbruch danach (etwa beim Schreiben in
            # pipeline_meta.lauf) hätte das Ergebnis mit dem alten Stand überschrieben
            if not teilbericht:
                bericht = json.loads(datei.read_text(encoding="utf-8"))
    bericht["abbruch"] = f"{type(fehler).__name__}: {fehler}"[:500]
    try:
        # Atomar (verzeichnis.schreiben): Ein Abbruch beim Schreiben hinterlässt keinen halben Bericht
        verzeichnis.schreiben(datei, json.dumps(bericht, ensure_ascii=False, indent=2))
    except OSError:
        return None
    # Textbericht wie im regulären Lauf (E50); ein Fehler hier ändert nichts am JSON
    with contextlib.suppress(Exception):
        bericht.setdefault("laufzeit_s", 0)
        verzeichnis.schreiben(datei.with_suffix(".txt"), zusammenfassung(bericht))
    return datei


def _leer_ungenutzt(bericht: dict, leer: dict[str, str], genutzt: set[str], nur: str | None) -> None:
    """Freigaben einer Leerlieferung (--leerlieferung), die in diesem Lauf nicht bei quelle_laden ankamen, als
    `leerlieferung_ungenutzt` in den Bericht: je Quelle Name, Grund und warum (Nachprüfung zu E50, Befund W7).
    Bis dahin verfiel eine solche Freigabe still, etwa mit --nur für eine andere Quelle oder bei einer Quelle,
    die nach Rhythmus nicht fällig war. Kein Datenrisiko (nichts wird gelöscht), aber eine Lücke im Prüfpfad.
    Eine Freigabe, die ankam, aber nicht wirkte (mehr als 0 Objekte), nennt quelle_laden als Hinweis der
    Quelle."""
    eintraege = {q["quelle"]: q for q in bericht["quellen"]}
    aus = [{"quelle": name, "grund": grund, "warum": _warum_ungenutzt(eintraege.get(name), name, nur)}
           for name, grund in leer.items() if name not in genutzt]
    if aus:
        bericht["leerlieferung_ungenutzt"] = aus


def _warum_ungenutzt(q: dict | None, name: str, nur: str | None) -> str:
    """Warum eine Freigabe für die Quelle `name` (Leerlieferung, E50; Umfang, E52) nicht bei quelle_laden
    ankam, aus ihrem Eintrag im Bericht `q` (None: nicht im Bericht). Bis E52 Teil von _leer_ungenutzt."""
    if q is None:
        return (f"nicht geladen (--nur {nur})" if nur and nur != name
                else "nicht geladen (Lauf abgebrochen)")
    if q.get("status") == "nicht_faellig":
        return f"nicht fällig nach Rhythmus, nächster Termin {q.get('naechster_termin')}"
    return f"nicht geladen ({q.get('status')}: {str(q.get('fehler') or '')[:200]})"


def _umfang_ungenutzt(bericht: dict, bestaetigen: set[str], genutzt: set[str], nur: str | None) -> None:
    """Bestätigungen einer Umfangsänderung (--umfang-bestaetigen, E52), die in diesem Lauf nicht bei
    quelle_laden ankamen, als `umfang_ungenutzt` in den Bericht (wie _leer_ungenutzt): je Quelle Name und
    warum. Eine Bestätigung, die ankam, aber nicht wirkte, nennt quelle_laden als Hinweis der Quelle."""
    eintraege = {q["quelle"]: q for q in bericht["quellen"]}
    aus = [{"quelle": name, "warum": _warum_ungenutzt(eintraege.get(name), name, nur)}
           for name in sorted(bestaetigen) if name not in genutzt]
    if aus:
        bericht["umfang_ungenutzt"] = aus


def _abschliessen(bericht: dict, t0: float | None) -> dict:
    """Laufzeit und die Listen fehlgeschlagen, angehalten und unvollständig aus den Einträgen der Quellen
    (gemeinsam für den regulären Bericht und den Abbruchbericht, E50). `t0` ist der Start auf der monotonen
    Uhr, None lässt eine vorhandene Laufzeit stehen. Rückgabe: derselbe Bericht."""
    if t0 is not None:
        bericht["laufzeit_s"] = round(time.monotonic() - t0, 2)
    bericht.setdefault("laufzeit_s", 0)
    bericht["fehlgeschlagen"] = [q["quelle"] for q in bericht["quellen"] if q.get("status") == "fehler"]
    bericht["angehalten"] = [q["quelle"] for q in bericht["quellen"] if q.get("status") == "angehalten"]
    bericht["unvollstaendig"] = [q["quelle"] for q in bericht["quellen"]
                                 if q.get("status") and verzeichnis.ergebnis(q) == "unvollstaendig"]
    return bericht


def lauf(config_pfad: str, nur: str | None = None, probelauf: bool = False, alle: bool = False,
         leer: dict[str, str] | None = None, *, vollabgleich: bool = False,
         umfang_bestaetigen: set[str] | None = None) -> dict:
    """Ein Importlauf über alle aktiven Quellen. Quellen mit Rhythmus, deren Takt noch nicht
    abgelaufen ist, werden übersprungen (Status nicht_faellig), außer mit alle=True oder nur=…

    Rahmen um _lauf: Berichtsordner anlegen, Sperre im Ordner nehmen, eindeutige Startzeit vergeben
    und bei jedem technischen Abbruch einen Abbruchbericht hinterlassen (abbruch_melden).

    Args:
        config_pfad: Pfad der Konfiguration.
        nur: Name einer einzelnen Quelle (lädt sie unabhängig vom Rhythmus) oder None.
        probelauf: alles zurückrollen, nur Prüfberichte schreiben.
        alle: Rhythmus übergehen, alle aktiven Quellen laden.
        leer: Quelle -> Grund, je bestätigter Leerlieferung für genau diesen Lauf (--leerlieferung, E50).
        vollabgleich: keine Quelle überspringen, auch nicht bei byte-gleicher Datei (--vollabgleich, E52).
        umfang_bestaetigen: Quellen, deren Umfangsänderung für diesen Lauf bestätigt ist
            (--umfang-bestaetigen, E52), oder None.

    Returns:
        Der Bericht des Laufs (wie in <lauf>.json).

    Raises:
        LaufLaeuftNoch: Eine der Sperren ist vergeben; ohne Bericht.
        KonfigFehler: Konfiguration unlesbar; ohne Bericht, der Berichtsordner ist dann unbekannt.
        OSError: Berichtsordner nicht anlegbar; ohne Bericht.
        BaseException: jeder andere Abbruch (auch ungültige Konfiguration, Beendet, KeyboardInterrupt),
            nachdem der Abbruchbericht geschrieben ist, soweit möglich.
    """
    cfg = konfiguration_lesen(config_pfad)   # unlesbar: kein Ordner bekannt, nur stderr (main)
    ordner = Path(cfg.get("berichte", "berichte"))
    try:
        ordner.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OSError(f"Berichtsordner {ordner} nicht anlegbar: {e}") from e
    # Vorläufige Startzeit nur für einen Abbruch vor startzeit(); sie ist nicht eindeutig
    jetzt = datetime.now(UTC)
    # Hat der innere Block den Abbruch schon gemeldet? Verhindert einen zweiten Bericht im äußeren
    gemeldet = False
    # Bericht im Aufbau (E50, K2): _lauf legt ihn hier ab, damit ein Abbruch die bisherigen Quellen meldet
    halter: dict = {}
    try:
        with sperre(ordner):
            jetzt = startzeit(ordner)
            try:
                return _lauf(cfg, ordner, jetzt, nur, probelauf, alle, leer, halter,
                             vollabgleich=vollabgleich, umfang_bestaetigen=umfang_bestaetigen)
            except LaufLaeuftNoch:
                raise   # datenbankweite Sperre (E46): kein Bericht, wie bei der Dateisperre unten
            except BaseException as e:   # auch Beendet (SIGTERM) und KeyboardInterrupt
                gemeldet = True
                _abbruch(ordner, jetzt, probelauf, e, teilbericht=halter.get("bericht"))
                raise
    except LaufLaeuftNoch:
        # Kein Bericht: Der laufende Lauf schreibt seinen eigenen; ein Abbruchbericht dieses Starts
        # wäre jünger und verdeckte ihn in --status. Meldung und Rückgabe 1 kommen aus main().
        raise
    except BaseException as e:            # Sperrdatei nicht anlegbar, Startzeit
        if not gemeldet:
            # jetzt stammt hier nicht aus startzeit(): einen vorhandenen Bericht derselben Sekunde
            # (eines anderen, eben beendeten Laufs) nicht anfassen
            _abbruch(ordner, jetzt, probelauf, e, nachtragen=False)
        raise


def _abbruch(ordner: Path, jetzt: datetime, probelauf: bool, e: BaseException,
             nachtragen: bool = True, teilbericht: dict | None = None) -> None:
    """Abbruchbericht schreiben (abbruch_melden) und im Log festhalten, wo er liegt oder dass keiner
    geschrieben wurde. Parameter wie abbruch_melden."""
    datei = abbruch_melden(ordner, jetzt, probelauf, e, nachtragen, teilbericht)
    if datei:
        log.error("Lauf technisch abgebrochen, Bericht: %s", datei)
    else:
        log.error("Lauf technisch abgebrochen, kein Bericht geschrieben in %s (nicht schreibbar, oder "
                  "die Kennung gehört einem anderen Lauf)", ordner)


def _lauf(cfg: dict, ordner: Path, jetzt: datetime, nur: str | None, probelauf: bool, alle: bool,
          leer: dict[str, str] | None = None, halter: dict | None = None, vollabgleich: bool = False,
          umfang_bestaetigen: set[str] | None = None) -> dict:
    """Der eigentliche Lauf unter der Sperre des Berichtsordners (Aufruf nur aus lauf).

    Schritte: Konfiguration vorab prüfen (Hintergrundkarten, Rhythmen, Zeitbudgets, Leerlieferungen),
    verbinden, pipeline_meta prüfen, datenbankweite Sperre; je aktiver Quelle Fälligkeit, quelle_laden und
    (außer im Probelauf) _nachlauf; danach Katalog und Zeile in pipeline_meta.lauf (beide nicht im Probelauf;
    vor der Berechnung des Katalogs seit E52 der Bericht mit dem Katalog „ausstehend“, bericht_vor_katalog),
    dann der Pflichtbericht (JSON und Text), danach die optionalen Ausgaben (Aufräumen, Änderungskarte), der
    Bericht erneut mit deren Ergebnis, zuletzt das Quellenverzeichnis (nicht im Probelauf).

    Reihenfolge der Ausgaben (E50, Befund K2): Bis E50 liefen Aufräumen und Karte vor dem JSON-Bericht;
    scheiterte eines, endete der Lauf als technischer Abbruch mit `quellen: []`, obwohl die Daten schon
    übernommen waren. Jetzt steht der Pflichtbericht zuerst. Jede optionale Ausgabe hat ihren eigenen
    Fehlerpfad: Ein Fehler kommt nach `ausgaben_fehler` (Textbericht, --status WARNING, Rückgabe 1), der Lauf
    endet regulär, und der Bericht verweist nur auf eine Karte, die geschrieben ist.

    Args:
        cfg: ganze Konfiguration.
        ordner: Berichtsordner.
        jetzt: eindeutige Startzeit aus startzeit(); ihre Sekunde ist die Laufkennung.
        nur: einzelne Quelle oder None.
        probelauf: Transaktionen zurückrollen, Prüfberichte statt Berichte.
        alle: Rhythmus übergehen.
        leer: Quelle -> Grund je bestätigter Leerlieferung für diesen Lauf (--leerlieferung, E50), oder None.
        halter: dict, in das der Bericht im Aufbau unter "bericht" kommt (lauf() meldet daraus bei einem
            Abbruch die bisherigen Quellen), oder None.
        vollabgleich: an quelle_laden weitergereicht (--vollabgleich, E52).
        umfang_bestaetigen: Quellen mit bestätigter Umfangsänderung für diesen Lauf (--umfang-bestaetigen,
            E52), oder None; nicht angekommene stehen unter `umfang_ungenutzt` im Bericht.

    Returns:
        Der Bericht, so wie er als JSON geschrieben wurde.

    Raises:
        DatenbankWeg: Datenbank während des Laufs verloren; vorher ist der Bericht mit `abbruch`
            geschrieben.
        Exception: Fehler beim Schreiben in pipeline_meta.lauf, ebenfalls nach dem Bericht. Fehler vor
            der ersten Quelle (Konfiguration, Verbindung, MetaFehlt) gehen ohne eigenen Bericht hinaus;
            den Abbruchbericht schreibt dann lauf(), bei LaufLaeuftNoch keinen. Ein Abbruch mitten in den
            Quellen (auch Beendet, KeyboardInterrupt) geht hinaus, nachdem die laufende Quelle als
            fehlgeschlagen im Bericht im Aufbau steht; lauf() schreibt daraus den Abbruchbericht mit allen
            bisherigen Quellen (E50). Scheitert das Schreiben des Pflichtberichts oder das Quellenverzeichnis,
            geht der Fehler ebenfalls hinaus; lauf() trägt den Abbruch dann in den schon geschriebenen Bericht
            nach bzw. schreibt ihn aus dem Bericht im Aufbau.
    """
    lauf_id = jetzt.strftime("%Y%m%dT%H%M%SZ")
    t0 = time.monotonic()
    bericht = {"lauf_id": lauf_id, "start": jetzt.isoformat(), "probelauf": probelauf,
               "sprache": sprache.wahl(cfg), "quellen": []}
    if halter is not None:
        halter["bericht"] = bericht
    leer = leer or {}
    umfang_bestaetigen = set(umfang_bestaetigen or ())
    # Je Quelle ihr letzter geladener Stand aus früheren Berichten, für den Schemavergleich
    vorher = waechter.letzter_bericht(ordner, lauf_id)
    kartenobjekte: dict[str, list[dict]] = {}
    karte.hintergruende(cfg)  # Tippfehler in karte.hintergrund vor dem Laden melden, nicht danach
    rhythmen_pruefen(cfg)     # ebenso Tippfehler im Rhythmus (E44, F1)
    zeitbudget_pruefen(cfg)   # und im Zeitbudget (E50)
    leerlieferung_pruefen(cfg, leer)
    freigaben_pruefen(cfg)    # Steuerzeichen in robots_freigabe (Nachprüfung zu E50)
    ueberspringen_pruefen(cfg)  # Schalter und vollabgleich_tage (E52)
    umfang_pruefen(cfg, umfang_bestaetigen)  # umfang_bestaetigt und --umfang-bestaetigen (E52)

    # Leerer DSN: psycopg nimmt PGHOST, PGUSER, PGPASSWORD, PGDATABASE aus der Umgebung. Der Stapel
    # schließt auch Verbindungen, die nach einem Abriss neu aufgebaut wurden (E44, F5)
    with contextlib.ExitStack() as stapel:
        conn = stapel.enter_context(verbinden(os.environ.get("DATABASE_URL", ""), warten_s=30,
                                              connect_timeout=VERBINDUNG_TIMEOUT_S))
        meta_pruefen(conn)
        db_sperre(conn)
        db_weg = None
        # Eintrag und Protokoll der gerade bearbeiteten Quelle; die Zweige für DatenbankWeg und für einen
        # Abbruch unten übernehmen sie in den Bericht
        eintrag: dict = {}
        prot: Protokoll | None = None
        q0 = time.monotonic()
        # Quellen, an die quelle_laden eine Freigabe der Leerlieferung übergeben hat (Nachprüfung zu E50)
        leer_genutzt: set[str] = set()
        # Ebenso für --umfang-bestaetigen (E52)
        umfang_genutzt: set[str] = set()

        def protokoll_uebernehmen() -> None:
            """Warnungen, Hinweise, info, letzte Abfrage, Merker „unvollständig“ und Laufzeit der laufenden
            Quelle in ihren Eintrag; im regulären Pfad und bei einem Abbruch mitten in der Quelle gleich."""
            if prot is not None:
                eintrag.update(warnungen=prot.warnungen, hinweise=prot.hinweise, info=prot.info,
                               letzte_abfrage=prot.letzte_abfrage, unvollstaendig=prot.unvollstaendig,
                               laufzeit_s=round(time.monotonic() - q0, 2))

        try:
            for name, qcfg in cfg["quellen"].items():
                if nur and name != nur:
                    continue
                if not qcfg.get("aktiv", True):
                    continue
                q0 = time.monotonic()
                eintrag = {"quelle": name, "typ": qcfg["typ"]}
                prot = Protokoll()
                try:
                    # Auch die Fälligkeit je Quelle: scheitert sie (quellenstand nicht lesbar), ist nur
                    # diese Quelle fehlgeschlagen (E44, F1, F5). Ist die Datenbank ganz weg, bricht der
                    # Lauf ab (E45)
                    conn = _verbindung(conn, stapel)
                    termin, wiederholung = None, False
                    if not (alle or nur):
                        termin, wiederholung = faelligkeit(conn, name, qcfg, jetzt)
                except DatenbankWeg:
                    raise
                except Exception as e:
                    log.exception("Fälligkeit der Quelle %s nicht prüfbar", name)
                    eintrag.update(status="fehler", fehler=f"{type(e).__name__}: {e}"[:500])
                    with contextlib.suppress(Exception):
                        conn.rollback()   # abgebrochene Transaktion nicht in die nächste Quelle tragen
                else:
                    if termin and jetzt < termin:
                        # Nicht fällig: kein Abruf, nur Protokoll und Berichtszeile mit dem nächsten Termin
                        eintrag.update(status="nicht_faellig", rhythmus=qcfg["rhythmus"],
                                       naechster_termin=termin.isoformat(timespec="seconds"))
                        if not probelauf:
                            conn = _protokoll_sicher(conn, stapel, lauf_id, eintrag)
                        bericht["quellen"].append(eintrag)
                        continue
                    if wiederholung:
                        prot.hinweise.append("Wiederholung: Der letzte Lauf dieser Quelle war unvollständig, "
                                             "deshalb schon vor dem nächsten Termin des Rhythmus fällig")
                    if name in leer:
                        leer_genutzt.add(name)
                    if name in umfang_bestaetigen:
                        umfang_genutzt.add(name)
                    try:
                        eintrag.update(quelle_laden(conn, name, qcfg, lauf_id, jetzt, prot, vorher.get(name),
                                                    probelauf, kartenobjekte if karte.aktiv(cfg) else None,
                                                    leer_grund=leer.get(name),
                                                    budget_min=zeitbudget(cfg, qcfg),
                                                    sperre_max_s=db_sperre_max(cfg, qcfg),
                                                    vollabgleich=vollabgleich,
                                                    umfang_bestaetigen=name in umfang_bestaetigen))
                    except Exception as e:  # Fehler je Quelle, der Lauf geht weiter
                        log.exception("Quelle %s fehlgeschlagen", name)
                        eintrag.update(status="fehler", fehler=f"{type(e).__name__}: {e}"[:500])
                        # Pre-existing, behoben in der Nachprüfung zu E50: quelle_laden legt die Kartenobjekte
                        # vor dem Schreiben ab. Scheitert die Quelle danach (Zeitbudget, anwenden, Metadaten),
                        # ist ihre Transaktion zurückgerollt; die Karte zeigte trotzdem ihre Änderungen
                        kartenobjekte.pop(name, None)
                # Auch eine fehlgeschlagene Quelle bekommt ihr Protokoll: Warnungen vor dem Fehler bleiben
                protokoll_uebernehmen()
                if not probelauf:
                    conn = _nachlauf(conn, stapel, ordner, lauf_id, name, qcfg, cfg, eintrag,
                                     bericht["sprache"])
                bericht["quellen"].append(eintrag)
        except DatenbankWeg as e:
            # Bericht mit den Quellen bis hierher, dann technischer Abbruch (wie meta_fehler unten). Die
            # Quelle, bei der die Datenbank wegblieb, steht mit ihrem Ergebnis darin, wenn sie eines hat;
            # noch nicht geprüfte Quellen fehlen, statt als fehlgeschlagen und mit Meldungsentwurf an den
            # Anbieter geführt zu werden, und behalten ihren Eintrag im Quellenverzeichnis (E45)
            db_weg = e
            if eintrag.get("status") and not any(q is eintrag for q in bericht["quellen"]):
                bericht["quellen"].append(eintrag)
        except BaseException as e:
            # Abbruch mitten in einer Quelle (Beendet, KeyboardInterrupt, ein Fehler außerhalb der
            # Fehlerbehandlung je Quelle; E50, K2): Die laufende Quelle kommt als fehlgeschlagen in den
            # Bericht im Aufbau (ihre Transaktion ist zurückgerollt), dann geht der Abbruch an lauf(), das
            # daraus den Abbruchbericht mit allen bisherigen Quellen schreibt. Bis E50 stand dort `quellen:
            # []`
            #
            # Nachprüfung zu E50: Die abgebrochene Quelle behält ihr Protokoll (Warnungen, Hinweise, info,
            # letzte Abfrage, Laufzeit) wie im regulären Pfad. Bis dahin stand sie nur mit status und fehler
            # da; eine schon genutzte robots_freigabe (ein tatsächlicher Abruf eines gesperrten Rechners)
            # fehlte im Abbruchbericht. Eine Zeile in pipeline_meta.quellenlauf schreibt der Abbruch bewusst
            # nicht: Die Ursache kann die Datenbank selbst sein, und ein Abbruch soll schnell enden
            # (docs/betrieb.md)
            if eintrag and not any(q is eintrag for q in bericht["quellen"]):
                if not eintrag.get("status"):
                    eintrag.update(status="fehler", fehler=f"{type(e).__name__}: {e}"[:500])
                kartenobjekte.pop(eintrag["quelle"], None)
                if "warnungen" not in eintrag:
                    protokoll_uebernehmen()
                bericht["quellen"].append(eintrag)
            _leer_ungenutzt(bericht, leer, leer_genutzt, nur)
            _umfang_ungenutzt(bericht, umfang_bestaetigen, umfang_genutzt, nur)
            _abschliessen(bericht, t0)
            raise

        _leer_ungenutzt(bericht, leer, leer_genutzt, nur)
        _umfang_ungenutzt(bericht, umfang_bestaetigen, umfang_genutzt, nur)

        _abschliessen(bericht, t0)
        # Eigene Dateinamen für den Probelauf: Er ersetzt keinen regulären Bericht und zählt nicht als
        # Vergleichsstand (waechter.letzter_bericht)
        stamm = f"{lauf_id}-probelauf" if probelauf else lauf_id
        # Fehler, der den Lauf erst nach dem Schreiben der Berichte als technischen Abbruch beendet
        meta_fehler: BaseException | None = db_weg

        def berichte_schreiben() -> None:
            """JSON- und Textbericht des Laufs (atomar, verzeichnis.schreiben)."""
            verzeichnis.schreiben(ordner / f"{stamm}.json", json.dumps(bericht, ensure_ascii=False, indent=2))
            verzeichnis.schreiben(ordner / f"{stamm}.txt", zusammenfassung(bericht))

        def bericht_vor_katalog(eintrag: dict) -> None:
            """Bericht mit allen Quellen und dem Katalog „ausstehend“, bevor die Berechnung beginnt (E52,
            Prüfbericht 07.11., K1). Bis E52 stand der Bericht erst nach dem Katalog; endete der Prozess
            währenddessen ohne Abbruchbericht (SIGKILL, Neustart des Rechners), gab es für diesen Lauf keinen,
            obwohl die Daten übernommen waren. Nach dem Katalog wird der Bericht unten wie bisher geschrieben
            und ersetzt diesen."""
            bericht["katalog"] = eintrag
            berichte_schreiben()

        if not probelauf and not db_weg:
            try:
                conn = _verbindung(conn, stapel)
                zeitlimit_min, sperre_max_s = katalog_grenzen(cfg)
                katalog = katalog_aktualisieren(conn, lauf_id, any(map(_mit_aenderung, bericht["quellen"])),
                                                zeitlimit_min=zeitlimit_min, sperre_max_s=sperre_max_s,
                                                vorab=bericht_vor_katalog)
                if katalog:
                    bericht["katalog"] = katalog
            except DatenbankWeg as e:
                # Nur aus _verbindung, also vor dem Aufruf und vor dem Bericht „ausstehend“;
                # katalog_aktualisieren selbst fängt jede Exception ab
                meta_fehler = e
        if not probelauf and not meta_fehler:
            try:
                conn = _verbindung(conn, stapel)
                # Eine Zeile je Lauf; `quellen` zählt nur die Quellen, die in diesem Lauf dran waren
                with conn.transaction(), conn.cursor() as cur:
                    cur.execute("""INSERT INTO pipeline_meta.lauf (lauf_id, start, dauer_s, quellen, fehler,
                                       angehalten, unvollstaendig, bericht)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                                (lauf_id, jetzt, bericht["laufzeit_s"],
                                 sum(q["status"] != "nicht_faellig" for q in bericht["quellen"]),
                                 len(bericht["fehlgeschlagen"]), len(bericht["angehalten"]),
                                 len(bericht["unvollstaendig"]), f"{stamm}.json"))
            except Exception as e:
                # Erst den Bericht mit allen Quellen schreiben, dann als technischen Abbruch melden: lauf()
                # trägt `abbruch` in diesen Bericht nach, statt einen leeren zu schreiben (E44, F5)
                meta_fehler = e
    if meta_fehler:
        # Schon vor dem Schreiben, damit auch Textbericht und Karte den Abbruch zeigen, nicht nur das
        # JSON, in das lauf() ihn nachträgt (gleicher Text, E45)
        bericht["abbruch"] = f"{type(meta_fehler).__name__}: {meta_fehler}"[:500]

    # 1. Pflichtbericht (LB 4.5): zuerst, mit allen Quellen, noch ohne die optionalen Ausgaben (E50, K2)
    berichte_schreiben()
    # 2. Optionale Ausgaben, je mit eigenem Fehlerpfad: Ein Fehler wird vermerkt, nie ein Abbruch
    fehler_ausgaben: list[str] = []
    if cfg.get("aufbewahrung_tage") and not probelauf:
        try:
            weg = betrieb.aufraeumen(ordner, int(cfg["aufbewahrung_tage"]), jetzt)
            bericht["aufgeraeumt"] = len(weg)
            if weg:
                log.info("Aufbewahrung: %d alte Laufdateien gelöscht", len(weg))
        except Exception as e:
            log.error("Aufräumen alter Laufdateien gescheitert", exc_info=e)
            fehler_ausgaben.append(f"Aufräumen alter Laufdateien: {type(e).__name__}: {e}"[:500])
    if karte.aktiv(cfg):
        try:
            karte.schreiben(ordner / f"{stamm}-karte.html", bericht, kartenobjekte, karte.hintergruende(cfg))
            # Erst nach dem Schreiben: der Bericht verweist nie auf eine Karte, die es nicht gibt
            bericht["karte"] = f"{stamm}-karte.html"
        except Exception as e:
            log.error("Änderungskarte nicht geschrieben", exc_info=e)
            fehler_ausgaben.append(f"Änderungskarte nicht geschrieben: {type(e).__name__}: {e}"[:500])
    if fehler_ausgaben:
        bericht["ausgaben_fehler"] = fehler_ausgaben
    # 3. Bericht mit dem Ergebnis der optionalen Ausgaben. Scheitert das, bleibt der Pflichtbericht aus
    # Schritt 1
    if fehler_ausgaben or "karte" in bericht or "aufgeraeumt" in bericht:
        try:
            berichte_schreiben()
        except Exception as e:
            log.error("Bericht mit den optionalen Ausgaben nicht geschrieben; der Pflichtbericht steht",
                      exc_info=e)
    # 4. Quellenverzeichnis; scheitert es, trägt lauf() den Abbruch in den geschriebenen Bericht nach
    if not probelauf:
        verzeichnis.aktualisieren(ordner, bericht, cfg)
    if meta_fehler:
        raise meta_fehler
    return bericht


def meta_pruefen(conn) -> None:
    """Ohne pipeline_meta kein Lauf: dann fehlt der Schritt `python -m pipeline.einrichten`.

    Prüft außerdem, ob das Schema zur Fassung des Codes passt: Spalten späterer Fassungen sowie
    Funktion katalog_aktualisieren() und Tabelle katalog_offen. Liest nur aus den Systemkatalogen.

    Raises:
        MetaFehlt: Schema fehlt oder ist älter als diese Fassung; die Meldung nennt, was fehlt.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('pipeline_meta.bestand') IS NOT NULL")
        da = cur.fetchone()[0]
        cur.execute("SELECT to_regprocedure('pipeline_meta.katalog_aktualisieren()') IS NOT NULL "
                    "AND to_regclass('pipeline_meta.katalog_offen') IS NOT NULL")
        katalog = cur.fetchone()[0]
        # Spalten, die spätere Fassungen ergänzt haben (einrichten legt sie idempotent an)
        cur.execute("""SELECT array_agg(s.t || '.' || s.n ORDER BY s.t, s.n)
                       FROM (VALUES ('bestand', 'quellschluessel'), ('aenderung', 'quellschluessel'),
                                    ('lauf', 'unvollstaendig'), ('quellenstand', 'datei_sha256'),
                                    ('quellenstand', 'konfig_sha256'), ('quellenstand', 'vollabgleich'),
                                    ('quellenstand', 'register_zeilen'),
                                    ('quellenstand', 'ziel_zeilen'), ('quellenstand', 'umfang')) s (t, n)
                       WHERE NOT EXISTS (SELECT 1 FROM pg_attribute a
                                         WHERE a.attrelid = to_regclass('pipeline_meta.' || s.t)
                                         AND a.attname = s.n AND NOT a.attisdropped)""")
        fehlen = cur.fetchone()[0]
    conn.rollback()
    if not da:
        raise MetaFehlt("Schema pipeline_meta fehlt: zuerst `python -m pipeline.einrichten` als "
                        "Administrator ausführen (docs/betrieb.md)")
    if fehlen or not katalog:
        # Seit E40 führt das Register den Quellschlüssel, seit E42 pipeline_meta.lauf die unvollständigen
        # Quellen, seit E46 gibt es die Funktion für den Katalog, seit E52 den Vergleichsstand für das
        # Überspringen und den gemerkten Umfang im Quellenstand; einrichten ergänzt sie (idempotent)
        teile = ([f"Spalten fehlen: {', '.join(fehlen)}"] if fehlen else []) + (
            [] if katalog else ["Funktion katalog_aktualisieren() oder Tabelle katalog_offen fehlt"])
        raise MetaFehlt(f"Schema pipeline_meta ist älter als diese Fassung ({'; '.join(teile)}): "
                        "`python -m pipeline.einrichten` als Administrator erneut ausführen")


def _abrufadressen(cfg: dict):
    """Je aktiver Quelle, die etwas abruft: (Name, Konfiguration, Adresse). Adresse ist `url`, die Seite eines
    Berichts (`seite`) oder ein `pfad`, der eine Adresse ist; ein lokaler Pfad und INKAR mit abgelegter Datei
    (`datei` oder PIPELINE_INKAR_DATEI, E48) rufen nichts ab und fehlen."""
    for name, qcfg in cfg["quellen"].items():
        if not qcfg.get("aktiv", True):
            continue
        if qcfg.get("typ") == "inkar" and (os.environ.get("PIPELINE_INKAR_DATEI") or qcfg.get("datei")):
            continue   # abgelegte Datei, kein Abruf (E48)
        pfad = qcfg.get("pfad", "")
        url = qcfg.get("url") or qcfg.get("seite") or (pfad if "://" in pfad else None)
        if url:
            yield name, qcfg, url


def ziele(cfg: dict) -> list[str]:
    """Rechner, die der Pipeline-Container erreichen muss, als host:port je aktiver Quelle. Ohne Rechner,
    deren robots.txt den Pfad der Quelle sperrt (ROBOTS_GESPERRT): Die Pipeline ruft sie nicht ab. Mit ihnen,
    wenn die Quelle eine benannte Freigabe für den Rechner ihrer Adresse hat (robots_freigabe, E50); welche,
    sagt freigaben().

    Ohne Datenbank und ohne Netzabruf; Grundlage der Freigaben in der Firewall (--ziele).

    Args:
        cfg: ganze Konfiguration.

    Returns:
        Sortierte Liste "host:port" ohne Doppelte. Ohne Port in der Adresse gilt 443 für https, sonst 80.
    """
    aus = set()
    for _name, qcfg, url in _abrufadressen(cfg):
        # gesperrt ohne Freigabe: die Quelle bricht ohne Abruf ab (E48)
        if robots_gesperrt(url) is None or freigabe_fuer(url, qcfg) is not None:
            t = urlsplit(url)
            aus.add(f"{t.hostname}:{t.port or (443 if t.scheme == 'https' else 80)}")
            # Links von der Seite eines Berichts gehen nur auf diese Rechner, immer https (xlsx, E48)
            aus.update(f"{r}:443" for r in qcfg.get("link_rechner") or [])
    return sorted(aus)


def freigaben(cfg: dict) -> list[str]:
    """Die genutzten Freigaben gesperrter Rechner (robots_freigabe, E50) als Kommentarzeilen für --ziele:
    „# robots.txt-Freigabe: <Rechner> (Quelle <Name>): <Grund>“, je Quelle eine. Kommentarzeilen, damit ein
    Skript, das die Liste aus --ziele in Firewall-Regeln umsetzt, sie mit einem Filter auf „#“ überspringen
    kann; ein Mensch sieht beim Freischalten, warum ein gesperrter Rechner dabei ist."""
    aus = []
    for name, qcfg, url in _abrufadressen(cfg):
        if robots_gesperrt(url) is not None and (grund := freigabe_fuer(url, qcfg)) is not None:
            aus.append(f"# robots.txt-Freigabe: {quellen.quell_rechner(qcfg)} (Quelle {name}): {grund}")
    return aus


def zusammenfassung(b: dict) -> str:
    """Textbericht eines Laufs (<lauf>.txt und Ausgabe auf stdout) in der Sprache des Berichts.

    Die Textbausteine stehen in pipeline/sprachen/<code>.json unter `bericht` (E21). Je Quelle eine
    Ergebniszeile, darunter Warnungen, Hinweise und ein Verweis auf den Meldungsentwurf; nicht fällige
    Quellen nur mit ihrer Zeile.

    Args:
        b: Bericht wie aus _lauf (auch ein Abbruchbericht mit `abbruch`).

    Returns:
        Der Text, mit Zeilenumbruch am Ende.
    """
    t = sprache.texte(b.get("sprache", sprache.STANDARD))["bericht"]
    art = t["art_probelauf"] if b.get("probelauf") else t["art_import"]
    zeilen = [t["kopf"].format(art=art, lauf_id=b["lauf_id"], laufzeit=b["laufzeit_s"])]
    if b.get("abbruch"):   # wie im JSON und in --status (E45)
        zeilen.append(t["abbruch"].format(fehler=b["abbruch"]))
    for q in b["quellen"]:
        # Ergebnis wie in Verzeichnis, pipeline_meta, --status, --kennzahlen und Karte (E44, F4)
        art = verzeichnis.ergebnis(q)
        if art in ("ok", "unvollstaendig"):
            zeilen.append(t[art].format(quelle=q["quelle"], **q["zaehler"]))
        elif q["status"] == "nicht_faellig":
            zeilen.append(t["nicht_faellig"].format(quelle=q["quelle"], rhythmus=q.get("rhythmus"),
                                                    termin=q.get("naechster_termin")))
            continue
        elif q["status"] == "angehalten":
            zeilen.append(t["angehalten"].format(quelle=q["quelle"]))
        else:
            zeilen.append(t["fehler"].format(quelle=q["quelle"], fehler=q["fehler"]))
        zeilen += [t["warnung"].format(text=w) for w in q.get("warnungen", [])]
        zeilen += [t["hinweis"].format(text=h) for h in q.get("hinweise", [])]
        if q.get("meldung"):
            zeilen.append(t["meldung"].format(datei=q["meldung"]))
    if b.get("katalog"):   # E46
        k = b["katalog"]
        zeile = t[f"katalog_{k['ergebnis']}"].format(view=k["view"], fehler=k.get("fehler"))
        # Seit E52: wie aktualisiert (gleichzeitig oder exklusiv) bzw. welche Zeitgrenze griff; ein Bericht
        # von vor E52 hat beides nicht
        if k.get("verfahren") in ("gleichzeitig", "exklusiv"):
            zeile += t[f"katalog_{k['verfahren']}"]
        if k.get("zeitgrenze"):
            zeile += t["katalog_zeitgrenze"].format(zeitgrenze=k["zeitgrenze"])
        zeilen.append(zeile)
    if b.get("karte"):
        zeilen.append(t["karte"].format(datei=b["karte"]))
    # Fehler optionaler Ausgaben (Karte, Aufräumen; E50): der Bericht steht, die Ausgabe fehlt
    zeilen += [t["ausgabe_fehler"].format(text=f) for f in b.get("ausgaben_fehler", [])]
    # Freigaben einer Leerlieferung, die in diesem Lauf nicht genutzt wurden (Nachprüfung zu E50)
    zeilen += [t["leerlieferung_ungenutzt"].format(**u) for u in b.get("leerlieferung_ungenutzt", [])]
    # Ebenso Bestätigungen einer Umfangsänderung (E52)
    zeilen += [t["umfang_ungenutzt"].format(**u) for u in b.get("umfang_ungenutzt", [])]
    return "\n".join(zeilen) + "\n"


ABBRUCH = 2   # Rückgabe bei technischem Abbruch; 1 = Quelle fehlgeschlagen, angehalten, unvollständig


class Beendet(BaseException):
    """Lauf von außen beendet (SIGTERM). Bewusst keine Exception: die Fehlerbehandlung je Quelle
    darf ihn nicht als Quellfehler abfangen und mit der nächsten Quelle weitermachen."""


def _beenden(signum, _frame):
    """Signalbehandlung für SIGTERM: wirft Beendet, damit der Lauf über die normale Abbruchbehandlung
    (Abbruchbericht, Rollback der laufenden Transaktion) endet."""
    raise Beendet(f"Lauf durch Signal {signal.Signals(signum).name} beendet")


def main() -> int:
    """Einstieg für `python -m pipeline.laden`: Optionen auswerten und Lauf, --ziele, --status,
    --kennzahlen oder --version ausführen.

    Returns:
        Rückgabewert für die Shell: 0 alles gut; 1 eine Quelle fehlgeschlagen, angehalten oder
        unvollständig, der Katalog nicht aktualisiert, eine optionale Ausgabe gescheitert (E50) oder eine
        Sperre vergeben; ABBRUCH (2) technischer
        Abbruch. Mit --status die Nagios-Werte aus betrieb.status (0 bis 3), bei einem Fehler dort
        betrieb.UNBEKANNT (3).
    """
    # Erste Zeile des Moduldocstrings als Kurzbeschreibung für --help
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # PIPELINE_CONFIG: Vorgabe für den Container, --config geht vor
    ap.add_argument("--config", default=os.environ.get("PIPELINE_CONFIG", "config/quellen.yaml"))
    ap.add_argument("--nur", help="nur diese Quelle laden")
    ap.add_argument("--probelauf", action="store_true",
                    help="alles lesen, prüfen und vergleichen, ohne dauerhafte Änderungen an den "
                         "Fachdaten; Prüfbericht und Cache werden geschrieben (unveränderte Dateiquellen "
                         "werden wie im regulären Lauf übersprungen und dann nicht geprüft; vollständig mit "
                         "--probelauf --vollabgleich --alle bzw. --nur QUELLE, E52)")
    ap.add_argument("--alle", action="store_true",
                    help="alle aktiven Quellen laden, auch wenn ihr Rhythmus noch nicht abgelaufen ist")
    ap.add_argument("--vollabgleich", action="store_true",
                    help="keine Quelle als unverändert überspringen: jede fällige Quelle wird eingelesen und "
                         "verglichen, auch bei byte-gleicher Datei (E52)")
    ap.add_argument("--ziele", action="store_true",
                    help="nur ausgeben, welche Rechner erreichbar sein müssen (für die Firewall); "
                         "Freigaben gesperrter Rechner als Kommentarzeilen (#) darunter")
    ap.add_argument("--leerlieferung", nargs=2, action="append", metavar=("QUELLE", "GRUND"),
                    help="für genau diesen Lauf: 0 Objekte dieser Quelle als bestätigte Leerlieferung "
                         "übernehmen (bisherige Zeilen werden gelöscht); der Grund steht im Bericht")
    ap.add_argument("--umfang-bestaetigen", action="append", metavar="QUELLE",
                    help="für genau diesen Lauf: geänderten Umfang dieser Quelle (Adresse, Ausschnitt, "
                         "Schlüssel, Ziel) bestätigen, wenn der Lauf deshalb Zeilen löschen würde; steht im "
                         "Bericht (E52)")
    ap.add_argument("--status", action="store_true",
                    help="Zustand des letzten Laufs für die Überwachung (Rückgabe 0/1/2/3)")
    ap.add_argument("--max-alter-h", type=float, default=26,
                    help="ab diesem Alter des letzten Laufs meldet --status CRITICAL (Standard 26)")
    ap.add_argument("--kennzahlen", action="store_true", help="Läufe eines Zeitraums zusammenfassen")
    ap.add_argument("--von", help="Beginn für --kennzahlen, JJJJ-MM-TT")
    ap.add_argument("--bis", help="Ende für --kennzahlen (ausschließlich), JJJJ-MM-TT")
    ap.add_argument("--version", action="store_true", help="Signatur und Notiz des Tages")
    a = ap.parse_args()
    if a.version:
        print(signatur.text(sprache.wahl()))
        return 0
    if a.ziele:
        # Bewusst ohne Datenbank und ohne Netz: läuft auch dort, wo die Firewall noch zu ist
        cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
        try:
            # Vor der Ausgabe (Nachprüfung zu E50): ein Grund mit Zeilenumbruch ergäbe eine Zeile ohne „#“
            freigaben_pruefen(cfg)
        except KonfigFehler as e:
            print(f"--ziele abgebrochen: {e}", file=sys.stderr)
            return ABBRUCH
        print("\n".join(ziele(cfg) + freigaben(cfg)))
        return 0
    if a.status or a.kennzahlen:
        try:
            cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
            ordner = Path(cfg.get("berichte", "berichte"))
            if a.status:
                code, zeile = betrieb.status(ordner, a.max_alter_h)
                print(zeile)
                return code
            tag = lambda t: datetime.strptime(t, "%Y-%m-%d").replace(tzinfo=UTC) if t else None  # noqa: E731
            print(betrieb.kennzahlen(ordner, tag(a.von), tag(a.bis)), end="")
            return 0
        except Exception as e:  # Überwachung soll UNKNOWN sehen, keinen Python-Absturz
            print(f"GEODATEN UNKNOWN - {type(e).__name__}: {e}"[:300])
            return betrieb.UNBEKANNT
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # systemd beendet einen hängenden Lauf mit SIGTERM (Timeout); als Ausnahme kommt er durch die
    # Abbruchbehandlung und hinterlässt einen Bericht. Gegen SIGKILL hilft nur die Altersgrenze in --status.
    signal.signal(signal.SIGTERM, _beenden)
    try:
        b = lauf(a.config, a.nur, a.probelauf, a.alle, dict(a.leerlieferung or []),
                 vollabgleich=a.vollabgleich, umfang_bestaetigen=set(a.umfang_bestaetigen or []))
    except LaufLaeuftNoch as e:
        print(e, file=sys.stderr)
        return 1
    except (Exception, Beendet) as e:  # technischer Abbruch: Bericht (wenn schreibbar) steht schon da
        # Bei Konfiguration, fehlendem Schema und Signal sagt die Meldung alles; sonst Traceback ins Log
        if not isinstance(e, KonfigFehler | MetaFehlt | Beendet):
            log.error("Ursache", exc_info=e)
        print(f"Lauf technisch abgebrochen: {type(e).__name__}: {e}", file=sys.stderr)
        return ABBRUCH
    print(zusammenfassung(b), end="")
    # Ein gescheiterter Katalog ist eine Warnung (Rückgabe 1), kein Abbruch: Die Daten sind übernommen
    katalog_fehler = (b.get("katalog") or {}).get("ergebnis") == "fehler"
    # Ebenso ein Fehler einer optionalen Ausgabe (Karte, Aufräumen; E50): Rückgabe 1, der Bericht steht
    return 1 if (b["fehlgeschlagen"] or b["angehalten"] or b["unvollstaendig"] or katalog_fehler
                 or b.get("ausgaben_fehler")) else 0


if __name__ == "__main__":
    sys.exit(main())
