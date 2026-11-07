"""Sprache der Ausgaben: Textbericht, Meldungsentwurf, Quellenverzeichnis, Änderungskarte.

Die Texte stehen in pipeline/sprachen/<code>.json, je Sprache eine Datei, wie die Sprachdateien
im Frontend von MOSIDI. Eine neue Sprache ist eine neue Datei, kein Code. Fehlt ein Text in einer
Sprache, gilt der deutsche.

Gewählt wird über `sprache: en` in der Konfiguration oder die Umgebungsvariable PIPELINE_SPRACHE
(sie hat Vorrang). Warnungen und Hinweise aus den Adaptern (z. B. „7 Zeilen ohne jeden Wert
ausgelassen“) bleiben deutsch; sie sind Protokollmeldungen für den Betrieb. Ebenso bleiben die Zeile
für die Überwachung (--status) und die Kennzahlen (--kennzahlen) deutsch (E21).

Stellung im Ablauf: `laden._lauf` legt die Sprache zu Beginn eines Laufs mit `wahl` fest und schreibt
sie in den Bericht; Textbericht (laden), Meldungsentwurf (waechter), Quellenverzeichnis (verzeichnis)
und Änderungskarte (karte) holen ihre Texte dann mit `texte` aus dieser Angabe. Netz und Datenbank
braucht das Modul nicht.
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import cache
from pathlib import Path

ORDNER = Path(__file__).parent / "sprachen"
STANDARD = "de"
log = logging.getLogger("pipeline")


def wahl(cfg: dict | None = None) -> str:
    """Sprachcode aus Umgebung oder Konfiguration; nur Buchstaben, damit kein Pfad entsteht.

    Der Code wird später Teil eines Dateinamens (pipeline/sprachen/<code>.json); zwei oder drei
    Kleinbuchstaben schließen „../“ und andere Pfadteile aus.

    Args:
        cfg: gesamte Konfiguration oder None (etwa für --version, ohne Konfiguration).

    Returns:
        Den Sprachcode in Kleinbuchstaben, bei ungültiger Angabe "de" (mit Warnung im Protokoll).
        Ob es zu dem Code eine Sprachdatei gibt, prüft erst `texte`.
    """
    code = (os.environ.get("PIPELINE_SPRACHE") or (cfg or {}).get("sprache") or STANDARD).strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}", code):
        log.warning("Sprache %r ungültig, es gilt %s", code, STANDARD)
        return STANDARD
    return code


def _mischen(basis: dict, eigen: dict) -> dict:
    """Texte einer Sprache über die deutschen legen, verschachtelte Abschnitte rekursiv.

    Was in `eigen` fehlt, bleibt aus `basis`. Die Eingaben werden nicht verändert (flache Kopie je
    Ebene); gibt das gemischte dict zurück."""
    aus = dict(basis)
    for k, v in eigen.items():
        aus[k] = _mischen(basis[k], v) if isinstance(v, dict) and isinstance(basis.get(k), dict) else v
    return aus


@cache
def texte(code: str = STANDARD) -> dict:
    """Alle Texte einer Sprache, Lücken mit den deutschen gefüllt.

    Je Code einmal von der Platte gelesen und dann im Speicher gehalten (functools.cache); die
    Warnung zu einer fehlenden Sprachdatei erscheint deshalb nur einmal je Prozess. Das zurückgegebene
    dict ist geteilt und darf nicht verändert werden.

    Args:
        code: Sprachcode, wie ihn `wahl` liefert.

    Returns:
        Texte als verschachteltes dict (Abschnitte bericht, meldung, verzeichnis, karte usw.).

    Raises:
        OSError oder ValueError, wenn eine vorhandene Sprachdatei nicht lesbar oder kein gültiges JSON ist.
    """
    basis = json.loads((ORDNER / f"{STANDARD}.json").read_text(encoding="utf-8"))
    if code == STANDARD:
        return basis
    datei = ORDNER / f"{code}.json"
    if not datei.exists():
        log.warning("Keine Sprachdatei für %r, es gilt %s", code, STANDARD)
        return basis
    return _mischen(basis, json.loads(datei.read_text(encoding="utf-8")))


def zeit(lauf_id: str, muster: str) -> str:
    """Lauf-ID (20261030T074334Z) nach dem Muster der Sprache, z. B. {tag}.{monat}.{jahr}.

    Zerlegt die Kennung nur nach Stellen, ohne Datumsprüfung und ohne Umrechnung: die Zeit bleibt
    UTC, wie in der Kennung.

    Args:
        lauf_id: Laufkennung im Format JJJJMMTTThhmmssZ.
        muster: Formatvorlage mit den Platzhaltern jahr, monat, tag, stunde, minute.

    Returns:
        Den formatierten Zeitpunkt als Text.
    """
    return muster.format(jahr=lauf_id[0:4], monat=lauf_id[4:6], tag=lauf_id[6:8],
                         stunde=lauf_id[9:11], minute=lauf_id[11:13])
