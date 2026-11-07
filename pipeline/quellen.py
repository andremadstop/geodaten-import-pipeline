"""Quell-Adapter. Jeder Adapter liefert Datensätze als dict:
{"objekt_id": str, "geom": (art, str), "werte": dict, "zeit": dict, "leer": bool}

  objekt_id  ID des Objekts in der Quelle (bei Kennzahlen meist der Gebietsschlüssel)
  geom       ("gml", GML-Fragment) beim WFS, ("wkt", EWKT mit SRID=…;) bei CSV mit Koordinaten,
             ("geojson", GeoJSON-Geometrie in Länge/Breite) bei OGC API und GeoJSON-Datei oder
             ("gebiet", Gebietsschlüssel) bei Tabellen ohne Geometrie; die Fläche kommt dann über den
             Schlüssel aus einer vorher geladenen Geometriequelle
  werte      Feldname -> Wert (Text, Zahl, Wahrheitswert oder None)
  zeit       optional (CSV, XLSX, INKAR): Feldname -> Zeit-Referenz des Werts (Jahr oder Datum)
  leer       optional (CSV, XLSX): Zeile ohne jeden Messwert; das Zielschreiben lässt sie aus, ihr bisheriger
             Stand bleibt (E41)

Stellung im Ablauf laden → quellen → ziel: `laden.quelle_laden` wählt den Adapter über ADAPTER nach dem
Schlüssel `typ` der Quelle, ruft ihn als Generator `adapter(cfg, prot)` auf und gibt jeden Datensatz an
`ziel.zeilen` weiter. Ein Adapter schreibt nie in die Datenbank; er ruft Netz oder Datei ab und hält im
Protokoll fest, was Bericht und Löschentscheidung brauchen (Warnungen, Hinweise, Feldliste, Kontakt, Lücken).
Ob gelöscht wird, entscheiden laden und ziel: Meldet ein Adapter über Protokoll.unvollstaendig_melden eine
Lücke, wird eingefügt und aktualisiert, aber nichts gelöscht (E23, E32); setzt er
prot.info["fehlende_felder"], hält laden die Quelle an und der alte Stand bleibt.

Wichtigste Entscheidungen (docs/entscheidungen.md):
  E6   WFS immer als GML; Paging, wenn der Dienst es meldet, sonst Kachelung mit Entdoppelung über die ID
       (seit E50 nur bei gleichem Inhalt, sonst Löschsperre)
  E9   eigene Kennung (User-Agent) gegenüber den Anbietern, im Betrieb über PIPELINE_KENNUNG
  E15  INKAR als eigener Quelltyp: ZIP auf die Platte, der CSV-Eintrag als Datenstrom (Deflate64 über unzip)
  E16  OGC API - Features, Folge-Links nur auf denselben Rechner; E30 GeoJSON-Datei, Objekt für Objekt
  E36  `pause_s` zwischen zwei WFS-Abrufen (Antwort 69: Abrufe moderat)
  E41  URL-Schema vor jeder Verbindung (schema_pruefen), auch vor der HEAD-Suche
  E46, E47  Vollständigkeit nur mit Beleg: Ende des WFS-Pagings, Beleg je Kachel, Datenbereich der
       Statistiktabellen, Zyklen in Folge-Links der OGC API
  E48  Statistische Berichte als XLSX; robots.txt je Rechner (ROBOTS_GESPERRT), INKAR nur aus abgelegter Datei
       (überholt durch E50)
  E50  INKAR per URL (Antwort 33) nur mit benannter Freigabe der Quelle (robots_freigabe), sichtbar in Bericht
       und Protokoll; Sperre auf dem gesendeten, normalisierten Pfad; INKAR-Zeilen syntaktisch vor dem Filter;
       Inhaltsvergleich bei doppelten WFS-IDs; Zeitbudget je Quelle (Protokoll.frist_setzen)

Neue Quelltypen bekommen hier eine eigene Funktion und einen Eintrag in ADAPTER.
Quelltypen: wfs (WFS 2.0, GML), ogcapi (OGC API - Features, GeoJSON), csv, xlsx (Statistische Berichte als
Excel-Datei, E48), inkar (INKAR-Gesamtdatei des BBSR: ZIP mit CSV im Langformat), geojson (GeoJSON-Datei,
gestreamt gelesen).

Alles, was von außen kommt, wird als nicht vertrauenswürdig behandelt: nur https, keine
Weiterleitungen, Größenlimit je Antwort, XML-Parser ohne Entitäten, DTD und Netzzugriff,
ZIP-Einträge mit Grenzen für Größe und Packrate (gegen ZIP-Bomben), XLSX nur ohne DTD und über
defusedxml, Folge-Links von OGC-API-Diensten und Links von Berichtsseiten nur auf erlaubte Rechner,
nie ein Pfad, den die robots.txt seines Rechners sperrt (ROBOTS_GESPERRT), außer eine Quelle hat für den
Rechner ihrer eigenen Adresse eine benannte Freigabe (robots_freigabe, E50). Die Sperrliste ist fest im
Code und wird nicht zur Laufzeit aus dem Netz gelesen; ein Rechner, der nicht in ihr steht, gilt als
erlaubt. Deshalb: vor dem ersten Abruf eines neuen Rechners seine robots.txt lesen und Sperren eintragen.
"""
from __future__ import annotations

import copy
import csv
import email.utils
import hashlib
import io
import json
import logging
import math
import os
import re
import shutil
import subprocess  # nosec B404
import tempfile
import time
import unicodedata
import zipfile
import zlib
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import requests
from lxml import etree

log = logging.getLogger(__name__)

GML = "http://www.opengis.net/gml/3.2"
GML31 = "http://www.opengis.net/gml"  # WFS 1.1.0 liefert GML 3.1.1
WFS = "http://www.opengis.net/wfs/2.0"
OWS = "http://www.opengis.net/ows/1.1"
OWS10 = "http://www.opengis.net/ows"  # WFS 1.1.0 nutzt OWS 1.0 (E50)
XS = "http://www.w3.org/2001/XMLSchema"
HTTP_TIMEOUT = 60
MAX_MB_STANDARD = 200
# Die Anbieter sehen in ihren Server-Logs, wer abfragt, und wissen, wohin sie sich wenden können.
# Betreiber setzen ihren eigenen Namen und Kontakt über PIPELINE_KENNUNG (docs/betrieb.md).
KENNUNG_STANDARD = "geodaten-import-pipeline (+https://github.com/andremadstop/geodaten-import-pipeline)"


def kennung() -> str:
    """User-Agent für jeden Abruf (E9): PIPELINE_KENNUNG, wenn gesetzt und nicht leer, sonst
    KENNUNG_STANDARD. Die Umgebungsvariable wird bei jedem Aufruf neu gelesen."""
    return os.environ.get("PIPELINE_KENNUNG") or KENNUNG_STANDARD

# Entitäten werden nicht aufgelöst (XXE, „Billion Laughs“), keine DTD, kein Nachladen aus dem Netz
_XML = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


class QuellenFehler(RuntimeError):
    """Die Quelle hat etwas geliefert, das die Pipeline aus Sicherheitsgründen ablehnt, oder die
    Konfiguration der Quelle reicht nicht aus, um sie sicher zu lesen. Bricht die Quelle ab, wo sie nicht
    ausdrücklich abgefangen wird.

    Unterklasse von RuntimeError. In kachel_belegen und beim DescribeFeatureType in wfs steht deshalb vor
    `except (…, RuntimeError)` ein eigenes `except QuellenFehler: raise`, damit eine Ablehnung nicht zur
    bloßen Lücke oder Warnung herabgestuft wird (DescribeFeatureType seit E50; bis dahin dort nur eine
    Warnung). Bei Startseite und queryables in ogcapi wird eine Ablehnung weiterhin nur als Warnung
    festgehalten; diese Abrufe sind für die Daten selbst nicht nötig."""


class ZeitbudgetUeberschritten(Exception):
    """Die Quelle hat ihr Zeitbudget (zeitbudget_min, E50, Befund W6) überschritten. Ausgelöst von
    Protokoll.zeit_pruefen an festen Prüfpunkten: vor jeder Anfrage, je gelesenem Block eines Downloads, in
    langen Schleifen der Adapter und zwischen den Schreibschritten in laden.quelle_laden. Seit E51 (Befund K1)
    auch, wenn PostgreSQL eine Anweisung der Quelle wegen statement_timeout oder lock_timeout abbricht
    (laden.db_zeitgrenze_melden, Text „Zeitbudget/Datenbank-Zeitgrenze …“). Die Transaktion der Quelle wird
    zurückgerollt, die nächste Quelle läuft.

    Bewusst weder QuellenFehler noch RuntimeError: Die Adapter halten RuntimeError und QuellenFehler an
    einigen Stellen als Lücke oder Warnung fest (Folgeseiten im WFS, Startseite und queryables in der OGC API)
    und machen dann weiter; das Zeitbudget muss die Quelle aber beenden. laden fängt es wie jeden Fehler einer
    Quelle über `except Exception` ab."""


class Protokoll:
    """Sammelt je Quellenlauf Warnungen, Hinweise und das, was die Quelle über sich sagt
    (Kontakt, Feldliste, updateSequence). Daraus entstehen Bericht und Meldung an den Anbieter.

    Attribute:
      warnungen        Warnungen für den Bericht (auch die Lücken aus unvollstaendig_melden)
      hinweise         Hinweise für den Bericht
      info             was der Adapter über Quelle und Abruf weiß; laden wertet u. a. `fehlende_felder`
                       aus (Quelle angehalten)
      letzte_abfrage   zuletzt abgefragte Adresse samt Parametern, damit sich ein Fehler nachstellen lässt
      unvollstaendig   True, sobald eine Lücke gemeldet ist; dann wird nichts gelöscht"""

    def __init__(self) -> None:
        """Leeres Protokoll für einen Quellenlauf, ohne Zeitbudget (frist_setzen setzt es)."""
        self.warnungen: list[str] = []
        self.hinweise: list[str] = []
        self.info: dict = {}
        self.letzte_abfrage: str | None = None
        # Fehlt im Abruf etwas (Objekt übersprungen, Seite oder Kachel unvollständig), darf die
        # Pipeline nichts löschen: Löschen nur bei vollständigem, fehlerfreiem Abruf (Antwort 52).
        self.unvollstaendig = False
        # Zeitbudget der Quelle (E50, W6): Frist auf der Uhr `_uhr` (Sekunden, monoton), None = ohne Budget
        self._frist: float | None = None
        self._budget_min: float | None = None
        self._uhr = time.monotonic

    def frist_setzen(self, minuten: float, uhr=time.monotonic) -> None:
        """Zeitbudget der Quelle ab jetzt: `minuten` Minuten auf der Uhr `uhr` (Standard time.monotonic, die
        Uhr ist nur für Tests austauschbar). laden.quelle_laden ruft das zu Beginn der Quelle auf."""
        self._uhr, self._budget_min = uhr, minuten
        self._frist = uhr() + minuten * 60

    def zeit_pruefen(self) -> None:
        """Prüfpunkt des Zeitbudgets: Ist die Frist überschritten, endet die Quelle mit
        ZeitbudgetUeberschritten. Ohne Budget (frist_setzen nicht aufgerufen) geschieht nichts.

        Warum an Prüfpunkten statt mit einem Signal oder Thread, der die Quelle von außen abbricht: Ein
        Abbruch mitten in einem Schreibvorgang könnte Cache und Verbindung in einem unklaren Zustand lassen.
        An den Prüfpunkten ist der Zustand klar: Die Ausnahme rollt die Transaktion der Quelle zurück,
        Teildateien im Cache werden entfernt (datei_abrufen). Eine Anfrage zwischen zwei Prüfpunkten läuft
        zu Ende (bis HTTP_TIMEOUT je Block); um so viel kann eine Quelle ihr Budget überschreiten.

        Datenbankanweisungen begrenzt seit E51 (Befund K1) die Datenbank selbst: laden.db_grenzen setzt an
        den Prüfpunkten zwischen den Schreibschritten statement_timeout auf den Rest des Budgets (rest_s) und
        lock_timeout auf den kleineren Wert aus Rest und eigener Wartegrenze; PostgreSQL bricht eine
        Anweisung dann selbst ab, und die Transaktion wird zurückgerollt. Bis E51 lief eine Anweisung, auch
        eine, die auf eine Sperre wartete, ohne Grenze zu Ende."""
        if self._frist is not None and self._uhr() > self._frist:
            raise ZeitbudgetUeberschritten(
                f"Zeitbudget von {self._budget_min:g} min überschritten (zeitbudget_min); Quelle "
                "abgebrochen, ihre Transaktion zurückgerollt, alter Stand bleibt")

    def rest_s(self) -> float | None:
        """Verbleibende Sekunden des Zeitbudgets (E51, Befund K1), nie negativ; None ohne Budget. Daraus
        leitet laden.db_grenzen die Zeitgrenzen der Datenbank für den nächsten Schreibschritt ab."""
        if self._frist is None:
            return None
        return max(0.0, self._frist - self._uhr())

    def unvollstaendig_melden(self, text: str) -> None:
        """Lücke im Abruf melden: Warnung `text` (gleicher Text nur einmal) und Merkmal unvollstaendig.
        Die Quelle läuft weiter; was bis dahin gelesen ist, wird übernommen, nichts wird gelöscht und der
        Lauf zählt nicht als Erfolg (E32)."""
        if text not in self.warnungen:
            self.warnungen.append(text)
        self.unvollstaendig = True


# Per robots.txt gesperrte Pfade je Rechner (Disallow für User-agent: *, je Rechner ein Abruf der
# robots.txt am 06.11.2026; Tabelle in docs/betrieb.md, E48). Andrés Regel: gesperrte Pfade nie abrufen,
# auch nicht im Test, Probe- oder Beleglauf. schema_pruefen lehnt sie vor jeder Verbindung ab (GET,
# Dateiabruf, HEAD-Suche), link_ermitteln zählt Links dorthin wie fremde, laden.ziele nennt sie nicht. Eine
# Konfiguration kann die Liste nicht verkürzen. Einzige Ausnahme (E50, Befund A1, Entscheidung André vom
# 06.11.2026): Eine Quelle mit benannter Freigabe (robots_freigabe) darf den Rechner ihrer eigenen Adresse
# abrufen; die Sperre bleibt für alle anderen Quellen und Rechner, und jede Nutzung steht in Bericht und
# Protokoll. Neue Rechner: vor dem ersten Abruf robots.txt lesen, Sperren hier eintragen.
ROBOTS_GESPERRT: dict[str, tuple[str, ...]] = {
    "www.bbr-server.de": ("/",),                       # INKAR: nur mit robots_freigabe der Quelle (E50)
    "www.regionalstatistik.de": ("/",),                # bis E47 Bevölkerung und Fläche
    "www.statistik-berlin-brandenburg.de": ("/scrivito/",),
    "sgx.geodatenzentrum.de": ("/gdz_geoviewserver/", "/gdz_geoviewserv/"),
}


def _ohne_punktsegmente(pfad: str) -> str:
    """Punktsegmente entfernen wie beim Auflösen einer Adresse (RFC 3986, Abschnitt 5.2.4): `.` fällt weg,
    `..` nimmt das Segment davor mit. Endet der Pfad auf `.` oder `..`, bleibt der Schrägstrich am Ende
    (`/scrivito/.` ist `/scrivito/`). Erwartet einen Pfad mit `/` am Anfang und ohne doppelte
    Schrägstriche."""
    teile = pfad.split("/")[1:]
    stapel: list[str] = []
    for i, seg in enumerate(teile):
        letztes = i == len(teile) - 1
        if seg == "..":
            if stapel:
                stapel.pop()
            if letztes:
                stapel.append("")
        elif seg == ".":
            if letztes:
                stapel.append("")
        else:
            stapel.append(seg)
    return "/" + "/".join(stapel)


def _pfad_normal(pfad: str) -> str:
    """Pfad für den Vergleich mit ROBOTS_GESPERRT: prozentdekodiert (/%73crivito/ ist /scrivito/, %2e%2e ist
    ..), Rückstrich als Schrägstrich, doppelte Schrägstriche zusammengelegt, ohne Punktsegmente.

    Warum so weit: requests (urllib3) löst Punktsegmente beim Senden auf, auch nach Dekodierung von %2e, und
    viele Server legen // zusammen oder lesen %2F und den Rückstrich als Trenner. Die Normalisierung sperrt
    damit eher zu viel als zu wenig; ein Pfad, der nur so geschrieben die Sperre träfe, wird nicht
    abgerufen."""
    p = unquote(pfad or "/").replace("\\", "/")
    p = re.sub(r"/{2,}", "/", p if p.startswith("/") else "/" + p)
    return _ohne_punktsegmente(p)


def _rechner(url: str) -> str:
    """Rechnername einer Adresse nach urlsplit: klein geschrieben, ohne Punkt am Ende; leer, wenn die Adresse
    keinen Rechner hat. Nur noch für robots_gesperrt, das die Adresse und die gesendete Fassung prüft (sperrt
    eher zu viel); Freigabe und Folge-Links nutzen seit der Nachprüfung zu E50 rechner_wie_gesendet.
    Ausnahme: ValueError bei einer Adresse, die urlsplit nicht zerlegen kann."""
    return (urlsplit(url).hostname or "").rstrip(".")


def rechner_wie_gesendet(url: str) -> str:
    """Der Rechner, den requests für `url` tatsächlich anwählt (Nachprüfung zu E50): aus der vorbereiteten
    Anfrage (requests.Request(…).prepare(), wie beim Senden, also nach IDNA und Kodierung), klein geschrieben,
    ohne Klammern einer IPv6-Adresse und ohne Punkt am Ende; leer, wenn die Adresse keinen Rechner hat.

    Warum nicht urlsplit allein: urlsplit und urllib3 lesen manche Adressen verschieden. Bei
    `https://a.example\\@b.example/` nimmt urlsplit alles vor dem „@“ als Anmeldedaten und liest b.example;
    requests kodiert den Rückstrich als Beginn des Pfads und verbindet zu a.example. Bis zur Nachprüfung
    verglichen freigabe_fuer, quell_rechner und ogcapi den Rechner nach urlsplit; so ließ sich mit der
    Freigabe eines Rechners ein anderer gesperrter abrufen, und ein Folge-Link führte auf einen fremden
    Rechner (Prüfer zu E50). Sperre, Freigabe und Folge-Links entscheiden deshalb über diesen Rechner.

    Abgelehnt wird, wo die Zerleger auseinanderlaufen können: Anmeldedaten (ein „@“), ein Rückstrich vor dem
    Rechner, und ein Rechner nach urlsplit, der in ASCII geschrieben ist und trotzdem vom gesendeten abweicht.
    Eine Datenquelle braucht keine Anmeldedaten in der Adresse; link_ermitteln zählt solche Links schon seit
    E48 als fremd. Ein Rechnername außerhalb von ASCII wird nur über die gesendete Fassung (IDNA) verglichen.

    Ausnahmen: QuellenFehler bei den abgelehnten Formen; ValueError bei einer Adresse, die urlsplit oder
    requests nicht zerlegen kann (requests.InvalidURL ist ein ValueError, MissingSchema ebenso). Kein
    Netzzugriff."""
    teile = urlsplit(url)
    if "@" in teile.netloc or "\\" in teile.netloc:
        raise QuellenFehler(f"Adresse mit Anmeldedaten oder Rückstrich vor dem Rechner abgelehnt (urlsplit "
                            f"und requests lesen den Rechner dort verschieden): {url[:120]}")
    try:
        gesendet = requests.Request("GET", url).prepare().url or ""
    except UnicodeError as e:
        raise ValueError(f"Rechnername nicht kodierbar: {e}") from e
    rechner = (urlsplit(gesendet).hostname or "").rstrip(".")
    roh = (teile.hostname or "").rstrip(".")
    if roh.isascii() and roh != rechner:
        raise QuellenFehler(f"Rechner der Adresse ({roh[:60]}) und gesendeter Rechner ({rechner[:60]}) "
                            f"weichen voneinander ab, abgelehnt: {url[:120]}")
    return rechner


def robots_gesperrt(url: str) -> str | None:
    """Gesperrter Pfadanfang aus ROBOTS_GESPERRT, den die Adresse trifft, sonst None.

    Verglichen wird der Pfad, wie ihn requests tatsächlich sendet (vorbereitete Anfrage), und der Pfad der
    Adresse selbst, beide nach _pfad_normal; der Rechner ohne Groß- und Kleinschreibung und ohne Punkt am
    Ende, auch hier aus beiden Fassungen. Bis E50 verglich die Funktion nur den prozentdekodierten Pfad der
    Adresse; Punktsegmente (`/a/../scrivito/`, `/a/%2e%2e/scrivito/`), doppelte Schrägstriche und kodierte
    Trenner rutschten durch (in E49 benannt, E50 behoben).

    Eine Adresse, die sich nicht zerlegen lässt, gilt hier als nicht gesperrt; abgerufen wird sie trotzdem
    nicht: schema_pruefen zerlegt sie vorher selbst mit urlsplit und scheitert mit ValueError, link_ermitteln
    überspringt sie, requests lehnt sie als InvalidURL ab."""
    # urlsplit kann bei kaputten Adressen ValueError werfen (etwa „[“ im Rechnernamen)
    try:
        fassungen = [(_rechner(url), urlsplit(url).path)]
    except ValueError:
        return None
    # Die Adresse, wie requests sie senden würde (Kodierung, Punktsegmente, IDNA). Scheitert die Vorbereitung,
    # würde requests sie auch nicht senden; dann zählt die Adresse selbst
    try:
        gesendet = requests.Request("GET", url).prepare().url or ""
        fassungen.append((_rechner(gesendet), urlsplit(gesendet).path))
    except (requests.RequestException, ValueError, UnicodeError):
        pass
    for rechner, pfad in fassungen:
        normal = _pfad_normal(pfad)
        treffer = next((p for p in ROBOTS_GESPERRT.get(rechner, ()) if normal.startswith(p)), None)
        if treffer is not None:
            return treffer
    return None


def robots_freigabe(cfg: dict) -> str | None:
    """Benannte Freigabe der Quelle für einen per robots.txt gesperrten Rechner (E50, Befund A1): der Text aus
    `robots_freigabe` ohne Rand, wenn er ein nicht leerer Text ist, sonst None.

    Nur ein Text zählt: True, 1, eine Liste oder Leerraum sind keine benannte Freigabe (wie `erlaube_http`,
    das nur `true` freischaltet, E41). Der Text sagt, wer den Abruf verlangt oder erlaubt hat; er steht in
    jedem Bericht und Protokoll, in dem die Freigabe genutzt wird, und in --ziele.

    Ausnahme: QuellenFehler bei Steuerzeichen oder Zeilentrennern im Text (Nachprüfung zu E50). Ein Grund mit
    Zeilenumbruch ergab in --ziele eine zweite Zeile ohne „#“, die ein Skript für die Firewall als Ziel läse;
    laden.freigaben_pruefen meldet das schon vor dem Lauf und vor --ziele."""
    text = cfg.get("robots_freigabe")
    if not isinstance(text, str) or not text.strip():
        return None
    text = text.strip()
    if any(unicodedata.category(z) in ("Cc", "Zl", "Zp") for z in text):
        raise QuellenFehler(f"robots_freigabe enthält Steuerzeichen oder einen Zeilenumbruch: {text[:80]!r}")
    return text


def quell_rechner(cfg: dict) -> str | None:
    """Rechner der eigenen Adresse einer Quelle (`url`, sonst `seite`, sonst `pfad`, wenn er eine Adresse
    ist), für den eine Freigabe gilt, so wie requests ihn anwählt (rechner_wie_gesendet); None ohne Adresse
    oder bei einer unlesbaren oder abgelehnten. Die Freigabe gilt für den ganzen Rechner, also auch für
    andere Pfade und Folge-Links dorthin; Links von einer Berichtsseite auf andere Rechner (link_rechner) und
    jeden anderen Rechner deckt sie nie ab. Bis zur Nachprüfung zu E50 nach urlsplit, siehe
    rechner_wie_gesendet."""
    pfad = cfg.get("pfad") or ""
    adresse = cfg.get("url") or cfg.get("seite") or (pfad if isinstance(pfad, str) and "://" in pfad
                                                     else None)
    if not isinstance(adresse, str):
        return None
    try:
        return rechner_wie_gesendet(adresse) or None
    except (QuellenFehler, ValueError):
        return None


def freigabe_fuer(url: str, cfg: dict) -> str | None:
    """Grund der Freigabe, wenn die Quelle `cfg` die Adresse `url` trotz Sperre abrufen darf, sonst None:
    benannte Freigabe (robots_freigabe) und `url` auf dem Rechner der eigenen Adresse der Quelle
    (quell_rechner). Eine Freigabe gilt so nur für genau diesen Rechner und nur für diese Quelle.

    Verglichen wird auf beiden Seiten der Rechner, den requests anwählt (rechner_wie_gesendet). Bis zur
    Nachprüfung zu E50 verglich die Funktion den Rechner nach urlsplit; mit
    `https://www.regionalstatistik.de\\@www.bbr-server.de/…` hob die Freigabe für www.bbr-server.de so die
    Sperre von www.regionalstatistik.de auf. Eine Adresse, die rechner_wie_gesendet ablehnt, hat keine
    Freigabe. Ausnahme: QuellenFehler aus robots_freigabe (Steuerzeichen im Grund)."""
    grund = robots_freigabe(cfg)
    if not grund:
        return None
    try:
        rechner = rechner_wie_gesendet(url)
    except (QuellenFehler, ValueError):
        return None
    return grund if rechner and rechner == quell_rechner(cfg) else None


def schema_pruefen(url: str, cfg: dict, prot: Protokoll | None = None) -> None:
    """Vor jeder Verbindung: https ist Standard, http nur mit `erlaube_http: true` in der Quelle, alles andere
    (file:, ftp: …) nie. Gilt für GET, Dateiabruf und die HEAD-Suche nach der neuesten Jahresdatei
    (Codex-Prüfung 05.11., B14). Ebenso vor jeder Verbindung: kein Pfad, den die robots.txt seines Rechners
    sperrt (ROBOTS_GESPERRT, Prüfung nach E48), außer die Quelle hat für den Rechner ihrer eigenen Adresse
    eine benannte Freigabe (robots_freigabe, E50).

    Parameter: url die Adresse, die gleich abgerufen werden soll; cfg die Konfiguration der Quelle; prot das
    Protokoll der Quelle. Wird eine Freigabe genutzt, kommt sie dort hinein: info["robots_freigabe"] (Rechner,
    gesperrter Pfad, Grund) und einmal je Quelle eine Warnung. So steht sie im JSON- und Textbericht und im
    Protokoll in pipeline_meta (Spalte warnungen).
    Seit der Nachprüfung zu E50 außerdem vor jeder Verbindung: keine Adresse, bei der urlsplit und requests
    den Rechner verschieden lesen (Anmeldedaten, Rückstrich vor dem Rechner; rechner_wie_gesendet). Damit gilt
    für jeden Abruf derselbe Rechner, den Sperre, Freigabe und Bericht nennen.
    Ausnahmen: QuellenFehler bei unerlaubtem Schema, bei einer abgelehnten Adresse oder bei gesperrtem Pfad
    ohne passende Freigabe, ValueError bei einer Adresse, die urlsplit oder requests nicht zerlegen kann. Kein
    Netzzugriff."""
    teile = urlsplit(url)
    # `is True`: ein beliebiger wahrer Wert in der Konfiguration (etwa der Text "false") schaltet http nicht
    # frei (E41)
    if teile.scheme != "https" and not (cfg.get("erlaube_http") is True and teile.scheme == "http"):
        raise QuellenFehler(f"Nur https ist erlaubt, Quelle nutzt '{teile.scheme}'")
    # Der Rechner, den requests anwählt; lehnt Adressen ab, deren Rechner die Zerleger verschieden lesen
    rechner = rechner_wie_gesendet(url)
    if (gesperrt := robots_gesperrt(url)) is None:
        return
    grund = freigabe_fuer(url, cfg)
    if grund is None:
        raise QuellenFehler(f"robots.txt von {rechner} sperrt {gesperrt} für automatische Abrufe; "
                            "nicht abgerufen. Abruf nur mit benannter Freigabe der Quelle für den Rechner "
                            "ihrer eigenen Adresse (robots_freigabe; docs/betrieb.md, Quellen und "
                            "Abrufregeln)")
    if prot is not None and "robots_freigabe" not in prot.info:
        prot.info["robots_freigabe"] = {"rechner": rechner, "gesperrt": gesperrt, "grund": grund}
        prot.warnungen.append(f"robots.txt von {rechner} sperrt {gesperrt} für automatische Abrufe; "
                              f"abgerufen mit der Freigabe dieser Quelle (robots_freigabe): {grund}")


def abrufen(url: str, params: dict | None, cfg: dict, prot: Protokoll) -> bytes:
    """Eine Antwort per GET ganz in den Speicher holen, für kleine bis mittlere Antworten (WFS-Seiten,
    JSON, Berichtsseiten). Große Dateien gehen über datei_abrufen auf die Platte.

    Parameter: url und params (Abfrageparameter oder None), cfg mit `max_mb` (Standard MAX_MB_STANDARD) und
    `erlaube_http`, prot für die nachstellbare Abfrage (prot.letzte_abfrage).
    Rückgabe: der Inhalt der Antwort als bytes.
    Ausnahmen: QuellenFehler bei unerlaubtem Schema, gesperrtem Pfad, Weiterleitung oder zu großer Antwort;
    requests.HTTPError bei Statuscode 4xx/5xx, sonstige requests.RequestException bei Netzfehlern;
    ZeitbudgetUeberschritten vor der Anfrage oder je Block (E50).
    Seiteneffekt: ein Netzabruf mit User-Agent aus kennung()."""
    # Zeitbudget vor der Anfrage (E50, W6): Eine Quelle mit vielen erfolgreichen Anfragen hält die übrigen
    # nicht beliebig lange auf
    prot.zeit_pruefen()
    schema_pruefen(url, cfg, prot)
    max_bytes = int(cfg.get("max_mb", MAX_MB_STANDARD) * 1024 * 1024)
    # Vor dem Senden festhalten, damit auch eine gescheiterte Abfrage nachstellbar bleibt
    prot.letzte_abfrage = requests.Request("GET", url, params=params).prepare().url
    with requests.get(url, params=params, timeout=HTTP_TIMEOUT, stream=True,
                      allow_redirects=False, headers={"User-Agent": kennung()}) as r:
        if r.is_redirect:
            raise QuellenFehler(f"Dienst leitet weiter auf {r.headers.get('Location', '?')}; "
                                "Weiterleitungen werden nicht verfolgt, URL in der Konfiguration prüfen")
        r.raise_for_status()
        # Zwei Schranken: Content-Length spart den Abruf, wenn der Dienst die Größe ehrlich ankündigt;
        # die Zählung beim Lesen greift auch ohne oder bei falscher Angabe
        if int(r.headers.get("Content-Length") or 0) > max_bytes:
            raise QuellenFehler(f"Antwort größer als {cfg.get('max_mb', MAX_MB_STANDARD)} MB")
        daten = bytearray()
        for stueck in r.iter_content(1 << 16):
            daten += stueck
            if len(daten) > max_bytes:
                raise QuellenFehler(f"Antwort größer als {cfg.get('max_mb', MAX_MB_STANDARD)} MB")
            prot.zeit_pruefen()   # auch eine langsam tröpfelnde Antwort zählt zum Zeitbudget (E50)
    return bytes(daten)


def xml_lesen(daten: bytes) -> etree._Element:
    """XML einer Dienstantwort mit dem abgesicherten Parser _XML lesen.

    Rückgabe: das Wurzelelement. Ausnahmen: etree.XMLSyntaxError bei kaputtem XML, RuntimeError, wenn der
    Dienst statt Daten einen ows:ExceptionReport schickt (Text auf 300 Zeichen gekürzt). Kein QuellenFehler:
    wfs behandelt eine Fehlerantwort bei Folgeseiten und Trefferzahl einer Kachel als Lücke statt als
    Abbruch."""
    root = etree.fromstring(daten, _XML)
    if etree.QName(root).localname == "ExceptionReport":
        text = " ".join(t.strip() for t in root.itertext() if t.strip())
        raise RuntimeError(f"WFS-Fehler: {text[:300]}")
    return root


def _kachel_m_pruefen(kachel_m) -> None:
    """kachel_m muss eine endliche Zahl über 0 sein (kein Text, kein Wahrheitswert); sonst QuellenFehler.
    Bis E50 lief kachel_m 0 oder negativ endlos (x wächst nie), NaN ergab eine unsinnige Kachel (in E49
    benannt, E50 behoben). Aufgerufen von wfs vor dem ersten Abruf (Nachprüfung zu E50) und von _kacheln."""
    if isinstance(kachel_m, bool) or not isinstance(kachel_m, (int, float)) or not math.isfinite(kachel_m) \
            or kachel_m <= 0:
        raise QuellenFehler(f"kachel_m muss eine Zahl über 0 sein (Meter bzw. Einheit des Bezugssystems), "
                            f"nicht {kachel_m!r}")


def _kacheln(bbox: list[float], kachel_m: float):
    """Das Suchrechteck [xmin, ymin, xmax, ymax] zeilenweise in Quadrate der Kantenlänge kachel_m zerlegen
    (Einheit des Koordinatensystems, bei EPSG:25833 Meter). Die letzte Kachel einer Zeile oder Spalte endet
    am Rand des Rechtecks, ragt also nicht darüber hinaus.

    Ausnahme: QuellenFehler, wenn kachel_m keine endliche Zahl über 0 ist (_kachel_m_pruefen), vor der ersten
    Kachel. wfs prüft den Wert seit der Nachprüfung zu E50 schon vor dem ersten Abruf; bis dahin fiel ein
    Tippfehler erst nach GetCapabilities und DescribeFeatureType auf."""
    _kachel_m_pruefen(kachel_m)
    xmin, ymin, xmax, ymax = bbox
    y = ymin
    while y < ymax:
        x = xmin
        while x < xmax:
            yield [x, y, min(x + kachel_m, xmax), min(y + kachel_m, ymax)]
            x += kachel_m
        y += kachel_m


def _text(root: etree._Element, tag: str) -> str | None:
    """Text des ersten Elements `tag` im Namensraum OWS 1.1 (WFS 2.0) oder OWS 1.0 (WFS 1.1.0) im ganzen Baum,
    ohne Rand; None, wenn es fehlt oder leer ist. In den Capabilities steht ServiceIdentification vor den
    Objektarten, „erstes“ trifft also den Dienst. Bis E50 nur OWS 1.1; bei WFS 1.1.0 kam dann None zurück
    (in E49 benannt, E50 behoben; mit einer Testantwort geprüft, nicht mit einem echten Dienst)."""
    for ns in (OWS, OWS10):
        el = root.find(f".//{{{ns}}}{tag}")
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return None


def capabilities_lesen(root: etree._Element) -> dict:
    """Was der Dienst über sich sagt: Anbieter, Kontakt, updateSequence, Paging, Sortierung und
    CountDefault (WFS 2.0: Höchstzahl der Objekte je Antwort, wenn der Dienst sie nennt; E47).

    Titel, Beschreibung, Anbieter, E-Mail und die Constraints werden in OWS 1.1 (WFS 2.0) und OWS 1.0
    (WFS 1.1.0) gesucht (seit E50, siehe _text). Paging und CountDefault wertet wfs nur bei WFS 2.0 aus."""
    kann = {"ImplementsResultPaging": False, "ImplementsSorting": False}
    count_default = None
    # Nur eine positive ganze Zahl zählt als CountDefault; alles andere (leer, 0, Text) heißt „nicht genannt“,
    # damit eine unsinnige Angabe nie eine Kachel als vollständig belegt
    for c in root.iter(f"{{{OWS}}}Constraint", f"{{{OWS10}}}Constraint"):
        if c.get("name") in kann:
            kann[c.get("name")] = "".join(c.itertext()).strip().upper() == "TRUE"
        elif c.get("name") == "CountDefault":
            wert = "".join(c.itertext()).strip()
            count_default = int(wert) if wert.isdigit() and int(wert) > 0 else None
    return {"titel": _text(root, "Title"),
            "beschreibung": _text(root, "Abstract"),
            "anbieter": _text(root, "ProviderName"),
            "email": _text(root, "ElectronicMailAddress"),
            "update_sequence": root.get("updateSequence"),
            "paging": kann["ImplementsResultPaging"],
            "sortierung": kann["ImplementsSorting"],
            "count_default": count_default}


def schema_felder(root: etree._Element, typename: str | None = None) -> list[str]:
    """Feldnamen des Objekttyps aus DescribeFeatureType (XML Schema).

    Manche Dienste (z. B. deegree bei den Verwaltungsgrenzen der LGB) liefern das Schema aller
    Objektarten, auch wenn nur eine angefragt ist. Dann zählen nur die Felder der angefragten Art:
    ihr Element mit eingebettetem Typ oder der benannte complexType, auf den es verweist.

    Parameter: root die Antwort von DescribeFeatureType, typename die angefragte Objektart (mit oder ohne
    Präfix). Rückgabe: sortierte Feldnamen. Findet sich die Objektart nicht oder hat sie keine eigenen
    Felder, kommen die Felder aller Elemente des Schemas zurück."""
    def felder(knoten) -> set[str]:
        """Namen der xs:element unter `knoten`; Elemente mit substitutionGroup sind Objektarten, keine
        Felder."""
        return {el.get("name") for el in knoten.iter(f"{{{XS}}}element")
                if el.get("name") and el.get("substitutionGroup") is None}

    if typename:
        name = typename.split(":")[-1]
        for el in root.iter(f"{{{XS}}}element"):
            if el.get("name") != name or el.get("substitutionGroup") is None:
                continue
            if el.get("type"):
                typ = el.get("type").split(":")[-1]
                knoten = next((t for t in root.iter(f"{{{XS}}}complexType") if t.get("name") == typ), None)
            else:
                knoten = el
            if knoten is not None and felder(knoten) - {name}:
                return sorted(felder(knoten) - {name})
    return sorted(felder(root))


def felder_pruefen(vorhanden: list[str], noetig: list[str], prot: Protokoll) -> None:
    """Feldlisten-Vergleich (E4): Fehlt ein konfiguriertes Feld in der Quelle, Warnung und
    prot.info["fehlende_felder"]. Daran hält laden die Quelle an und der alte Stand bleibt, statt dass ein
    umbenanntes Feld bei allen Objekten still leer würde. Fehlt etwas, ersetzt die neue Liste eine schon
    gesetzte; fehlt nichts, bleibt eine frühere Meldung stehen."""
    fehlen = [f for f in noetig if f not in vorhanden]
    if fehlen:
        prot.warnungen.append(f"Feld fehlt in der Quelle: {', '.join(fehlen)}")
        prot.info["fehlende_felder"] = fehlen


def _wfs_objekte(root: etree._Element) -> Iterator[etree._Element]:
    """Die Objekte einer GetFeature-Antwort: wfs:member (WFS 2.0) oder gml:featureMember(s)
    (WFS 1.1.0). Kommentare vor dem Objekt zählen nicht."""
    for member in root.iter(f"{{{WFS}}}member", f"{{{GML31}}}featureMember"):
        feat = next((k for k in member if isinstance(k.tag, str)), None)
        if feat is not None:
            yield feat
    for sammlung in root.iter(f"{{{GML31}}}featureMembers"):
        yield from (k for k in sammlung if isinstance(k.tag, str))


# id_feld für die Kennung aus dem Attribut gml:id des Features statt aus einem Kindelement (E51, Befund W3)
GML_ID_FELD = "@gml:id"


def _kennung(feat: etree._Element, id_feld: str) -> str | None:
    """Objekt-ID eines WFS-Features ohne Rand, None, wenn sie fehlt oder leer ist (E51, Befund W3).

    id_feld "@gml:id": das Attribut gml:id des Features selbst (GML 3.2 oder 3.1). Bis E51 las der Adapter
    die Kennung nur aus einem Kindelement; ein Dienst, der sie nur als gml:id führt, ließ sich nicht allein
    über die Konfiguration anbinden (Prüfbericht vom 07.11.2026, W3). Nur verwenden, wenn der Dienst gml:id
    über Abrufe hinweg gleich vergibt (etwa „GebaeudeBauwerk.4711“ aus der Objektnummer): Manche Dienste
    vergeben gml:id je Antwort neu (siehe _ohne_gml_id); dann wäre jeder Lauf ein Austausch aller Objekte.
    Sonst: der Text des ersten Kindelements mit diesem lokalen Namen."""
    if id_feld == GML_ID_FELD:
        return (feat.get(f"{{{GML}}}id") or feat.get(f"{{{GML31}}}id") or "").strip() or None
    el = next((k for k in feat if isinstance(k.tag, str) and etree.QName(k).localname == id_feld), None)
    return ((el.text or "").strip() or None) if el is not None else None


def _ohne_gml_id(el: etree._Element) -> etree._Element:
    """Kopie eines Geometrie-Elements ohne gml:id-Attribute (GML 3.2 und 3.1): Viele Dienste vergeben diese
    Kennungen je Antwort neu; für den Inhaltsvergleich doppelter Objekte (E50) sind sie kein Inhalt."""
    kopie = copy.deepcopy(el)
    for e in kopie.iter():
        if isinstance(e.tag, str):
            for ns in (GML, GML31):
                e.attrib.pop(f"{{{ns}}}id", None)
    return kopie


def _inhalt(werte: dict, geom_el: etree._Element | None) -> bytes:
    """Prüfsumme des Inhalts eines WFS-Objekts für den Vergleich doppelter IDs (E50, Befund W5): die Werte
    (sortiert, als JSON) und die Geometrie in kanonischer Form (exklusive C14N, ohne gml:id). Gleiche Objekte
    aus zwei Antworten ergeben dieselbe Summe, auch wenn Reihenfolge der Attribute, Namensraum-Deklarationen
    der Antwort oder gml:id abweichen. Ein anderes Präfix für denselben Namensraum gilt als Abweichung (dann
    wird nichts gelöscht, nichts geht verloren).

    16 Bytes (BLAKE2b) statt 32 (SHA-256, E50): Die Summe unterscheidet nur Fassungen derselben Objekt-ID
    innerhalb eines Abrufs, nicht beliebige Daten; 128 Bit reichen dafür bei weitem und halten den Speicher je
    Objekt klein (Nachprüfung zu E50, _fassung_merken)."""
    teile = [json.dumps(werte, sort_keys=True, ensure_ascii=False).encode()]
    if geom_el is not None:
        # Exklusive Kanonisierung: nur Namensräume, die das Element selbst nutzt; zusätzliche Deklarationen an
        # der Wurzel einer Antwort ändern die Summe so nicht
        teile.append(etree.tostring(_ohne_gml_id(geom_el), method="c14n", exclusive=True))
    return hashlib.blake2b(b"\x00".join(teile), digest_size=16).digest()


def _fassung_merken(gesehen: dict[str, bytes | set[bytes]], oid: str, summe: bytes) -> str:
    """Fassung `summe` der Objekt-ID `oid` in `gesehen` eintragen (E50, Befund W5) und sagen, was sie ist:
    "neu" (erste Fassung dieser ID), "gleich" (schon gesehen) oder "abweichend" (weitere, andere Fassung).

    Speicher (Nachprüfung zu E50): je ID nur die Summe als bytes, ein set erst ab der ersten abweichenden
    Fassung. In E50 stand je ID ein set mit einem SHA-256-Digest, rund 380 B je ID statt 103 B für das
    frühere set[str] der IDs (tracemalloc, Prüfer zu E50); der Kommentar dort sagte das Gegenteil."""
    alt = gesehen.get(oid)
    if alt is None:
        gesehen[oid] = summe
        return "neu"
    if alt == summe or (isinstance(alt, set) and summe in alt):
        return "gleich"
    gesehen[oid] = (alt | {summe}) if isinstance(alt, set) else {alt, summe}
    return "abweichend"


def wfs(cfg: dict, prot: Protokoll) -> Iterator[dict]:
    """WFS 2.0.0 oder 1.1.0 (`version`) GetFeature. Paginiert per STARTINDEX, wenn der Dienst es kann
    (nur 2.0); sonst wird die BBOX in Kacheln zerlegt (Objekte an Kachelgrenzen werden über ihre ID
    entdoppelt, wenn ihr Inhalt gleich ist; siehe unten, E50). WFS 1.1.0 (Antwort 67) kennt kein Paging:
    immer Kachelung.

    Vollständig ist eine Kachel nur mit Beleg (Prüfbericht 05.11. abends, Befund 2, E47): Gesamtzahl
    (numberMatched) erreicht; ohne Gesamtzahl weniger Objekte als min(max_je_kachel, CountDefault), wenn der
    Dienst CountDefault nennt; sonst bei WFS 2.0 eine leere Folgeseite am nächsten STARTINDEX derselben
    Kachel (Folgeseiten mit neuen Objekten werden übernommen), bei WFS 1.1.0 eine Trefferzahl
    (RESULTTYPE=hits), die nicht über der gelieferten Zahl liegt. Ohne Beleg gilt der Abruf als unvollständig
    (nichts wird gelöscht). Bis E46 galt eine Kachel unter dem angefragten Limit als vollständig; ein Dienst
    kann aber selbst niedriger begrenzen.

    Folgeseiten (Nachprüfung zu E47): Meldet der Dienst Sortierung, trägt jede Abfrage SORTBY nach der
    Objekt-ID, auch die einer Kachel. Ohne Sortierung belegt die leere Seite das Ende nur, wenn die Seiten
    davor so viele verschiedene Objekte brachten, wie sie zählten (sonst kann eines zwischen zwei Seiten
    gerutscht sein); das gilt für Kacheln und für das Blättern ohne Gesamtzahl. Ein Dienst, der STARTINDEX
    übergeht (meist einer mit ImplementsResultPaging=FALSE, also gerade der, der in die Kachelung führt),
    belegt Vollständigkeit nur über numberMatched oder CountDefault; kleinere Kacheln helfen dann nicht.

    Konfiguration: url, typename, id_feld, geometrie_feld, bbox; optional version, crs, felder (Quellfeld ->
    Zielfeld), seitengroesse, kachel_m, max_je_kachel, pause_s (E36). id_feld ist ein Kindelement des Features
    oder "@gml:id" für das Attribut gml:id des Features (E51, _kennung); mit "@gml:id" entfällt SORTBY (eine
    Sortierung nach gml:id kann der Dienst nicht zusagen), die Seiten gelten als ungeordnet, und das Schema
    muss kein Feld für die Kennung haben. Andere Attribute nach „@“ lehnt der Adapter vor dem ersten Abruf ab.
    Rückgabe: Datensätze mit ("gml", …) als Geometrie, je Objekt-ID einmal; eine ID mit abweichendem Inhalt
    mehrfach (E50, unten).
    Seiteneffekte: Netzabrufe (GetCapabilities, DescribeFeatureType, GetFeature, ggf. RESULTTYPE=hits);
    Kontakt, Titel, updateSequence (E5: nur mitgeschrieben), Feldliste und Lücken landen im Protokoll.
    Ausnahmen: QuellenFehler aus abrufen bricht die Quelle ab, bei jeder Abfrage (beim DescribeFeatureType
    seit E50); ebenso Netz- und XML-Fehler bei GetCapabilities, bei jeder Seite des Pagings und bei der ersten
    Abfrage jeder Kachel. Nur andere Fehler bei Folgeseiten und Trefferzahl einer Kachel (kachel_belegen) und
    beim DescribeFeatureType werden als Lücke bzw. Warnung abgefangen. ZeitbudgetUeberschritten (E50) beendet
    die Quelle immer.

    Doppelte Objekt-IDs (Kachelgrenzen, Folgeseiten; E50, Befund W5): verglichen wird der Inhalt (Werte und
    Geometrie in kanonischer Form ohne gml:id, _inhalt). Gleich: einmal übernommen. Abweichend: Warnung, Abruf
    unvollständig, und die weitere Fassung geht mit an das Zielschreiben, das den Schlüssel wie jeden
    widersprüchlichen auslässt (ziel.neu_bilden, E42). Bis E50 galt ungeprüft „das erste zählt“."""
    url, version = cfg["url"], cfg.get("version", "2.0.0")
    # Vor dem ersten Abruf (Nachprüfung zu E50): Ein Tippfehler in kachel_m löst keine Netzabrufe mehr aus,
    # bevor er gemeldet wird; geprüft auch, wenn der Dienst später blättert statt zu kacheln
    _kachel_m_pruefen(cfg.get("kachel_m", 500))
    v11 = version.startswith("1.1")
    typ_param = "TYPENAME" if v11 else "TYPENAMES"
    anzahl_param = "MAXFEATURES" if v11 else "COUNT"
    seitengroesse = cfg.get("seitengroesse", 500)
    crs = cfg.get("crs", "urn:ogc:def:crs:EPSG::25833")
    id_feld = cfg["id_feld"]
    geom_feld = cfg["geometrie_feld"]
    felder = cfg.get("felder")  # Mapping Quellfeld -> Zielfeld, None = alle
    # Kennung aus gml:id (E51, W3): kein Feld im Schema und in den Objekten, keine Sortierung danach. Ein
    # anderes Attribut nach „@“ ergäbe Objekte ohne Kennung; abgelehnt, bevor etwas abgerufen wird
    id_attr = id_feld == GML_ID_FELD
    if str(id_feld).startswith("@") and not id_attr:
        raise QuellenFehler(f"id_feld {id_feld!r}: als Attribut ist nur {GML_ID_FELD!r} vorgesehen (E51)")
    # Felder, die Schema bzw. gelieferte Objekte haben müssen (Feldlisten-Vergleich, E4)
    noetig = [*([] if id_attr else [id_feld]), geom_feld, *(felder or {})]

    pause_s = float(cfg.get("pause_s", 0))
    # Liste statt int: die innere Funktion hole zählt hier mit, ohne nonlocal
    abrufe = [0]

    def hole(params: dict) -> etree._Element:
        """Eine Abfrage an den Dienst (Adresse aus cfg["url"]), Antwort als XML-Wurzel; vor jedem Abruf
        außer dem ersten pause_s Sekunden Pause."""
        # Antwort 69: Abrufe moderat. Mit pause_s wartet die Pipeline zwischen zwei Abrufen
        # desselben Dienstes, wichtig bei großen Gebieten mit vielen Kacheln
        if abrufe[0] and pause_s:
            time.sleep(pause_s)
        abrufe[0] += 1
        return xml_lesen(abrufen(url, params, cfg, prot))

    cap = capabilities_lesen(hole({"SERVICE": "WFS", "REQUEST": "GetCapabilities",
                                   "VERSION": version}))
    prot.info.update(kontakt={"anbieter": cap["anbieter"], "email": cap["email"]}, titel=cap["titel"],
                     beschreibung=cap["beschreibung"],
                     update_sequence=cap["update_sequence"])
    paging = cap["paging"] and not v11
    if not paging and not v11:
        prot.hinweise.append("Dienst meldet ImplementsResultPaging=FALSE, Abruf per Kachelung")

    try:
        prot.info["felder"] = schema_felder(hole({"SERVICE": "WFS", "REQUEST": "DescribeFeatureType",
                                                  "VERSION": version, typ_param: cfg["typename"]}),
                                            cfg["typename"])
        felder_pruefen(prot.info["felder"], noetig, prot)
    # Eine Ablehnung (Weiterleitung, Größenlimit, robots.txt) bricht die Quelle ab wie bei jeder anderen
    # Abfrage; bis E50 fing die Klausel darunter sie als RuntimeError ab (in E49 benannt, E50 behoben)
    except QuellenFehler:
        raise
    # Ein anderer Fehler bei DescribeFeatureType hält die Quelle nicht an: Die Felder prüft die Pipeline dann
    # an den gelieferten Objekten (unten, schema_ungeprueft, Codex B4)
    except (requests.RequestException, etree.XMLSyntaxError, RuntimeError) as e:
        prot.warnungen.append(f"Schema nicht lesbar (DescribeFeatureType): {e}; Felder werden an den "
                              "gelieferten Objekten geprüft"[:300])
        prot.info["schema_ungeprueft"] = True

    basis = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": version,
             typ_param: cfg["typename"], "SRSNAME": crs}
    sortiert = bool(cap.get("sortierung")) and not v11 and not id_attr
    if id_attr and paging:
        prot.hinweise.append(f"Kennung aus gml:id (id_feld {GML_ID_FELD}): ohne SORTBY, Seiten ohne feste "
                             "Reihenfolge")
    if sortiert:
        # Ohne feste Reihenfolge kann ein Dienst zwischen zwei Seiten anders sortieren, dann fehlen Objekte
        # oder kommen doppelt. Auch in jeder Abfrage einer Kachel, weil Folgeseiten dort ebenso am STARTINDEX
        # anknüpfen (Nachprüfung zu E47)
        basis["SORTBY"] = f"{id_feld} ASC"
    elif paging and not id_attr:
        prot.hinweise.append("Dienst meldet ImplementsSorting=FALSE, Seiten ohne feste Reihenfolge")
    # Objekt-ID -> Inhaltsprüfsumme der gelieferten Fassung (E50, W5), ein set erst bei abweichenden Fassungen
    # (_fassung_merken). Gespeichert wird nur die Summe von 16 Bytes, nicht der Inhalt; trotzdem wächst der
    # Speicher mit der Zahl der Objekte (gemessen in der Nachprüfung zu E50, entscheidungen.md). Berechnet
    # wird die Summe für jedes Objekt, nicht nur für doppelte: Ob eine ID wiederkommt, weiß der Adapter vorher
    # nicht
    gesehen: dict[str, bytes | set[bytes]] = {}
    vorhanden: set[str] = set()  # Feldnamen, die in gelieferten Objekten vorkamen

    def anzahl(root: etree._Element) -> int:
        """Zahl der Objekte einer Antwort: numberReturned (2.0), numberOfFeatures (1.1.0), sonst gezählt."""
        return int(root.get("numberReturned") or root.get("numberOfFeatures")
                   or sum(1 for _ in _wfs_objekte(root)))

    def ids(root: etree._Element) -> set[str]:
        """Objekt-IDs einer Antwort, für den Fortschritt innerhalb einer Kachel (nicht über `gesehen`:
        Objekte an der Grenze kennt die Pipeline schon aus der Nachbarkachel)."""
        # Über _kennung wie die Schleife unten, auch für "@gml:id" (E51); sonst brächte jede Folgeseite
        # scheinbar kein neues Objekt
        return {k for k in (_kennung(feat, id_feld) for feat in _wfs_objekte(root)) if k}

    def kachel_belegen(k, p: dict, root: etree._Element, erhalten: int):
        """Ohne Gesamtzahl: Folgeseiten der Kachel (WFS 2.0) bzw. Trefferzahl (WFS 1.1.0), siehe oben.

        Parameter: k die Kachel, p die Parameter ihrer ersten Abfrage, root deren Antwort, erhalten die Zahl
        der Objekte darin. Generator: liefert Folgeseiten mit neuen Objekten zur Verarbeitung wie die erste
        Seite; fehlt der Beleg, meldet er die Kachel über prot.unvollstaendig_melden."""
        ohne = f"Kachel {k}: Vollständigkeit nicht belegt, Dienst nennt keine Gesamtzahl"
        if v11:
            # Abhilfe kachel_m nur, wo eine kleinere Kachel hilft: mehr Treffer als geliefert
            try:
                treffer = hole({**{s: w for s, w in p.items() if s != anzahl_param}, "RESULTTYPE": "hits"})
                zahl = treffer.get("numberOfFeatures") or treffer.get("numberMatched") or ""
            # QuellenFehler ist ein RuntimeError; ohne diese Zeile würde die nächste Klausel eine Ablehnung
            # (Weiterleitung, Größenlimit, robots) zur bloßen Lücke herabstufen
            except QuellenFehler:
                raise
            except (requests.RequestException, etree.XMLSyntaxError, RuntimeError) as e:
                zahl = f"({e})"
            if not zahl.isdigit():
                grund = f" {zahl[:200]}" if zahl else ""
                prot.unvollstaendig_melden(f"{ohne} und RESULTTYPE=hits ergab keine Trefferzahl{grund}; "
                                           "Vollständigkeit nur mit Trefferzahl belegbar (Dienst)")
            elif int(zahl) > erhalten:
                prot.unvollstaendig_melden(f"Kachel {k} unvollständig ({erhalten} von {zahl} Treffern), "
                                           "kachel_m verkleinern")
            return
        bekannt, start = ids(root), erhalten
        while True:
            try:
                folge = hole(dict(p, STARTINDEX=start))
            # wie oben: Ablehnungen brechen die Quelle ab, Fehlerantworten des Dienstes sind eine Lücke
            except QuellenFehler:
                raise
            except (requests.RequestException, etree.XMLSyntaxError, RuntimeError) as e:
                prot.unvollstaendig_melden(f"{ohne}, Folgeseite ab STARTINDEX {start} nicht abrufbar "
                                           f"({e}); ohne STARTINDEX nur mit numberMatched oder "
                                           "CountDefault belegbar"[:400])
                return
            n = anzahl(folge)
            if n == 0:
                if not sortiert and len(bekannt) < start:
                    # Die leere Seite belegt: die Kachel hat `start` Objekte. Ohne feste Reihenfolge kann
                    # eines zwischen zwei Seiten gerutscht sein; dann kam ein anderes doppelt (Nachprüfung
                    # zu E47)
                    prot.unvollstaendig_melden(f"{ohne}, Seiten ohne feste Reihenfolge brachten "
                                               f"{len(bekannt)} verschiedene Objekte bei {start} gezählten")
                return
            neu = ids(folge) - bekannt
            if not neu:
                prot.unvollstaendig_melden(f"{ohne}, Folgeseite ab STARTINDEX {start} brachte kein neues "
                                           "Objekt: Der Dienst blättert nicht (übergeht STARTINDEX), "
                                           "Vollständigkeit ist nur mit numberMatched oder CountDefault "
                                           "belegbar; kleinere Kacheln helfen nicht")
                return
            bekannt |= neu
            yield folge
            start += n
    gemeldet: list[int] = []  # numberMatched der ersten Seite, falls der Dienst es angibt

    def abfragen():
        """Generator über alle Antworten (Seiten bzw. Kacheln mit ihren Folgeseiten) als XML-Wurzeln.

        Die Objekte einer Antwort verarbeitet die Schleife unten, während dieser Generator bei `yield` ruht;
        danach ist `gesehen` um die neuen IDs gewachsen. Daran misst das Paging den Fortschritt einer Seite
        (bei Kacheln zählt kachel_belegen über eigene IDs je Kachel)."""
        if paging:
            start = 0
            while True:
                p = dict(basis, **{anzahl_param: seitengroesse}, STARTINDEX=start,
                         BBOX=",".join(map(str, cfg["bbox"])) + "," + crs)
                root = hole(p)
                n = int(root.get("numberReturned") or sum(1 for _ in _wfs_objekte(root)))
                if start == 0 and (root.get("numberMatched") or "").isdigit():
                    gemeldet.append(int(root.get("numberMatched")))
                prot.info["seiten"] = prot.info.get("seiten", 0) + 1
                bisher = len(gesehen)
                yield root
                # Eine kürzere Seite beweist das Ende nicht: Ein Dienst mit kleinerem Seitenlimit als
                # `seitengroesse` liefert jede Seite kürzer. Ohne Gesamtzahl beweist erst eine leere
                # Antwort am nächsten startIndex das Ende; mit Gesamtzahl genügt es, sie zu erreichen
                # (Prüfbericht 05.11., F5, E46)
                if n == 0 and not gemeldet and not sortiert and len(gesehen) < start:
                    # Wie bei den Kacheln (Nachprüfung zu E47): Die leere Seite belegt `start` Objekte; ohne
                    # feste Reihenfolge und mit weniger verschiedenen kann eines gerutscht sein
                    prot.unvollstaendig_melden(f"Seiten ohne feste Reihenfolge brachten {len(gesehen)} "
                                               f"verschiedene Objekte bei {start} gezählten, Vollständigkeit "
                                               "nicht belegt")
                if n == 0 or (gemeldet and start + n >= gemeldet[0]):
                    break
                if len(gesehen) == bisher:
                    # Kein neues Objekt auf einer nicht leeren Seite: Der Dienst übergeht STARTINDEX
                    # (oder liefert nur bekannte Objekte); weiterblättern endete nie
                    prot.unvollstaendig_melden(f"Seite ab startIndex {start} brachte kein neues Objekt, "
                                               "Abruf abgebrochen (Dienst übergeht STARTINDEX?)")
                    break
                start += n
        else:
            grenze = cfg.get("max_je_kachel", 10000)
            # Höchstzahl je Antwort: angefragt, oder weniger, wenn der Dienst seine nennt (CountDefault)
            limit = min(grenze, cap["count_default"]) if cap["count_default"] else None
            # Objekte, die über eine Kachelgrenze reichen, liefert der Dienst in beiden Kacheln; die
            # Schleife unten übernimmt jede ID bei gleichem Inhalt nur einmal (`gesehen`, E50)
            for k in _kacheln(cfg["bbox"], cfg.get("kachel_m", 500)):
                p = dict(basis, **{anzahl_param: grenze}, BBOX=",".join(map(str, k)) + "," + crs)
                root = hole(p)
                erhalten = anzahl(root)
                gesamt = root.get("numberMatched") or ""
                yield root
                if gesamt.isdigit():
                    if int(gesamt) > erhalten:
                        prot.unvollstaendig_melden(f"Kachel {k} unvollständig ({erhalten}/{gesamt}), "
                                                   "kachel_m verkleinern")
                elif erhalten and not (limit and erhalten < limit):
                    # Unter dem angefragten Limit beweist nichts: der Dienst kann selbst niedriger begrenzen.
                    # Eine leere Kachel (erhalten == 0) braucht keinen Beleg
                    yield from kachel_belegen(k, p, root, erhalten)

    for root in abfragen():
        for feat in _wfs_objekte(root):
            # Kennung aus gml:id vorab (E51); sonst aus dem Kindelement id_feld in der Schleife
            werte, oid, geom, kind = {}, (_kennung(feat, id_feld) if id_attr else None), None, None
            vorhanden.update(etree.QName(k).localname for k in feat if isinstance(k.tag, str))
            for el in feat:
                if not isinstance(el.tag, str):  # Kommentare, Verarbeitungsanweisungen
                    continue
                name = etree.QName(el).localname
                if name == geom_feld:
                    # Erstes Kindelement, nicht ein Kommentar davor (deegree: <!--Inlined geometry …-->)
                    kind = next((k for k in el if isinstance(k.tag, str)), None)
                    geom = etree.tostring(kind).decode() if kind is not None else None
                elif name == id_feld:
                    oid = (el.text or "").strip()
                # Nur einfache Felder ohne Kindelemente. Ein Feld nur aus Leerraum wird None; ein ganz leeres
                # Element (<feld/>, el.text ist None) fehlt in `werte`
                elif len(el) == 0 and el.text is not None and (felder is None or name in felder):
                    werte[(felder or {}).get(name, name)] = el.text.strip() or None
            if not oid or geom is None:
                prot.unvollstaendig_melden("Objekt ohne ID oder Geometrie übersprungen")
                continue
            fassung = _fassung_merken(gesehen, oid, _inhalt(werte, kind))
            # Schon gesehen: Nachbarkachel oder Folgeseite brachte dasselbe Objekt. Gleicher Inhalt: einmal
            # übernommen. Anderer Inhalt: Der Dienst widerspricht sich; welche Fassung stimmt, ist offen
            if fassung == "gleich":
                continue
            if fassung == "abweichend":
                prot.unvollstaendig_melden(f"Objekt-ID {oid[:80]} mehrfach mit abweichendem Inhalt geliefert "
                                           "(Werte oder Geometrie); der Schlüssel wird ausgelassen, sein "
                                           "bisheriger Stand bleibt; Abruf unvollständig, nichts wird "
                                           "gelöscht")
            yield {"objekt_id": oid, "geom": ("gml", geom), "werte": werte}
    if prot.info.get("schema_ungeprueft") and gesehen:
        # Ohne Schema bleibt nur die Probe am Objekt: fehlt ein konfiguriertes Feld in allen Objekten,
        # hält die Pipeline die Quelle an wie bei einem Feld, das im Schema fehlt (Codex B4)
        felder_pruefen(sorted(vorhanden), noetig, prot)
    if gemeldet and len(gesehen) < gemeldet[0]:
        # Ohne feste Reihenfolge kann ein Objekt zwischen zwei Seiten rutschen und fehlen.
        prot.unvollstaendig_melden(f"Nur {len(gesehen)} von {gemeldet[0]} gemeldeten Objekten erhalten "
                                   "(Seiten ohne feste Reihenfolge?), seitengroesse erhöhen")


def gebietsschluessel(roh: str, gebiet: dict) -> str:
    """Schlüssel so formen, dass er zum Feld der Geometriequelle passt.

    schluessel_laenge: führende Nullen ergänzen, die Tabellenkalkulationen oft abschneiden
    (Sachsen-Anhalt 15001 bleibt, Schleswig-Holstein 1001 wird 01001).
    schluessel_stellen: auf die ersten n Stellen kürzen, etwa INKAR-Kreise 12051000 auf den
    fünfstelligen Kreisschlüssel 12051 der VG250.

    Parameter: roh der Schlüssel aus der Quelle, gebiet der Abschnitt `gebiet` der Konfiguration (darf leer
    sein). Rückgabe: der Schlüssel ohne Rand, erst aufgefüllt, dann gekürzt."""
    s = roh.strip()
    if gebiet.get("schluessel_laenge"):
        s = s.zfill(gebiet["schluessel_laenge"])
    if gebiet.get("schluessel_stellen"):
        s = s[:gebiet["schluessel_stellen"]]
    return s


def _datum(text: str) -> str:
    """31.12.2025 -> 2025-12-31; alles andere bleibt, wie es ist (z. B. eine Jahreszahl)."""
    t = text.strip()
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", t)
    return f"{m[3]}-{m[2]}-{m[1]}" if m else t


# Fehlwerte des CSV-Adapters, wenn die Quelle keine eigenen nennt (`fehlwerte`)
CSV_FEHLWERTE = ["-", ".", "x", "…", "/"]


def _schluesselartig(text: str, form: re.Pattern, trenner: str = "") -> bool:
    """Beginnt `text` mit etwas, das wie ein Schlüssel aussieht (E51, Befund K2)? Geprüft wird nur das erste
    Wort: bis zum ersten Leerraum, Anführungszeichen oder Trenner, Anführungszeichen am Anfang zählen nicht.
    Schlüsselartig ist es ab vier Zeichen, wenn es nach schluessel_form gültig ist, oder wenn es mindestens
    vier Ziffern und höchstens ein anderes Zeichen hat (12O60005, 1206000x, 2013:).

    Nicht schlüsselartig: Fußnoten wie „1 Bevölkerungsfortschreibung“, „4 Stand 31.12.2024“ oder „1) …“, ein
    Datum (zwei Punkte), ein Name. Warum nur das erste Wort: Eine Quellenangabe nennt oft am Ende eine
    Jahreszahl („…, Deutschland, 2026.“); eine beschädigte Datenzeile beginnt dagegen mit ihrem Schlüssel.

    Args:
        text: Feld (CSV) oder Zelltext (XLSX).
        form: schluessel_form der Quelle.
        trenner: Feldtrenner der CSV; ein Feld, das mit einem Anführungszeichen beginnt, schließt der Parser
            erst beim nächsten Anführungszeichen und enthält dann Trenner ("12060096;Ort;… als ein Feld).
    """
    trenn = "".join(sorted({'"', re.escape(trenner)} - {""}))
    wort = re.split(rf"[\s{trenn}]+", text.strip().lstrip('"'), maxsplit=1)[0]
    ziffern = sum(c.isdigit() for c in wort)
    return len(wort) >= 4 and (bool(form.fullmatch(wort)) or (ziffern >= 4 and len(wort) - ziffern <= 1))


def _datenbereich(zeilen: list[str], cfg: dict, trenner: str, prot: Protokoll) -> list[tuple[int, str]]:
    """Datenbereich und Gebietsauswahl getrennt (Prüfbericht 05.11. abends, Befund 1, E47). Bis E46 war
    zeilen_muster beides: Eine Datenzeile mit fehlendem oder beschädigtem Schlüssel fiel vor jeder Prüfung
    heraus, nur `uebergangene_zeilen` stieg, und der Abgleich durfte den bisherigen Wert löschen.

    Datenbereich: die Zeilen nach dem Kopf (kopf_pruefen.zeile, zeitbezug.zeile) bis zur letzten Zeile in
    Form einer Datenzeile, deren Schlüssel gültig ist oder es nach Bereinigung wäre; danach beginnt der Fuß.
    Form einer Datenzeile: dieselbe Spaltenzahl wie die meisten gewählten Zeilen. Gemeldet (Abruf
    unvollständig, nichts wird gelöscht):
      - Zeilen in dieser Form ohne gültigen Schlüssel. Geprüft wird das rohe Feld, ohne strip(): leer,
        Buchstabe statt Ziffer, Leerzeichen oder Tab im Schlüssel oder an seinem Rand.
      - Zeilen, die erst bereinigt zum Gebiet passen (Felder ohne Rand und Anführungszeichen, wieder mit dem
        Trenner verbunden, passen auf zeilen_muster, die Rohzeile nicht), etwa "12060005";… (Nachprüfung zu
        E47).
      - gewählte Zeilen mit anderer Spaltenzahl (Werte stünden sonst in der falschen oder in keiner Spalte).
      - eine Mehrheit der gewählten Zeilen, deren Spaltenzahl von der Kopfzeile abweicht (kopf_pruefen.zeile,
        sonst zeitbezug.zeile); verglichen wird gegen die Mehrheit, die Kopfzeile ist die Gegenprobe.
      - seit E51 (Befund K2) jede Zeile nach dem Datenbereich, die nicht eindeutig eine erlaubte Fußzeile ist.
        Erlaubt: Leerzeilen (auch nur aus Trennern) und, als strenger Standard, Zeilen mit genau einem Feld
        mit Inhalt, und zwar in der ersten Spalte (Quellenangabe, Fußnote, „Fußnote;;;;“), wenn dieses Feld
        nicht mit einem Schlüssel beginnt (_schluesselartig). `fuss_muster` (regulärer Ausdruck auf die
        Rohzeile, je Quelle) erlaubt zusätzlich Zeilen, auf die es passt, auch mit mehreren Feldern
        („Quelle:;Amt;;;“) und auch, wenn das erste Feld mit einem Schlüssel beginnt („2014 Gebietsreform“;
        Nachprüfung zu E51: bis dahin blieb eine solche Fußnote auch mit passendem Muster zweifelhaft, die
        Quelle dauerhaft unvollständig, ohne Abhilfe über die Konfiguration). Das Muster deshalb eng fassen:
        Passt es auch auf den Anfang einer Datenzeile (etwa '.*'), bleibt eine abgeschnittene letzte
        Datenzeile, von der nur der Schlüssel übrig ist, stumm. Immer zweifelhaft, auch wenn das Muster
        passt: ein Feld nach dem ersten, das mit einem Schlüssel beginnt, und eine Zahl oder ein Fehlwert in
        einem Feld nach dem ersten (Fußzeilen tragen keine Messwerte). Bis E50 galt alles nach der letzten
        Datenzeile ohne Prüfung als Fuß; eine beschädigte letzte Datenzeile (Schlüssel leer, mit Buchstabe,
        oder die Zeile beginnt mit einem Anführungszeichen) verschwand still, und ihr bisheriger Wert konnte
        gelöscht werden (Prüfbericht vom 07.11.2026, K2).
    Stumm: gültige Schlüssel anderer Gebiete oder Ebenen innerhalb des Datenbereichs und Zeilen anderer
    Spaltenzahl dort (Leer- und Zwischenzeilen), dazu die erlaubten Fußzeilen.
    Grenzen: Ein Schlüssel, der nach dem Schaden nur aus Ziffern besteht, gilt als gültiger Schlüssel eines
    anderen Gebiets oder einer anderen Ebene und fällt nicht auf (fehlende oder doppelte Ziffer, Tippfehler,
    der einen anderen Schlüssel ergibt). Eine Datenzeile, von der nur ein Text in der ersten Spalte übrig ist
    (etwa nur der Name, ohne Schlüssel davor), sieht aus wie eine Fußnote und bleibt stumm.
    Rückgabe: die gewählten Zeilen als (Zeilennummer in der Datei ab 1, Text); die Nummer nutzt _csv_lesen für
    seine Meldungen (seit E50, vorher zählte es die gewählten Zeilen).
    Ausnahme: QuellenFehler, wenn weder kopf_pruefen noch zeitbezug aus dem Kopf angibt, wo der Kopf endet."""
    kopf = [cfg["kopf_pruefen"]["zeile"]] if cfg.get("kopf_pruefen") else []
    if isinstance(cfg.get("zeitbezug"), dict):
        kopf.append(cfg["zeitbezug"]["zeile"])
    if not kopf:
        # Kopfzeilen haben oft dieselbe Spaltenzahl wie Datenzeilen (;;Insgesamt;männlich;weiblich)
        raise QuellenFehler("zeilen_muster braucht kopf_pruefen oder zeitbezug aus dem Kopf ({zeile: …}), "
                            "damit feststeht, wo die Datenzeilen beginnen")
    muster = re.compile(cfg["zeilen_muster"])
    form = re.compile(cfg.get("schluessel_form", r"^\d+$"))
    schluessel = (cfg.get("gebiet") or {}).get("schluessel_spalte", cfg["id_spalte"])
    spalte = cfg["spalten_namen"].index(schluessel)
    # Je Zeile nach dem Kopf: Nummer in der Datei (ab 1), Rohtext, Felder, auf zeilen_muster gewählt?
    rest = [(nr, z, next(csv.reader([z], delimiter=trenner), []), bool(muster.match(z)))
            for nr, z in enumerate(zeilen, start=1) if nr > max(kopf)]
    # Spaltenzahl einer Datenzeile: die häufigste unter den gewählten Zeilen
    breiten = Counter(len(f) for _, _, f, gewaehlt in rest if gewaehlt)
    if not breiten:
        return []
    breite = breiten.most_common(1)[0][0]

    def gueltig(f: list[str]) -> bool:
        """Zeile in Form einer Datenzeile, Schlüssel im rohen Feld gültig nach schluessel_form."""
        # Rohes Feld: strip() machte ' 12060005' gültig, die Rohzeile passte aber nicht zum Gebiet
        return len(f) == breite and spalte < breite and bool(form.fullmatch(f[spalte]))

    def bereinigt_im_gebiet(f: list[str]) -> bool:
        """Zeile in Form einer Datenzeile, die erst ohne Rand und Anführungszeichen auf zeilen_muster passt
        (Anführungszeichen um ein ganzes Feld entfernt schon csv.reader; hier kommen der Rand ab und die
        Felder wieder mit dem Trenner zusammen)."""
        return len(f) == breite and bool(muster.match(trenner.join(x.strip() for x in f)))

    def bereinigt_gueltig(f: list[str]) -> bool:
        """Zeile in Form einer Datenzeile, deren Schlüssel ohne Rand gültig wäre."""
        return len(f) == breite and spalte < breite and bool(form.fullmatch(f[spalte].strip()))

    # Ende des Datenbereichs: letzte Zeile, die gewählt ist oder eine Datenzeile ist oder es bereinigt wäre.
    # Was danach kommt, ist Fuß (Quellenangaben, Fußnoten) und bleibt stumm
    ende = max(nr for nr, _, f, gewaehlt in rest
               if gewaehlt or gueltig(f) or bereinigt_gueltig(f) or bereinigt_im_gebiet(f))
    daten, ohne, bereinigt, andere = [], [], [], {}
    for nr, z, f, gewaehlt in rest:
        if nr > ende:
            break
        if gewaehlt and len(f) != breite:
            andere.setdefault(len(f), []).append(nr)
        elif gewaehlt:
            daten.append((nr, z))
        elif len(f) == breite and not gueltig(f):
            ohne.append(nr)
        elif bereinigt_im_gebiet(f):
            bereinigt.append(nr)

    def liste(nrs: list[int]) -> str:
        """Die ersten zehn Zeilennummern für die Meldung, „…“, wenn es mehr sind."""
        return ", ".join(map(str, nrs[:10])) + (" …" if len(nrs) > 10 else "")

    art = "Gebietsschlüssel" if cfg.get("gebiet") else "Schlüssel"
    if ohne:
        prot.unvollstaendig_melden(f"{len(ohne)} Datenzeilen ohne gültigen {art} übergangen (Zeilen "
                                   f"{liste(ohne)}); Abruf unvollständig, nichts wird gelöscht")
    if bereinigt:
        prot.unvollstaendig_melden(f"{len(bereinigt)} Datenzeilen passen erst ohne Leerzeichen oder "
                                   f"Anführungszeichen zum Gebiet, übergangen (Zeilen {liste(bereinigt)}); "
                                   "Abruf unvollständig, nichts wird gelöscht")
    for n, nrs in sorted(andere.items()):
        prot.unvollstaendig_melden(f"{len(nrs)} Datenzeilen mit {n} statt {breite} Spalten übergangen "
                                   f"(Zeilen {liste(nrs)}); Abruf unvollständig, nichts wird gelöscht")
    # Nach dem Datenbereich nur erlaubte Fußzeilen (E51, Befund K2; Regeln im Docstring). Die Zeilen bleiben
    # außerhalb der Daten wie bisher; neu ist nur, dass eine zweifelhafte die Löschung sperrt
    fuss_re = re.compile(cfg["fuss_muster"]) if cfg.get("fuss_muster") else None
    fehlwerte = set(cfg.get("fehlwerte", CSV_FEHLWERTE))
    zweifel = []
    for nr, z, f, _ in rest:
        felder = [x.strip() for x in f]
        if nr <= ende or not any(felder):
            continue   # Datenbereich oder Leerzeile
        muster_passt = bool(fuss_re and fuss_re.match(z))
        if (any(_schluesselartig(x, form, trenner) for x in felder[1:] if x)
                or any(_ZAHL.fullmatch(x) or x in fehlwerte for x in felder[1:] if x)):
            # Hart, auch mit passendem fuss_muster: Schlüssel, Zahl oder Fehlwert nach dem ersten Feld
            zweifel.append(nr)
        elif not muster_passt and (not felder[0] or any(felder[1:])
                                   or _schluesselartig(felder[0], form, trenner)):
            # Standard: genau ein Feld mit Inhalt, in der ersten Spalte, das nicht mit einem Schlüssel
            # beginnt. fuss_muster erlaubt zusätzlich, auch ein erstes Feld in Schlüsselform („2014
            # Gebietsreform“; Nachprüfung zu E51, bis dahin war diese Regel auch mit Muster hart)
            zweifel.append(nr)
    if zweifel:
        prot.unvollstaendig_melden(f"{len(zweifel)} Zeilen nach dem Datenbereich sind nicht eindeutig als "
                                   f"Fußzeilen erkennbar (Zeilen {liste(zweifel)}); Abruf unvollständig, "
                                   "nichts wird gelöscht (weitere Fußzeilen erlaubt fuss_muster der Quelle)")
    # Gegenprobe zur Mehrheit: Fehlt allen gewählten Zeilen dieselbe Spalte, fiele sonst nichts auf
    # (Nachprüfung zu E47)
    kz = cfg["kopf_pruefen"]["zeile"] if cfg.get("kopf_pruefen") else cfg["zeitbezug"]["zeile"]
    kopf_breite = len(next(csv.reader([zeilen[kz - 1]], delimiter=trenner), [])) if len(zeilen) >= kz else 0
    if kopf_breite != breite:
        prot.unvollstaendig_melden(f"Die gewählten Datenzeilen haben meist {breite} Spalten, die Kopfzeile "
                                   f"{kz} hat {kopf_breite}; Abruf unvollständig, nichts wird gelöscht")
    return daten


def csv_quelle(cfg: dict, prot: Protokoll) -> Iterator[dict]:
    """CSV-Adapter mit Bilanz am Ende (Werte, die keine Zahl sind). Konfiguration und Verhalten siehe
    _csv_lesen; zahlen_bilanz läuft erst, wenn alle Datensätze abgeholt sind."""
    yield from _csv_lesen(cfg, prot)
    zahlen_bilanz(prot)


def _csv_lesen(cfg: dict, prot: Protokoll) -> Iterator[dict]:
    """CSV lokal oder per URL. Geometrie aus WKT-Spalte, x/y-Spalten oder, bei Tabellen ohne
    Koordinaten, ein Gebietsschlüssel (Abschnitt `gebiet`, z. B. AGS). Er steht in der Zieltabelle als
    fachlicher Schlüssel (Antwort 28 der TH) und lässt sich dort als Feld `_gebiet` zuordnen.

    Für Statistik-Tabellen mit Kopf- und Fußblock (CSV; Berichte als Excel-Datei liest der Typ xlsx, E48):
      zeilen_muster   Gebietsauswahl: nur Zeilen, die auf diesen regulären Ausdruck passen, werden
                      übernommen. Dann gibt spalten_namen die Namen der Spalten nach Position vor, weil es
                      keine Kopfzeile gibt, und kopf_pruefen oder zeitbezug aus dem Kopf sagt, wo der Kopf
                      endet. Die übrigen Zeilen prüft `_datenbereich` (E47): Zeilen nach dem Kopf mit der
                      Spaltenzahl der gewählten Zeilen sind Datenzeilen; steht in ihrer Schlüsselspalte kein
                      Schlüssel in gültiger Form (schluessel_form, am rohen Feld geprüft) oder passt die Zeile
                      erst ohne Leerzeichen und Anführungszeichen zum Gebiet, gilt der Abruf als unvollständig
                      (nichts wird gelöscht). Datenzeilen anderer Gebiete und Ebenen, Kopf und Fuß bleiben
                      stumm.
      schluessel_form regulärer Ausdruck für einen gültigen Schlüssel einer Datenzeile, gleich welchen
                      Gebiets (Standard: nur Ziffern; mit Kennung für Deutschland etwa '^(DG|\\d+)$')
      fuss_muster     regulärer Ausdruck für weitere erlaubte Fußzeilen nach dem Datenbereich (E51). Ohne
                      Angabe sind dort nur Leerzeilen und Zeilen mit genau einem Feld in der ersten Spalte
                      erlaubt, das nicht mit einem Schlüssel beginnt; jede andere Zeile macht den Abruf
                      unvollständig (_datenbereich). Eine passende Zeile darf mehrere Felder haben und mit
                      einem Schlüssel beginnen („2014 Gebietsreform“), aber nach dem ersten Feld weder Zahl
                      noch Fehlwert noch Schlüssel; eng fassen, nie so, dass es auf Datenzeilen passt
      zeitbezug       Zeit-Referenz der Messwerte (zahl_felder, sonst aller Werte): fest (2025)
                      oder aus dem Kopf ({zeile: 7, spalte: 3}, beide ab 1 gezählt;
                      31.12.2025 wird 2025-12-31)
      kopf_pruefen    Kopfzeile, die so aussehen muss wie erwartet ({zeile: 8, erwartet: [...]}).
                      Ohne Spaltenzeile ist das der Feldlisten-Vergleich: Schiebt der Anbieter
                      eine Spalte ein oder stellt um, wird die Quelle angehalten, statt dass
                      Werte still in die falsche Spalte rutschen.
      zeit_spalte     Zeit-Referenz je Zeile aus dieser Spalte
      zahl_felder     Zielfelder, die als Zahl abgelegt werden (Dezimalkomma, Leerzeichen erlaubt)
      fehlwerte       Zeichen für „kein Wert“ (Standard: -, ., x, …, /), werden zu null
      leere_auslassen Zeilen, in denen alle zahl_felder ohne Wert sind, auslassen (z. B. aufgelöste
                      Gemeinden, die die Statistik noch mit „-“ führt). Der Adapter gibt sie mit
                      Schlüssel und Merkmal `leer` weiter; das Zielschreiben lässt sie aus, ihr
                      bisheriger Wert bleibt, der Bericht warnt (Antwort 63, Codex-Prüfung 05.11., B2).
                      Ohne Schlüssel gilt der Abruf als unvollständig, dann wird nichts gelöscht.
                      Braucht zahl_felder (sonst ist keine Zeile „leer“, die Quelle bricht mit Meldung
                      ab). Einzelne leere Zellen werden null; dass eine Kennzahlzeile ohne Wert nicht
                      übernommen wird, regelt ziel.pflicht (E42).

    Weitere Schlüssel: pfad (Datei oder https-Adresse), encoding (Standard utf-8), trenner (Standard „,“),
    id_spalte, spalten (Quellspalte -> Zielfeld; ohne: alle Spalten), srid (Standard 25833), wkt_spalte oder
    x_spalte/y_spalte. Rückgabe: Datensätze mit ("wkt", …) oder ("gebiet", …) als Geometrie, dazu `zeit`
    und `leer`. Seiteneffekt: Netzabruf über abrufen, wenn pfad eine Adresse ist.
    Ausnahmen: QuellenFehler bei widersprüchlicher Konfiguration oder unlesbarem Zeitbezug; eine
    abweichende Kopfzeile hält die Quelle an (fehlende_felder), ohne Ausnahme.
    """
    if cfg.get("leere_auslassen") and not cfg.get("zahl_felder"):
        # Ohne zahl_felder wäre der Schalter wirkungslos und leere Zeilen überschrieben Werte mit null
        raise QuellenFehler("leere_auslassen braucht zahl_felder (die Felder, die eine Zeile ohne Wert "
                            "kennzeichnen), Konfiguration ergänzen")
    pfad = cfg["pfad"]
    if "://" in pfad:
        text = abrufen(pfad, None, cfg, prot).decode(cfg.get("encoding", "utf-8"))
    else:
        with open(pfad, encoding=cfg.get("encoding", "utf-8")) as f:
            text = f.read()
    trenner = cfg.get("trenner", ",")
    zeilen = text.splitlines()
    if cfg.get("kopf_pruefen"):
        kp = cfg["kopf_pruefen"]
        ist = next(csv.reader([zeilen[kp["zeile"] - 1]], delimiter=trenner)) \
            if len(zeilen) >= kp["zeile"] else []
        ist = [z.strip() for z in ist][:len(kp["erwartet"])]
        if ist != kp["erwartet"]:
            prot.info["fehlende_felder"] = [f"Kopfzeile {kp['zeile']}: {';'.join(ist)}"[:300]]
            prot.warnungen.append(f"Kopfzeile {kp['zeile']} weicht ab: erwartet "
                                  f"{';'.join(kp['erwartet'])}, gefunden {';'.join(ist)}"[:500])
            return
    zeitbezug = cfg.get("zeitbezug")
    if isinstance(zeitbezug, dict):
        try:
            zelle = next(csv.reader([zeilen[zeitbezug["zeile"] - 1]], delimiter=trenner))
            zeitbezug = _datum(zelle[zeitbezug["spalte"] - 1])
        except (IndexError, StopIteration) as e:
            raise QuellenFehler(f"Zeitbezug nicht im Kopf gefunden ({zeitbezug})") from e
        if not re.fullmatch(r"\d{4}(-\d{2}-\d{2})?", zeitbezug):
            # Verrutschter Kopf: sonst würde z. B. „Insgesamt“ still zur Zeit-Referenz
            raise QuellenFehler(f"Zeitbezug im Kopf ist kein Datum oder Jahr: {zeitbezug[:40]!r}")
        prot.info["zeitbezug"] = zeitbezug
    elif zeitbezug is not None:
        zeitbezug = str(zeitbezug)

    # Zeilennummer in der Datei je gelesener Zeile des Lesers (E50): mit zeilen_muster über die Nummern aus
    # _datenbereich, sonst die Zählung des Lesers selbst (line_num zählt auch Zeilenumbrüche in Feldern)
    nummern: list[int] | None = None
    if cfg.get("zeilen_muster"):
        paare = _datenbereich(zeilen, cfg, trenner, prot)
        nummern = [nr for nr, _ in paare]
        prot.info["uebergangene_zeilen"] = len(zeilen) - len(paare)
        # Ohne Kopfzeile: spalten_namen gibt die Namen nach Position vor
        leser = csv.DictReader([z for _, z in paare], fieldnames=cfg["spalten_namen"], delimiter=trenner)
    else:
        leser = csv.DictReader(zeilen, delimiter=trenner)
    srid = cfg.get("srid", 25833)
    spalten = cfg.get("spalten", {})  # Quellspalte -> Zielfeld
    gebiet = cfg.get("gebiet")  # Verknüpfung über Gebietsschlüssel statt Koordinaten
    zahl_felder = set(cfg.get("zahl_felder", []))
    fehlwerte = set(cfg.get("fehlwerte", CSV_FEHLWERTE))
    zeit_spalte = cfg.get("zeit_spalte")

    prot.info["felder"] = sorted(f for f in (leser.fieldnames or []) if f)
    noetig = [cfg["id_spalte"], *spalten]
    if gebiet:
        noetig.append(gebiet["schluessel_spalte"])
    elif "wkt_spalte" in cfg:
        noetig.append(cfg["wkt_spalte"])
    else:
        noetig += [cfg["x_spalte"], cfg["y_spalte"]]
    if zeit_spalte:
        noetig.append(zeit_spalte)
    felder_pruefen(prot.info["felder"], list(dict.fromkeys(noetig)), prot)

    ohne_wert = 0
    for zeile in leser:
        # Zeile der Datei für Meldungen; bis E50 zählte nr die gewählten Zeilen ab 2 bzw. physische Zeilen
        # ohne Umbrüche in Feldern (in E49 benannt, E50 behoben). Bei einem Feld über mehrere Zeilen die
        # letzte davon
        nr = nummern[leser.line_num - 1] if nummern is not None else leser.line_num
        oid = (zeile.get(cfg["id_spalte"]) or "").strip()
        werte, fehlend = {}, 0
        for k, v in zeile.items():
            # k ist None für überzählige Felder einer Zeile (DictReader sammelt sie unter dem Schlüssel None)
            if k is None or (spalten and k not in spalten):
                continue
            feld = spalten.get(k, k)
            v = (v or "").strip()
            if v in fehlwerte:
                v, fehlend = None, fehlend + 1
            elif feld in zahl_felder:
                v = _zahl(v.replace(" ", ""), prot)
            werte[feld] = v
        leer = bool(cfg.get("leere_auslassen") and zahl_felder
                    and all(werte.get(f) is None for f in zahl_felder))
        if not leer:
            # Zellen der ausgelassenen Zeilen werden nicht als null abgelegt, also nicht mitgezählt
            ohne_wert += fehlend
        zeit_wert = _datum(zeile.get(zeit_spalte) or "") if zeit_spalte else zeitbezug
        # Die Zeit-Referenz gilt für die Messwerte (zahl_felder), nicht für Name oder Schlüssel
        zeit = {f: zeit_wert for f in werte if f in zahl_felder or not zahl_felder} if zeit_wert else {}
        if gebiet:
            schluessel = (zeile.get(gebiet["schluessel_spalte"]) or "").strip()
            if not schluessel:
                prot.unvollstaendig_melden(f"Zeile {nr}: ohne Gebietsschlüssel übersprungen")
                continue
            schluessel = gebietsschluessel(schluessel, gebiet)
            yield {"objekt_id": oid or schluessel, "geom": ("gebiet", schluessel), "werte": werte,
                   "zeit": zeit, "leer": leer}
            continue
        try:
            if "wkt_spalte" in cfg:
                wkt = zeile[cfg["wkt_spalte"]]
            else:
                x = float(zeile[cfg["x_spalte"]].replace(",", "."))
                y = float(zeile[cfg["y_spalte"]].replace(",", "."))
                wkt = f"POINT({x} {y})"
        except (KeyError, ValueError, AttributeError) as e:
            prot.unvollstaendig_melden(f"Zeile {nr}: keine gültige Geometrie ({e})")
            continue
        if not oid:
            prot.unvollstaendig_melden(f"Zeile {nr}: ohne ID übersprungen")
            continue
        yield {"objekt_id": oid, "geom": ("wkt", f"SRID={srid};{wkt}"), "werte": werte, "zeit": zeit,
               "leer": leer}
    if ohne_wert > 0:
        prot.hinweise.append(f"{ohne_wert} Zellen ohne Wert (statistische Zeichen wie „-“) als null abgelegt")


# --- XLSX: Statistische Berichte als Excel-Datei (E48) --------------------------------------

XLSX_FEHLWERTE = ["-", "–", ".", "x", "…", "/", "•"]
# Hochgestellte Ziffern sind in Kopfzeilen Fußnotenzeichen (Fläche⁴, Bevölkerung¹)
_FUSSNOTE = str.maketrans("", "", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def kopf_normal(text) -> str:
    """Kopfbeschriftung zum Vergleich: ohne Leerzeichen, Zeilenumbrüche und Fußnotenzeichen. Aus
    'Fläche⁴\\nin km²' und 'Fläche in km²' wird beides 'Flächeinkm'."""
    return "".join(str(text).split()).translate(_FUSSNOTE) if text is not None else ""


def link_ermitteln(cfg: dict, prot: Protokoll) -> str:
    """Link auf die jüngste Ausgabe von der Seite eines Berichts (`seite`): Links (a href), deren Dateiname
    auf `datei_muster` passt, nur auf dem Rechner der Seite oder in `link_rechner`, nur https auf Port 443,
    nie auf einem Pfad, den die robots.txt sperrt (ROBOTS_GESPERRT; www.statistik-berlin-brandenburg.de sperrt
    /scrivito/). Eine Gruppe `jahr` im Muster wählt die jüngste Ausgabe; ohne sie muss genau ein Link passen.
    Abgerufen wird nur die Seite selbst (abrufen: keine Weiterleitung, Größenlimit), keinem Link wird
    gefolgt.

    Rückgabe: die Adresse der Datei. Ausnahmen: QuellenFehler, wenn kein erlaubter Link passt oder mehrere
    für dieselbe Ausgabe. Seiteneffekt: ein Netzabruf (die Seite), Dateiname als Hinweis im Protokoll."""
    seite = cfg["seite"]
    html = abrufen(seite, None, cfg, prot)
    # HTML-Parser von lxml, ebenfalls ohne Netzzugriff; bei leerer Seite liefert er None (unten abgefangen)
    doc = etree.fromstring(html, etree.HTMLParser(no_network=True, huge_tree=False))
    erlaubt = {urlsplit(seite).hostname, *(cfg.get("link_rechner") or [])}
    muster = re.compile(cfg["datei_muster"])
    je_jahr: dict[str, set[str]] = {}
    fremd = 0
    for href in (doc.xpath("//a/@href") if doc is not None else []):
        # Relative Links gegen die Seite auflösen, Sprungmarke abschneiden (sonst zählte derselbe Link mit
        # zwei Marken als zwei Ausgaben)
        try:
            url = urljoin(seite, str(href).strip()).split("#", 1)[0]
            t = urlsplit(url)
        except ValueError:
            continue     # keine lesbare Adresse (etwa „[“ im Rechner)
        m = muster.fullmatch(t.path.rsplit("/", 1)[-1])
        if not m:
            continue
        try:
            port = t.port
        except ValueError:
            port = -1    # Port keine Zahl (Prüfung nach E48): wie fremd, statt die Quelle scheitern zu lassen
        # Nur https auf dem Standardport, ohne Anmeldedaten in der Adresse, nur auf erlaubten Rechnern und
        # nie auf einem gesperrten Pfad
        if t.scheme != "https" or t.hostname not in erlaubt or port not in (None, 443) or t.username \
                or robots_gesperrt(url) is not None:
            fremd += 1   # fremde und gesperrte Links nie, auch wenn der Dateiname passt
            continue
        je_jahr.setdefault(m.groupdict().get("jahr") or "", set()).add(url)
    if not je_jahr:
        raise QuellenFehler(f"Kein Link nach datei_muster auf {seite}"
                            + (f" ({fremd} passende Links auf anderen Rechnern, ohne https oder auf einem "
                               "per robots.txt gesperrten Pfad, nicht gefolgt; link_rechner prüfen)"
                               if fremd else ""))
    # Jüngste Ausgabe nach dem Zahlenwert der Gruppe `jahr` (bis E50 als Text verglichen: „999“ lag hinter
    # „2025“, in E49 benannt, E50 behoben). Ohne Gruppe `jahr` gibt es nur den Schlüssel "" und damit genau
    # eine Ausgabe
    jahr = max(je_jahr, key=lambda j: (int(j) if j.isdigit() else -1, j))
    if len(je_jahr[jahr]) != 1:
        raise QuellenFehler(f"Seite {seite} hat mehrere Links für dieselbe Ausgabe ({jahr or 'ohne Jahr'}): "
                            f"{', '.join(sorted(je_jahr[jahr]))[:300]}")
    url = je_jahr[jahr].pop()
    prot.hinweise.append(f"Datei laut Seite: {url.rsplit('/', 1)[-1]}")
    return url


def cache_datei(url: str, endungen: tuple[str, ...], cfg: dict) -> Path:
    """Pfad im Cache für eine Datei aus dem Netz: Ordner `cache` der Quelle, sonst PIPELINE_CACHE, sonst
    ./cache; Name = letzter Teil des Pfads der Adresse.

    Der Name aus dem Netz wird Dateiname im Cache, deshalb nur ein einfacher Name: beginnt mit einem
    Wortzeichen (also nie „..“, nie leer, nie versteckt), sonst nur Wortzeichen, Punkt und Bindestrich, und
    eine der `endungen`. Seit E50 für XLSX, INKAR und GeoJSON gleich; bis dahin prüften INKAR und GeoJSON den
    Namen nicht, „..“ zeigte auf den Ordner über dem Cache (in E49 benannt, E50 behoben).
    Ausnahme: QuellenFehler bei einem anderen Namen, vor jedem Abruf."""
    name = urlsplit(url).path.rsplit("/", 1)[-1]
    muster = "|".join(re.escape(e) for e in endungen)
    if not re.fullmatch(rf"\w[\w.-]*\.(?:{muster})", name):
        raise QuellenFehler(f"Dateiname {name[:80]!r} aus der Adresse ist kein einfacher Name einer Datei "
                            f"mit Endung {', '.join('.' + e for e in endungen)}")
    return Path(cfg.get("cache") or os.environ.get("PIPELINE_CACHE", "cache")) / name


def xlsx_datei(cfg: dict, prot: Protokoll) -> Path:
    """Genau eine Bezugsart: `pfad` (abgelegte Datei, Antwort 33, oder https-Adresse) oder `seite` mit
    `datei_muster` (Link von der Seite). Abgerufene Dateien liegen in cache/ und werden mit If-Modified-Since
    nur bei Änderung neu geladen; zwei Quellen aus derselben Datei laden sie so nur einmal.

    Rückgabe: Pfad der lokalen Datei. Ausnahmen: QuellenFehler bei keiner oder beiden Bezugsarten und bei
    einem Dateinamen, der kein einfacher .xlsx-Name ist. Seiteneffekte: Netzabruf und Schreiben in den
    Cache (cfg["cache"], sonst PIPELINE_CACHE, sonst ./cache), außer bei einer abgelegten Datei."""
    arten = [k for k in ("pfad", "seite") if cfg.get(k)]
    if len(arten) != 1:
        raise QuellenFehler("xlsx braucht genau eines: pfad (abgelegte Datei oder https-Adresse) oder seite "
                            "mit datei_muster")
    if cfg.get("pfad") and "://" not in cfg["pfad"]:
        return Path(cfg["pfad"])
    url = cfg.get("pfad") or link_ermitteln(cfg, prot)
    datei = cache_datei(url, ("xlsx",), cfg)
    name = datei.name
    datei_abrufen(url, datei, cfg, prot)
    prot.info["datei"] = {"name": name, "url": url}
    return datei


# Leerraum, den XML vor dem ersten Zeichen erlaubt
_LEER = b" \t\r\n"
# XML in UTF-16 oder UTF-32 ohne BOM: Leerraum und dann „<“ in der jeweiligen Kodierung (E50). Ein XML-Parser
# erkennt diese Kodierungen am ersten „<“ (XML 1.0, Anhang F); bis E50 prüfte _xlsx_teil_pruefen nur „<“
# direkt am Anfang neben einem Nullbyte und übersah UTF-32BE und Leerraum davor (in E49 benannt, E50 behoben)
_BREIT_OHNE_BOM = re.compile(rb"(?:\x00\x00\x00[ \t\r\n])*\x00\x00\x00<"     # UTF-32BE
                             rb"|(?:[ \t\r\n]\x00\x00\x00)*<\x00\x00\x00"     # UTF-32LE
                             rb"|(?:\x00[ \t\r\n])*\x00<"                     # UTF-16BE
                             rb"|(?:[ \t\r\n]\x00)*<\x00")                    # UTF-16LE


def _xlsx_teil_pruefen(z: zipfile.ZipFile, info: zipfile.ZipInfo) -> None:
    """Ein Teil der XLSX: Kann ein XML-Parser ihn lesen (erstes Zeichen nach BOM und Leerraum „<“), dann nur
    UTF-8 (UTF-16/32 abgelehnt, Deklaration ohne encoding oder mit UTF-8) und ohne DTD oder Entität. Alles
    andere (Bilder, Druckeinstellungen, eingebettete Dateien) kann kein XML-Parser lesen; es wird nicht als
    XML geprüft. Am Inhalt, nicht an der Endung: openpyxl liest Blätter über rels und [Content_Types], gleich
    welche Endung der Teil hat (Prüfung nach E48).

    Die Kodierungsprüfung (BOM von UTF-16/32, oder ohne BOM Leerraum und „<“ in UTF-16/32, _BREIT_OHNE_BOM)
    läuft vor der Frage, ob der Teil XML ist; ein Nicht-XML-Teil, der mit diesen Bytes beginnt, wird deshalb
    ebenfalls abgelehnt. Bilder (EMF beginnt mit 01 00 00 00, PNG) und Druckeinstellungen in UTF-16 ohne „<“
    treffen das Muster nicht. Gelesen wird in Blöcken zu 64 KiB, nie der ganze Teil auf einmal.
    Ausnahme: QuellenFehler bei fremder Kodierung, unvollständiger Deklaration, DTD oder Entität."""
    with z.open(info) as f:
        stueck = f.read(1 << 16)
        # UTF-16/32 mit BOM oder ohne BOM (Leerraum und „<“ in UTF-16/32): Die Suche nach <!DOCTYPE unten
        # arbeitet auf UTF-8-Bytes und sähe solche Teile nicht
        if stueck.startswith((b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff")) \
                or _BREIT_OHNE_BOM.match(stueck):
            raise QuellenFehler(f"{info.filename}: nicht UTF-8 kodiert, abgelehnt")
        stueck = stueck.removeprefix(b"\xef\xbb\xbf").lstrip(_LEER)
        # Besteht der erste Block nur aus Leerraum, entscheidet der nächste, ob XML folgt
        while not stueck and (mehr := f.read(1 << 16)):
            stueck = mehr.lstrip(_LEER)
        if not stueck.startswith(b"<"):
            return
        # Die XML-Deklaration muss in den ersten 1024 Bytes vollständig stehen; mindestens so viel lesen
        while len(stueck) < 1024 and (mehr := f.read(1 << 16)):
            stueck += mehr
        if stueck.startswith(b"<?xml"):
            ende = stueck.find(b"?>", 0, 1024)
            m = re.search(rb"""\sencoding\s*=\s*["']([^"']*)["']""", stueck[:ende] if ende > 0 else b"")
            if ende < 0 or (m and m[1].lower() not in (b"utf-8", b"utf8")):
                art = m[1].decode("ascii", "replace")[:20] if m else "Deklaration unvollständig"
                raise QuellenFehler(f"{info.filename}: nicht UTF-8 kodiert ({art}), abgelehnt")
        # Den ganzen Teil blockweise nach <!DOCTYPE und <!ENTITY durchsuchen. Die letzten 16 Bytes des
        # vorigen Blocks kommen mit, damit ein Schlüsselwort über einer Blockgrenze nicht durchfällt
        rest = b""
        while stueck:
            rest = rest[-16:] + stueck
            if b"<!DOCTYPE" in rest or b"<!ENTITY" in rest:
                raise QuellenFehler(f"{info.filename}: DTD oder Entität im XML, abgelehnt")
            stueck = f.read(1 << 16)


def xlsx_pruefen(pfad: Path, cfg: dict) -> None:
    """Vor openpyxl, am ZIP selbst: alle Teile zusammen entpackt höchstens max_entpackt_mb, ab 1 MB je Teil
    Packrate höchstens max_packrate (ZIP-Bombe), höchstens 10 000 Teile; jeder Teil, den ein XML-Parser lesen
    kann, nur in UTF-8 und ohne DTD oder Entität (externe Entitäten, „Billion Laughs“; _xlsx_teil_pruefen).
    Alle Teile, nicht nur .xml und .rels: openpyxl liest Blätter und sharedStrings über die Ziele in rels und
    [Content_Types], gleich welche Endung (Prüfung nach E48). Zusätzlich liest openpyxl über defusedxml (ohne
    defusedxml liest die Pipeline nicht). Die angegebenen Größen sind verlässlich: zipfile liest einen Eintrag
    nie über seine angegebene Größe hinaus.

    Parameter: pfad der XLSX, cfg mit optional max_entpackt_mb (Standard 100) und max_packrate (Standard 100).
    Ausnahme: QuellenFehler bei jedem Befund; die Datei wird dann gar nicht erst von openpyxl geöffnet."""
    # Spät importiert: openpyxl wird nur für den Quelltyp xlsx gebraucht
    import openpyxl
    # openpyxl.DEFUSEDXML zeigt, ob openpyxl seine XML-Teile über defusedxml liest
    if openpyxl.DEFUSEDXML is not True:
        raise QuellenFehler("openpyxl liest ohne defusedxml (Paket fehlt oder OPENPYXL_DEFUSEDXML gesetzt); "
                            "XLSX wird nicht gelesen")
    try:
        z = zipfile.ZipFile(pfad)
    except (zipfile.BadZipFile, OSError) as e:
        raise QuellenFehler(f"{Path(pfad).name}: keine lesbare XLSX-Datei ({e})"[:300]) from None
    with z:
        infos = z.infolist()
        if len(infos) > 10_000:
            raise QuellenFehler(f"XLSX mit {len(infos)} Teilen, ungewöhnlich viele")
        grenze = int(cfg.get("max_entpackt_mb", 100) * 1024 * 1024)
        gesamt = sum(i.file_size for i in infos)
        for i in infos:
            rate = i.file_size / max(i.compress_size, 1)
            if i.file_size > 1 << 20 and rate > cfg.get("max_packrate", 100):
                raise QuellenFehler(f"{i.filename}: Packrate {rate:.0f}:1 ungewöhnlich hoch (ZIP-Bombe?), "
                                    "max_packrate")
        if gesamt > grenze:
            raise QuellenFehler(f"Teile der XLSX entpackt {gesamt / 1e6:.0f} MB, erlaubt "
                                f"{cfg.get('max_entpackt_mb', 100)} MB (max_entpackt_mb)")
        try:
            for i in infos:
                _xlsx_teil_pruefen(z, i)
        except (zipfile.BadZipFile, zlib.error, NotImplementedError, EOFError) as e:
            raise QuellenFehler(f"{Path(pfad).name}: keine lesbare XLSX-Datei ({e})"[:300]) from None


def _zelle_schluessel(v) -> str | None:
    """Schlüssel einer Zelle als Text: Zahlen ohne Nachkommastellen (12060005, 12060005.0), Text unverändert
    (ohne strip, wie E47: ' 12060005' ist nicht gültig). Leer: ''. Anderes (Wahrheitswert, Datum): None."""
    if v is None:
        return ""
    # bool vor int prüfen: True ist in Python auch ein int und würde sonst zum Schlüssel "1"
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else None
    return v if isinstance(v, str) else None


def xlsx(cfg: dict, prot: Protokoll) -> Iterator[dict]:
    """Statistischer Bericht als XLSX (E48), etwa des Amts für Statistik Berlin-Brandenburg. Je gewählter
    Zeile ein Datensatz mit Gebietsschlüssel (Abschnitt `gebiet` wie bei CSV) und den Werten aus `werte`.

      blaetter / blatt_muster  Blätter als Liste (jedes muss es geben) oder regulärer Ausdruck (mindestens
                               eines); sonst hält die Quelle an.
      schluessel               Beschriftung der Schlüsselspalte. Steht sie mehrfach im Kopf (AfS: erste und
                               letzte Spalte), müssen alle diese Spalten in jeder Datenzeile gleich sein.
      werte                    {feld: {kopf: Beschriftung, zeitbezug: …}}; jede Beschriftung genau einmal.
                               Beschriftungen werden ohne Leerzeichen, Zeilenumbrüche und Fußnotenzeichen
                               verglichen (kopf_normal). Kopfzeile ist je Blatt die erste der ersten
                               kopf_bis_zeile Zeilen (30) mit allen Beschriftungen; fehlt sie, hält die
                               Quelle an.
      zeitbezug                je Feld fest (2025, "2025-12-31") oder aus der Datei: {muster: regulärer
                               Ausdruck mit einer Gruppe, als: '{}-12-31'}; gesucht in allen Textzellen der
                               Blätter, genau ein Ergebnis, sonst bricht die Quelle ab.
      schluessel_form          gültiger Schlüssel einer Datenzeile, gleich welcher Ebene (Standard: Ziffern)
      zeilen_auswahl           {schluessel: Gebiet, ohne: auszulassen, ohne_ausser: doch zu nehmen}, je ein
                               regulärer Ausdruck auf den Schlüssel
      summe                    {schluessel: Summenzeile, toleranz: Betrag}: Summe der gewählten Werte gegen
                               diese Zeile; Abweichung oder fehlende Zeile: unvollständig. Dazu optional
                               teilsummen: regulärer Ausdruck mit einer Gruppe (AfS '^(\\d{5})000$'): Zeilen
                               mit passendem Schlüssel sind Teilsummen ihres Blatts, die Gruppe ist der
                               Anfang der Schlüssel, die dazu gehören. Jede gewählte Zeile eines Blatts muss
                               zu einer Teilsumme desselben Blatts gehören, und deren Summe muss stimmen
                               (gleiche Toleranz); sonst unvollständig
      fehlwerte                statistische Zeichen ohne Wert (Standard XLSX_FEHLWERTE, darunter „–“)

    Datenzeile ist jede Zeile nach dem Kopf mit gültigem Schlüssel oder mit einem Eintrag in einer Wertspalte.
    Unvollständig (nichts wird gelöscht, E47 sinngemäß), mit Blatt und Zeile: Datenzeile ohne gültigen
    Schlüssel (leer, Buchstabe, Rand, falsche Länge, Wahrheitswert, Formel ohne zwischengespeicherten Wert),
    verschiedene Schlüssel in den Schlüsselspalten, ein gewählter Schlüssel zum zweiten Mal (Prüfung nach
    E48; beide Zeilen gehen weiter, ziel lässt den Schlüssel bei verschiedenen Werten aus), Wert, der weder
    endliche Zahl noch statistisches Zeichen ist (Text wird nicht als Zahl geraten, 1E999 ist keine Zahl; der
    Wert bleibt leer, ziel.pflicht hält die Zeile zurück), Abweichung einer Summe oder Teilsumme, seit E51
    (Befund K2 sinngemäß) auch eine Zeile ohne Wert, deren Schlüsselspalte etwas in Schlüsselform
    (_schluesselartig) oder einen Wert enthält, der kein Text ist. Stumm: Zeilen mit gültigem Schlüssel
    außerhalb der Auswahl, Leer-, Titel- und Fußnotenzeilen ohne Wert (etwa „4 Stand 31.12.2024“). Eine
    Zeile ganz ohne Wert (nur statistische Zeichen, Formeln ohne Wert) geht mit Merkmal `leer` weiter, ihr
    bisheriger Stand bleibt (wie leere_auslassen bei CSV); fehlt dadurch ein Wert in einer Summe, ist der
    Abruf unvollständig.
    Grenze: Summen und Teilsummen erkennen fehlende, zusätzliche und veränderte Werte, aber keinen geänderten
    Schlüssel. Wird ein Schlüssel in beiden Spalten zu einem anderen gültigen, fällt das auf, wenn es den
    neuen schon gibt (mehrfach) oder er in einen anderen Kreis fällt (Teilsumme); ein neuer, bisher nicht
    vorhandener Schlüssel im selben Kreis fällt nicht auf (nur gebiet_pruefen meldet eine Gemeinde ohne
    Gebiet). Vertauschte Werte innerhalb eines Kreises bleiben unentdeckt.

    Ablauf: xlsx_datei (Bezug, ggf. Netzabruf in den Cache), xlsx_pruefen (am ZIP, vor openpyxl), Blätter
    ganz einlesen, dann _xlsx_zeilen. Rückgabe: Datensätze mit ("gebiet", …) als Geometrie, `zeit` und
    `leer`. Ausnahmen: QuellenFehler bei unlesbarer oder abgelehnter Datei, unlesbarem Blatt oder
    Zeitbezug; fehlende Blätter und Kopfzeilen halten die Quelle über fehlende_felder an."""
    import openpyxl
    datei = xlsx_datei(cfg, prot)
    xlsx_pruefen(datei, cfg)
    # read_only: Blätter werden gestreamt; data_only: zwischengespeicherte Ergebnisse statt Formeln (eine
    # Formel ohne gespeichertes Ergebnis wird None); keep_links=False: Verknüpfungen zu fremden Mappen werden
    # nicht übernommen
    try:
        wb = openpyxl.load_workbook(datei, read_only=True, data_only=True, keep_links=False)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as e:
        raise QuellenFehler(f"{datei.name}: keine lesbare XLSX-Datei ({e})"[:300]) from None
    try:
        if cfg.get("blaetter"):
            namen = [str(b) for b in cfg["blaetter"]]
            fehlen = [b for b in namen if b not in wb.sheetnames]
        else:
            muster = re.compile(cfg["blatt_muster"])
            namen = [b for b in wb.sheetnames if muster.fullmatch(b)]
            fehlen = [] if namen else [f"nach {cfg['blatt_muster']}"]
        if fehlen:
            prot.info["fehlende_felder"] = [f"Blatt {b}" for b in fehlen]
            prot.warnungen.append(f"Blätter fehlen: {', '.join(fehlen)}; vorhanden "
                                  f"{', '.join(wb.sheetnames)}"[:500])
            return
        # Alle gewählten Blätter ganz in den Speicher: Zeitbezug, Teilsummen und doppelte Schlüssel brauchen
        # alle Blätter zugleich; die Größe begrenzt vorher xlsx_pruefen (max_entpackt_mb)
        blaetter = {}
        for b in namen:
            # Nur-Lese-Modus: Ohne reset_dimensions endet iter_rows an der Größe, die das Blatt von sich
            # angibt (<dimension>); Zeilen und Spalten dahinter fielen still weg
            wb[b].reset_dimensions()
            try:
                blaetter[b] = [list(z) for z in wb[b].iter_rows(values_only=True)]
            except (ValueError, KeyError, TypeError) as e:
                # etwa eine Zahlzelle „NaN“: openpyxl bricht beim Lesen ab; ein Befund der Quelle mit Blatt
                raise QuellenFehler(f"Blatt {b}: nicht lesbar ({type(e).__name__}: {e})"[:300]) from None
    finally:
        wb.close()
    yield from _xlsx_zeilen(cfg, blaetter, prot)


def _xlsx_zeitbezug(feld: str, angabe, blaetter: dict, prot: Protokoll) -> str | None:
    """Zeitbezug eines Felds: None ohne Angabe, ein fester Wert als Text, sonst aus der Datei gesucht.

    Bei {muster, als} wird jede Textzelle aller Blätter (Leerraum zu einem Leerzeichen zusammengezogen)
    durchsucht; die erste Gruppe eines Treffers wird in `als` eingesetzt (Standard "{}") und wie bei CSV
    aus TT.MM.JJJJ ins ISO-Format gebracht. Alle Treffer müssen dasselbe ergeben.
    Ausnahme: QuellenFehler, wenn nichts oder Verschiedenes gefunden wird oder das Ergebnis weder Jahr noch
    Datum ist. Der Parameter prot wird nicht benutzt."""
    if angabe is None or not isinstance(angabe, dict):
        return None if angabe is None else str(angabe)
    muster = re.compile(angabe["muster"])
    gefunden = set()
    for zeilen in blaetter.values():
        for zeile in zeilen:
            for v in zeile:
                if isinstance(v, str) and (m := muster.search(" ".join(v.split()))):
                    gefunden.add(_datum(angabe.get("als", "{}").format(m[1])))
    if len(gefunden) != 1:
        art = f"mehrdeutig: {', '.join(sorted(gefunden))}" if gefunden else "nicht gefunden"
        raise QuellenFehler(f"Zeitbezug für {feld} nach {angabe['muster']} {art}")
    zeit = gefunden.pop()
    if not re.fullmatch(r"\d{4}(-\d{2}-\d{2})?", zeit):
        raise QuellenFehler(f"Zeitbezug für {feld} ist kein Datum oder Jahr: {zeit[:40]!r}")
    return zeit


def _endliche_zahl(v) -> bool:
    """Zahl einer Zelle, endlich: kein Wahrheitswert, nicht unendlich (1E999), nicht NaN."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _xlsx_teilsummen(werte_cfg: dict, zeilen: dict, glieder: dict, toleranz, prot: Protokoll) -> None:
    """summe.teilsummen: Jede gewählte Zeile gehört zur Teilsumme ihres Blatts, deren Gruppe ihr Schlüssel
    beginnt (längster Anfang); deren Summe muss stimmen. Prüft auch die Kreisstelle eines Gemeindeschlüssels:
    Wechselt er in einen anderen Kreis, gehört er zu keiner Teilsumme seines Blatts.

    Parameter: werte_cfg die konfigurierten Felder, zeilen Blatt -> Anfang -> (Ort, Schlüssel, Rohwerte) der
    Teilsummenzeilen, glieder Blatt -> [(Ort, Schlüssel, Werte)] der gewählten Zeilen, toleranz zulässige
    Abweichung. Befunde gehen als Lücke ins Protokoll (nichts wird gelöscht), keine Ausnahme.
    Eine Teilsumme, zu der keine gewählte Zeile gehört, wird nicht geprüft."""
    ohne, abweichung = [], []
    for blatt, liste in glieder.items():
        gruppen = zeilen.get(blatt, {})
        je: dict[str, list] = {}
        for ort, k, werte in liste:
            anfang = max((a for a in gruppen if k.startswith(a)), key=len, default=None)
            if anfang is None:
                ohne.append(f"{ort} ({k})")
            else:
                je.setdefault(anfang, []).append(werte)
        for anfang, alle in je.items():
            ort, k, roh = gruppen[anfang]
            for f in werte_cfg:
                da = [w[f] for w in alle if w[f] is not None]
                # Auf 6 Nachkommastellen gerundet, damit Rundungsreste der Gleitkommasumme nicht als
                # Abweichung zählen. Stimmig ist: Summe innerhalb der Toleranz, oder kein Wert und auch
                # keine Zahl in der Teilsummenzeile (etwa „–“ für den ganzen Kreis)
                soll, ist = roh.get(f), round(sum(da), 6)
                if not (_endliche_zahl(soll) and abs(ist - soll) <= toleranz) \
                        and not (not da and not _endliche_zahl(soll)):
                    abweichung.append(f"{ort} ({k}, {f}): Summe {ist:g}, Zeile {soll!r}")
    if ohne:
        prot.unvollstaendig_melden(f"{len(ohne)} Zeilen gehören zu keiner Teilsumme ihres Blatts ("
                                   + "; ".join(ohne[:10]) + (" …" if len(ohne) > 10 else "")
                                   + "); Schlüssel in fremdem Gebiet? Abruf unvollständig, nichts wird "
                                   "gelöscht")
    if abweichung:
        prot.unvollstaendig_melden(f"{len(abweichung)} Teilsummen weichen ab (Toleranz {toleranz}): "
                                   + "; ".join(abweichung[:10]) + (" …" if len(abweichung) > 10 else "")
                                   + "; Abruf unvollständig, nichts wird gelöscht")


def _xlsx_zeilen(cfg: dict, blaetter: dict[str, list[list]], prot: Protokoll) -> Iterator[dict]:
    """Die eingelesenen Blätter in Datensätze übersetzen; Regeln und Grenzen im Docstring von xlsx.

    Parameter: cfg die Konfiguration der Quelle, blaetter Blattname -> Zeilen (Listen von Zellwerten, wie
    openpyxl sie liefert), prot das Protokoll.
    Ablauf: Zeitbezug je Feld; je Blatt die Kopfzeile suchen (fehlt sie oder ist eine Beschriftung doppelt:
    fehlende_felder, keine Datensätze); dann jede Zeile nach dem Kopf einordnen (stumm übergangen, Lücke
    oder gewählt) und gewählte Zeilen sofort liefern; zum Schluss Lücken melden und Summe und Teilsummen
    prüfen. Weil die Prüfungen erst nach dem letzten Datensatz laufen, gilt ihr Ergebnis erst, wenn der
    Generator ganz abgearbeitet ist (laden tut das, bevor es entscheidet)."""
    werte_cfg = cfg["werte"]
    k_schluessel = kopf_normal(cfg["schluessel"])
    k_werte = {f: kopf_normal(w["kopf"]) for f, w in werte_cfg.items()}
    form = re.compile(cfg.get("schluessel_form", r"^\d+$"))
    auswahl = cfg.get("zeilen_auswahl") or {}
    gebiet_re = re.compile(auswahl.get("schluessel", ".*"))
    ohne = re.compile(auswahl["ohne"]) if auswahl.get("ohne") else None
    ausser = re.compile(auswahl["ohne_ausser"]) if auswahl.get("ohne_ausser") else None
    fehlwerte = set(cfg.get("fehlwerte", XLSX_FEHLWERTE))
    summe = cfg.get("summe")
    zeit = {f: _xlsx_zeitbezug(f, w.get("zeitbezug"), blaetter, prot) for f, w in werte_cfg.items()}
    prot.info["zeitbezug"] = {f: z for f, z in zeit.items() if z}
    prot.info["felder"] = sorted(werte_cfg)
    prot.info["blaetter"] = list(blaetter)

    # Kopf je Blatt: Spalten der Schlüssel und Werte
    spalten = {}
    for name, zeilen in blaetter.items():
        for nr, zeile in enumerate(zeilen[:cfg.get("kopf_bis_zeile", 30)], start=1):
            normal = [kopf_normal(v) for v in zeile]
            if k_schluessel in normal and all(k in normal for k in k_werte.values()):
                doppelt = [w["kopf"] for f, w in werte_cfg.items() if normal.count(k_werte[f]) > 1]
                if doppelt:
                    prot.info["fehlende_felder"] = [f"Blatt {name}: {', '.join(doppelt)} mehrfach"]
                    prot.warnungen.append(f"Blatt {name}, Kopfzeile {nr}: Beschriftung {', '.join(doppelt)} "
                                          "steht mehrfach, Spalte nicht eindeutig; alter Stand bleibt")
                    return
                spalten[name] = (nr, [i for i, k in enumerate(normal) if k == k_schluessel],
                                 {f: normal.index(k) for f, k in k_werte.items()})
                break
        else:
            fehlt = [cfg["schluessel"], *(w["kopf"] for w in werte_cfg.values())]
            prot.info["fehlende_felder"] = [f"Blatt {name}: Kopf mit {'; '.join(fehlt)}"[:300]]
            prot.warnungen.append(f"Blatt {name}: keine Kopfzeile mit {'; '.join(fehlt)} in den ersten "
                                  f"{cfg.get('kopf_bis_zeile', 30)} Zeilen; alter Stand bleibt"[:500])
            return

    ohne_schluessel, verschieden, keine_zahl, doppelt = [], [], [], []
    summen = dict.fromkeys(werte_cfg, 0.0)
    summenzeile = None
    uebergangen = 0
    gesehen: dict[str, str] = {}
    teil_re = re.compile(summe["teilsummen"]) if summe and summe.get("teilsummen") else None
    teil_zeilen: dict[str, dict[str, tuple]] = {}      # Blatt -> Anfang -> (Ort, Schlüssel, roh)
    teil_glieder: dict[str, list[tuple]] = {}           # Blatt -> [(Ort, Schlüssel, Werte)]
    for name, zeilen in blaetter.items():
        kopf_nr, s_spalten, w_spalten = spalten[name]
        for nr, zeile in enumerate(zeilen, start=1):
            if nr <= kopf_nr:
                continue
            # z=zeile bindet die aktuelle Zeile beim Anlegen (sonst späte Bindung an die Schleifenvariable,
            # ruff B023). Eine Zeile kann kürzer sein als der Kopf; fehlende Zellen gelten als leer (None)
            def zelle(i, z=zeile):
                return z[i] if i < len(z) else None
            schluessel = [_zelle_schluessel(zelle(i)) for i in s_spalten]
            roh = {f: zelle(i) for f, i in w_spalten.items()}
            erster = schluessel[0]
            gueltig = erster is not None and bool(form.fullmatch(erster))
            mit_wert = any(v is not None and v != "" for v in roh.values())
            if not gueltig and not mit_wert:
                # Leer-, Titel- und Fußnotenzeilen bleiben stumm. Seit E51 (Befund K2 sinngemäß) nicht mehr,
                # wenn eine Schlüsselspalte etwas in Schlüsselform enthält (12O60005, 1206000) oder einen
                # Wert, der kein Text ist (None aus _zelle_schluessel: Kommazahl, Datum, Wahrheitswert): Das
                # war vermutlich eine Datenzeile, deren Wert fehlt; ohne Meldung wäre ihr bisheriger Wert
                # gelöscht worden, und die Summenprüfung merkt eine Zeile ohne Wert nicht
                if any(s is None or _schluesselartig(s, form) for s in schluessel):
                    ohne_schluessel.append(f"Blatt {name}, Zeile {nr}")
                else:
                    uebergangen += 1
                continue
            ort = f"Blatt {name}, Zeile {nr}"
            if not gueltig:
                ohne_schluessel.append(ort)
                continue
            if any(s != erster for s in schluessel[1:]):
                verschieden.append(ort)
                continue
            # Summen- und Teilsummenzeilen werden vor der Gebietsauswahl erkannt, damit sie auch zählen, wenn
            # die Auswahl sie ausschließt. Steht die Summenzeile in mehreren Blättern, zählt die zuletzt
            # gelesene
            if summe and erster == str(summe["schluessel"]):
                summenzeile = (ort, roh)
            if teil_re and (m := teil_re.fullmatch(erster)):
                teil_zeilen.setdefault(name, {})[m[1]] = (ort, erster, roh)
            if not gebiet_re.fullmatch(erster) or (ohne and ohne.fullmatch(erster)
                                                     and not (ausser and ausser.fullmatch(erster))):
                uebergangen += 1   # gültiger Schlüssel einer anderen Ebene oder eines anderen Gebiets
                continue
            # Doppelter Schlüssel: melden, aber beide Zeilen weitergeben; ziel entscheidet über gleiche und
            # verschiedene Werte (Prüfung nach E48)
            if erster in gesehen:
                doppelt.append(f"{erster} in {gesehen[erster]} und {ort}")
            else:
                gesehen[erster] = ort
            werte = {}
            # Zahl, statistisches Zeichen oder sonst etwas: Text wird nie als Zahl geraten
            for f, v in roh.items():
                if _endliche_zahl(v):
                    werte[f] = v
                    summen[f] += v
                elif v is None or (isinstance(v, str) and v.strip() in fehlwerte):
                    werte[f] = None
                else:
                    werte[f] = None
                    keine_zahl.append(f"{ort} ({f}: {str(v)[:20]!r})")
            teil_glieder.setdefault(name, []).append((ort, erster, werte))
            yield {"objekt_id": erster,
                   "geom": ("gebiet", gebietsschluessel(erster, cfg.get("gebiet") or {})), "werte": werte,
                   "zeit": {f: z for f, z in zeit.items() if z},
                   "leer": all(v is None for v in werte.values())}
    prot.info["uebergangene_zeilen"] = uebergangen

    def liste(orte: list[str]) -> str:
        """Die ersten zehn Fundstellen für die Meldung, „…“, wenn es mehr sind."""
        return "; ".join(orte[:10]) + (" …" if len(orte) > 10 else "")

    if ohne_schluessel:
        prot.unvollstaendig_melden(f"{len(ohne_schluessel)} Datenzeilen ohne gültigen Schlüssel übergangen "
                                   f"({liste(ohne_schluessel)}); Abruf unvollständig, nichts wird gelöscht")
    if verschieden:
        prot.unvollstaendig_melden(f"{len(verschieden)} Datenzeilen mit verschiedenen Schlüsseln in den "
                                   f"Schlüsselspalten übergangen ({liste(verschieden)}); Abruf "
                                   "unvollständig, nichts wird gelöscht")
    if doppelt:
        prot.unvollstaendig_melden(f"{len(doppelt)} Schlüssel mehrfach geliefert ({liste(doppelt)}); ein "
                                   "Schlüssel kann einen anderen überdecken, Abruf unvollständig, nichts "
                                   "wird gelöscht")
    if keine_zahl:
        prot.unvollstaendig_melden(f"{len(keine_zahl)} Werte sind keine Zahl und wurden nicht übernommen "
                                   f"({liste(keine_zahl)}); Abruf unvollständig, nichts wird gelöscht")
    if teil_re:
        _xlsx_teilsummen(werte_cfg, teil_zeilen, teil_glieder, summe.get("toleranz", 0), prot)
    if summe:
        if summenzeile is None:
            prot.unvollstaendig_melden(f"Summenzeile {summe['schluessel']} fehlt, Vollständigkeit nicht "
                                       "belegt; nichts wird gelöscht")
            return
        ort, roh = summenzeile
        for f, soll in roh.items():
            ist = round(summen[f], 6)
            # NaN > Toleranz ist falsch: nicht endliche Summen oder Summenzeilen zählen ausdrücklich als
            # Abweichung (Prüfung nach E48)
            if not _endliche_zahl(soll) or not math.isfinite(ist) \
                    or abs(ist - soll) > summe.get("toleranz", 0):
                prot.unvollstaendig_melden(
                    f"Summe {f} der gewählten Zeilen {ist:g} weicht von der Summenzeile "
                    f"{summe['schluessel']} ({ort}: {soll!r}) ab (Toleranz {summe.get('toleranz', 0)}); "
                    "Abruf unvollständig, nichts wird gelöscht")


# --- OGC API - Features ------------------------------------------------------------------

def ogcapi(cfg: dict, prot: Protokoll) -> Iterator[dict]:
    """OGC API - Features (Nachfolger von WFS): GeoJSON, Seiten über den Link rel=next.

    url ist die Collection, z. B. https://ogc-api.geobasis-bb.de/datasets/vg/collections/gem.
    Geometrien kommen in CRS84 (Länge/Breite, entspricht EPSG:4326). Folge-Links werden nur
    verfolgt, wenn sie auf denselben Rechner zeigen; sonst bricht die Quelle ab.

    Konfiguration: url, id_feld; optional felder (Eigenschaft -> Feldname; ohne: alle einfachen
    Eigenschaften), seitengroesse (Standard 500), bbox in Länge/Breite.
    Rückgabe: Datensätze mit ("geojson", …) als Geometrie, je Objekt-ID einmal.
    Seiteneffekte: Netzabrufe (Startseite des Datensatzes, queryables, items und Folgeseiten); Kontakt,
    Titel, Lizenz laut Dienst, Feldliste und Lücken im Protokoll. Die Startseite und queryables dürfen
    fehlen (Warnung bzw. Hinweis); Fehler bei items und Folgeseiten brechen die Quelle ab.
    Vollständigkeit: Bringt eine Seite kein neues Objekt oder zeigt `next` auf einen schon abgerufenen Link,
    endet der Abruf als unvollständig (E47); ebenso, wenn numberMatched nicht zur Zahl der Objekte passt."""
    url = cfg["url"].rstrip("/")
    # Rechner, den requests anwählt (Nachprüfung zu E50); eine abgelehnte Adresse bricht die Quelle hier ab
    host = rechner_wie_gesendet(url)
    id_feld = cfg["id_feld"]
    felder = cfg.get("felder")

    def hole(adresse: str, params: dict | None = None) -> dict:
        """JSON von `adresse` holen, nur auf dem Rechner der Collection. Verglichen wird der Rechner, den
        requests anwählt (rechner_wie_gesendet); Schema, robots-Sperre, Weiterleitung und Größe prüft abrufen.

        Pre-existing seit E47, behoben in der Nachprüfung zu E50: Verglichen wurde der Rechner nach urlsplit.
        Ein rel=next `https://fremd.example\\@ogc.example/…` bestand die Prüfung (urlsplit: ogc.example),
        requests verband aber zu fremd.example.
        Ausnahmen: QuellenFehler bei fremdem Rechner oder einer abgelehnten Adresse (Anmeldedaten, Rückstrich
        vor dem Rechner), ValueError bei ungültigem JSON oder unlesbarer Adresse, Netzfehler aus abrufen."""
        try:
            rechner = rechner_wie_gesendet(adresse)
        except QuellenFehler as e:
            raise QuellenFehler(f"Folge-Link nicht verfolgt, Rechner nicht eindeutig: {e}") from None
        if rechner != host:
            raise QuellenFehler(f"Folge-Link zeigt auf einen anderen Rechner: {adresse[:120]}")
        return json.loads(abrufen(adresse, params, cfg, prot))

    # Die Startseite des Datensatzes nennt Kontakt und Lizenz, wie beim WFS die Capabilities
    if "/collections/" in url:
        try:
            start = hole(url.split("/collections/")[0], {"f": "json"})
            kontakt = start.get("contact") or {}
            prot.info["kontakt"] = {"anbieter": kontakt.get("name"), "email": kontakt.get("email")}
            if start.get("title"):
                prot.info["titel"] = start["title"]
            if start.get("description"):
                prot.info["beschreibung"] = start["description"]
            lizenz = next((lk.get("title") for lk in start.get("links", []) if lk.get("rel") == "license"),
                          None)
            if lizenz:
                prot.info["lizenz_laut_dienst"] = lizenz
        except (requests.RequestException, ValueError, QuellenFehler) as e:
            prot.warnungen.append(f"Startseite des Dienstes nicht lesbar: {e}"[:300])

    try:
        queryables = hole(f"{url}/queryables", {"f": "json"})
        prot.info["felder"] = sorted(queryables.get("properties", {}))
    except requests.HTTPError as e:
        # queryables ist im Standard optional; dann kommt die Feldliste aus den Objekten
        if e.response is not None and e.response.status_code == 404:
            prot.hinweise.append("Dienst bietet keine Feldliste (queryables), Felder aus den Objekten")
        else:
            prot.warnungen.append(f"Feldliste nicht lesbar (queryables): {e}"[:300])
        queryables = None
    except (requests.RequestException, ValueError, QuellenFehler) as e:
        prot.warnungen.append(f"Feldliste nicht lesbar (queryables): {e}"[:300])
        queryables = None

    params = {"f": "json", "limit": cfg.get("seitengroesse", 500)}
    if cfg.get("bbox"):
        params["bbox"] = ",".join(map(str, cfg["bbox"]))  # in CRS84, Länge/Breite
    seite = hole(f"{url}/items", params)
    gesehen: set[str] = set()
    besucht: set[str] = set()   # abgerufene Folge-Links (Prüfbericht 05.11. abends, Befund 6, E47)
    erste = True
    while True:
        feats = seite.get("features", [])
        if erste:
            if queryables is None:
                prot.info["felder"] = sorted({k for f in feats for k in (f.get("properties") or {})})
            felder_pruefen(prot.info["felder"], [id_feld, *(felder or {})], prot)
            prot.info["anzahl_laut_dienst"] = seite.get("numberMatched")
            erste = False
        bisher = len(gesehen)
        for f in feats:
            props = f.get("properties") or {}
            oid = str(props.get(id_feld) or "").strip()
            if not oid or not f.get("geometry"):
                prot.unvollstaendig_melden("Objekt ohne ID oder Geometrie übersprungen")
                continue
            if oid in gesehen:
                continue
            gesehen.add(oid)
            # Nur einfache Eigenschaften (Text, Zahl, Wahrheitswert, null); Objekte und Listen bleiben weg
            werte = {(felder or {}).get(k, k): v for k, v in props.items()
                     if (felder is None or k in felder) and not isinstance(v, (dict, list))}
            yield {"objekt_id": oid, "geom": ("geojson", json.dumps(f["geometry"])), "werte": werte}
        weiter = next((lk["href"] for lk in seite.get("links", []) if lk.get("rel") == "next"), None)
        if not weiter or not feats:
            break
        # Ohne diese Prüfung lief ein zyklischer next-Verweis mit nicht leerer Seite endlos und hielt den
        # ganzen Lauf auf. Wie beim WFS (F5, E46): Abruf als unvollständig beenden, nichts wird gelöscht,
        # die übrigen Quellen laufen weiter
        if len(gesehen) == bisher:
            prot.unvollstaendig_melden(f"Seite vor {weiter[:120]} brachte kein neues Objekt, Abruf beendet "
                                       "(Folge-Links ohne Fortschritt)")
            break
        if weiter in besucht:
            prot.unvollstaendig_melden(f"Folge-Link {weiter[:120]} schon abgerufen (Zyklus), Abruf beendet")
            break
        besucht.add(weiter)
        seite = hole(weiter)
    gemeldet = prot.info.get("anzahl_laut_dienst")
    if isinstance(gemeldet, int) and gemeldet != len(gesehen):
        prot.unvollstaendig_melden(f"Dienst meldet {gemeldet} Objekte, gelesen wurden {len(gesehen)}")


# --- GeoJSON-Datei (z. B. Eurostat GISCO) -------------------------------------------------

# Koordinaten in Länge/Breite, wie GeoJSON (RFC 7946) sie vorschreibt; ein anderes Koordinatensystem im
# Mitglied "crs" lehnt der Adapter ab, vor oder nach dem Array "features" und in jedem Objekt
# (geojson_objekte, _geojson_crs_pruefen; nach dem Array und je Objekt seit E50)
GEOJSON_CRS = {"urn:ogc:def:crs:OGC:1.3:CRS84", "urn:ogc:def:crs:OGC::CRS84",
               "urn:ogc:def:crs:EPSG::4326", "EPSG:4326"}
_GEOJSON_KOPF = re.compile(r'"features"\s*:\s*\[')
_GEOJSON_CRS = re.compile(r'"crs"\s*:\s*\{.*?"name"\s*:\s*"([^"]+)"', re.S)
# Zwischen zwei Objekten des Arrays: Leerraum und Komma
_GEOJSON_TRENNER = re.compile(r"[\s,]*")


def _geojson_crs_pruefen(crs, wo: str) -> None:
    """Ein Mitglied "crs" (GeoJSON 2008; RFC 7946 kennt es nicht mehr) prüfen: nur {"type": "name",
    "properties": {"name": …}} mit einem Namen aus GEOJSON_CRS ist erlaubt, alles andere (fremdes System, Typ
    link, kein Objekt) wird abgelehnt. None heißt „nicht angegeben“ und gilt als Länge/Breite.
    Ausnahme: QuellenFehler mit dem gefundenen Namen und dem Ort (`wo`)."""
    if crs is None:
        return
    name = ((crs.get("properties") or {}).get("name") if isinstance(crs, dict)
            and isinstance(crs.get("properties"), dict) and crs.get("type") == "name" else None)
    if name not in GEOJSON_CRS:
        raise QuellenFehler(f"GeoJSON in {name or json.dumps(crs)[:80]} ({wo}, crs), erwartet Länge/Breite "
                            "(EPSG:4326 bzw. CRS84)")


def geojson_objekte(pfad: Path, max_objekt_bytes: int, block: int = 1 << 20) -> Iterator[dict]:
    """Die Objekte des Arrays `features` einer FeatureCollection, eins nach dem anderen.

    Die Datei wird in Blöcken gelesen und jedes Objekt einzeln dekodiert, damit eine Datei von
    150 MB nicht als Ganzes in den Speicher muss (json.load bräuchte ein Vielfaches). Ein Objekt,
    das über max_objekt_bytes hinaus nicht vollständig ist, gilt als zu groß oder fehlerhaft.

    Parameter: pfad der Datei (UTF-8), max_objekt_bytes Obergrenze je Objekt (auch für Kopf und Rest nach dem
    Array), block Lesegröße. Gezählt wird in Zeichen des dekodierten Texts, nicht in Bytes; bei
    Mehrbyte-Zeichen liegt die Grenze in Bytes also höher (höchstens das Vierfache). Koordinatensystem
    ("crs"): im Kopf vor dem Array, in jedem Objekt und seiner Geometrie und im Rest der Sammlung nach dem
    Array (die beiden letzten seit E50; JSON legt die Reihenfolge der Mitglieder nicht fest, bis dahin las der
    Adapter eine Datei mit "crs" nach "features" als Länge/Breite, in E49 benannt, E50 behoben). Ein fremdes
    System nach dem Array fällt erst am Ende auf: Die schon gelieferten Objekte stehen dann nur in der
    Transaktion der Quelle, die mit der Ausnahme zurückgerollt wird.
    Ausnahme: QuellenFehler ohne Array `features`, bei fremdem oder unlesbarem Koordinatensystem, zu großem
    oder kaputtem Objekt, Eintrag, der kein Objekt ist, oder Dateiende mitten im Objekt."""
    dec = json.JSONDecoder()
    with open(pfad, encoding="utf-8") as f:
        puffer = ""
        # Kopf bis zum Beginn des Arrays lesen; auch der Kopf ist durch max_objekt_bytes begrenzt
        while not (m := _GEOJSON_KOPF.search(puffer)):
            stueck = f.read(block)
            if not stueck or len(puffer) > max_objekt_bytes:
                raise QuellenFehler("Keine FeatureCollection: Array 'features' nicht gefunden")
            puffer += stueck
        # Kopf als JSON lesen ({"type": …, "crs": …, ohne das Array): genau. Gelingt das nicht (ungewöhnlicher
        # Kopf), bleibt die Suche per Muster wie bis E50
        try:
            kopf = json.loads(puffer[:m.start()].rstrip().rstrip(",") + "}")
            _geojson_crs_pruefen(kopf.get("crs") if isinstance(kopf, dict) else None, "vor den Objekten")
        except json.JSONDecodeError:
            crs = _GEOJSON_CRS.search(puffer, 0, m.start())
            if crs and crs[1] not in GEOJSON_CRS:
                raise QuellenFehler(f"GeoJSON in {crs[1]}, erwartet Länge/Breite (EPSG:4326 bzw. "
                                    "CRS84)") from None
        # Ab hier beginnt der Puffer im Array; ungelesen ist puffer[pos:]. Schon gelieferte Objekte fallen
        # erst beim Nachlesen vorn weg, so bleibt der Speicher bei etwa Block plus Objekt
        puffer, pos, ende = puffer[m.end():], 0, False
        while True:
            pos = _GEOJSON_TRENNER.match(puffer, pos).end()
            if pos < len(puffer) and puffer[pos] == "]":
                _geojson_rest_pruefen(puffer[pos + 1:], f, block, max_objekt_bytes)
                return
            try:
                if pos == len(puffer):
                    raise json.JSONDecodeError("Puffer leer", puffer, pos)
                obj, pos = dec.raw_decode(puffer, pos)
            except json.JSONDecodeError:
                # Meist liegt das Objekt nur zum Teil im Puffer: nachlesen
                if ende:
                    raise QuellenFehler("GeoJSON endet mitten in einem Objekt oder ist fehlerhaft") from None
                if len(puffer) - pos > max_objekt_bytes:
                    raise QuellenFehler(f"Objekt größer als {max_objekt_bytes // (1024 * 1024)} MB "
                                        "oder fehlerhaftes JSON (max_objekt_mb)") from None
                stueck = f.read(block)
                ende = not stueck
                puffer, pos = puffer[pos:] + stueck, 0
                continue
            if not isinstance(obj, dict):
                raise QuellenFehler("Eintrag im Array 'features' ist kein Objekt")
            # "crs" je Objekt und je Geometrie (GeoJSON 2008 erlaubte beides; E50)
            _geojson_crs_pruefen(obj.get("crs"), "im Objekt")
            if isinstance(obj.get("geometry"), dict):
                _geojson_crs_pruefen(obj["geometry"].get("crs"), "in der Geometrie")
            yield obj


def _geojson_rest_pruefen(rest: str, f, block: int, max_bytes: int) -> None:
    """Rest der FeatureCollection nach dem Array `features` (E50): bis zum Dateiende lesen (höchstens
    max_bytes Zeichen), als Mitglieder eines Objekts lesen und ein "crs" dort prüfen. Ist der Rest leer oder
    nur „}“, gibt es nichts zu prüfen. Ausnahme: QuellenFehler bei zu großem oder unlesbarem Rest und bei
    fremdem Koordinatensystem (_geojson_crs_pruefen)."""
    while stueck := f.read(block):
        rest += stueck
        if len(rest) > max_bytes:
            raise QuellenFehler("GeoJSON: Rest der Sammlung nach dem Array 'features' zu groß "
                                "(max_objekt_mb)")
    rest = rest.strip()
    if rest in ("", "}"):
        return
    try:
        # Aus „, "crs": {…}, "name": "x"}“ wird „{"crs": {…}, "name": "x"}“
        mitglieder = json.loads("{" + rest.lstrip(",")) if rest.startswith(",") else None
    except json.JSONDecodeError:
        mitglieder = None
    if not isinstance(mitglieder, dict):
        raise QuellenFehler("GeoJSON: Rest der Sammlung nach dem Array 'features' nicht lesbar")
    _geojson_crs_pruefen(mitglieder.get("crs"), "nach den Objekten")


def geojson(cfg: dict, prot: Protokoll) -> Iterator[dict]:
    """GeoJSON-Datei (FeatureCollection) per URL, z. B. die Gemeindegrenzen (LAU) von Eurostat
    GISCO. Wie bei INKAR auf die Platte gestreamt und nur bei Änderung neu geladen
    (If-Modified-Since), dann Objekt für Objekt gelesen. Koordinaten in Länge/Breite (EPSG:4326).

    id_feld     Eigenschaft mit der Objekt-ID
    felder      Eigenschaft -> Feldname (ohne: alle einfachen Eigenschaften)
    max_mb      Größe der Datei, max_objekt_mb Größe eines Objekts (Standard 50)

    Rückgabe: Datensätze mit ("geojson", …) als Geometrie. Seiteneffekte: Netzabruf und Schreiben in den
    Cache (datei_abrufen), Dateiname und Stand im Protokoll. Fehlt ein konfiguriertes Feld im ersten Objekt,
    endet der Adapter ohne Datensätze (fehlende_felder, die Quelle wird angehalten)."""
    url = cfg["url"]
    datei = cache_datei(url, ("geojson", "json"), cfg)   # Name geprüft vor dem Abruf (E50)
    datei_abrufen(url, datei, cfg, prot)
    # Stand = Änderungszeit der Datei; datei_abrufen setzt sie auf Last-Modified des Servers, wenn er es nennt
    prot.info["datei"] = {"name": datei.name, "stand": datetime.fromtimestamp(
        datei.stat().st_mtime, UTC).strftime("%Y-%m-%d")}
    id_feld = cfg["id_feld"]
    felder = cfg.get("felder")
    gesehen: set[str] = set()
    doppelt = 0
    erste = True
    for f in geojson_objekte(datei, int(cfg.get("max_objekt_mb", 50) * 1024 * 1024)):
        prot.zeit_pruefen()   # Zeitbudget je Objekt (E50); das Lesen einer großen Datei zählt mit
        props = f.get("properties") or {}
        if erste:
            # Feldliste aus dem ersten Objekt, wie beim OGC-API-Dienst ohne queryables
            prot.info["felder"] = sorted(props)
            felder_pruefen(prot.info["felder"], [id_feld, *(felder or {})], prot)
            if prot.info.get("fehlende_felder"):
                return
            erste = False
        oid = str(props.get(id_feld) or "").strip()
        if not oid or not f.get("geometry"):
            prot.unvollstaendig_melden("Objekt ohne ID oder Geometrie übersprungen")
            continue
        if oid in gesehen:
            doppelt += 1
        gesehen.add(oid)
        werte = {(felder or {}).get(k, k): v for k, v in props.items()
                 if (felder is None or k in felder) and not isinstance(v, (dict, list))}
        yield {"objekt_id": oid, "geom": ("geojson", json.dumps(f["geometry"])), "werte": werte}
    if doppelt:
        # Kein „das erste zählt“ (E40): Das Zielschreiben übernimmt gleiche Objekte einmal und lässt
        # IDs mit verschiedenem Inhalt aus (bisheriger Stand bleibt, Warnung)
        prot.hinweise.append(f"{doppelt} Objekte mit schon gelesener ID weitergegeben, Abgleich im Ziel")


# --- Große Dateien: Abruf auf die Platte, ZIP sicher lesen ---------------------------------

def neueste_url(muster: str, cfg: dict, prot: Protokoll, jahre: int = 6) -> str:
    """Für Dateien mit Jahr im Namen (inkar_{jahr}.zip): das jüngste vorhandene Jahr finden.

    Fragt per HEAD absteigend vom nächsten Jahr an `jahre` Jahre ab (Standard: nächstes Jahr bis vier Jahre
    zurück) und nimmt das erste mit Status 200; Weiterleitungen zählen nicht. Vor jeder HEAD-Abfrage
    schema_pruefen (E41, robots-Sperre E48, Freigabe E50) und das Zeitbudget (E50).
    Rückgabe: die Adresse. Ausnahme: QuellenFehler, wenn kein Jahr passt. Seiteneffekt: bis zu `jahre`
    Netzabrufe; Dateiname als Hinweis im Protokoll."""
    jahr = datetime.now(UTC).year + 1
    for j in range(jahr, jahr - jahre, -1):
        kandidat = muster.format(jahr=j)
        prot.zeit_pruefen()
        schema_pruefen(kandidat, cfg, prot)
        r = requests.head(kandidat, timeout=HTTP_TIMEOUT, allow_redirects=False,
                          headers={"User-Agent": kennung()})
        if r.status_code == 200:
            prot.hinweise.append(f"Neueste Datei: {kandidat.rsplit('/', 1)[-1]}")
            return kandidat
    raise QuellenFehler(f"Keine Datei nach Muster {muster} in den letzten {jahre} Jahren gefunden")


def datei_abrufen(url: str, ziel: Path, cfg: dict, prot: Protokoll) -> bool:
    """Große Datei auf die Platte streamen statt in den Speicher. Liegt sie schon vor, fragt
    die Pipeline mit If-Modified-Since nach und lädt nur bei Änderung neu. Gibt zurück, ob neu
    geladen wurde. Dieselben Regeln wie abrufen(): https, keine Weiterleitung, Größenlimit.

    Parameter: url, ziel (Pfad im Cache), cfg mit `max_mb`, prot. Geschrieben wird erst in `<ziel>.teil`
    und erst nach vollständigem Abruf über die alte Datei gelegt (replace). Bricht das Schreiben mit einer
    Ausnahme ab (auch ZeitbudgetUeberschritten je Block, E50), wird die Teildatei entfernt und die alte Datei
    bleibt unberührt. Ausnahmen wie abrufen. Ein unlesbares Last-Modified ist seit E50 nur ein Hinweis (bis
    dahin ValueError, als die neue Datei schon an ihrem Platz lag); die Änderungszeit ist dann die Abrufzeit.
    Seiteneffekte: Netzabruf, Schreiben im Cache, Änderungszeit der Datei = Last-Modified des Servers."""
    prot.zeit_pruefen()
    schema_pruefen(url, cfg, prot)
    max_bytes = int(cfg.get("max_mb", MAX_MB_STANDARD) * 1024 * 1024)
    kopf = {"User-Agent": kennung()}
    if ziel.exists():
        kopf["If-Modified-Since"] = email.utils.formatdate(ziel.stat().st_mtime, usegmt=True)
    prot.letzte_abfrage = url
    ziel.parent.mkdir(parents=True, exist_ok=True)
    teil = ziel.with_name(ziel.name + ".teil")
    with requests.get(url, timeout=HTTP_TIMEOUT, stream=True, allow_redirects=False,
                      headers=kopf) as r:
        if r.status_code == 304:
            prot.hinweise.append(f"Datei unverändert seit dem letzten Abruf: {ziel.name}")
            return False
        if r.is_redirect:
            raise QuellenFehler(f"Dienst leitet weiter auf {r.headers.get('Location', '?')}; "
                                "Weiterleitungen werden nicht verfolgt, URL in der Konfiguration prüfen")
        r.raise_for_status()
        if int(r.headers.get("Content-Length") or 0) > max_bytes:
            raise QuellenFehler(f"Datei größer als {cfg.get('max_mb', MAX_MB_STANDARD)} MB (max_mb)")
        n = 0
        # BaseException: auch bei KeyboardInterrupt oder SystemExit die Teildatei entfernen
        try:
            with open(teil, "wb") as f:
                for stueck in r.iter_content(1 << 20):
                    n += len(stueck)
                    if n > max_bytes:
                        raise QuellenFehler(f"Datei größer als {cfg.get('max_mb', MAX_MB_STANDARD)} MB")
                    f.write(stueck)
                    prot.zeit_pruefen()
        except BaseException:
            teil.unlink(missing_ok=True)
            raise
        stand = r.headers.get("Last-Modified")
    # replace ist auf demselben Dateisystem atomar: Leser sehen die alte oder die neue Datei, nie eine halbe
    teil.replace(ziel)
    if stand:  # Stand des Servers merken, damit If-Modified-Since beim nächsten Lauf passt
        try:
            zeit = email.utils.parsedate_to_datetime(stand)
            # Ohne Zeitzone (etwa „-0000“) gilt die Angabe als UTC, wie HTTP-Daten es immer sind
            t = (zeit if zeit.tzinfo else zeit.replace(tzinfo=UTC)).timestamp()
            os.utime(ziel, (t, t))
        except (TypeError, ValueError, IndexError, OverflowError, OSError):
            # Bis E50 brach die Quelle hier ab, obwohl die Datei vollständig war (in E49 benannt, E50 behoben)
            prot.hinweise.append(f"Last-Modified des Servers unlesbar ({stand[:40]!r}); Änderungszeit der "
                                 f"Datei {ziel.name} ist die Abrufzeit")
    prot.hinweise.append(f"Datei neu geladen: {ziel.name} ({n / 1e6:.0f} MB)")
    return True


def zip_zeilen(pfad: Path, eintrag: str | None, cfg: dict, prot: Protokoll) -> Iterator[str]:
    """Liest genau einen Eintrag eines ZIP als Textzeilen, ohne ihn auf die Platte zu entpacken.

    Vor dem Lesen: Eintrag muss existieren, entpackte Größe unter max_entpackt_mb, Packrate unter
    max_packrate (ZIP-Bombe). Beim Lesen wird mitgezählt und abgebrochen, wenn mehr kommt als
    angekündigt. Deflate64 (INKAR) kann Pythons zipfile nicht; dann liest unzip aus Debian.

    Parameter: pfad des ZIP, eintrag (None: die einzige .csv im ZIP), cfg mit optional max_entpackt_mb
    (Standard 10 000), max_packrate (Standard 100) und encoding (Standard utf-8), prot.
    Generator: liefert Zeilen samt Zeilenende. Ausnahmen: QuellenFehler bei fehlendem oder mehrdeutigem
    Eintrag, Grenzüberschreitung, fehlendem unzip oder Rückgabewert von unzip ungleich 0.
    Seiteneffekt: startet bei Deflate64 einen unzip-Prozess, der beim Abbruch beendet wird."""
    with zipfile.ZipFile(pfad) as z:
        if eintrag is None:
            kandidaten = [i.filename for i in z.infolist() if i.filename.lower().endswith(".csv")]
            if len(kandidaten) != 1:
                raise QuellenFehler(f"ZIP enthält {len(kandidaten)} CSV-Dateien, 'eintrag' angeben")
            eintrag = kandidaten[0]
        try:
            info = z.getinfo(eintrag)
        except KeyError:
            raise QuellenFehler(f"Eintrag '{eintrag}' fehlt im ZIP") from None
        max_entpackt = int(cfg.get("max_entpackt_mb", 10_000) * 1024 * 1024)
        if info.file_size > max_entpackt:
            raise QuellenFehler(f"Eintrag entpackt {info.file_size / 1e6:.0f} MB, "
                                f"erlaubt {cfg.get('max_entpackt_mb', 10_000)} MB (max_entpackt_mb)")
        rate = info.file_size / max(info.compress_size, 1)
        if rate > cfg.get("max_packrate", 100):
            raise QuellenFehler(f"Packrate {rate:.0f}:1 ungewöhnlich hoch (ZIP-Bombe?), max_packrate")
        prot.info["eintrag"] = {"name": eintrag, "mb": round(info.file_size / 1e6)}
        grenze = info.file_size
        encoding = cfg.get("encoding", "utf-8")
        # Verfahren, die zipfile selbst kann; alles andere (Deflate64) geht nach dem Schließen an unzip
        if info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2,
                                  zipfile.ZIP_LZMA):
            with z.open(info) as roh:
                yield from _gezaehlt(roh, grenze, encoding)
            return
    unzip = shutil.which("unzip")
    if not unzip:
        raise QuellenFehler("ZIP nutzt ein Verfahren, das nur unzip kann (z. B. Deflate64); unzip fehlt")
    # Feste Argumentliste, keine Shell; Pfad und Eintrag stammen aus Konfiguration bzw. ZIP-Verzeichnis
    # Fehlerausgabe in eine Datei statt in eine Pipe: so kann unzip nicht an einem vollen Puffer hängen
    with tempfile.TemporaryFile() as fehler_datei:
        proc = subprocess.Popen([unzip, "-p", "--", str(pfad), eintrag],  # noqa: S603  # nosec B603
                                stdout=subprocess.PIPE, stderr=fehler_datei)
        fertig = False
        # Hört der Leser vorzeitig auf (Fehler, Grenze, Generator geschlossen), wird unzip beendet, statt im
        # Hintergrund weiterzulaufen
        try:
            yield from _gezaehlt(proc.stdout, grenze, encoding)
            fertig = True
        finally:
            proc.stdout.close()
            if not fertig:
                proc.kill()
            code = proc.wait()
        fehler_datei.seek(0)
        meldung = fehler_datei.read(500).decode("utf-8", "replace").strip()
    # Ein kaputtes Archiv endet sonst wie ein vollständiges: unzip bricht ab, der Strom ist nur kürzer
    if code != 0:
        raise QuellenFehler(f"unzip endete mit Rückgabewert {code}: {meldung or 'ohne Meldung'}"[:300])


def _gezaehlt(roh, grenze: int, encoding: str) -> Iterator[str]:
    """Binärstrom `roh` als Textzeilen lesen und abbrechen, sobald mehr als `grenze` Zeichen kamen.

    newline="": Zeilenenden bleiben unverändert in der Zeile (csv.reader kommt damit zurecht). Gezählt wird
    in Zeichen, nicht in Bytes; bei Mehrbyte-Zeichen kann der Strom die Grenze in Bytes überschreiten (bei
    UTF-8 höchstens um das Vierfache). Ausnahme: QuellenFehler bei Überschreitung, UnicodeDecodeError bei
    falscher Kodierung."""
    gelesen = 0
    for zeile in io.TextIOWrapper(roh, encoding=encoding, newline=""):
        gelesen += len(zeile)  # Zeichen, nicht Bytes: reicht als Schranke gegen Endlos-Ströme
        if gelesen > grenze:
            raise QuellenFehler("ZIP-Eintrag liefert mehr Daten als angekündigt, abgebrochen")
        yield zeile


# --- INKAR (BBSR) --------------------------------------------------------------------------

# Spalten, die die INKAR-CSV haben muss; fehlt eine, hält felder_pruefen die Quelle an (E15)
INKAR_SPALTEN = ["Kuerzel", "Indikator", "Raumbezug", "Kennziffer", "Name", "Zeitbezug", "Wert"]
# Fachlicher Schlüssel einer INKAR-Zeile (Antwort 31 der TH), in der Konfiguration änderbar
INKAR_SCHLUESSEL = ["Kennziffer", "Bereich", "Kuerzel", "Indikator", "Zeitbezug"]


# Schreibweise einer Zahl in INKAR und Statistiktabellen: Vorzeichen, Ziffern mit Dezimalkomma oder -punkt,
# optional Exponent; nur ASCII-Ziffern (E50)
_ZAHL = re.compile(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?", re.ASCII)


def _zahl(text: str, prot: Protokoll | None = None) -> float | None:
    """INKAR schreibt Dezimalkomma ohne Tausenderpunkte (184290,00); leer = kein Wert. Was keine
    Zahl ist, wird leer übernommen und gezählt; die Warnung schreibt zahlen_bilanz().

    Auch der CSV-Adapter nutzt diese Funktion (zahl_felder, Leerzeichen vorher entfernt). Als Zahl gilt nur
    die Schreibweise _ZAHL mit endlichem Ergebnis. Bis E50 galt alles, was float() annimmt; damit waren nan,
    inf, 1E999 (unendlich), 1_000 und Ziffern anderer Schriften Zahlen (in E49 benannt, E50 behoben). Am
    echten INKAR-Bestand der Ausgabe 2025 ändert die engere Regel keinen Wert (alle 63 426 864 Werte
    nachgeprüft, E50).
    Rückgabe: float oder None. Seiteneffekt: zählt in prot.info["zahlen_unlesbar"] (höchstens fünf
    Beispiele)."""
    roh = text.strip()
    if not roh:
        return None
    try:
        if not _ZAHL.fullmatch(roh):
            raise ValueError(roh)
        wert = float(roh.replace(",", "."))
        if not math.isfinite(wert):
            raise ValueError(roh)
        return wert
    except ValueError:
        if prot is not None:
            u = prot.info.setdefault("zahlen_unlesbar", {"anzahl": 0, "beispiele": []})
            u["anzahl"] += 1
            if len(u["beispiele"]) < 5 and text.strip() not in u["beispiele"]:
                u["beispiele"].append(text.strip()[:20])
        return None


def zahlen_bilanz(prot: Protokoll) -> None:
    """Am Ende einer Quelle: unlesbare Zahlen und zu kurze Zeilen als Warnung bzw. Lücke melden."""
    u = prot.info.get("zahlen_unlesbar")
    if u:
        prot.warnungen.append(f"{u['anzahl']} Werte sind keine Zahl und wurden leer übernommen "
                              f"(z. B. {', '.join(repr(b) for b in u['beispiele'])})")
    kurz = prot.info.get("zeilen_zu_kurz")
    if kurz:
        prot.unvollstaendig_melden(f"{kurz} Zeilen mit zu wenigen Spalten oder ohne lesbaren Zeitbezug "
                                   "übersprungen")


def inkar(cfg: dict, prot: Protokoll) -> Iterator[dict]:
    """INKAR-Adapter mit Bilanz am Ende (unlesbare Zahlen und Zeilen). Konfiguration und Verhalten
    siehe _inkar_lesen; zahlen_bilanz und _inkar_bilanz laufen erst, wenn alle Datensätze abgeholt sind."""
    yield from _inkar_lesen(cfg, prot)
    zahlen_bilanz(prot)
    _inkar_bilanz(prot)


def _inkar_zeitbezug(cfg: dict, lang: bool) -> str | int:
    """`zeitbezug` einer INKAR-Quelle geprüft: `neuester` (Standard), in der Langform auch `alle`, sonst eine
    Jahreszahl (Zahl oder Ziffernfolge). Rückgabe: der Text oder das Jahr als int. Ausnahme: QuellenFehler mit
    den erlaubten Werten (bis E50 endete ein falscher Wert der breiten Form als ValueError aus int(), mitten
    im Lesen; in E49 benannt, E50 behoben)."""
    wert = cfg.get("zeitbezug", "neuester")
    erlaubt = ("neuester", "alle") if lang else ("neuester",)
    if wert in erlaubt:
        return wert
    if isinstance(wert, int) and not isinstance(wert, bool):
        return wert
    if isinstance(wert, str) and wert.isascii() and wert.isdigit():
        return int(wert)
    raise QuellenFehler(f"zeitbezug {str(wert)[:40]!r} nicht erlaubt; {' oder '.join(erlaubt)} oder eine "
                        f"Jahreszahl{'' if lang else ' (alle gibt es nur mit form: lang)'}")


def _inkar_lesen(cfg: dict, prot: Protokoll) -> Iterator[dict]:
    """INKAR-Gesamtdatei des BBSR: ZIP mit einer CSV im Langformat (eine Zeile je Indikator,
    Gebiet und Jahr, entpackt rund 6,8 GB). Gefiltert nach Raumbezug, Kennziffer-Anfang und
    Indikatoren; je Gebiet entsteht ein Objekt mit den Indikatoren als Werten. Die Geometrie
    kommt über die Kennziffer aus einer vorher geladenen Quelle (Abschnitt `gebiet`).

    Mit `form: lang` entsteht wie im Import der TH eine Zeile je Indikator, Gebiet und Jahr
    (Ziel dashboard_data_de). Objekt-ID ist dann der fachliche Schlüssel aus `schluessel`
    (Standard Kennziffer, Bereich, Kürzel, Indikator, Zeitbezug); die Werte heißen wie die
    Spalten der CSV, klein geschrieben (kennziffer, indikator, zeitbezug, wert, …). `indikatoren`
    ist dann eine Liste von Kürzeln oder `alle`, `zeitbezug` ist `alle`, `neuester` oder ein Jahr.

    Vorbild ist der INKAR-Import im Repository MOSIDI der TH (Download der neuesten Jahresdatei,
    Formatprüfung, Import); dieser Adapter ist eigenständig geschrieben.

    Bezug (E50, Befund A1): Regelbetrieb ist der automatische Abruf per `url` (Antwort 33), mit `{jahr}` über
    die HEAD-Suche nach der jüngsten Jahresdatei, dann der Download in den Cache, danach nur bei Änderung
    (If-Modified-Since). Steht der Rechner in ROBOTS_GESPERRT (www.bbr-server.de), ruft die Quelle ihn nur mit
    ihrer benannten Freigabe ab (robots_freigabe; im Bericht und im Protokoll ausgewiesen), sonst bricht sie
    vor jeder Verbindung ab. Zusätzlich und mit Vorrang: `datei` (oder die Umgebungsvariable
    PIPELINE_INKAR_DATEI, sie hat Vorrang und gilt für alle INKAR-Quellen), eine abgelegte Gesamtdatei ohne
    jeden Netzabruf, etwa für Prüfläufe (E48); keine Voraussetzung des Regelbetriebs.

    Zeilen (E50, Befund K1): Jede Zeile wird mit dem CSV-Parser zerlegt, bevor gefiltert wird; zulässig
    zitierte Felder werden gelesen. Was zu unserer Raumebene gehören kann, sich aber nicht sicher deuten
    lässt, wird nicht übernommen und macht den Abruf unvollständig (nichts wird gelöscht, _inkar_zeilen). Bis
    E50 übersprang ein Vorfilter auf den Rohtext „;Gemeinden;“ zitierte Zeilen, und Zeilen mit falscher
    Kennziffer fielen still weg; ihr bisheriger Wert konnte gelöscht werden. Ein Datensatz, den der Parser aus
    mehreren Zeilen der Datei zusammensetzt (Feld mit Zeilenumbruch, oder ein einzelnes Anführungszeichen, das
    bis zum nächsten reicht), ist seit der Nachprüfung zu E50 unlesbar, gleich welcher Raumebene; die echte
    Gesamtdatei 2025 enthält kein Anführungszeichen.

    Weitere Schlüssel: raumbezug (Wert der Spalte Raumbezug, Pflicht), kennziffer_beginnt, kennziffer_stellen,
    indikatoren (Liste von Kürzeln oder Kürzel -> Feldname), zeitbezug (Standard `neuester`; in der breiten
    Form `neuester` oder ein Jahr), eintrag (CSV im ZIP), gebiet, cache, jahr (bei `{jahr}` in der url).
    Rückgabe: in der breiten Form je Gebiet ein Datensatz mit ("gebiet", …), `name` und je Indikator dem Wert
    des jüngsten Jahrs, `zeit` je Indikator; in der Langform siehe _inkar_lang.
    Ausnahmen: QuellenFehler bei fehlender abgelegter Datei, fehlendem raumbezug, fehlender url ohne abgelegte
    Datei, falschem zeitbezug, leerem CSV-Eintrag (bis E50 KeyError, ValueError aus int() und RuntimeError; in
    E49 benannt, E50 behoben), gesperrter url ohne Freigabe, unlesbarem Dateinamen der url und aus zip_zeilen;
    beim Abruf außerdem aus neueste_url und datei_abrufen (dort auch requests.HTTPError und andere
    requests.RequestException); ZeitbudgetUeberschritten (E50). Fehlt eine Pflichtspalte oder ein
    konfigurierter Indikator, hält die Quelle über fehlende_felder an."""
    lang = cfg.get("form") == "lang"
    raumbezug = cfg.get("raumbezug")
    if not isinstance(raumbezug, str) or not raumbezug.strip():
        raise QuellenFehler("INKAR-Quelle ohne raumbezug (Wert der Spalte Raumbezug, etwa Gemeinden); "
                            "Konfiguration ergänzen")
    zeitbezug = _inkar_zeitbezug(cfg, lang)
    abgelegt = os.environ.get("PIPELINE_INKAR_DATEI") or cfg.get("datei")
    if abgelegt:
        # Abgelegte Datei statt Abruf (Antwort 33, E48): kein Netzabruf, auch keine HEAD-Suche nach dem
        # jüngsten Jahr und keine Nachfrage mit If-Modified-Since
        datei = Path(abgelegt)
        if not datei.is_file():
            # Nur der Dateiname (Nachprüfung zu E50): Der Text kann in den Meldungsentwurf an den Anbieter
            # gelangen, und ein relativer Pfad oder einer mit Leerzeichen entging dort dem Muster für lokale
            # Pfade; den ganzen Pfad nennt die Konfiguration bzw. die Umgebung
            raise QuellenFehler(f"Abgelegte INKAR-Datei fehlt: {datei.name} (Pfad aus datei bzw. "
                                "PIPELINE_INKAR_DATEI)")
        prot.hinweise.append(f"Abgelegte Datei, kein Abruf: {datei.name}")
        if robots_freigabe(cfg):
            # Sichtbar, dass die Freigabe in diesem Lauf nicht gebraucht wurde (E50)
            prot.hinweise.append("robots_freigabe konfiguriert, nicht genutzt (abgelegte Datei)")
    else:
        url = cfg.get("url")
        if not isinstance(url, str) or not url:
            raise QuellenFehler("INKAR-Quelle ohne url und ohne abgelegte Datei (datei bzw. "
                                "PIPELINE_INKAR_DATEI); Konfiguration ergänzen")
        if robots_gesperrt(url) is not None and freigabe_fuer(url, cfg) is None:
            # Ohne Freigabe bricht die Quelle ab, bevor irgendetwas abgerufen wird (auch kein HEAD; Prüfung
            # nach E48). Mit Freigabe prüft schema_pruefen jede Verbindung und vermerkt die Freigabe
            raise QuellenFehler(f"robots.txt von {urlsplit(url).hostname} sperrt automatische Abrufe; INKAR "
                                "nicht abgerufen. Abruf per URL nur mit benannter Freigabe der Quelle "
                                "(robots_freigabe), sonst Gesamtdatei ablegen und `datei` in der Quelle oder "
                                "PIPELINE_INKAR_DATEI setzen (docs/betrieb.md, E50)")
        # Dateiname im Cache vor jedem Abruf prüfen (E50), bei {jahr} an einem Beispieljahr
        cache_datei(url.replace("{jahr}", "2000"), ("zip",), cfg)
        if "{jahr}" in url:
            url = neueste_url(url, cfg, prot) if cfg.get("jahr", "neuester") == "neuester" \
                else url.format(jahr=cfg["jahr"])
        datei = cache_datei(url, ("zip",), cfg)
        datei_abrufen(url, datei, cfg, prot)
    prot.info["datei"] = {"name": datei.name, "stand": datetime.fromtimestamp(
        datei.stat().st_mtime, UTC).strftime("%Y-%m-%d"), **({"abgelegt": True} if abgelegt else {})}

    praefix = str(cfg.get("kennziffer_beginnt", ""))
    stellen = cfg.get("kennziffer_stellen")
    indikatoren = cfg.get("indikatoren")  # Liste von Kürzeln oder Mapping Kürzel -> Feldname
    namen = indikatoren if isinstance(indikatoren, dict) else {k: k for k in (indikatoren or [])}
    gebiet = cfg.get("gebiet") or {}
    schluessel = cfg.get("schluessel", INKAR_SCHLUESSEL) if lang else []
    if lang and indikatoren == "alle":
        namen = {}

    # Die erste Zeile der CSV ist der Kopf; die Spalten werden über ihren Namen gefunden, nicht über die
    # Position, damit eine umgestellte Datei richtig gelesen wird. Ein Leser über den ganzen Strom (nicht je
    # Zeile), schneller; ein Datensatz über mehr als eine Zeile der Datei gilt als unlesbar (_inkar_zeilen,
    # Nachprüfung zu E50), denn ein einzelnes Anführungszeichen zöge sonst Zeilen still zusammen
    leser = csv.reader(zip_zeilen(datei, cfg.get("eintrag"), cfg, prot), delimiter=";")
    try:
        kopf = next(leser)
    except StopIteration:
        raise QuellenFehler("INKAR-CSV ist leer (nicht einmal eine Kopfzeile)") from None
    prot.info["felder"] = kopf
    felder_pruefen(kopf, list(dict.fromkeys(INKAR_SPALTEN + schluessel)), prot)
    if prot.info.get("fehlende_felder"):
        return
    sp = {n: kopf.index(n) for n in kopf}
    # Pflichtfelder einer gewählten Zeile: in der Langform die Spalten des fachlichen Schlüssels, in der
    # breiten Form Kennziffer, Kürzel und Zeitbezug (der Wert darf fehlen, ziel.pflicht hält ihn zurück)
    pflicht = list(dict.fromkeys([*schluessel, "Kennziffer", "Kuerzel", "Zeitbezug"]))
    zeilen = _inkar_zeilen(leser, len(kopf), sp, raumbezug, praefix, stellen, namen, pflicht, prot)
    if lang:
        yield from _inkar_lang(zeilen, sp, zeitbezug, schluessel, gebiet, prot)
        if namen:
            felder_pruefen(prot.info["indikatoren"], list(namen), prot)
        return

    gebiete: dict[str, dict] = {}
    gefunden: set[str] = set()
    for f, kz, kuerzel, jahr in zeilen:
        if zeitbezug != "neuester" and jahr != zeitbezug:
            continue
        gefunden.add(kuerzel)
        g = gebiete.setdefault(kz, {"name": f[sp["Name"]].strip(), "werte": {}})
        feld = namen.get(kuerzel, kuerzel)
        alt = g["werte"].get(feld)
        # Je Gebiet und Indikator bleibt der Wert des jüngsten Jahrs, gleich in welcher Reihenfolge der Zeilen
        if alt is None or jahr > alt["jahr"]:
            g["werte"][feld] = {"wert": _zahl(f[sp["Wert"]], prot), "jahr": jahr}

    prot.info["indikatoren"] = sorted(gefunden)
    if namen:
        # Ein Indikator, den das BBSR umbenennt oder streicht, soll nicht still verschwinden
        felder_pruefen(sorted(gefunden), list(namen), prot)
    for kz, g in sorted(gebiete.items()):
        werte, zeit = {"name": g["name"]}, {}
        for feld, w in sorted(g["werte"].items()):
            werte[feld] = w["wert"]
            zeit[feld] = w["jahr"]  # Zeit-Referenz je Indikator: das Jahr des Werts
        yield {"objekt_id": kz, "geom": ("gebiet", gebietsschluessel(kz, gebiet)), "werte": werte,
               "zeit": zeit}


# Gründe, aus denen _inkar_zeilen eine Zeile unserer Raumebene nicht übernimmt (E50, Befund K1): Schlüssel in
# prot.info["inkar_unlesbar"] -> Text für die Warnung in _inkar_bilanz
INKAR_UNLESBAR = {
    "csv": "nicht als CSV lesbar",
    "zeilen": "über mehrere Zeilen der Datei zusammengezogen (Anführungszeichen öffnet ein Feld, das erst in "
              "einer späteren Zeile endet; darin verschluckte Zeilen fehlen)",
    "spalten": "mit falscher Zahl der Spalten (Spalten nicht zuzuordnen; die Datei hat keinen Fußblock)",
    "raumbezug": "mit einem Raumbezug, der erst ohne Leerraum oder Groß- und Kleinschreibung passt",
    "kennziffer": "mit einer Kennziffer, die keine Ziffernfolge der Länge kennziffer_stellen ist",
    "pflichtfeld": "mit leerem Pflichtfeld",
    "zeitbezug": "mit einem Zeitbezug, der keine Jahreszahl ist",
}
# Ab so vielen Zeilen prüft _inkar_zeilen das Zeitbudget (E50); die Langform mit `neuester` liefert erst nach
# der ganzen Datei Datensätze, der Prüfpunkt je Datensatz in laden griffe dort zu spät
INKAR_ZEIT_ALLE = 65536


def _inkar_zeilen(leser, breite: int, sp: dict, raumbezug: str, praefix: str, stellen, namen: dict,
                  pflicht: list[str], prot: Protokoll) -> Iterator[tuple[list[str], str, str, int]]:
    """Die gewählten Zeilen der INKAR-CSV, syntaktisch geprüft vor der fachlichen Filterung (E50, Befund K1).

    Gemeinsam für breite und lange Form, damit beide dieselben Regeln haben. Je Zeile in dieser Reihenfolge:
      1. als CSV zerlegt (csv.reader über den ganzen Strom); ein Fehler des Parsers: unlesbar. Ein Datensatz
         über mehr als eine Zeile der Datei (leser.line_num springt um mehr als 1): unlesbar, gleich welcher
         Raumbezug, vor dem Vergleich der Spaltenzahl (Nachprüfung zu E50). Ein einzelnes Anführungszeichen
         am Anfang eines Felds öffnet ein Feld bis zum nächsten Anführungszeichen; lag das in derselben oder
         der letzten Spalte, hatte der zusammengezogene Datensatz genau die Breite des Kopfs, bestand jede
         Prüfung und trug den Wert einer anderen Zeile, die verschluckten Zeilen fehlten still. Ein Feld mit
         Zeilenumbruch fällt unter dieselbe Regel; mit newline="" (_gezaehlt) ist jeder Umbruch eine Zeile der
         Datei, eine eigene Suche nach Zeilenumbrüchen je Feld ist deshalb nicht nötig.
      2. Spaltenzahl wie der Kopf; sonst unlesbar, außer bei einer Leerzeile (auch nur aus Trennern). Bis E51
         war eine solche Zeile nur unlesbar, wenn ein Feld unser Raumbezug sein konnte; eine abgeschnittene
         Zeile ohne dieses Feld blieb stumm, obwohl sie zu unserer Raumebene gehören kann (Befund K2
         sinngemäß). Die Gesamtdatei hat weder Kopf- noch Fußblock: INKAR 2025 hat in allen 63 426 864 Zeilen
         9 Felder und keine Leerzeile (gezählt am 07.11.2026 aus der abgelegten Datei, E51).
      3. Raumbezug genau gleich; nur nach Bereinigung (Rand, Groß- und Kleinschreibung) gleich: unlesbar.
         Andere Raumbezüge: stumm.
      4. Kennziffer nicht leer; mit kennziffer_stellen eine Ziffernfolge genau dieser Länge, sonst unlesbar,
         vor dem Filter nach kennziffer_beginnt (ein Schlüssel, der seinen Anfang verloren hat, gehört
         vielleicht zu uns). Anderer Anfang: stumm.
      5. Kürzel nicht leer, sonst unlesbar; nicht angeforderte Kürzel: stumm.
      6. Pflichtfelder (`pflicht`) nicht leer und Zeitbezug eine Jahreszahl, sonst unlesbar.
    Unlesbar heißt: nicht übernommen, gezählt mit den ersten zehn Zeilennummern in
    prot.info["inkar_unlesbar"]; _inkar_bilanz meldet daraus Warnungen, und der Abruf gilt als unvollständig
    (nichts wird gelöscht). Am echten Bestand (INKAR 2025, 63 426 864 Zeilen, 33 547 606 mit Raumbezug
    Gemeinden, alle Kennziffern achtstellig, kein leeres Pflichtfeld) bleibt keine Zeile unlesbar (E50).

    Generator: (Felder, Kennziffer ohne Rand, Kürzel ohne Rand, Jahr) je gewählter Zeile. Seiteneffekt:
    prot.zeit_pruefen alle INKAR_ZEIT_ALLE Zeilen; prot.info["inkar_unlesbar"]."""
    rb_cf = raumbezug.strip().casefold()
    i_rb, i_kz, i_k, i_zb = sp["Raumbezug"], sp["Kennziffer"], sp["Kuerzel"], sp["Zeitbezug"]

    def unlesbar(grund: str, nr: int, zusatz: str = "") -> None:
        """Zeile `nr` als nicht übernommen zählen; `zusatz` ergänzt den Grund (etwa das leere Feld)."""
        u = prot.info.setdefault("inkar_unlesbar", {}).setdefault(grund, {"anzahl": 0, "zeilen": [],
                                                                          "zusatz": []})
        u["anzahl"] += 1
        if len(u["zeilen"]) < 10:
            u["zeilen"].append(nr)
        if zusatz and zusatz not in u["zusatz"] and len(u["zusatz"]) < 5:
            u["zusatz"].append(zusatz)

    n = 0
    # Zeilen der Datei, die der Leser bisher verbraucht hat (nach dem Kopf 1); daran misst die Schleife, aus
    # wie vielen Zeilen ein Datensatz besteht
    vorher = leser.line_num
    while True:
        n += 1
        if n % INKAR_ZEIT_ALLE == 0:
            prot.zeit_pruefen()
        try:
            f = next(leser)
        except StopIteration:
            return
        except csv.Error as e:
            # Der Leser setzt nach einem Fehler mit der nächsten Zeile fort
            unlesbar("csv", leser.line_num, str(e)[:60])
            vorher = leser.line_num
            continue
        # nr: erste Zeile des Datensatzes in der Datei (für die Meldung); bei einem einzeiligen Datensatz ist
        # sie gleich leser.line_num
        nr, vorher = vorher + 1, leser.line_num
        if leser.line_num > nr:
            unlesbar("zeilen", nr, f"Zeilen {nr} bis {leser.line_num}")
            continue
        if len(f) != breite:
            # Jede nicht leere Zeile mit falscher Spaltenzahl (E51); welcher Raumebene sie angehört, lässt
            # sich nicht sicher sagen
            if any(x.strip() for x in f):
                unlesbar("spalten", nr, f"{len(f)} statt {breite}")
            continue
        rb = f[i_rb]
        if rb != raumbezug:
            if rb.strip().casefold() == rb_cf:
                unlesbar("raumbezug", nr, repr(rb)[:40])
            continue
        kz, kuerzel = f[i_kz].strip(), f[i_k].strip()
        if not kz:
            unlesbar("pflichtfeld", nr, "Kennziffer")
            continue
        if stellen and not (kz.isascii() and kz.isdigit() and len(kz) == stellen):
            unlesbar("kennziffer", nr, repr(kz)[:20])
            continue
        if not kz.startswith(praefix):
            continue
        if not kuerzel:
            unlesbar("pflichtfeld", nr, "Kuerzel")
            continue
        if namen and kuerzel not in namen:
            continue
        leer = [s for s in pflicht if not f[sp[s]].strip()]
        if leer:
            unlesbar("pflichtfeld", nr, ", ".join(leer))
            continue
        zb = f[i_zb].strip()
        if not (zb.isascii() and zb.isdigit()):
            unlesbar("zeitbezug", nr, repr(zb)[:20])
            continue
        yield f, kz, kuerzel, int(zb)


def _inkar_bilanz(prot: Protokoll) -> None:
    """Am Ende einer INKAR-Quelle: je Grund aus INKAR_UNLESBAR eine Warnung mit Anzahl, Zeilennummern und
    Beispielen; jede macht den Abruf unvollständig (E50, Befund K1)."""
    for grund, u in (prot.info.get("inkar_unlesbar") or {}).items():
        zeilen = ", ".join(map(str, u["zeilen"])) + (" …" if u["anzahl"] > len(u["zeilen"]) else "")
        wort = "Zeile" if u["anzahl"] == 1 else "Zeilen"
        zusatz = f": {'; '.join(u['zusatz'])}" if u["zusatz"] else ""
        prot.unvollstaendig_melden(f"{u['anzahl']} INKAR-{wort} {INKAR_UNLESBAR[grund]}{zusatz}, nicht "
                                   f"übernommen ({wort} {zeilen}); Abruf unvollständig, nichts wird gelöscht")


def _inkar_lang(zeilen, sp, zeitbezug, schluessel, gebiet, prot) -> Iterator[dict]:
    """INKAR in Langform: eine Zeile je Indikator, Gebiet und Jahr, wie dashboard_data_de.

    Parameter wie in _inkar_lesen vorbereitet: zeilen (gewählte, geprüfte Zeilen aus _inkar_zeilen), sp
    (Spaltenname -> Position), zeitbezug (`alle`, `neuester` oder ein Jahr als int), schluessel (Spalten des
    fachlichen Schlüssels, E40), gebiet.
    Rückgabe: je Zeile ein Datensatz; objekt_id sind die Schlüsselspalten mit „|“ verbunden, `werte` alle
    Spalten klein geschrieben, `wert` als Zahl, `zeitbezug` als Jahr. Mit `neuester` erst nach dem Durchlauf
    der ganzen Datei, je Reihe nur das jüngste Jahr, nach objekt_id sortiert.
    Seiteneffekt: prot.info["indikatoren"] (die gefundenen Kürzel), auch wenn der Aufrufer nicht alle
    Datensätze abholt."""
    neueste: dict[tuple, tuple[int, dict]] = {}
    gefunden: set[str] = set()
    prot.info["indikatoren"] = []
    for f, kz, kuerzel, jahr in zeilen:
        if zeitbezug not in ("alle", "neuester") and jahr != zeitbezug:
            continue
        gefunden.add(kuerzel)
        werte = {n.lower(): f[i].strip() for n, i in sp.items()}
        werte.update(zeitbezug=jahr, wert=_zahl(f[sp["Wert"]], prot))
        ds = {"objekt_id": "|".join(f[sp[n]].strip() for n in schluessel),
              "geom": ("gebiet", gebietsschluessel(kz, gebiet)), "werte": werte,
              "zeit": {"wert": jahr}}
        if zeitbezug == "neuester":
            # Jüngstes Jahr je Reihe: der Quellschlüssel ohne Zeitbezug. Kennziffer, Bereich und Kürzel
            # allein genügen nicht: INKAR 2025 führt unter einem Kürzel mehrere Indikatoren (a_bb_4G im
            # Bereich LRB: Arbeitslosigkeit, Bevölkerung, Bildung …; beispielberichte/inkar-schluessel/)
            k = tuple(f[sp[n]].strip() for n in schluessel if n != "Zeitbezug")
            if k not in neueste or jahr > neueste[k][0]:
                neueste[k] = (jahr, ds)
        else:
            yield ds
    prot.info["indikatoren"] = sorted(gefunden)
    # Nach objekt_id sortiert: die Folge hängt nicht von der Reihenfolge der Zeilen in der Datei ab
    for _, ds in sorted(neueste.values(), key=lambda x: x[1]["objekt_id"]):
        yield ds


# Quelltyp (Schlüssel `typ` in der Konfiguration) -> Adapter; laden.quelle_laden wählt hierüber
ADAPTER = {"wfs": wfs, "ogcapi": ogcapi, "csv": csv_quelle, "xlsx": xlsx, "inkar": inkar, "geojson": geojson}
