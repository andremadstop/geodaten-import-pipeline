"""Unveränderte Lieferung erkennen und überspringen (E52).

Anlass: Der Folgelauf von INKAR im Vollumfang dauerte nach E51 ohne jede Änderung 159,7 min, weil die
Pipeline 33,5 Mio. Zeilen erneut einlas und verglich. Für Dateiquellen (Typen csv, xlsx und inkar, die Datei
abgelegt oder per URL) bildet die Pipeline deshalb, wenn die Quelle es mit `unveraendert_ueberspringen: true`
einschaltet, die SHA-256 der gelieferten Datei und speichert sie nach einem vollständigen Vollabgleich im
Quellenstand (pipeline_meta.quellenstand). Beim nächsten Lauf wird die Quelle übersprungen, wenn alles gilt:

  - die Datei ist byte-gleich (gleiche SHA-256, geprüft, bevor der Adapter sie liest),
  - der Fingerabdruck aus der Konfiguration der Quelle und dem Code der Pipeline ist gleich (fingerabdruck),
  - der letzte Vollabgleich liegt weniger als `vollabgleich_tage` zurück (Standard 7; geprüft, wenn die Quelle
    nach ihrem Rhythmus läuft, also keine Frist im Kalender),
  - die Zählprüfung stimmt: Register und Zieltabelle (im Bereich der Quelle) haben so viele Zeilen wie nach
    dem letzten Vollabgleich (zaehlen),
  - und nichts verlangt ausdrücklich einen Vollabgleich (--vollabgleich, Freigabe einer Leerlieferung, eine
    Zielabbildung, die von einer anderen Tabelle abhängt).

Übersprungen heißt: keine Schreibvorgänge in Zieltabelle, Bestandsregister, Änderungsprotokoll und
table_metadata; nur der Quellenstand (letzter Lauf, letzter Erfolg, damit der Rhythmus weiterzählt) und das
Protokoll des Laufs. Der Bericht nennt es ausdrücklich („unverändert (Datei byte-gleich, sha256 …)“).

Warum ein Dateihash etwas anderes ist als `updateSequence` (E5): updateSequence ist eine Angabe des Dienstes
über sich selbst, die beim BKG hinter dem Lastverteiler zwischen zwei Werten wechselte. Die Prüfsumme bildet
die Pipeline selbst über genau die Bytes, die sie sonst lesen würde. Irren kann sie nur in die sichere
Richtung: Andere Bytes mit gleichem Inhalt (etwa ein neu gepacktes ZIP) ergeben einen Vollabgleich, mehr
nicht. Was die Prüfsumme nicht sehen kann, ist eine Änderung auf der Seite der Datenbank (Zeilen von Hand
geändert oder gelöscht); dafür gibt es die Zählprüfung (grob, nur Zeilenzahlen) und den regelmäßigen
Vollabgleich.

Stellung im Ablauf: laden.quelle_laden ruft vorpruefen in der Transaktion der Quelle nach ziel.pruefen und
vor dem Einlesen (dann ist noch kein COPY offen, die Abfragen sind möglich), schaltet über das Protokoll die
Prüfsumme ein (quellen.Protokoll.datei_bereit) und fängt quellen.DateiUnveraendert außerhalb der Transaktion
ab. Nach einem vollständigen Lauf schreibt es die Werte aus vergleichsstand in den Quellenstand.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from . import ziel

# Quelltypen mit einer gelieferten Datei. WFS und OGC API liefern Seiten eines Dienstes, keine Datei; für sie
# gibt es keine Prüfsumme (bleibt wie vor E52). GeoJSON ist ebenfalls eine Datei, wurde in E52 aber nicht
# einbezogen (nicht verlangt, nicht getestet); dort hätte der Adapter dieselbe Stelle wie inkar
DATEI_TYPEN = ("csv", "xlsx", "inkar")

# Schalter je Quelle und Abstand des Vollabgleichs
SCHALTER = "unveraendert_ueberspringen"
TAGE = "vollabgleich_tage"
VOLLABGLEICH_STANDARD_TAGE = 7

# Schlüssel einer Quelle, die nachweislich nicht beeinflussen, was die Pipeline aus derselben Datei in die
# Datenbank schreibt: Zeitgrenzen, an/aus, dieser Schalter selbst und die Änderungskarte. Alle anderen
# Schlüssel, auch unbekannte und künftige, gehen in den Fingerabdruck ein: Eine Änderung dort führt zum
# Vollabgleich (konservativ; im schlimmsten Fall ein Vollabgleich zu viel). `rhythmus` gehört nicht hierher
# (Nachprüfung durch Codex): Er steht als dct_accrualperiodicity in table_metadata (ziel._metadaten_zeilen)
UNERHEBLICH = frozenset({"zeitbudget_min", "db_sperre_max_s", "aktiv", SCHALTER, TAGE, "karte",
                         "karte_max_objekte"})

# Obergrenze für vollabgleich_tage (100 Jahre): größere Werte ließen timedelta überlaufen (Nachprüfung)
TAGE_HOECHST = 36_500

# Spalten des Quellenstands für den Vergleichsstand (sql/pipeline_meta.sql); meta_pruefen verlangt sie
SPALTEN = ("datei_sha256", "konfig_sha256", "vollabgleich", "register_zeilen", "ziel_zeilen")


def aktiv(qcfg: dict) -> bool:
    """Ist das Überspringen für diese Quelle eingeschaltet (Schalter genau True und Dateityp)? Ohne Schalter
    verhält sich die Quelle wie vor E52: keine Prüfsumme, jeder Lauf ein Vollabgleich."""
    return qcfg.get(SCHALTER) is True and qcfg.get("typ") in DATEI_TYPEN


def tage(qcfg: dict) -> float:
    """Alter des letzten Vollabgleichs in Tagen, ab dem der nächste tatsächlich ausgeführte Lauf der Quelle
    wieder vollständig abgleicht: vollabgleich_tage der Quelle, sonst VOLLABGLEICH_STANDARD_TAGE. Keine
    Frist im Kalender (der Rhythmus bestimmt, wann die Quelle läuft). Gültigkeit prüft konfig_fehler vor dem
    Lauf."""
    return qcfg.get(TAGE, VOLLABGLEICH_STANDARD_TAGE)


def konfig_fehler(cfg: dict) -> list[str]:
    """Prüft die beiden Schlüssel in allen Quellen (auch abgeschalteten), bevor eine Quelle lädt; laden macht
    aus jedem Fund einen KonfigFehler (wie zeitbudget_pruefen).

    Regeln: `unveraendert_ueberspringen` ist true oder false und true nur bei einem Typ aus DATEI_TYPEN;
    `vollabgleich_tage` ist eine Zahl über 0 bis TAGE_HOECHST (kein Wahrheitswert) und steht nur bei einer
    Quelle mit eingeschaltetem Schalter (sonst wirkte er nicht, und wer ihn setzt, hielte das Überspringen für
    aktiv).

    Returns:
        Liste der Fehlertexte, leer, wenn alles gültig ist."""
    fehler = []
    for name, q in (cfg.get("quellen") or {}).items():
        if not isinstance(q, dict):
            continue
        if SCHALTER in q:
            if not isinstance(q[SCHALTER], bool):
                fehler.append(f"{name}: {SCHALTER} muss true oder false sein, nicht {q[SCHALTER]!r}")
            elif q[SCHALTER] and q.get("typ") not in DATEI_TYPEN:
                fehler.append(f"{name}: {SCHALTER} gibt es nur für Dateiquellen ({', '.join(DATEI_TYPEN)}), "
                              f"nicht für typ {q.get('typ')!r}")
        if TAGE in q:
            w = q[TAGE]
            if not (isinstance(w, (int, float)) and not isinstance(w, bool) and math.isfinite(w)
                    and 0 < w <= TAGE_HOECHST):
                fehler.append(f"{name}: {TAGE} muss eine Zahl über 0 und höchstens {TAGE_HOECHST} sein "
                              f"(Tage), nicht {w!r}")
            elif q.get(SCHALTER) is not True:
                fehler.append(f"{name}: {TAGE} wirkt nur mit {SCHALTER}: true")
    return fehler


@lru_cache(maxsize=1)
def code_fingerabdruck() -> str:
    """SHA-256 über Namen und Inhalt aller Module der Pipeline (pipeline/*.py), einmal je Prozess. Geht in den
    Fingerabdruck ein: Nach einem Update der Pipeline (etwa einer Korrektur im Parser) liest der nächste Lauf
    dieselbe Datei neu, statt bis zum nächsten Vollabgleich den alten Stand zu behalten. Auch eine Änderung
    nur an Kommentaren zählt (dann ein Vollabgleich zu viel)."""
    summe = hashlib.sha256()
    for pfad in sorted(Path(__file__).resolve().parent.glob("*.py")):
        summe.update(pfad.name.encode() + b"\0" + pfad.read_bytes() + b"\0")
    return summe.hexdigest()


def _kanonisch(wert):
    """Wert der Konfiguration in eine Form, die json.dumps immer annimmt und die Typen erhält: ein Wörterbuch
    als Liste von Paaren ([Typ des Schlüssels, Schlüssel als Text], Wert), sortiert nach dem Schlüssel; Tupel
    als Liste. So lassen sich gemischte Schlüssel (YAML erlaubt Zahlen) sortieren, und 1 und "1" bleiben
    verschieden (Nachprüfung durch Codex: ziel.je_wert mit {1: …} und {"1": …} schreibt Verschiedenes; bis
    dahin wurden beide zu "1" und ergaben denselben Fingerabdruck). Andere Werte (etwa ein Datum aus YAML)
    wandelt json.dumps über default=str."""
    if isinstance(wert, dict):
        paare = [([type(k).__name__, str(k)], _kanonisch(v)) for k, v in wert.items()]
        return sorted(paare, key=lambda p: p[0])
    if isinstance(wert, (list, tuple)):
        return [_kanonisch(v) for v in wert]
    return wert


def _json_sha256(wert) -> str:
    """SHA-256 (hexadezimal) des JSON-Texts von `wert` in UTF-8 (ensure_ascii=False, default=str)."""
    return hashlib.sha256(json.dumps(wert, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def summe(wert) -> str:
    """SHA-256 eines Werts der Konfiguration in kanonischer Form (_kanonisch: Reihenfolge der Schlüssel egal,
    Typen bleiben verschieden), hexadezimal; je Schlüssel des Umfangs (umfang.teile)."""
    return _json_sha256(_kanonisch(wert))


def fingerabdruck(qcfg: dict) -> str:
    """Fingerabdruck der Konfiguration einer Quelle samt Code der Pipeline (E52): SHA-256 über die Quelle ohne
    die Schlüssel in UNERHEBLICH, kanonisch mit sortierten Schlüsseln (_kanonisch; die Reihenfolge in der
    YAML-Datei zählt nicht; Schlüssel mit ihrem Typ), und code_fingerabdruck. Ziel, Spalten, Filter, Adresse,
    Pfad, Rhythmus und jeder andere Schlüssel zählen."""
    bedeutsam = {k: v for k, v in qcfg.items() if k not in UNERHEBLICH}
    return _json_sha256({"quelle": _kanonisch(bedeutsam), "code": code_fingerabdruck()})


def entscheiden(stand: dict | None, abdruck: str, jetzt: datetime, max_tage: float, vollabgleich: bool,
                leer_grund: str | None, abhaengig: bool) -> str | None:
    """Darf die Quelle bei byte-gleicher Datei übersprungen werden, soweit es ohne Zählung zu entscheiden ist?
    Reine Funktion, die Zählprüfung folgt in vorpruefen.

    Args:
        stand: Vergleichsstand aus dem Quellenstand (Spalten aus SPALTEN) oder None (noch nie, oder Spalten
            leer: der letzte schreibende Lauf war kein vollständiger Vollabgleich mit Prüfsumme).
        abdruck: fingerabdruck der Quelle jetzt.
        jetzt: Startzeit des Laufs (UTC).
        max_tage: vollabgleich_tage.
        vollabgleich: --vollabgleich gesetzt.
        leer_grund: Freigabe einer Leerlieferung für diesen Lauf oder None.
        abhaengig: Ergebnis hängt von einer anderen Tabelle ab (ziel.gebiet mit ohne_flaeche: auslassen).

    Returns:
        None, wenn nichts dagegen spricht; sonst der Grund für den Vollabgleich (Text für den Bericht)."""
    if vollabgleich:
        return "erzwungen (--vollabgleich)"
    if leer_grund:
        return "Freigabe einer Leerlieferung für diesen Lauf"
    if abhaengig:
        # Welche Zeilen übernommen werden, hängt hier von der Gebietstabelle ab; die ist nicht Teil der Datei
        return "ziel.gebiet mit ohne_flaeche: auslassen hängt von der Gebietstabelle ab, nie übersprungen"
    if not stand or not stand.get("datei_sha256"):
        return "kein Vergleichsstand mit Prüfsumme (erster Lauf, oder der letzte Lauf war kein vollständiger"\
               " Vollabgleich)"
    if stand.get("konfig_sha256") != abdruck:
        return "Konfiguration der Quelle oder Code der Pipeline seit dem letzten Vollabgleich geändert"
    zuletzt = stand.get("vollabgleich")
    if zuletzt is None or zuletzt > jetzt:
        # Ein Zeitpunkt in der Zukunft (Uhr zurückgestellt) zählt nicht als junger Vollabgleich
        return "Zeitpunkt des letzten Vollabgleichs fehlt oder liegt nach diesem Lauf"
    if jetzt - zuletzt >= timedelta(days=max_tage):
        tage_her = (jetzt - zuletzt).total_seconds() / 86400
        return f"fällig (letzter vor {tage_her:.1f} Tagen, {TAGE}: {max_tage:g})"
    return None


def zaehlen(cur, name: str, z: ziel.Ziel) -> tuple[int, int]:
    """Zählprüfung (E52): Zeilen im Bestandsregister dieser Quelle (ziel.bisher) und in der Zieltabelle im
    Bereich der Quelle (ziel.bereich_zeilen). Zwei count(*), bei INKAR im Vollumfang über je rund 33,5 Mio.
    Zeilen; die Dauer ist auf dem Zielrechner nicht gemessen.

    Returns:
        (Registerzeilen, Zeilen der Zieltabelle im Bereich)."""
    return ziel.bisher(cur, name, z), ziel.bereich_zeilen(cur, z)


def vorpruefen(cur, name: str, z: ziel.Ziel, qcfg: dict, jetzt: datetime, vollabgleich: bool,
               leer_grund: str | None) -> tuple[str | None, str | None]:
    """Vor dem Einlesen, in der Transaktion der Quelle: Mit welcher Prüfsumme darf die Quelle übersprungen
    werden?

    Liest den Vergleichsstand aus pipeline_meta.quellenstand, entscheidet (entscheiden) und zählt erst dann
    (zaehlen), also nur, wenn sonst alles für ein Überspringen spricht. Vergleicht die Zählung mit dem Stand
    nach dem letzten Vollabgleich.

    Args:
        cur: Cursor in der Transaktion der Quelle, nach ziel.pruefen und vor dem Einlesen (kein COPY offen).
        name, z, qcfg: Quelle, ihr Ziel, ihre Konfiguration.
        jetzt: Startzeit des Laufs.
        vollabgleich: --vollabgleich gesetzt.
        leer_grund: Freigabe einer Leerlieferung oder None.

    Returns:
        (Prüfsumme, bei der übersprungen wird, oder None; Grund für den Vollabgleich oder None). Genau eines
        von beiden ist gesetzt."""
    cur.execute("SELECT datei_sha256, konfig_sha256, vollabgleich, register_zeilen, ziel_zeilen "
                "FROM pipeline_meta.quellenstand WHERE quelle = %s AND tabelle = %s", (name, z.name))
    zeile = cur.fetchone()
    stand = dict(zip(SPALTEN, zeile, strict=True)) if zeile else None
    abhaengig = (z.gebiet or {}).get("ohne_flaeche") == "auslassen"
    grund = entscheiden(stand, fingerabdruck(qcfg), jetzt, tage(qcfg), vollabgleich, leer_grund, abhaengig)
    if grund:
        return None, grund
    register, im_ziel = zaehlen(cur, name, z)
    if (register, im_ziel) != (stand["register_zeilen"], stand["ziel_zeilen"]):
        return None, (f"Zählprüfung: Register {register} (nach dem letzten Vollabgleich "
                      f"{stand['register_zeilen']}), {z.name} im Bereich der Quelle {im_ziel} (damals "
                      f"{stand['ziel_zeilen']})")
    return stand["datei_sha256"], None
