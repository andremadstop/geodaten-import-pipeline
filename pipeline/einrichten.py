"""Einrichten der Datenbank für die Pipeline, einmalig und nach jeder Änderung an den Zielen.

Aufruf (als Administrator der Datenbank, Zugang über PGHOST, PGUSER, PGPASSWORD, PGDATABASE):
    python -m pipeline.einrichten --config config/quellen.yaml [--haerten]

Legt an bzw. bringt auf Stand, ohne Bestandstabellen zu verändern (Antworten 29 und 47 der TH):
  - Schema pipeline_meta mit Laufprotokoll, Änderungen, Bestandsregister, Quellenstand
    (sql/pipeline_meta.sql)
  - Rolle pipeline_import (Passwort aus IMPORT_PASSWORD): je Zieltabelle aus der Konfiguration
    SELECT, INSERT/UPDATE nur auf die zugeordneten Spalten, Nutzung der Sequenzen der Tabelle und
    DELETE nur, wenn mindestens eine Quelle dort löschen darf (nicht bei `loeschen: false`, E35);
    SELECT auf Gebietstabellen; table_metadata lesen, einfügen, Metadatenspalten ändern;
    pipeline_meta lesen und schreiben; temporäre Tabellen und für Quellen mit Geometrie eine
    temporäre Funktion (plpgsql) in pg_temp, das Recht `USAGE ON LANGUAGE plpgsql` kommt in der
    Regel über PUBLIC (einrichten prüft es und warnt). Kein CREATE, ALTER, DROP, TRUNCATE.
  - Passwörter gehen nur als SCRAM-Hash an den Server, nicht im Klartext.
    Rechte zum Schreiben (INSERT, UPDATE, DELETE, bei Sequenzen USAGE, UPDATE) außerhalb von
    pipeline_meta, die nicht mehr zur Konfiguration passen, entzieht einrichten (Sollstand, E46);
    deshalb einrichten immer mit allen Konfigurationen aufrufen, die dieselbe Datenbank beschreiben
    (--config mehrfach). Was sich nicht entziehen lässt (von einer anderen Rolle vergeben), bleibt
    stehen und steht als Warnung im Protokoll (Nachprüfung zu E46).
  - Funktion pipeline_meta.katalog_aktualisieren() (SECURITY DEFINER, Eigentümer ist, wer einrichten
    zuerst ausgeführt hat; CREATE OR REPLACE ändert ihn nicht): aktualisiert nur die Materialized
    View public.source_granularities des Katalogs (Antwort 75, E46); ausführen darf sie nur
    pipeline_import. einrichten warnt, wenn ihr Eigentümer die View nicht aktualisieren darf
    (Nachprüfung zu E46)
  - Rolle mosidi_lesen (Passwort aus LESE_PASSWORD): nur lesen
Gibt es eine der beiden Rollen schon mit weiteren Rechten (SUPERUSER, CREATEROLE, CREATEDB, BYPASSRLS,
REPLICATION, Mitglied einer anderen Rolle oder, seit der Nachprüfung zu E47, Eigentümerin der Datenbank,
eines Schemas, einer Tabelle oder Funktion), bricht einrichten ab, bevor es etwas ändert, und nennt die
Abhilfe (Prüfbericht 05.11. abends, Befund 11, E47).
Mit --haerten zusätzlich: PUBLIC verliert alle Rechte auf die Datenbank (CONNECT, TEMPORARY, CREATE)
und CREATE auf das Schema public; die beiden Rollen behalten ihre ausdrücklich vergebenen Rechte. Nur
für die eigene Datenbank der Pipeline gedacht; in einer gemeinsam genutzten Datenbank wie der von
MOSIDI nicht verwenden, dort könnten andere Dienste (pg_tileserv, GeoServer) auf diese Rechte
angewiesen sein.

Läuft beliebig oft; Rollen bekommen dabei das Passwort aus der Umgebung neu gesetzt. Alles läuft in
einer Transaktion: Scheitert ein Schritt, bleibt die Datenbank wie vorher (Ausnahme: ein REVOKE, das
scheitert, wird in einem eigenen Sicherungspunkt übergangen, siehe _entziehen).

Stellung im Ablauf: einrichten läuft vor dem ersten Lauf und nach jeder Änderung an den Zielen, als
Administrator. Der Lauf selbst (pipeline.laden) nutzt von hier nur verbinden(); er prüft mit
meta_pruefen, ob das Schema zur Fassung passt, und verweist sonst hierher. Die Ziele liest einrichten
wie der Lauf über pipeline.ziel.aus_konfiguration.

Wichtigste Entscheidungen (docs/entscheidungen.md): Datenbankrollen nach geringsten Rechten (E10), aus
den Zielen der Konfiguration bis auf die Spalte (E22), kein Löschrecht auf Raumdaten (E35), Passwörter
nur als SCRAM-Hash (E39), Schemarechte für weitere Schemas (E44), Sollstand der Schreibrechte und
Katalogfunktion (E46), Abbruch bei zu weiten vorhandenen Rollen (E47).
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from pathlib import Path

import psycopg
import yaml
from psycopg import sql

from . import ziel as zielmod

log = logging.getLogger("pipeline.einrichten")

IMPORT_ROLLE = "pipeline_import"
LESE_ROLLE = "mosidi_lesen"
# Relativ zum Paket, nicht zum Arbeitsverzeichnis: einrichten findet die Datei auch im Container
META_DDL = Path(__file__).resolve().parent.parent / "sql" / "pipeline_meta.sql"


def verbinden(dsn: str = "", warten_s: float = 60, **kw) -> psycopg.Connection:
    """Verbindung mit Wiederholung, solange die Datenbank noch startet.

    Wiederholt nur bei psycopg.OperationalError (Server nicht erreichbar, startet noch), alle 2 s, bis
    `warten_s` überschritten ist; andere Fehler gehen sofort durch. Auch eine abgewiesene Anmeldung
    meldet psycopg als OperationalError, sie wird deshalb ebenfalls bis zum Ende der Wartezeit
    wiederholt. Auch der Lauf (pipeline.laden) verbindet sich hierüber.

    Args:
        dsn: Verbindungsangabe; leer heißt: libpq nimmt PGHOST, PGUSER, PGPASSWORD, PGDATABASE.
        warten_s: wie lange insgesamt wiederholt wird, in Sekunden.
        **kw: weiter an psycopg.connect, etwa connect_timeout.

    Returns:
        Offene Verbindung (ohne autocommit: jede Abfrage öffnet eine Transaktion).

    Raises:
        psycopg.OperationalError: auch nach Ablauf der Wartezeit keine Verbindung.
    """
    ende = time.monotonic() + warten_s
    while True:
        try:
            return psycopg.connect(dsn, **kw)
        except psycopg.OperationalError:
            if time.monotonic() > ende:
                raise
            time.sleep(2)


def ziele(cfg: dict) -> list[zielmod.Ziel]:
    """Ziele aller Quellen mit Abschnitt `ziel`, auch abgeschalteter (`aktiv: false`); aus ihnen
    entstehen die Rechte. Quellen ohne `ziel` bekommen keine Rechte.

    Args:
        cfg: Konfiguration (bei mehreren --config die zusammengeführten Quellen).

    Returns:
        Liste der Ziele in der Reihenfolge der Quellen.

    Raises:
        ziel.ZielFehler: ein Ziel ist unvollständig (siehe ziel.aus_konfiguration).
    """
    aus = []
    for name, q in cfg.get("quellen", {}).items():
        if q.get("ziel"):
            aus.append(zielmod.aus_konfiguration(name, q))
    return aus


class RolleZuWeit(RuntimeError):
    """Eine vorhandene Rolle der Pipeline hat mehr Rechte, als sie braucht; einrichten ändert nichts."""


# Rollenattribute, die über die beschriebenen Rechte hinausgehen (pg_roles), mit ihrem Schlüsselwort
ROLLEN_ATTRIBUTE = (("rolsuper", "SUPERUSER"), ("rolcreaterole", "CREATEROLE"), ("rolcreatedb", "CREATEDB"),
                    ("rolbypassrls", "BYPASSRLS"), ("rolreplication", "REPLICATION"))


# Objekte, die einer Rolle gehören (Nachprüfung zu E47): Der Eigentümer hat alle Rechte am Objekt, auch DDL
# und TRUNCATE, unabhängig von GRANTs. Temporäre Objekte zählen nicht: Die Importrolle legt während eines
# Laufs Tabellen und Funktionen in pg_temp an, ein gleichzeitiges einrichten sähe sie sonst
_EIGENTUM_SQL = """
    SELECT 'Datenbank ' || quote_ident(datname) FROM pg_database WHERE datdba = to_regrole(%(r)s)
    UNION ALL
    SELECT 'Schema ' || quote_ident(nspname) FROM pg_namespace
    WHERE nspowner = to_regrole(%(r)s) AND nspname !~ '^pg_(toast_)?temp_'
    UNION ALL
    SELECT 'Tabelle ' || c.oid::regclass::text FROM pg_class c
    WHERE c.relowner = to_regrole(%(r)s) AND c.relpersistence <> 't'
    AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
    UNION ALL
    SELECT 'Funktion ' || p.oid::regprocedure::text FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE p.proowner = to_regrole(%(r)s) AND n.nspname !~ '^pg_(toast_)?temp_'
    LIMIT 11"""


def rolle_pruefen(cur, name: str) -> list[str]:
    """Was eine schon vorhandene Rolle über die Rechte hinaus hat, die einrichten vergibt (Prüfbericht 05.11.
    abends, Befund 11, E47): Attribute aus ROLLEN_ATTRIBUTE und jede Mitgliedschaft in einer anderen Rolle
    (pg_auth_members, die Rolle als Mitglied: sie erbt deren Rechte, etwa pg_read_all_data). Die umgekehrte
    Richtung zählt nicht: Ab PostgreSQL 16 wird ein Administrator mit CREATEROLE, der eine Rolle anlegt,
    selbst Mitglied dieser Rolle; das gibt der Rolle keine Rechte. Seit der Nachprüfung zu E47 auch Eigentum:
    die Datenbank, Schemas, Tabellen (auch Views, Sequenzen) und Funktionen der aktuellen Datenbank, die der
    Rolle gehören, ohne temporäre Objekte (_EIGENTUM_SQL, höchstens elf genannt). Rückgabe: leere Liste, wenn
    die Rolle fehlt oder eng genug ist.

    Args:
        cur: Cursor des Administrators (liest nur Systemkataloge).
        name: Name der Rolle.

    Returns:
        Lesbare Teile wie "SUPERUSER", "Mitglied von <Rolle>", "Eigentümerin von <Objekt>".
    """
    # Spaltennamen als Identifier aus der festen Liste ROLLEN_ATTRIBUTE, nichts aus der Konfiguration
    cur.execute(sql.SQL("SELECT {} FROM pg_roles WHERE rolname = %s").format(
        sql.SQL(", ").join(sql.Identifier(a) for a, _ in ROLLEN_ATTRIBUTE)), (name,))
    zeile = cur.fetchone()
    if zeile is None:
        return []
    teile = [wort for (_, wort), gesetzt in zip(ROLLEN_ATTRIBUTE, zeile, strict=True) if gesetzt]
    cur.execute("SELECT m.roleid::regrole::text FROM pg_auth_members m WHERE m.member = to_regrole(%s) "
                "ORDER BY 1", (name,))
    teile += [f"Mitglied von {r}" for (r,) in cur.fetchall()]
    cur.execute(_EIGENTUM_SQL, {"r": name})
    return teile + [f"Eigentümerin von {o}" for (o,) in cur.fetchall()]


def zu_weit_text(name: str, teile: list[str]) -> str:
    """Meldung mit Abhilfe für RolleZuWeit, eine Zeile.

    Die Abhilfe nennt je Art die passenden SQL-Befehle: ALTER ROLE … NO<Attribut>, REVOKE der
    Mitgliedschaft, ALTER DATABASE … OWNER und für anderes Eigentum REASSIGN OWNED. Sie wird nur
    angezeigt, nicht ausgeführt.

    Args:
        name: Name der Rolle.
        teile: Rückgabe von rolle_pruefen (nicht leer).

    Returns:
        Meldung mit Befund, Abhilfe und Verweis auf die Betriebsdoku.
    """
    # Aufteilen nach den Präfixen, die rolle_pruefen setzt
    attribute = [t for t in teile if not t.startswith(("Mitglied von ", "Eigentümerin von "))]
    rollen = [t.removeprefix("Mitglied von ") for t in teile if t.startswith("Mitglied von ")]
    eigentum = [t.removeprefix("Eigentümerin von ") for t in teile if t.startswith("Eigentümerin von ")]
    datenbanken = [o.removeprefix("Datenbank ") for o in eigentum if o.startswith("Datenbank ")]
    abhilfe = ([f"ALTER ROLE {name} {' '.join('NO' + a for a in attribute)}"] if attribute else []) + \
        [f"REVOKE {r} FROM {name}" for r in rollen] + \
        [f"ALTER DATABASE {d} OWNER TO <Administratorrolle>" for d in datenbanken] + \
        ([f"REASSIGN OWNED BY {name} TO <Administratorrolle> (in jeder betroffenen Datenbank)"]
         if len(eigentum) > len(datenbanken) else [])
    return (f"Rolle {name} gibt es schon, mit mehr Rechten, als die Pipeline braucht: {', '.join(teile)}. "
            f"einrichten bricht ab und hat nichts geändert. Abhilfe als Administrator: {'; '.join(abhilfe)}; "
            "danach einrichten erneut ausführen. Braucht ein anderer Dienst diese Rechte, gehört die Rolle "
            "nicht der Pipeline (docs/betrieb.md, docs/sicherheit.md)")


def _rolle(cur, name: str, passwort: str) -> None:
    """Rolle anlegen oder Passwort neu setzen. An den Server geht nur der SCRAM-Hash, nie das
    Passwort: Scheitert die Anweisung, steht sie sonst samt Passwort im Server-Log
    (log_min_error_statement), ebenso bei log_statement = ddl/all und in pg_stat_statements; in einer
    gemeinsam genutzten Datenbank lesen diese Logs auch andere.

    Args:
        cur: Cursor des Administrators.
        name: Name der Rolle.
        passwort: Klartextpasswort aus der Umgebung; verlässt den Prozess nur als Hash.
    """
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    befehl = "ALTER ROLE {} LOGIN PASSWORD {}" if cur.fetchone() else "CREATE ROLE {} LOGIN PASSWORD {}"
    # Der Hash entsteht im Client (libpq PQencryptPasswordConn, bei SCRAM mit zufälligem Salz)
    geheim = cur.connection.pgconn.encrypt_password(passwort.encode(), name.encode(), b"scram-sha-256")
    # Einen Wert im SCRAM-Format speichert der Server unverändert als Hash
    cur.execute(sql.SQL(befehl).format(sql.Identifier(name), sql.Literal(geheim.decode("ascii"))))


def sprache_pruefen(cur, rolle: str = IMPORT_ROLLE) -> str | None:
    """Die Importrolle legt für jede Quelle mit Geometrie eine Funktion in pg_temp an (plpgsql,
    ziel.GEOM_LESEN). Das Recht dazu hat sie in der Regel über PUBLIC. Hat eine gehärtete Datenbank
    PUBLIC `USAGE ON LANGUAGE plpgsql` entzogen, scheiterte sonst jede Geometriequelle erst beim
    Lauf. Rückgabe: Warnung oder None.

    Nur eine Warnung, kein Abbruch: Quellen ohne Geometrie laufen auch ohne dieses Recht. einrichten
    ruft die Prüfung nur auf, wenn mindestens ein Ziel eine Geometriespalte hat.

    Args:
        cur: Cursor des Administrators.
        rolle: zu prüfende Rolle, Vorgabe die Importrolle.
    """
    cur.execute("SELECT has_language_privilege(%s, 'plpgsql', 'USAGE')", (rolle,))
    if cur.fetchone()[0]:
        return None
    return (f"Warnung: {rolle} darf plpgsql nicht nutzen; Quellen mit Geometrie scheitern damit. "
            f"Abhilfe (als Eigentümer der Sprache): GRANT USAGE ON LANGUAGE plpgsql TO {rolle}")


def _sequenzen(cur, z: zielmod.Ziel) -> list[str]:
    """Sequenzen, die die Vorgabewerte der Tabelle nutzen (serial oder nextval('…')).

    Identitätsspalten (GENERATED … AS IDENTITY) stehen nicht in pg_attrdef und tauchen hier nicht
    auf; ihr INSERT braucht kein Recht auf die Sequenz.

    Args:
        cur: Cursor.
        z: Ziel.

    Returns:
        Sequenznamen so, wie pg_get_expr sie im Ausdruck schreibt (bei Bedarf mit Schema und
        Anführungszeichen), also direkt als SQL-Text verwendbar.
    """
    cur.execute("""SELECT pg_get_expr(d.adbin, d.adrelid) FROM pg_attrdef d
                   WHERE d.adrelid = to_regclass(%s)""", (z.ident.as_string(cur),))
    aus = []
    for (ausdruck,) in cur.fetchall():
        # Form von serial und nextval('…') mit regclass-Literal; andere Schreibweisen erkennt das Muster nicht
        m = re.search(r"nextval\('([^']+)'::regclass\)", ausdruck or "")
        if m:
            aus.append(m[1])
    return aus


# Schreibrechte je Art des Objekts: Tabellen, Views, Fremdtabellen (auch auf Spaltenebene) und Sequenzen
# (USAGE erlaubt nextval, UPDATE auch setval; Nachprüfung zu E46). Andere Rechte (SELECT) zählen nicht
# zum Sollstand
_SCHREIBRECHT_SQL = """
    SELECT c.oid, c.oid::regclass::text, c.relkind = 'S', NULL::text, x.privilege_type,
           x.grantor::regrole::text
    FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) x
    WHERE x.grantee = to_regrole(%(r)s) AND c.relnamespace <> to_regnamespace('pipeline_meta')
    AND ((c.relkind IN ('r', 'p', 'v', 'f') AND x.privilege_type IN ('INSERT', 'UPDATE', 'DELETE'))
         OR (c.relkind = 'S' AND x.privilege_type IN ('USAGE', 'UPDATE')))
    UNION ALL
    SELECT c.oid, c.oid::regclass::text, false, a.attname::text, x.privilege_type, x.grantor::regrole::text
    FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
    CROSS JOIN LATERAL aclexplode(a.attacl) x
    WHERE x.grantee = to_regrole(%(r)s) AND x.privilege_type IN ('INSERT', 'UPDATE')
    AND c.relkind IN ('r', 'p', 'v', 'f') AND NOT a.attisdropped
    AND c.relnamespace <> to_regnamespace('pipeline_meta')
    ORDER BY 2, 4 NULLS FIRST, 5, 6"""


def _schreibrechte(cur) -> list[tuple[int, str, bool, str | None, str, str]]:
    """Schreibrechte der Importrolle außerhalb von pipeline_meta, auf Tabellen- oder Spaltenebene und auf
    Sequenzen: (oid, Name als regclass-Text, ist Sequenz, Spalte oder None, Recht, vergeben von)."""
    cur.execute(_SCHREIBRECHT_SQL, {"r": IMPORT_ROLLE})
    return cur.fetchall()


def _entziehen(cur, protokoll: list[str]) -> list[str]:
    """Erster Schritt des Sollstands (F10, E46): alle Schreibrechte der Importrolle außerhalb von
    pipeline_meta entziehen. Jedes REVOKE in einem eigenen Sicherungspunkt (Nachprüfung zu E46): Ein
    Administrator ohne Superuser-Rechte, der auf einer Tabelle selbst kein Recht hat, bekommt dort
    `permission denied`; bis E46 rollte das das ganze einrichten zurück (Passwörter, GRANTs, Katalog).
    Jetzt bleibt dieses Recht stehen, und die Rückgabe enthält eine Warnung dazu. Ins Protokoll kommen nur
    REVOKE, die ausgeführt wurden. Rechte, die eine andere Rolle vergeben hat, entzieht ein REVOKE ohne
    Fehler nicht; die meldet `_rest_melden` nach den GRANTs.

    Args:
        cur: Cursor des Administrators in der Transaktion von einrichten.
        protokoll: Liste, an die jedes ausgeführte REVOKE als SQL-Text angehängt wird.

    Returns:
        Warnungen zu gescheiterten REVOKE (leer, wenn alle gelangen).
    """
    imp = sql.Identifier(IMPORT_ROLLE)
    warnungen = []
    # Ein REVOKE je Objekt, auch wenn es mehrere Rechte oder Spalten hat
    objekte = sorted({(name, seq) for _, name, seq, *_ in _schreibrechte(cur)})
    for name, seq in objekte:
        # name ist regclass-Text aus dem Katalog (schon passend gequotet), daher sql.SQL statt Identifier.
        # Ein REVOKE auf Tabellenebene nimmt die Spaltenrechte derselben Art mit
        befehl = (sql.SQL("REVOKE USAGE, UPDATE ON SEQUENCE {} FROM {}") if seq
                  else sql.SQL("REVOKE INSERT, UPDATE, DELETE ON {} FROM {}")).format(sql.SQL(name), imp)
        try:
            # Verschachtelte transaction() = Sicherungspunkt: Ein gescheitertes REVOKE rollt nur sich
            # selbst zurück, nicht das ganze einrichten
            with cur.connection.transaction():
                cur.execute(befehl)
        except psycopg.Error as e:
            text = " ".join(str(e).split())
            warnungen.append(f"Warnung: REVOKE auf {name} gescheitert ({text}), einrichten läuft weiter")
            continue
        protokoll.append(befehl.as_string(cur))
    return warnungen


def _rest_melden(cur, soll: set[tuple[int, str | None, str]]) -> list[str]:
    """Letzter Schritt des Sollstands (Nachprüfung zu E46): die Schreibrechte erneut lesen und jedes
    melden, das nicht zur Konfiguration gehört. Das sind Rechte, die eine andere Rolle vergeben hat
    (REVOKE entzieht nur, was der ausführende Administrator vergeben hat, als Superuser nur, was der
    Eigentümer vergeben hat), und solche, bei denen `_entziehen` scheiterte.
    Rückgabe: Warnungen, eine je Objekt.

    Args:
        cur: Cursor des Administrators.
        soll: Sollstand als (oid, Spalte oder None, Recht), gesammelt in rechte().
    """
    # Objektname -> lesbare Rechte mit vergebender Rolle, damit die Warnung sagt, wer sie entziehen kann
    rest: dict[str, list[str]] = {}
    for oid, name, _, spalte, recht, grantor in _schreibrechte(cur):
        if (oid, spalte, recht) in soll:
            continue
        rest.setdefault(name, []).append(f"{recht}{f' ({spalte})' if spalte else ''} von {grantor}")
    return [f"Warnung: {IMPORT_ROLLE} behält auf {name} Schreibrechte, die nicht zur Konfiguration "
            f"gehören: {', '.join(teile)}. einrichten konnte sie nicht entziehen; entziehen kann sie, "
            "wer sie vergeben hat (docs/betrieb.md)" for name, teile in sorted(rest.items())]


def katalog_pruefen(cur) -> str | None:
    """Hinweis zur View des Katalogs (Antwort 75): fehlt sie, oder darf die Funktion
    pipeline_meta.katalog_aktualisieren() sie nicht aktualisieren? Maßgeblich ist der Eigentümer der
    Funktion (SECURITY DEFINER), nicht wer einrichten gerade ausführt: CREATE OR REPLACE FUNCTION lässt
    einen vorhandenen Eigentümer stehen (Nachprüfung zu E46). Rückgabe: Text oder None.

    Ändert nichts; die Abhilfe in der Warnung muss ein Superuser selbst ausführen.

    Args:
        cur: Cursor des Administrators, nachdem sql/pipeline_meta.sql die Funktion angelegt hat.
    """
    # Ab PostgreSQL 17 genügt auch MAINTAIN; auf 16 kennt has_table_privilege das Recht nicht (Fehler)
    maintain = sql.SQL("OR has_table_privilege(p.proowner, c.oid, 'MAINTAIN')"
                       if cur.connection.info.server_version >= 170000 else "")
    # REFRESH darf nur der Eigentümer der View: Der Eigentümer der Funktion ist es selbst oder erbt dessen
    # Rechte (pg_has_role mit USAGE), oder er ist Superuser
    cur.execute(sql.SQL("""SELECT c.relkind, pg_get_userbyid(p.proowner), pg_get_userbyid(c.relowner),
                                  pg_has_role(p.proowner, c.relowner, 'USAGE') OR r.rolsuper {}
                           FROM pg_class c
                           JOIN pg_proc p ON p.oid = to_regprocedure('pipeline_meta.katalog_aktualisieren()')
                           JOIN pg_roles r ON r.oid = p.proowner
                           WHERE c.oid = to_regclass('public.source_granularities')""").format(maintain))
    zeile = cur.fetchone()
    # Keine Zeile: Die View fehlt (die Funktion legt einrichten vorher immer an)
    if not zeile:
        return ("Hinweis: public.source_granularities gibt es in dieser Datenbank nicht; die Pipeline "
                "aktualisiert den Katalog nach einem Lauf nur, wenn es sie gibt")
    art, funktion, view, darf = zeile
    if art != "m":
        return ("Hinweis: public.source_granularities ist keine Materialized View; die Pipeline "
                "aktualisiert sie nicht")
    if not darf:
        pg17 = (f" oder GRANT MAINTAIN ON public.source_granularities TO "
                f"{sql.Identifier(funktion).as_string(cur)}" if cur.connection.info.server_version >= 170000
                else "")
        return (f"Warnung: pipeline_meta.katalog_aktualisieren() gehört {funktion}, der "
                f"public.source_granularities nicht aktualisieren darf (Eigentümer der View: {view}); der "
                "Katalog bleibt dann nach jedem Lauf alt. Abhilfe als Superuser: ALTER FUNCTION "
                f"pipeline_meta.katalog_aktualisieren() OWNER TO {sql.Identifier(view).as_string(cur)}{pg17} "
                "(docs/betrieb.md)")
    return None


def rechte(cur, liste: list[zielmod.Ziel], db: str) -> list[str]:
    """Rechte für beide Rollen setzen. Gibt eine lesbare Liste der Rechte zurück (ohne Passwörter).

    Schreibrechte der Importrolle (INSERT, UPDATE, DELETE) außerhalb von pipeline_meta werden zuerst
    entzogen und dann nach der Konfiguration neu vergeben, in derselben Transaktion: So entsprechen sie
    nach jedem Einrichten dem Sollstand, auch wenn eine Spalte oder ein Ziel aus der Konfiguration
    verschwunden ist (Prüfbericht 05.11., F10, E46). Ein REVOKE auf Tabellenebene entzieht die
    Spaltenrechte mit. Seit der Nachprüfung zu E46 gehören Sequenzen dazu (USAGE, UPDATE), ein REVOKE,
    das scheitert, bricht einrichten nicht mehr ab, und was danach noch über den Sollstand hinausgeht
    (von einer anderen Rolle vergeben), steht als Warnung im Protokoll.

    Args:
        cur: Cursor des Administrators in der Transaktion von einrichten.
        liste: Ziele aus der Konfiguration (ziele()).
        db: Name der aktuellen Datenbank (für CONNECT und TEMPORARY).

    Returns:
        Jede ausgeführte Anweisung als SQL-Text, Warnungen als Zeilen mit "-- " davor.

    Raises:
        ziel.ZielFehler: ein Ziel passt nicht zur Datenbank (zielmod.pruefen); einrichten rollt dann
            alles zurück.
        psycopg.Error: ein GRANT scheitert, ebenfalls mit Rollback des ganzen einrichten.
    """
    imp, lese = sql.Identifier(IMPORT_ROLLE), sql.Identifier(LESE_ROLLE)
    protokoll: list[str] = []
    soll: set[tuple[int, str | None, str]] = set()

    def gib(text: sql.Composable) -> None:
        """Anweisung ausführen und als SQL-Text ins Protokoll schreiben."""
        cur.execute(text)
        protokoll.append(text.as_string(cur))

    def oid(name: str) -> int:
        """OID eines Objekts aus seinem SQL-Namen; der Sollstand vergleicht über OIDs, nicht über Namen."""
        cur.execute("SELECT to_regclass(%s)::oid", (name,))
        return cur.fetchone()[0]

    # Erst alles entziehen, dann nach der Konfiguration neu vergeben (Sollstand, E46)
    warnungen = _entziehen(cur, protokoll)

    # Grundrechte: TEMPORARY für die temporären Tabellen und die Funktion in pg_temp während eines Laufs.
    # ON ALL TABLES gilt nur für die Tabellen, die es jetzt gibt; neue Tabellen in pipeline_meta bekommen
    # ihre Rechte beim nächsten einrichten
    gib(sql.SQL("GRANT CONNECT, TEMPORARY ON DATABASE {} TO {}").format(sql.Identifier(db), imp))
    gib(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(db), lese))
    gib(sql.SQL("GRANT USAGE ON SCHEMA public, pipeline_meta TO {}, {}").format(imp, lese))
    gib(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA pipeline_meta TO {}")
        .format(imp))
    gib(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA pipeline_meta TO {}").format(lese))

    meta_noetig = False
    gebiete = set()
    # Löschrecht nur auf Tabellen, in denen mindestens eine Quelle löschen darf; Raumdaten mit
    # loeschen: false (Antwort 74) bekommen keins, auch nicht aus einem früheren Einrichten
    mit_loeschen = {z.name for z in liste if z.loeschen}
    for z in liste:
        zielmod.pruefen(cur, z)
        ident = z.ident
        tabelle = oid(ident.as_string(cur))
        if z.name in mit_loeschen:
            gib(sql.SQL("GRANT SELECT, DELETE ON {} TO {}").format(ident, imp))
            soll.add((tabelle, None, "DELETE"))
        else:
            gib(sql.SQL("GRANT SELECT ON {} TO {}").format(ident, imp))
        # INSERT nur auf die Spalten des neuen Stands, UPDATE nur auf die Spalten, die ein Abgleich
        # ändert (ohne Schlüssel und nur_einfuegen, mit Geometrie); in alle übrigen Spalten kann die
        # Importrolle nicht schreiben
        gib(sql.SQL("GRANT INSERT ({}) ON {} TO {}").format(
            sql.SQL(", ").join(map(sql.Identifier, z.spalten_neu())), ident, imp))
        soll |= {(tabelle, s, "INSERT") for s in z.spalten_neu()}
        aendern = z.spalten_aendern() + ([z.geometrie] if z.geometrie else [])
        if aendern:
            gib(sql.SQL("GRANT UPDATE ({}) ON {} TO {}").format(
                sql.SQL(", ").join(map(sql.Identifier, aendern)), ident, imp))
            soll |= {(tabelle, s, "UPDATE") for s in aendern}
        for seq in _sequenzen(cur, z):
            gib(sql.SQL("GRANT USAGE ON SEQUENCE {} TO {}").format(sql.SQL(seq), imp))
            soll.add((oid(seq), None, "USAGE"))
        gib(sql.SQL("GRANT SELECT ON {} TO {}").format(ident, lese))
        if z.gebiet:
            gebiete.add((z.gebiet.get("schema", "public"), z.gebiet["tabelle"]))
        meta_noetig = meta_noetig or bool(z.metadaten)
    # USAGE auch auf jedes andere Schema mit Zielen oder Gebietstabellen: sonst nützen die Tabellenrechte
    # dort nichts, und die Quelle scheitert erst im Lauf (Code-Review 05.11., F3, E44). Erst hier, nach
    # zielmod.pruefen: Fehlt ein Schema, meldet das die Prüfung klarer als GRANT
    schemas = ({z.schema for z in liste} | {s for s, _ in gebiete}) - {"public", "pipeline_meta"}
    if schemas:
        gib(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}, {}").format(
            sql.SQL(", ").join(sql.Identifier(s) for s in sorted(schemas)), imp, lese))
    for schema, tabelle in sorted(gebiete):
        gib(sql.SQL("GRANT SELECT ON {} TO {}, {}").format(sql.Identifier(schema, tabelle), imp, lese))
    if meta_noetig:
        meta = sql.Identifier("public", zielmod.META_TABELLE)
        # Rechte nur auf die Metadatenspalten, die es in dieser Fassung von table_metadata gibt: GRANT auf
        # eine fehlende Spalte schlüge fehl
        cur.execute("""SELECT attname FROM pg_attribute WHERE attrelid = to_regclass(%s)
                       AND attnum > 0 AND NOT attisdropped""", (meta.as_string(cur),))
        da = {r[0] for r in cur.fetchall()}
        # Dazu dcat_ap_id (E52), nur in der Fassung des MOSIDI-Skripts vorhanden; die Pipeline setzt sie nur,
        # wo sie leer ist (ziel.metadaten_schreiben), das Recht ist trotzdem INSERT und UPDATE auf die Spalte
        namen = [s for s in zielmod.META_SPALTEN + zielmod.META_SPALTEN_NUR_LEER if s in da]
        spalten = sql.SQL(", ").join(map(sql.Identifier, namen))
        gib(sql.SQL("GRANT SELECT ON {} TO {}, {}").format(meta, imp, lese))
        gib(sql.SQL("GRANT INSERT ({s}), UPDATE ({s}) ON {m} TO {r}").format(s=spalten, m=meta, r=imp))
        m = oid(meta.as_string(cur))
        soll |= {(m, s, r) for s in namen for r in ("INSERT", "UPDATE")}
    # Katalog (Antwort 75, E46): nur ausführen, nicht ändern; PUBLIC hat kein Recht (pipeline_meta.sql)
    gib(sql.SQL("GRANT EXECUTE ON FUNCTION pipeline_meta.katalog_aktualisieren() TO {}").format(imp))
    for text in warnungen + _rest_melden(cur, soll):
        log.warning("%s", text)
        protokoll.append(f"-- {text}")
    return protokoll


def einrichten(conn: psycopg.Connection, cfg: dict, haerten: bool = False) -> list[str]:
    """Datenbank für die Pipeline einrichten oder auf Stand bringen, alles in einer Transaktion.

    Reihenfolge: vorhandene Rollen prüfen (vor jeder Änderung, E47), sql/pipeline_meta.sql ausführen
    (idempotent), Rollen anlegen bzw. Passwort setzen, Rechte auf den Sollstand bringen (rechte),
    Sprachrecht und Katalogfunktion prüfen, mit `haerten` PUBLIC-Rechte entziehen.

    Args:
        conn: Verbindung als Administrator der Datenbank.
        cfg: Konfiguration mit allen Quellen, die in diese Datenbank schreiben.
        haerten: zusätzlich PUBLIC-Rechte auf Datenbank und Schema public entziehen.

    Returns:
        Protokoll: jede ausgeführte Rechteanweisung als SQL-Text (ohne Passwörter), Warnungen mit "-- ".

    Raises:
        SystemExit: IMPORT_PASSWORD oder LESE_PASSWORD fehlt oder ist leer; vor der Transaktion, nichts
            geändert.
        RolleZuWeit: eine vorhandene Rolle hat zu weite Rechte; nichts wurde geändert.
        ziel.ZielFehler, psycopg.Error: ein Schritt scheitert; die Transaktion wird zurückgerollt.
    """
    import_pw, lese_pw = os.environ.get("IMPORT_PASSWORD"), os.environ.get("LESE_PASSWORD")
    if not import_pw or not lese_pw:
        raise SystemExit("IMPORT_PASSWORD und LESE_PASSWORD müssen gesetzt sein (.env)")
    with conn.transaction(), conn.cursor() as cur:
        # Vor jeder Änderung: Warnen statt abbrechen ließe die Pipeline mit diesen Rechten laufen (E47)
        for rolle in (IMPORT_ROLLE, LESE_ROLLE):
            teile = rolle_pruefen(cur, rolle)
            if teile:
                raise RolleZuWeit(zu_weit_text(rolle, teile))
        # Die ganze Datei in einem Aufruf (ohne Parameter erlaubt psycopg mehrere Anweisungen); sie ist
        # wiederholbar geschrieben und ergänzt, was einer älteren Fassung fehlt
        cur.execute(META_DDL.read_text(encoding="utf-8"))
        _rolle(cur, IMPORT_ROLLE, import_pw)
        _rolle(cur, LESE_ROLLE, lese_pw)
        cur.execute("SELECT current_database()")
        db = cur.fetchone()[0]
        liste = ziele(cfg)
        protokoll = rechte(cur, liste, db)
        # Prüfungen ohne Abbruch: Sie ergänzen das Protokoll um Warnungen
        warnung = sprache_pruefen(cur) if any(z.geometrie for z in liste) else None
        for text in (warnung, katalog_pruefen(cur)):
            if text:
                log.warning("%s", text)
                protokoll.append(f"-- {text}")
        if haerten:
            for text in (sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(db)),
                         sql.SQL("REVOKE CREATE ON SCHEMA public FROM PUBLIC")):
                cur.execute(text)
                protokoll.append(text.as_string(cur))
    return protokoll


def main() -> int:
    """Einstieg für `python -m pipeline.einrichten`: Konfigurationen lesen, verbinden, einrichten,
    Protokoll ausgeben.

    Returns:
        0 eingerichtet, 2 eine vorhandene Rolle ist zu weit (RolleZuWeit). Andere Fehler beenden das
        Programm mit Traceback; fehlende Passwörter mit Meldung (SystemExit, Rückgabe 1).
    """
    # Erste Zeile des Moduldocstrings als Kurzbeschreibung für --help
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", action="append",
                    help="Konfiguration(en) mit den Zielen; mehrfach möglich")
    ap.add_argument("--haerten", action="store_true", help="PUBLIC-Rechte entziehen (nur eigene Datenbank)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pfade = a.config or [os.environ.get("PIPELINE_CONFIG", "config/quellen.yaml")]
    # Alle Konfigurationen derselben Datenbank zusammenführen, sonst entzöge der Sollstand die Rechte
    # der fehlenden. Gleichnamige Quellen: Die später genannte Konfiguration gilt
    cfg: dict = {"quellen": {}}
    for p in pfade:
        cfg["quellen"].update(yaml.safe_load(Path(p).read_text(encoding="utf-8")).get("quellen", {}))
    # Leerer DSN: libpq nimmt PGHOST, PGUSER, PGPASSWORD, PGDATABASE; der with-Block schließt die Verbindung
    with verbinden(os.environ.get("DATABASE_URL", "")) as conn:
        try:
            protokoll = einrichten(conn, cfg, a.haerten)
        except RolleZuWeit as e:
            log.error("%s", e)
            return 2
        for zeile in protokoll:
            print(zeile)
    print(f"pipeline_meta und Rollen {IMPORT_ROLLE}, {LESE_ROLLE} eingerichtet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
