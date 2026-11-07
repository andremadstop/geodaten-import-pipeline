"""Quellen-Wächter: merkt, wenn sich eine Quelle verändert, bevor kaputte Daten in der
Datenbank landen, und schreibt dazu eine Meldung, die ein Mensch an den Anbieter schicken kann.

Verglichen wird mit dem letzten Bericht (Feldliste der Quelle) und mit dem Bestand in der
Datenbank (Objektzahl). Versendet wird nichts automatisch.

Die updateSequence aus den Capabilities wird nur mitgeschrieben, nicht ausgewertet: Beim
VG250-WFS des BKG kamen am 30.10.2026 abwechselnd 128464 und 129155. Wechselnde Werte beobachtet;
Ursache nicht nachgewiesen. Ob sich Daten geändert haben, zeigt der Datenvergleich beim Laden (E5).

Stellung im Ablauf: `laden._lauf` liest vor den Quellen mit `letzter_bericht` den Vergleichsstand,
`laden.quelle_laden` fragt zwischen Abruf (quellen) und Schreiben (ziel) `schema_vergleichen`,
`rueckgang_zu_gross` und `loeschen_erlaubt`, und `laden._nachlauf` legt nach der Quelle mit
`meldung_noetig` und `meldung_text` den Meldungsentwurf ab. Das Modul selbst ruft kein Netz und keine
Datenbank ab; es liest nur Laufberichte.

Wichtige Entscheidungen:
- Rückgang-Schutz: bei 0 Objekten oder starkem Einbruch bleibt der alte Stand (E4).
- Meldungen an Anbieter nur als Entwurf, nie automatisch versendet (E8).
- Gelöscht wird nur nach vollständigem, fehlerfreiem Abruf (E23, E32, Antwort 52 der TH).
- Ein Metadatenkonflikt im eigenen Katalog ist kein Fall für den Anbieter (E46).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import betrieb, sprache

# Liefert eine Quelle mehr als die Hälfte weniger Objekte als beim letzten Mal, bleibt der alte
# Stand stehen. Je Quelle über `max_rueckgang` einstellbar (0.2 = 20 %), `null` schaltet es ab.
MAX_RUECKGANG_STANDARD = 0.5


def letzter_bericht(ordner: Path, vor_lauf: str, tiefe: int = 400) -> dict:
    """Je Quelle ihr jüngster Eintrag vor diesem Lauf, in dem sie wirklich geladen wurde. Quellen
    mit Rhythmus stehen in den Läufen dazwischen nur als „nicht fällig“ im Bericht; als unverändert
    übersprungene Quellen (Eintrag mit `uebersprungen`, E52) zählen ebenfalls nicht.

    Args:
        ordner: Ordner der Laufberichte.
        vor_lauf: Laufkennung des laufenden Laufs; nur ältere Berichte zählen (Vergleich als Text, das
            Format der Kennung sortiert zeitlich, siehe betrieb.LAUF).
        tiefe: höchstens so viele Berichte rückwärts lesen; 400 decken bei einem Lauf am Tag mehr
            als ein Jahr ab, also auch eine Quelle mit jährlichem Rhythmus.

    Returns:
        Quellname -> Eintrag der Quelle im Bericht (dict wie in bericht["quellen"]). Ein Eintrag mit
        Fehler zählt auch; Quellen ohne früheren Eintrag fehlen. Probeläufe zählen nicht.
    """
    # Jüngster Bericht zuerst; setdefault unten behält deshalb je Quelle den jüngsten Eintrag
    frueher = sorted((p for p in ordner.glob("2*.json")
                      if p.stem < vor_lauf and not p.stem.endswith("-probelauf")), reverse=True)
    aus: dict = {}
    for p in frueher[:tiefe]:
        # Ein unlesbarer (etwa abgeschnittener) Bericht darf keinen späteren Lauf blockieren (E42)
        b = betrieb.lesen(p)
        for q in (b or {}).get("quellen", []):
            # Eine als unverändert übersprungene Quelle (E52) wurde nicht gelesen, ihr Eintrag hat keine
            # Feldliste; Vergleichsstand bleibt der Lauf davor
            if q.get("status") != "nicht_faellig" and not q.get("uebersprungen"):
                aus.setdefault(q["quelle"], q)
    return aus


def schema_vergleichen(vorher: dict | None, info: dict) -> list[str]:
    """Hinweise auf Änderungen an der Quelle selbst (nicht an ihren Daten).

    Verglichen wird nur die Feldliste, die der Adapter in info["felder"] ablegt, mit der aus dem
    letzten Bericht, in dem die Quelle geladen wurde. Ein Unterschied hält nichts an; fehlende
    konfigurierte Felder erkennt der Adapter selbst (info["fehlende_felder"], E4).

    Args:
        vorher: Eintrag der Quelle aus `letzter_bericht`, None beim ersten Lauf.
        info: prot.info des laufenden Abrufs.

    Returns:
        Liste der Hinweistexte (leer, wenn es keinen Vergleichsstand gibt oder nichts anders ist).
    """
    if not vorher:
        return []
    alt = vorher.get("info", {})
    meldungen = []
    if alt.get("felder") and info.get("felder") and alt["felder"] != info["felder"]:
        neu = sorted(set(info["felder"]) - set(alt["felder"]))
        weg = sorted(set(alt["felder"]) - set(info["felder"]))
        teile = ([f"neu {', '.join(neu)}"] if neu else []) + ([f"entfallen {', '.join(weg)}"] if weg else [])
        meldungen.append("Feldliste der Quelle geändert: " + "; ".join(teile))
    return meldungen


def rueckgang_zu_gross(bisher: int, jetzt: int, max_rueckgang: float | None) -> bool:
    """Rückgang-Schutz (E4): liefert die Quelle mehr als den Anteil `max_rueckgang` weniger Objekte
    als bisher?

    Args:
        bisher: Zeilen der Quelle laut Bestandsregister (`ziel.bisher`).
        jetzt: Objekte im neuen Abruf.
        max_rueckgang: erlaubter Rückgang als Anteil (0.5 = 50 %), None = Schutz abgeschaltet.

    Returns:
        True, wenn der alte Stand stehen bleiben soll. Beim ersten Laden (bisher 0) nie; 0 Objekte
        fängt `laden.quelle_laden` schon vorher eigens ab.
    """
    if max_rueckgang is None or bisher == 0:
        return False
    return jetzt < bisher * (1 - max_rueckgang)


def loeschen_erlaubt(prot) -> bool:
    """Löschen nur bei vollständigem und fehlerfreiem Abruf (Antwort 52 der TH). Fehler brechen
    die Quelle ohnehin ab; unvollständig ist ein Abruf, wenn ein Adapter Objekte übersprungen hat
    oder eine Seite bzw. Kachel weniger lieferte, als der Dienst gemeldet hat.

    Args:
        prot: Protokoll der Quelle (quellen.Protokoll); gelesen wird nur `unvollstaendig`, das auch
            `ziel` beim Bilden des neuen Stands setzt (etwa unbrauchbare Geometrien).

    Returns:
        True, wenn Zeilen, die die Quelle nicht mehr liefert, gelöscht werden dürfen. `loeschen: false`
        im Ziel (E35) wird nicht hier, sondern danach in `laden.quelle_laden` berücksichtigt.
    """
    return not prot.unvollstaendig


def meldung_noetig(eintrag: dict) -> bool:
    """Braucht diese Quelle nach dem Lauf einen Meldungsentwurf an den Anbieter?

    Ja bei Status fehler oder angehalten und bei fehlenden konfigurierten Feldern; nein, wenn die
    Quelle nicht fällig war, der Grund ein Metadatenkonflikt im eigenen Katalog ist (E46), eine
    Umfangsänderung der eigenen Konfiguration auf Bestätigung wartet (E52) oder das Zeitbudget
    der Quelle überschritten wurde (E50: liegt an Menge oder eigener Einstellung, nicht nachweislich am
    Anbieter). Ein unvollständiger Abruf mit Status ok bekommt keinen Entwurf; er wird beim nächsten Lauf
    wiederholt.

    Args:
        eintrag: Eintrag der Quelle im Laufbericht.

    Returns:
        True, wenn `laden._nachlauf` einen Entwurf schreiben soll.
    """
    if eintrag["status"] == "nicht_faellig":
        return False
    if eintrag.get("info", {}).get("metadaten_belegt"):
        return False   # Konflikt im Katalog der eigenen Datenbank, nichts für den Anbieter (E46)
    if (eintrag.get("info", {}).get("umfang") or {}).get("angehalten"):
        return False   # eigene Konfiguration geändert, wartet auf Bestätigung (E52), nichts für den Anbieter
    if str(eintrag.get("fehler") or "").startswith("ZeitbudgetUeberschritten"):
        return False   # Zeitbudget der Quelle (E50)
    return eintrag["status"] != "ok" or bool(eintrag.get("info", {}).get("fehlende_felder"))


# Fehlerarten, die vom Abruf der Quelle kommen und dem Anbieter beim Nachstellen helfen. Alles
# andere (Datenbank, Dateisystem, Programmfehler) betrifft nur den eigenen Betrieb und kann Rechner,
# Rollen oder Pfade nennen; das gehört nicht in eine Meldung nach außen.
FEHLER_DER_QUELLE = ("QuellenFehler", "HTTPError", "ConnectionError", "ConnectTimeout", "ReadTimeout",
                     "Timeout", "SSLError", "TooManyRedirects", "ChunkedEncodingError",
                     "XMLSyntaxError", "JSONDecodeError", "UnicodeDecodeError", "BadZipFile")


def befund_fuer_anbieter(fehler: str | None) -> str:
    """Fehlertext für die Meldung nach außen.

    Der Fehler im Bericht hat die Form „<Ausnahmeklasse>: <Text>“ (laden._lauf). Nur Klassen aus
    FEHLER_DER_QUELLE erscheinen mit Text; bei allen anderen nur der Klassenname, damit keine internen
    Angaben (Rechner, Rollen, Pfade) in einen Entwurf an Dritte geraten.

    Args:
        fehler: Fehlertext aus dem Bericht, None, wenn keiner da ist.

    Returns:
        Den Fehlertext unverändert oder eine neutrale Zeile mit der Fehlerart.
    """
    art = (fehler or "").split(":", 1)[0].strip()
    if art in FEHLER_DER_QUELLE:
        return fehler
    return f"interner Fehler ({art or 'unbekannt'}), Einzelheiten nur im eigenen Laufbericht"


# Lokaler Pfad in einem Meldungstext (E50): ein „/“ oder „~/“ am Anfang eines Worts (nicht nach Buchstabe,
# Ziffer, „:“, „/“ oder „.“, also nicht der Pfad einer Adresse wie https://rechner/pfad) und mindestens ein
# Zeichen danach. Erfasst nur bis zum ersten Leerzeichen und keine relativen Pfade; die konfigurierten Pfade
# ersetzt ohne_lokale_pfade deshalb vorher ausdrücklich (Nachprüfung zu E50)
_LOKALER_PFAD = re.compile(r"(?<![\w:/.%~-])~?/[^\s,;()<>'\"]+")
# Umgebungsvariablen mit lokalen Pfaden, die in Meldungen auftauchen können
_PFAD_VARIABLEN = ("PIPELINE_INKAR_DATEI", "PIPELINE_CACHE")


def _bekannte_pfade(cfg: dict) -> list[str]:
    """Konfigurierte lokale Pfade, die in einem Meldungstext stehen können (Nachprüfung zu E50): `datei`,
    `pfad` (wenn er keine Adresse ist) und `cache` der Quelle, PIPELINE_INKAR_DATEI und PIPELINE_CACHE. Nur
    Werte mit Schrägstrich oder Rückstrich: ein bloßer Name (etwa `cache: c`) verrät nichts, und ihn überall
    zu ersetzen machte den Text unlesbar. Längste zuerst, damit ein Pfad nicht nur zum Teil ersetzt wird."""
    werte = [cfg.get(k) for k in ("datei", "pfad", "cache")] + [os.environ.get(v) for v in _PFAD_VARIABLEN]
    pfade = {str(w).rstrip("/") for w in werte
             if isinstance(w, str) and "://" not in w and ("/" in w or "\\" in w) and len(w.strip("/")) > 1}
    return sorted(pfade, key=len, reverse=True)


def ohne_lokale_pfade(text: str, cfg: dict | None = None) -> str:
    """Lokale Pfade in `text` durch „<lokaler Pfad>“ ersetzen (E50); Adressen (https://…) bleiben. Für Texte,
    die nach außen gehen (Meldungsentwurf an den Anbieter).

    Zuerst die konfigurierten Pfade der Quelle `cfg` und der Umgebung (_bekannte_pfade), ganz, auch relativ
    oder mit Leerzeichen; danach das allgemeine Muster für absolute Pfade und `~/…`. Bis zur Nachprüfung zu
    E50 nur das Muster: `cache/inkar.zip`, `~/…` und der Rest eines Pfads nach einem Leerzeichen blieben
    stehen (ein Mensch prüft den Entwurf vor dem Versand, E8)."""
    for pfad in _bekannte_pfade(cfg or {}):
        text = text.replace(pfad, "<lokaler Pfad>")
    return _LOKALER_PFAD.sub("<lokaler Pfad>", text)


def meldung_text(name: str, cfg: dict, eintrag: dict, lauf_id: str, code: str = sprache.STANDARD) -> str:
    """Entwurf einer Meldung an den Anbieter: Abfrage, Zeitpunkt, Befund. Gefiltert wird nach der
    Fehlerklasse (`befund_fuer_anbieter`): Klassen außerhalb von FEHLER_DER_QUELLE erscheinen ohne Text. Seit
    E50 außerdem ohne lokale Pfade (ohne_lokale_pfade), in Befund und Abfrage: Texte von QuellenFehler können
    Pfade nennen (etwa „Abgelegte INKAR-Datei fehlt: <Pfad>“), und ohne Netzabruf (`letzte_abfrage` leer, etwa
    CSV oder XLSX aus einer abgelegten Datei) nennt die Zeile „Abfrage“ statt eines lokalen `pfad` nur den
    Dateinamen (bis E50 den ganzen Pfad, in E49 benannt, E50 behoben).
    Bei einer angehaltenen Quelle besteht der Befund aus allen ihren Warnungen, und die können auch Namen
    und Längen von Zielspalten (ziel.laengen_pruefen) oder Zielschlüssel-Kollisionen nennen. Versendet wird
    nichts; ein Mensch prüft den Entwurf vor dem Versand (E8).
    Der Befund selbst (Warnung oder Fehler aus dem Lauf) bleibt in der Sprache des Protokolls.

    Args:
        name: Name der Quelle aus der Konfiguration.
        cfg: Konfiguration der Quelle (Kontakt, url/pfad, typename).
        eintrag: Eintrag der Quelle im Laufbericht.
        lauf_id: Laufkennung, als Zeitpunkt in den Text gesetzt.
        code: Sprachcode der Vorlage (pipeline/sprachen/<code>.json, Abschnitt „meldung“).

    Returns:
        Text des Entwurfs. Empfänger ist der Kontakt aus der Konfiguration, sonst der, den der Dienst
        selbst nennt (etwa in den WFS-Capabilities), sonst ein Platzhalter. Versendet wird nichts (E8).
    """
    t = sprache.texte(code)["meldung"]
    info = eintrag.get("info", {})
    kontakt = cfg.get("kontakt") or info.get("kontakt") or {}
    # Bei einem Fehler nur, was der Anbieter nachstellen kann (befund_fuer_anbieter); sonst (angehalten)
    # die Warnungen der Quelle
    befund = ohne_lokale_pfade(befund_fuer_anbieter(eintrag["fehler"]) if eintrag["status"] == "fehler"
                               else "; ".join(eintrag["warnungen"]), cfg)
    # Die zuletzt abgerufene Adresse, damit der Anbieter genau diese Abfrage nachstellen kann; ohne
    # Netzabruf url oder seite aus der Konfiguration, ein lokaler pfad nur mit dem Dateinamen
    pfad = str(cfg.get("pfad") or "")
    abfrage = (eintrag.get("letzte_abfrage") or cfg.get("url") or cfg.get("seite")
               or (pfad if "://" in pfad else Path(pfad).name or None))
    return t["text"].format(an=kontakt.get("email") or t["an_unbekannt"],
                            dienst=cfg.get("typename") or abfrage, lauf_id=lauf_id, befund=befund,
                            zeit=sprache.zeit(lauf_id, t["zeit"]), abfrage=abfrage, name=name,
                            anbieter=kontakt.get("anbieter") or t["anbieter_unbekannt"])
