"""Betrieb: Zustand für die Überwachung, Kennzahlen für Berichte, Aufbewahrung, Stand-Archiv.

Alles arbeitet auf den Laufberichten in berichte/ und braucht (außer dem Archiv) keine Datenbank.

Stellung im Ablauf: Das Modul liegt neben der Kette laden → quellen → ziel. `laden.main` ruft
`status` (Option --status) und `kennzahlen` (--kennzahlen) auf, ohne einen Lauf zu starten und ohne
Datenbank. Im Lauf (`laden._lauf`, aufgerufen von `laden.lauf`) schreibt `laden._nachlauf` gleich
nach jeder Quelle mit Status ok und neu/geändert/gelöscht deren Stand mit `archiv_schreiben` (nur mit
`archiv: true`, nicht im Probelauf); nach allen Quellen, vor dem Schreiben der Berichte, löscht
`aufraeumen` alte Laufdateien (nur mit `aufbewahrung_tage`, nicht im Probelauf).

Wichtige Entscheidungen:
- Rückgabewerte und Zeilenformat nach der Konvention von Nagios/Icinga/Checkmk, damit jede übliche
  Überwachung den Zustand ohne eigenes Plugin lesen kann (docs/betrieb.md).
- Ein unvollständiger Abruf ist kein Erfolg, aber auch kein Ausfall: --status meldet WARNING, nie allein
  CRITICAL (E32, E42, E44 F2); welches Ergebnis eine Quelle hat, entscheidet nur `verzeichnis.ergebnis`.
- Unlesbare Laufberichte werden übersprungen statt die Auswertung anzuhalten (E42).
- Stand-Archiv außerhalb der Tabellen, standardmäßig aus (E17); Aufbewahrung schützt den jüngsten
  regulären Bericht als Vergleichsstand (E18).
"""
from __future__ import annotations

import gzip
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .verzeichnis import ergebnis

log = logging.getLogger("pipeline")
# Laufkennung am Anfang eines Dateinamens (UTC, sekundengenau, z. B. 20261030T074334Z). Alle Laufdateien
# beginnen damit: Bericht (.json, .txt), Karte, Meldungsentwürfe, Archivordner. Weil das Format fest und
# gleich lang ist, sortieren die Namen als Text in zeitlicher Reihenfolge.
LAUF = re.compile(r"^(\d{8}T\d{6}Z)")

# Rückgabewerte nach der Konvention von Nagios/Icinga/Checkmk
OK, WARNUNG, KRITISCH, UNBEKANNT = 0, 1, 2, 3
STATUSNAME = {OK: "OK", WARNUNG: "WARNING", KRITISCH: "CRITICAL", UNBEKANNT: "UNKNOWN"}


def einzeilig(text: str) -> str:
    """Eine Zeile für die Überwachung: Fehlertexte aus PL/pgSQL (CONTEXT) oder psycopg sind mehrzeilig, die
    Perfdata stünden sonst auf einer späteren Zeile, die Nagios nicht liest (Nachprüfung zu E46).

    Fasst jede Folge von Leerraum (Zeilenumbrüche, Tabulatoren, mehrere Leerzeichen) zu einem
    Leerzeichen zusammen und entfernt Leerraum an den Rändern. Gibt den neuen Text zurück."""
    return " ".join(text.split())


def _zeit(lauf_id: str) -> datetime:
    """Zeitpunkt einer Laufkennung (Format wie LAUF) als zeitzonenbewusstes datetime in UTC.

    Löst ValueError aus, wenn die Kennung nicht genau diesem Format entspricht."""
    return datetime.strptime(lauf_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def lesen(datei: Path) -> dict | None:
    """Ein Laufbericht, oder None, wenn er nicht lesbar ist (etwa abgeschnitten durch SIGKILL oder eine
    volle Platte beim Schreiben, bevor die Berichte atomar ersetzt wurden). Ein solcher Bericht darf
    keinen späteren Lauf und keine Auswertung blockieren (Prüfung 05.11., Runde 2, E42).

    Args:
        datei: Pfad eines JSON-Laufberichts.

    Returns:
        Den Bericht als dict, oder None. None gibt es auch, wenn die Datei gültiges JSON enthält, aber
        kein Objekt (etwa eine Liste); nur ein Lese- oder Dekodierfehler steht als Warnung im Protokoll,
        ein JSON ohne Objekt wird still übergangen. Ausnahmen beim Lesen gibt die Funktion nicht weiter."""
    try:
        b = json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        log.warning("Laufbericht %s nicht lesbar, übersprungen", datei)
        return None
    return b if isinstance(b, dict) else None


def berichte(ordner: Path) -> list[Path]:
    """Reguläre Laufberichte (ohne Probeläufe), älteste zuerst.

    Gemeint sind die JSON-Berichte direkt in `ordner`, deren Name mit einer Laufkennung beginnt; die
    Reihenfolge ergibt sich aus dem Dateinamen (siehe LAUF), nicht aus dem Änderungsdatum der Datei.
    Gelesen wird hier nichts, es werden nur Pfade gesammelt."""
    return sorted(p for p in ordner.glob("2*.json")
                  if LAUF.match(p.stem) and not p.stem.endswith("-probelauf"))


def status(ordner: Path, max_alter_h: float, jetzt: datetime | None = None) -> tuple[int, str]:
    """Eine Zeile und ein Rückgabewert für die Überwachung.

    OK: letzter Lauf jünger als max_alter_h, alle Quellen ok.
    WARNING: eine Quelle fehlgeschlagen oder angehalten (der alte Stand dieser Quelle bleibt)
    oder unvollständig abgerufen (nichts gelöscht, der nächste Lauf holt sie erneut), auch wenn alle
    geladenen Quellen unvollständig sind; oder der Katalog (source_granularities) nicht aktualisiert (E46)
    oder im Bericht noch „ausstehend“ (Bericht vor der Katalogaktualisierung, E52);
    oder eine optionale Ausgabe (Änderungskarte, Aufräumen) gescheitert (`ausgaben_fehler`, E50).
    CRITICAL: kein lesbarer Bericht, letzter Lauf zu alt, technisch abgebrochen, oder keine geladene
    Quelle ok oder unvollständig (alle fehlgeschlagen oder angehalten). „ok“ heißt wie im
    Quellenverzeichnis und in pipeline_meta: vollständig abgerufen (verzeichnis.ergebnis); ein
    unvollständiger Abruf ist kein Erfolg (E41, E42), aber auch kein Ausfall: Mit Rhythmen lädt ein Lauf
    oft nur eine Quelle, deren Lücke allein kein CRITICAL ist (Code-Review 05.11., F2, E44).

    Ausgewertet wird nur der jüngste reguläre Bericht (Probeläufe zählen nicht), ohne Datenbank.

    Args:
        ordner: Ordner der Laufberichte (berichte/).
        max_alter_h: Höchstalter des letzten Laufs in Stunden (--max-alter-h).
        jetzt: Bezugszeitpunkt, None = aktuelle Zeit (für Tests einstellbar).

    Returns:
        (Rückgabewert, Zeile): Rückgabewert OK/WARNUNG/KRITISCH, Zeile im Format
        „GEODATEN <STATUS> - <Text> | <Perfdata>“, immer einzeilig.

    Raises:
        ValueError, wenn die lauf_id im Bericht kein gültiges Zeitformat hat; `laden.main` meldet
        jede Ausnahme hier als UNKNOWN."""
    jetzt = jetzt or datetime.now(UTC)
    liste = berichte(ordner)
    if not liste:
        return KRITISCH, f"GEODATEN CRITICAL - kein Laufbericht in {ordner}"
    b = lesen(liste[-1])
    if b is None or "lauf_id" not in b:
        # Ein abgeschnittener Bericht (Abbruch beim Schreiben) ist selbst eine Störung
        return KRITISCH, f"GEODATEN CRITICAL - letzter Laufbericht {liste[-1].name} nicht lesbar"
    alter_h = (jetzt - _zeit(b["lauf_id"])).total_seconds() / 3600
    # Quellen, deren Rhythmus noch nicht abgelaufen ist, zählen nicht (sie wurden nicht geladen)
    quellen = [q for q in b.get("quellen", []) if q.get("status") != "nicht_faellig"]
    arten = [ergebnis({"status": q.get("status", "fehler"), "unvollstaendig": q.get("unvollstaendig")})
             for q in quellen]
    n_ok = arten.count("ok")
    fehler = [q["quelle"] for q, a in zip(quellen, arten, strict=True) if a == "fehler"]
    angehalten = [q["quelle"] for q, a in zip(quellen, arten, strict=True) if a == "angehalten"]
    luecke = [q["quelle"] for q, a in zip(quellen, arten, strict=True) if a == "unvollstaendig"]
    katalog = b.get("katalog") or {}
    katalog_fehler = einzeilig(katalog.get("fehler") or "?") if katalog.get("ergebnis") == "fehler" else None
    # „ausstehend“ (E52): der Bericht vor der Katalogaktualisierung. Steht er als letzter da, läuft sie noch
    # oder der Prozess endete währenddessen ohne Abbruchbericht (SIGKILL); der Katalog ist dann nicht
    # aktualisiert, pipeline_meta.katalog_offen hält es für den nächsten Lauf fest
    if katalog.get("ergebnis") == "ausstehend":
        katalog_fehler = "ausstehend (Aktualisierung läuft noch oder wurde abgebrochen)"
    perf = (f"quellen_ok={n_ok} fehler={len(fehler)} angehalten={len(angehalten)} "
            f"unvollstaendig={len(luecke)} "
            f"alter_h={alter_h:.1f};;{max_alter_h:g}")
    if b.get("abbruch"):
        return KRITISCH, (einzeilig(f"GEODATEN CRITICAL - Lauf {b['lauf_id']} technisch abgebrochen: "
                                     f"{b['abbruch']}")[:300] + f" | {perf}")
    if alter_h > max_alter_h:
        code = KRITISCH
        text = f"letzter Lauf {b['lauf_id']} ist {alter_h:.0f} h alt (Grenze {max_alter_h:g} h)"
    elif quellen and n_ok + len(luecke) == 0:
        teile = [f"fehlgeschlagen: {', '.join(fehler)}" if fehler else "",
                 f"angehalten: {', '.join(angehalten)}" if angehalten else ""]
        code, text = KRITISCH, (f"keine Quelle ok oder unvollständig im Lauf {b['lauf_id']} ("
                                + "; ".join(t for t in teile if t) + ")")
    elif fehler or angehalten or luecke or katalog_fehler or b.get("ausgaben_fehler"):
        teile = [f"fehlgeschlagen: {', '.join(fehler)}" if fehler else "",
                 f"angehalten: {', '.join(angehalten)}" if angehalten else "",
                 f"unvollständig: {', '.join(luecke)}" if luecke else "",
                 f"Katalog nicht aktualisiert: {katalog_fehler}"[:120] if katalog_fehler else "",
                 # Fehler optionaler Ausgaben (E50): Bericht vollständig, Karte oder Aufräumen fehlt
                 einzeilig(f"Ausgabe gescheitert: {b['ausgaben_fehler'][0]}")[:120]
                 if b.get("ausgaben_fehler") else ""]
        code, text = WARNUNG, f"Lauf {b['lauf_id']}, {n_ok} ok, " + "; ".join(t for t in teile if t)
    else:
        code, text = OK, f"Lauf {b['lauf_id']}, {n_ok} Quellen ok"
    return code, f"GEODATEN {STATUSNAME[code]} - {einzeilig(text)} | {perf}"


def kennzahlen(ordner: Path, von: datetime | None = None, bis: datetime | None = None) -> str:
    """Zusammenfassung über einen Zeitraum, als Markdown für Zwischenberichte und
    Verwendungsnachweise.

    Liest nur die regulären Laufberichte in `ordner` (keine Probeläufe, keine Datenbank). Gezählt wird
    je Quelle nach demselben Ergebnis wie im Quellenverzeichnis (`verzeichnis.ergebnis`); Quellen, die
    im Lauf nicht fällig waren, zählen nicht mit.

    Args:
        ordner: Ordner der Laufberichte (berichte/).
        von: Beginn des Zeitraums (einschließlich), None = ohne Untergrenze.
        bis: Ende des Zeitraums (ausschließlich), None = ohne Obergrenze.

    Returns:
        Markdown mit Gesamtzahlen und einer Tabelle je Quelle, oder „Keine Läufe im Zeitraum.“.
        Unlesbare Berichte im Zeitraum werden übersprungen und mit Namen (höchstens fünf) genannt."""
    laeufe, unlesbar = [], []
    for p in berichte(ordner):
        # Zeitpunkt aus dem Dateinamen, nicht aus dem Inhalt: so fällt auch ein unlesbarer Bericht
        # in den richtigen Zeitraum und wird dort als übersprungen gezählt
        t = _zeit(LAUF.match(p.stem).group(1))
        if (von and t < von) or (bis and t >= bis):
            continue
        b = lesen(p)
        if b is None or "lauf_id" not in b:
            unlesbar.append(p.name)
        else:
            laeufe.append(b)
    if not laeufe:
        return "Keine Läufe im Zeitraum.\n"
    je: dict[str, dict] = {}
    for b in laeufe:
        for q in b.get("quellen", []):
            if q.get("status") == "nicht_faellig":
                continue
            e = je.setdefault(q["quelle"], {"typ": q.get("typ"), "ok": 0, "unvollstaendig": 0, "fehler": 0,
                                            "angehalten": 0, "neu": 0, "geaendert": 0, "geloescht": 0,
                                            "objekte": None, "meldungen": 0})
            # Erfolg wie im Quellenverzeichnis und in pipeline_meta (Codex-Prüfung 05.11., B3): ein
            # unvollständiger Abruf zählt eigens, nicht als „ok“
            art = ergebnis({"status": q.get("status", "fehler"), "unvollstaendig": q.get("unvollstaendig")})
            e[art] = e.get(art, 0) + 1
            z = q.get("zaehler") or {}
            if q.get("status") == "ok":   # übernommen wurde auch bei Lücke (nur nichts gelöscht)
                for k in ("neu", "geaendert", "geloescht"):
                    e[k] += z.get(k, 0)
            # Objektzahl nur aus vollständigen Abrufen; die Berichte laufen von alt nach jung, also
            # bleibt die des jüngsten vollständigen Abrufs stehen
            if art == "ok":
                e["objekte"] = (q.get("info") or {}).get("objekte", e["objekte"])
            e["meldungen"] += 1 if q.get("meldung") else 0
    erster, letzter = laeufe[0]["lauf_id"], laeufe[-1]["lauf_id"]
    zeilen = [
        f"# Kennzahlen der Geodaten-Pipeline, {_zeit(erster):%d.%m.%Y} bis {_zeit(letzter):%d.%m.%Y}",
        "",
        f"- Läufe: {len(laeufe)}",
        *([f"- Laufberichte nicht lesbar, übersprungen: {len(unlesbar)} ({', '.join(unlesbar[:5])}"
           f"{' …' if len(unlesbar) > 5 else ''})"] if unlesbar else []),
        f"- Quellen: {len(je)}",
        f"- Objekte im Bestand nach dem letzten erfolgreichen Lauf je Quelle: "
        f"{sum(e['objekte'] or 0 for e in je.values())}",
        f"- Änderungen übernommen: {sum(e['neu'] for e in je.values())} neu, "
        f"{sum(e['geaendert'] for e in je.values())} geändert, "
        f"{sum(e['geloescht'] for e in je.values())} gelöscht",
        f"- Störungen abgefangen (Quelle fehlgeschlagen oder angehalten, alter Stand blieb): "
        f"{sum(e['fehler'] + e['angehalten'] for e in je.values())}",
        f"- Unvollständige Abrufe (übernommen, nichts gelöscht, beim nächsten Lauf wiederholt): "
        f"{sum(e['unvollstaendig'] for e in je.values())}",
        f"- Meldungsentwürfe an Anbieter: {sum(e['meldungen'] for e in je.values())}",
        "",
        "| Quelle | Typ | Läufe ok | unvollständig | fehlgeschlagen | angehalten | Objekte | neu | geändert "
        "| gelöscht |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, e in sorted(je.items()):
        zeilen.append(f"| {name} | {e['typ']} | {e['ok']} | {e['unvollstaendig']} | {e['fehler']} | "
                      f"{e['angehalten']} | "
                      f"{e['objekte'] if e['objekte'] is not None else '–'} | {e['neu']} | "
                      f"{e['geaendert']} | {e['geloescht']} |")
    return "\n".join(zeilen) + "\n"


def aufraeumen(ordner: Path, tage: int, jetzt: datetime) -> list[str]:
    """Löscht Laufdateien (Bericht, Karte, Meldungen, Archiv) älter als `tage` (E18).

    Bleibt immer stehen: der jüngste reguläre Bericht (Vergleichsstand für den nächsten Lauf),
    auch wenn er älter ist, und alles, was nicht wie ein Lauf heißt (quellenverzeichnis.*).
    Mit dem jüngsten Bericht bleiben auch alle Dateien derselben Laufkennung stehen (Textbericht,
    Karte, Meldungsentwürfe, Archivordner), weil der Schutz an der Kennung hängt, nicht an der Datei.

    Args:
        ordner: Ordner der Laufberichte; durchsucht werden er selbst und ordner/archiv/.
        tage: Aufbewahrungsfrist in Tagen.
        jetzt: Bezugszeitpunkt (Start des laufenden Laufs), damit die Grenze für alle Dateien gleich ist.

    Returns:
        Namen der gelöschten Dateien und Archivordner.

    Seiteneffekte:
        Löscht Dateien und Archivordner (je Lauf ein Ordner mit GeoJSON-Dateien) im Dateisystem.
        Ein Fehler beim Löschen (etwa fehlende Rechte) geht als Ausnahme an den Aufrufer."""
    grenze = jetzt - timedelta(days=tage)
    regulaer = berichte(ordner)
    schutz = LAUF.match(regulaer[-1].stem).group(1) if regulaer else None
    weg = []
    kandidaten = list(ordner.glob("2*")) + list((ordner / "archiv").glob("2*"))
    for p in sorted(kandidaten):
        # Nur, was wie ein Lauf heißt; das Alter kommt aus der Kennung, nicht aus dem Änderungsdatum
        m = LAUF.match(p.name)
        if not m or m.group(1) == schutz or _zeit(m.group(1)) >= grenze:
            continue
        if p.is_dir():
            # Archivordner eines Laufs: enthält nur Dateien (eine je Quelle), keine Unterordner
            for kind in p.iterdir():
                kind.unlink()
            p.rmdir()
        else:
            p.unlink()
        weg.append(p.name)
    return weg


def archiv_schreiben(conn, ordner: Path, lauf_id: str, quelle: str, z) -> Path:
    """Stand einer Quelle nach dem Lauf als GeoJSON (gzip), damit sich später sagen lässt,
    welcher Datenstand einer Auswertung zugrunde lag. Die Tabellen bleiben ohne Versionen (E2, E17).
    Gelesen werden die Zeilen der Zieltabelle, die laut Bestandsregister zu dieser Quelle gehören.

    Args:
        conn: offene Verbindung; der Aufrufer (`laden._nachlauf`) hält eine Transaktion offen.
        ordner: Ordner der Laufberichte; die Datei liegt unter archiv/<lauf_id>/.
        lauf_id: Laufkennung, zugleich Ordnername und Eigenschaft `_lauf` jedes Objekts.
        quelle: Name der Quelle aus der Konfiguration, zugleich Dateiname.
        z: Ziel der Quelle (`ziel.aus_konfiguration`).

    Returns:
        Pfad der geschriebenen Datei <ordner>/archiv/<lauf_id>/<quelle>.geojson.gz.

    Raises:
        Fehler aus `ziel.pruefen` (Zieltabelle oder Spalten fehlen), Datenbank- und Dateifehler. Der
        Aufrufer macht daraus eine Warnung der Quelle (nur eine verlorene Datenbankverbindung reicht er
        weiter); eine halb geschriebene Datei bleibt dann liegen.

    Seiteneffekte:
        Liest nur aus der Datenbank (Planer-Einstellung per SET LOCAL), schreibt eine Datei."""
    from . import ziel as zielmod
    datei = ordner / "archiv" / lauf_id / f"{quelle}.geojson.gz"
    datei.parent.mkdir(parents=True, exist_ok=True)
    with conn.cursor() as cur, gzip.open(datei, "wt", encoding="utf-8") as f:
        zielmod.planer_einstellen(cur)  # läuft in der Transaktion des Aufrufers (laden._nachlauf)
        zielmod.pruefen(cur, z)
        cur.execute(zielmod.archiv_sql(quelle, z))
        f.write('{"type":"FeatureCollection","name":' + json.dumps(quelle) + ',"features":[')
        # Die Geometrie kommt schon als GeoJSON-Text aus der Datenbank (ziel.archiv_sql, 7 Nachkommastellen),
        # die übrigen Spalten als jsonb ohne die Geometriespalte; hier wird nur noch zusammengesetzt
        for i, (oid, geom, werte) in enumerate(cur):
            feat = {"type": "Feature", "id": oid, "geometry": json.loads(geom) if geom else None,
                    "properties": {**(werte or {}), "_tabelle": z.name, "_lauf": lauf_id}}
            f.write(("," if i else "") + json.dumps(feat, ensure_ascii=False))
        f.write("]}")
    return datei
