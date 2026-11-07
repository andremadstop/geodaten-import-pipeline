"""Einrichten ohne Datenbank: Passwörter nur als SCRAM-Hash, Warnung ohne plpgsql (Prüfung zu E38).

pipeline.einrichten legt vor dem ersten Lauf die Rollen und Rechte an (E10); laden setzt sie voraus.
Die Tests ersetzen Cursor und Verbindung durch kleine Stellvertreter und brauchen kein PostgreSQL.
Abgesichert werden: kein Klartextpasswort an den Server (E39), eine Warnung, wenn die Importrolle
plpgsql nicht nutzen darf, der Abbruch bei einer schon vorhandenen Rolle mit zu weiten Rechten oder
mit Eigentum (E47) und die Rückgabe 2 von main in diesem Fall.
"""
from pipeline import einrichten


class _PGconn:
    """Ersatz für die libpq-Verbindung (pgconn): prüft, dass einrichten das Verfahren scram-sha-256 verlangt,
    und gibt statt einer echten Berechnung einen festen SCRAM-Hash zurück."""
    def encrypt_password(self, passwort: bytes, rolle: bytes, verfahren: bytes) -> bytes:
        assert verfahren == b"scram-sha-256"
        return b"SCRAM-SHA-256$4096:c2FsdA==$abc:def"


class _Cursor:
    """Ersatz für einen psycopg-Cursor: merkt sich jede Anweisung samt Parametern in `befehle`, beantwortet
    fetchone mit der vorgegebenen Antwort und reicht über connection.pgconn den _PGconn durch."""
    def __init__(self, antwort):
        self.antwort, self.befehle = antwort, []
        self.connection = type("C", (), {"pgconn": _PGconn()})()

    def execute(self, befehl, parameter=None):
        self.befehle.append((befehl, parameter))

    def fetchone(self):
        return self.antwort


def test_passwort_geht_nur_als_scram_hash_an_den_server():
    """Ob die Rolle neu angelegt wird (CREATE ROLE) oder schon besteht (ALTER ROLE): an den Server geht nur
    der SCRAM-Hash, das Klartextpasswort steht in keiner Anweisung und keinem Parameter (E39)."""
    for vorhanden, anfang in ((None, "CREATE ROLE"), ((1,), "ALTER ROLE")):
        cur = _Cursor(vorhanden)
        einrichten._rolle(cur, "pipeline_import", "klartext-geheim-123")
        befehl = cur.befehle[-1][0]
        text = repr(befehl)
        assert anfang in text and "SCRAM-SHA-256$4096" in text
        assert all("klartext-geheim-123" not in repr(b) for b in cur.befehle)


def test_warnung_ohne_plpgsql():
    """sprache_pruefen gibt None zurück, wenn die Importrolle plpgsql nutzen darf, sonst eine Warnung mit der
    passenden GRANT-Anweisung als Abhilfe."""
    assert einrichten.sprache_pruefen(_Cursor((True,))) is None
    warnung = einrichten.sprache_pruefen(_Cursor((False,)))
    assert "plpgsql" in warnung and "GRANT USAGE ON LANGUAGE plpgsql TO pipeline_import" in warnung


class _RollenCursor:
    """Antwortet auf die Abfragen von einrichten.rolle_pruefen: Attribute aus pg_roles, Mitgliedschaften,
    Eigentum (Objekte, die der Rolle gehören)."""

    def __init__(self, attribute, mitglied_in, eigentum=()):
        self.attribute, self.mitglied_in, self.eigentum = attribute, mitglied_in, eigentum

    def execute(self, befehl, parameter=None):
        self.letzte = repr(befehl)

    def fetchone(self):
        return self.attribute

    def fetchall(self):
        if "pg_auth_members" in self.letzte:
            return [(r,) for r in self.mitglied_in]
        return [(r,) for r in self.eigentum]


def test_vorhandene_rolle_mit_zu_weiten_rechten_bricht_ab():
    """Prüfbericht 05.11. abends, Befund 11 (E47): Bei einer schon vorhandenen Rolle setzte einrichten nur
    Login und Passwort. War sie Superuser, durfte Rollen oder Datenbanken anlegen, RLS umgehen oder war
    Mitglied anderer Rollen, liefen die Pipeline (bzw. die Leserolle) mit diesen Rechten weiter. Jetzt bricht
    einrichten vor jeder Änderung ab und nennt Abhilfe."""
    assert einrichten.rolle_pruefen(_RollenCursor(None, []), "pipeline_import") == []          # neu
    assert einrichten.rolle_pruefen(_RollenCursor((False,) * 5, []), "pipeline_import") == []  # eng
    teile = einrichten.rolle_pruefen(_RollenCursor((True, False, True, False, True), ["pg_read_all_data"]),
                                     "pipeline_import")
    assert teile == ["SUPERUSER", "CREATEDB", "REPLICATION", "Mitglied von pg_read_all_data"]
    text = einrichten.zu_weit_text("pipeline_import", teile)
    assert "ALTER ROLE pipeline_import NOSUPERUSER NOCREATEDB NOREPLICATION" in text
    assert "REVOKE pg_read_all_data FROM pipeline_import" in text and "nichts geändert" in text


def test_vorhandene_rolle_als_eigentuemerin_bricht_ab():
    """Nachprüfung zu E47 (Befund 7): Die Rollenprüfung sah kein Eigentum. Eine vorhandene pipeline_import,
    der Tabellen, Schemas oder die Datenbank gehören, hat dort alle Rechte einschließlich DDL und TRUNCATE;
    das Entziehen der Schreibrechte (E46) sieht Eigentümerrechte nicht. Jetzt bricht einrichten auch dann
    ab."""
    teile = einrichten.rolle_pruefen(_RollenCursor((False,) * 5, [], ["Tabelle public.\"Arzte\"",
                                                                    "Datenbank geodaten"]), "pipeline_import")
    assert teile == ["Eigentümerin von Tabelle public.\"Arzte\"", "Eigentümerin von Datenbank geodaten"]
    text = einrichten.zu_weit_text("pipeline_import", teile)
    assert "REASSIGN OWNED BY pipeline_import TO <Administratorrolle>" in text
    assert "ALTER DATABASE geodaten OWNER TO <Administratorrolle>" in text and "nichts geändert" in text


def test_main_endet_mit_2_bei_zu_weiter_rolle(monkeypatch, tmp_path, capsys):
    """Nachprüfung zu E47 (Befund 7): Der Weg von RolleZuWeit zur Rückgabe 2 war ungetestet."""
    import contextlib
    import sys

    konfig = tmp_path / "q.yaml"
    konfig.write_text("quellen: {}\n", encoding="utf-8")

    def zu_weit(conn, cfg, haerten=False):
        raise einrichten.RolleZuWeit("Rolle pipeline_import gibt es schon …")

    monkeypatch.setattr(einrichten, "verbinden", lambda dsn: contextlib.nullcontext(object()))
    monkeypatch.setattr(einrichten, "einrichten", zu_weit)
    monkeypatch.setattr(sys, "argv", ["pipeline-einrichten", "--config", str(konfig)])
    assert einrichten.main() == 2
    assert "eingerichtet" not in capsys.readouterr().out
