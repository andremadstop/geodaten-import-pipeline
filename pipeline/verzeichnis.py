"""Quellenverzeichnis: eine Übersicht aller Quellen, die sich nach jedem Lauf selbst aktualisiert.

Je Quelle: Typ, Anbieter, Kontakt, Lizenz, letzter erfolgreicher Abruf, Anzahl Objekte, Ergebnis
des letzten Laufs. Gedacht für den Betrieb (wer ist bei einer Störung zuständig?) und für
Forschungsdatenmanagement und Projektberichte (woher stammen die Daten, unter welcher Lizenz?).
Der Stand liegt in quellenverzeichnis.json, lesbar als quellenverzeichnis.md.

Stellung im Ablauf: Am Ende jedes regulären Laufs (nicht im Probelauf) ruft `laden._lauf`
`aktualisieren` auf, nachdem Bericht und Textbericht geschrieben sind; Quellen, die in diesem Lauf
nicht fällig waren, behalten ihren Eintrag. Daneben stellt das Modul zwei Bausteine für die ganze
Pipeline bereit: `schreiben` (atomares Ersetzen von Dateien, auch für Berichte und Meldungsentwürfe)
und `ergebnis` (die eine Regel, was als „ok“ gilt; ebenso genutzt von Textbericht, --status,
--kennzahlen und Änderungskarte).

Wichtige Entscheidungen:
- Ein unvollständiger Abruf ist kein Erfolg: „letzter erfolgreicher Abruf“ und Objektzahl ändern sich
  nur bei vollständigem Abruf, wie in pipeline_meta.quellenstand (E32, E41, E44).
- Dateien werden atomar ersetzt, damit ein abgebrochener Lauf keine abgeschnittene Datei hinterlässt (E42).
- Texte zweisprachig über die Sprachdateien (E21).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from . import sprache

log = logging.getLogger("pipeline")


def schreiben(datei: Path, text: str) -> None:
    """Datei atomar ersetzen: erst eine temporäre Datei im selben Ordner, dann os.replace. Bricht der
    Lauf beim Schreiben ab (SIGKILL, volle Platte), bleibt die alte Fassung oder gar keine stehen, nie
    eine abgeschnittene, die spätere Läufe beim Lesen anhält (Prüfung 05.11., Runde 2, E42).

    Args:
        datei: Zieldatei; ihr Ordner muss existieren.
        text: Inhalt, geschrieben als UTF-8.

    Raises:
        OSError (etwa volle Platte, fehlende Rechte); die temporäre Datei ist dann schon entfernt.
    """
    # Im selben Ordner, damit os.replace nicht über Dateisystemgrenzen geht (dort wäre es nicht atomar,
    # sondern scheiterte). Der Punkt am Anfang hält sie aus der Suche nach Laufdateien (2*) heraus, die
    # Prozessnummer trennt die Zwischendateien zweier Prozesse
    tmp = datei.with_name(f".{datei.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, datei)
    except BaseException:   # auch bei Beendet (SIGTERM) und KeyboardInterrupt aufräumen, dann weiterreichen
        tmp.unlink(missing_ok=True)
        raise


def ergebnis(q: dict) -> str:
    """Ergebnis einer Quelle im Verzeichnis: `ok` nur bei vollständigem Abruf, sonst `unvollstaendig`
    (Status ok, aber Lücke: nichts gelöscht, Wiederholung beim nächsten Lauf), `fehler`, `angehalten`.

    Der JSON-Bericht führt einen unvollständigen Abruf weiter als status ok mit unvollstaendig true;
    alle Ausgaben, die ein Ergebnis zeigen, gehen deshalb über diese Funktion (E44, F4).

    Args:
        q: Eintrag einer Quelle im Laufbericht, mindestens mit `status`.

    Returns:
        "ok", "unvollstaendig", "fehler", "angehalten" oder "nicht_faellig" (Status unverändert).
    """
    if q["status"] == "ok" and q.get("unvollstaendig"):
        return "unvollstaendig"
    return q["status"]


def aktualisieren(ordner: Path, bericht: dict, cfg: dict) -> dict:
    """Quellenverzeichnis mit dem Ergebnis eines Laufs fortschreiben.

    Liest den bisherigen Stand aus quellenverzeichnis.json, setzt je geladener Quelle Typ, Adresse,
    Kontakt, Lizenz und Ergebnis neu und schreibt JSON und Markdown atomar. Quellen, die nicht mehr in
    der Konfiguration stehen, behalten ihren alten Eintrag.

    Args:
        ordner: Ordner der Laufberichte; dort liegen quellenverzeichnis.json und .md.
        bericht: Laufbericht des eben beendeten Laufs.
        cfg: gesamte Konfiguration (Abschnitt `quellen` und `sprache`).

    Returns:
        Der neue Stand (Quellname -> Eintrag), wie er in quellenverzeichnis.json steht.

    Seiteneffekte:
        Schreibt quellenverzeichnis.json und quellenverzeichnis.md. Ist die JSON-Datei unlesbar,
        wird sie mit einer Warnung im Protokoll neu aufgebaut.
    """
    datei = ordner / "quellenverzeichnis.json"
    stand = {}
    if datei.exists():
        try:
            stand = json.loads(datei.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            # Neu aufbauen statt jeden Lauf anzuhalten; letzter_erfolg kommt mit dem nächsten Erfolg zurück
            log.warning("%s nicht lesbar, wird neu aufgebaut", datei)
    for q in bericht["quellen"]:
        if q["status"] == "nicht_faellig":
            continue
        # Kontakt aus der Konfiguration vor dem, den der Dienst nennt; fehlen beide in diesem Lauf (etwa
        # weil der Abruf vor den Capabilities scheiterte), bleibt der bisher bekannte stehen
        qcfg = cfg["quellen"].get(q["quelle"], {})
        info = q.get("info", {})
        kontakt = qcfg.get("kontakt") or info.get("kontakt") or {}
        alt = stand.get(q["quelle"], {})
        eintrag = {
            "typ": q["typ"],
            "adresse": qcfg.get("url") or qcfg.get("pfad"),
            "anbieter": kontakt.get("anbieter") or alt.get("anbieter"),
            "email": kontakt.get("email") or alt.get("email"),
            "lizenz": qcfg.get("lizenz"),
            "letzter_lauf": bericht["lauf_id"],
            "ergebnis": ergebnis(q),
            "letzter_erfolg": alt.get("letzter_erfolg"),
            "objekte": alt.get("objekte"),
        }
        # Erfolg wie in pipeline_meta.quellenstand.letzter_erfolg (laden.quelle_laden, E32): nur ein
        # vollständiger Abruf. Ein unvollständiger behält den letzten Erfolg (Codex-Prüfung 05.11., B3)
        if eintrag["ergebnis"] == "ok":
            eintrag["letzter_erfolg"] = bericht["lauf_id"]
            eintrag["objekte"] = info.get("objekte")
        stand[q["quelle"]] = eintrag
    schreiben(datei, json.dumps(stand, ensure_ascii=False, indent=2))
    code = bericht.get("sprache") or sprache.wahl(cfg)
    schreiben(ordner / "quellenverzeichnis.md", als_markdown(stand, code))
    return stand


def als_markdown(stand: dict, code: str = sprache.STANDARD) -> str:
    """Quellenverzeichnis als Markdown-Tabelle, eine Zeile je Quelle, nach Namen sortiert.

    Args:
        stand: Stand aus quellenverzeichnis.json.
        code: Sprachcode für Überschrift, Spaltenköpfe und Ergebnisnamen (Abschnitt „verzeichnis“).

    Returns:
        Markdown-Text mit Titel, Hinweis und Tabelle. Leere Angaben erscheinen als Strich, eine Quelle
        ohne Erfolg als „noch nie“. Werte aus Konfiguration und Dienst werden nicht maskiert; ein „|“
        darin verschöbe die Spalten dieser Zeile.
    """
    t = sprache.texte(code)["verzeichnis"]
    leer = t["leer"]

    def zeit(lauf_id: str | None) -> str:
        """Laufkennung als lesbarer Zeitpunkt der gewählten Sprache, ohne Kennung „noch nie“."""
        return sprache.zeit(lauf_id, t["zeit"]) if lauf_id else t["noch_nie"]

    # Trennzeile aus der Spaltenzahl des Kopfs, damit eine Sprachdatei Spalten anders benennen kann
    spalten = t["kopf"].count("|") - 1
    zeilen = [t["titel"], "", t["hinweis"], "", t["kopf"], "|" + "---|" * spalten]
    for name, e in sorted(stand.items()):
        objekte = e.get("objekte") if e.get("objekte") is not None else leer
        ergebnis = t["ergebnis"].get(e["ergebnis"], e["ergebnis"])
        zeilen.append(f"| {name} | {e['typ']} | {e.get('anbieter') or leer} | {e.get('email') or leer} "
                      f"| {e.get('lizenz') or leer} | {zeit(e.get('letzter_erfolg'))} "
                      f"| {objekte} | {ergebnis}, {zeit(e['letzter_lauf'])} |")
    return "\n".join(zeilen) + "\n"
