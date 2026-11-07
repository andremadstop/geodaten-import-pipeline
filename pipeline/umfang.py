"""Umfangsänderung einer Quelle sperren, bis jemand bestätigt (E52).

Anlass (Mitbewerber-Sichtung 08.11.2026): Ändert jemand die Konfiguration einer schon geladenen Quelle so,
dass sie einen anderen Ausschnitt beschreibt (andere Adresse, anderer Feature-Typ, kleinere BBOX, andere
Indikatoren, anderer Schlüssel, andere Zieltabelle oder Raumebene), sieht der nächste vollständige Lauf die
bisherigen Zeilen als „nicht mehr in der Quelle“ und löscht sie. Der Rückgang-Schutz (E4) fängt das nur ab,
wenn mehr als die Hälfte wegfällt; ein Tippfehler in der BBOX, der 40 % abschneidet, ginge durch.

Deshalb merkt sich die Pipeline je Quelle den Umfang, unter dem sie zuletzt vollständig abgeglichen wurde
(pipeline_meta.quellenstand.umfang), und vergleicht ihn vor dem Schreiben mit der Konfiguration jetzt:

  - gleich, oder noch nie gemerkt (erster Lauf, oder Einrichtung von vor E52): wie bisher;
  - geändert, und der Lauf würde Zeilen löschen (oder einen Quellschlüssel ersetzen): Quelle angehalten,
    alter Stand bleibt, der Bericht nennt die geänderten Schlüssel und wie man freigibt;
  - geändert, ohne Löschung: Zusätze und Änderungen laufen durch; nach einem vollständigen Abruf gilt der neue
    Umfang als gemerkt, nach einem unvollständigen bleibt der alte (sonst löschte der nächste vollständige
    Lauf ohne Bestätigung).

Freigabe für genau einen Umfang: einmal `--umfang-bestaetigen QUELLE` beim Aufruf, oder in der Quelle
`umfang_bestaetigt: <Kennung>` mit der Kennung, die der Bericht nennt (die ersten Zeichen des neuen
Fingerabdrucks). Der Eintrag in der Konfiguration gilt nur für genau diesen Umfang; nach dem Lauf ist er
ohne Wirkung und kann entfernt werden, eine spätere Änderung sperrt wieder. Jede genutzte Bestätigung steht
als Warnung im Bericht und damit in pipeline_meta.quellenlauf.

Was zum Umfang gehört: jeder Schlüssel der Quelle und ihres Ziels außer denen in UNERHEBLICH bzw.
ZIEL_UNERHEBLICH (Beschreibung, Rhythmus, Zeitgrenzen, Größen- und Seitengrenzen, Schutzschwellen, Karte und
die Schalter von E52). Auch unbekannte und künftige Schlüssel zählen: lieber einmal zu viel bestätigen als
eine Änderung des Ausschnitts übersehen. Anders als der Fingerabdruck in unveraendert geht der Code der
Pipeline nicht ein; ein Update der Pipeline ändert den Umfang einer Quelle nicht.

Gespeichert wird nicht die Konfiguration selbst, sondern je Schlüssel eine Prüfsumme seines Werts (teile);
so nennt der Bericht, welche Schlüssel sich geändert haben, ohne Adressen oder Pfade in der Datenbank
abzulegen. Der Fingerabdruck ist die SHA-256 über diese Teile.

Stellung im Ablauf: laden._quelle_abgleichen ruft pruefen nach dem Vergleich mit dem Register und der
Löschentscheidung, vor Karte und Schreiben; bis dahin gibt es nur temporäre Tabellen. Die Ausnahmen von
Rückgang-Schutz, Nullmenge und Löschsperre bei unvollständigem Abruf bleiben unberührt: Eine Bestätigung des
Umfangs hebt keine davon auf.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

# Prüfsumme je Wert in derselben kanonischen Form wie der Fingerabdruck in unveraendert
from .unveraendert import summe

# Schlüssel einer Quelle, die nicht bestimmen, welche Objekte sie liefert und wohin sie geschrieben werden:
# Beschreibung und Lizenz (gehen nur nach table_metadata), Rhythmus, Zeitgrenzen, Pausen, Größen- und
# Seitengrenzen der Abrufe, Schutzschwellen, Karte und die Schalter von E52. Alles andere zählt, auch was
# hier niemand vorhergesehen hat
UNERHEBLICH = frozenset({
    "titel", "beschreibung", "lizenz", "kontakt", "rhythmus", "aktiv", "zeitbudget_min", "db_sperre_max_s",
    "pause_s", "seitengroesse", "max_je_kachel", "max_mb", "max_entpackt_mb", "max_packrate", "max_objekt_mb",
    "cache", "robots_freigabe", "max_rueckgang", "karte", "karte_max_objekte", "unveraendert_ueberspringen",
    "vollabgleich_tage", "umfang_bestaetigt"})
# Unter `ziel`: nur der Metadatensatz (table_metadata) gehört nicht zum Umfang der Fachdaten
ZIEL_UNERHEBLICH = frozenset({"metadaten"})

# Umgebungsvariable mit der abgelegten INKAR-Datei; Vorrang vor `datei` und `url` (quellen.inkar, E48), daher
# Teil des Umfangs einer INKAR-Quelle, wenn sie gesetzt ist (teile)
INKAR_UMGEBUNG = "PIPELINE_INKAR_DATEI"

# Schlüssel der Freigabe in der Konfiguration und Länge der Kennung im Bericht (Hexadezimalzeichen)
SCHLUESSEL = "umfang_bestaetigt"
KENNUNG_LAENGE = 12
_KENNUNG = re.compile(rf"^[0-9a-f]{{{KENNUNG_LAENGE},64}}$")


def teile(qcfg: dict) -> dict[str, str]:
    """Je Schlüssel des Umfangs die Prüfsumme seines Werts: Schlüssel der Quelle mit ihrem Namen, Schlüssel
    des Ziels als `ziel.<name>`. Ein Ziel, das kein Wörterbuch ist, zählt als ganzes unter `ziel`.

    INKAR (Gesamtprüfung E52 durch Codex, Muss 1): Die Umgebungsvariable PIPELINE_INKAR_DATEI hat beim
    Adapter Vorrang vor `datei` und `url` (quellen.inkar). Ist sie gesetzt, zählt deshalb ihr Wert als Teil
    `PIPELINE_INKAR_DATEI` zum Umfang, und `datei` aus der Konfiguration entfällt (sie wird dann nicht
    gelesen). Sonst ließe ein Wechsel von einer vollständigen auf eine Teildatei über die Umgebung den Umfang
    gleich, und der Lauf löschte ohne Bestätigung, was in der Teildatei fehlt."""
    umgebung = os.environ.get(INKAR_UMGEBUNG) if qcfg.get("typ") == "inkar" else None
    aus = {str(k): summe(v) for k, v in qcfg.items()
           if k not in UNERHEBLICH and k != "ziel" and not (umgebung and k == "datei")}
    if umgebung:
        aus[INKAR_UMGEBUNG] = summe(umgebung)
    z = qcfg.get("ziel")
    if isinstance(z, dict):
        aus.update({f"ziel.{k}": summe(v) for k, v in z.items() if k not in ZIEL_UNERHEBLICH})
    elif z is not None:
        aus["ziel"] = summe(z)
    return aus


def fingerabdruck(teile_: dict[str, str]) -> str:
    """SHA-256 über die Teile (sortiert), hexadezimal; seine ersten KENNUNG_LAENGE Zeichen sind die Kennung
    im Bericht und in `umfang_bestaetigt`."""
    return hashlib.sha256(json.dumps(sorted(teile_.items())).encode("utf-8")).hexdigest()


def geaendert(alt: dict[str, str], neu: dict[str, str]) -> list[str]:
    """Namen der Schlüssel, die hinzugekommen, weggefallen oder anders sind, sortiert."""
    return sorted(k for k in alt.keys() | neu.keys() if alt.get(k) != neu.get(k))


def konfig_fehler(cfg: dict) -> list[str]:
    """Prüft `umfang_bestaetigt` in allen Quellen (auch abgeschalteten), bevor eine Quelle lädt; laden macht
    aus jedem Fund einen KonfigFehler. Erlaubt ist eine Kennung aus KENNUNG_LAENGE bis 64 Kleinbuchstaben
    a-f und Ziffern (so, wie der Bericht sie nennt). `true` oder ein freier Text wäre eine Dauerfreigabe
    für jeden künftigen Umfang und wird abgelehnt.

    Returns:
        Liste der Fehlertexte, leer, wenn alles gültig ist."""
    fehler = []
    for name, q in (cfg.get("quellen") or {}).items():
        if isinstance(q, dict) and SCHLUESSEL in q:
            w = q[SCHLUESSEL]
            if not (isinstance(w, str) and _KENNUNG.match(w)):
                fehler.append(f"{name}: {SCHLUESSEL} muss die Kennung des Umfangs aus dem Bericht sein "
                              f"({KENNUNG_LAENGE} bis 64 Zeichen 0-9 und a-f), nicht {w!r}")
    return fehler


def bestaetigung(qcfg: dict, abdruck: str, aufruf: bool) -> str | None:
    """Wodurch ist der Umfang `abdruck` für diesen Lauf bestätigt? "--umfang-bestaetigen" (Aufruf),
    "Konfiguration (umfang_bestaetigt)" (Kennung passt zum Fingerabdruck) oder None."""
    if aufruf:
        return "--umfang-bestaetigen"
    w = qcfg.get(SCHLUESSEL)
    if isinstance(w, str) and _KENNUNG.match(w) and abdruck.startswith(w):
        return f"Konfiguration ({SCHLUESSEL})"
    return None


def lesen(cur, name: str) -> dict[str, str] | None:
    """Gemerkter Umfang der Quelle aus pipeline_meta.quellenstand, nur nach dem Namen der Quelle gesucht
    (nicht nach der Tabelle: eine geänderte Zieltabelle ist selbst eine Umfangsänderung und darf nicht als
    „noch nie gemerkt“ durchgehen). None, wenn es keinen Eintrag gibt oder die Spalte leer ist."""
    cur.execute("SELECT umfang FROM pipeline_meta.quellenstand WHERE quelle = %s", (name,))
    zeile = cur.fetchone()
    if not zeile or not zeile[0]:
        return None
    w = zeile[0]
    return json.loads(w) if isinstance(w, str) else dict(w)


def entscheiden(alt: dict[str, str] | None, neu: dict[str, str], loeschungen: int, vollstaendig: bool,
                bestaetigt: str | None) -> tuple[bool, bool]:
    """Reine Entscheidung (E52): Anhalten, und soll der neue Umfang gemerkt werden?

    Args:
        alt: gemerkter Umfang (teile) oder None (noch nie gemerkt).
        neu: Umfang jetzt (teile).
        loeschungen: Zeilen, die der Lauf tatsächlich löschen würde, plus ersetzte Quellschlüssel (nach der
            Löschentscheidung: bei unvollständigem Abruf oder `loeschen: false` sind Löschkandidaten schon
            zurückgehalten und zählen nicht).
        vollstaendig: Abruf vollständig (keine Lücke gemeldet).
        bestaetigt: Ergebnis von bestaetigung oder None.

    Returns:
        (anhalten, merken). Anhalten nur bei geändertem Umfang mit Löschungen ohne Bestätigung. Gemerkt wird
        der neue Umfang, wenn er gleich oder noch nie gemerkt war, oder wenn er geändert ist und der Abruf
        vollständig war (mit Löschungen nur bestätigt, sonst hielte die Quelle an). Nach einem unvollständigen
        Abruf mit geändertem Umfang bleibt der alte gemerkt, auch mit Bestätigung: Gelöscht wurde dann nichts,
        und der nächste vollständige Lauf soll nicht ohne Bestätigung löschen."""
    if alt is None or alt == neu:
        return False, True
    if loeschungen and not bestaetigt:
        return True, False
    return False, vollstaendig


def kennung(abdruck: str) -> str:
    """Kurze Kennung eines Fingerabdrucks für Bericht und `umfang_bestaetigt`."""
    return abdruck[:KENNUNG_LAENGE]
