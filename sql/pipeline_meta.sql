-- Eigenes Schema der Pipeline in derselben Datenbank wie MOSIDI (zulässig nach Antwort 29 und 47b
-- der TH). Hier liegen Steuerung und Protokoll, nie Fachdaten. Die Bestandstabellen in public
-- bleiben unverändert. Angelegt von `python -m pipeline.einrichten` (idempotent, als Administrator).
--
-- Zwischentabellen (Eingang, neuer Stand, Vergleich) sind temporäre Tabellen der Sitzung (pg_temp)
-- und verschwinden mit dem Ende der Transaktion. Sie brauchen kein dauerhaftes Schema und stören
-- sich nicht, wenn zwei Läufe gleichzeitig laufen.
--
-- Die Datei läuft bei jedem `einrichten` erneut. Deshalb nur IF NOT EXISTS, ADD COLUMN IF NOT EXISTS und
-- CREATE OR REPLACE: Vorhandene Tabellen und ihr Inhalt bleiben, Spalten neuerer Fassungen kommen dazu.
--
-- Rechte vergibt nicht diese Datei, sondern einrichten.rechte (pipeline/einrichten.py):
--   pipeline_import  SELECT, INSERT, UPDATE, DELETE auf allen Tabellen dieses Schemas, EXECUTE auf
--                    katalog_aktualisieren() (nicht auf insert_table_metadata() von MOSIDI, E52)
--   mosidi_lesen     nur SELECT (Leserolle für die Plattform)
-- Keine der beiden Rollen darf hier Tabellen anlegen oder ihre Struktur ändern (kein CREATE auf dem
-- Schema, nicht Eigentümer). In dieser Datei steht nur der Entzug des Ausführungsrechts für PUBLIC (bei
-- der Funktion unten).

-- Schema der Pipeline; es gehört dem Administrator, der einrichten zuerst ausgeführt hat, die beiden
-- Rollen bekommen nur USAGE
CREATE SCHEMA IF NOT EXISTS pipeline_meta;

-- Ein Eintrag je Importlauf (nicht bei Probeläufen); geschrieben von laden am Ende des Laufs. Die Zahlen
-- zählen Quellen, nicht Objekte
CREATE TABLE IF NOT EXISTS pipeline_meta.lauf (
    lauf_id       text PRIMARY KEY,               -- z. B. 20261103T120000Z, wie Bericht und Karte
    start         timestamptz NOT NULL,           -- Beginn des Laufs (UTC)
    dauer_s       numeric     NOT NULL,           -- Laufzeit in Sekunden
    quellen       integer     NOT NULL,           -- geladene Quellen (ohne „nicht fällig“)
    fehler        integer     NOT NULL,           -- Quellen mit Status fehler (zurückgerollt)
    angehalten    integer     NOT NULL,           -- Quellen angehalten, alter Stand blieb (Schutzregeln)
    bericht       text                            -- Dateiname des Laufberichts
);
-- Quellen mit Status ok, aber unvollständigem Abruf (nichts gelöscht, kein Erfolg; E41/E42). Seit
-- 05.11.2026; bei älteren Einrichtungen ergänzt, ältere Einträge bleiben leer.
ALTER TABLE pipeline_meta.lauf ADD COLUMN IF NOT EXISTS unvollstaendig integer;

-- Protokoll je Lauf und Quelle: was neu, geändert, entfernt, unverändert ist (Antworten 30 und 51).
-- Geschrieben von laden.protokollieren in einer eigenen Transaktion nach der Quelle, auch für Quellen mit
-- Fehler oder ohne Fälligkeit; die Zähler sind dann leer oder 0
CREATE TABLE IF NOT EXISTS pipeline_meta.quellenlauf (
    lauf_id         text        NOT NULL,         -- wie pipeline_meta.lauf.lauf_id
    quelle          text        NOT NULL,         -- Name der Quelle aus der Konfiguration
    tabelle         text,                         -- Zieltabelle, ohne Schema, wenn es public ist (Ziel.name)
    status          text        NOT NULL,         -- ok | unvollstaendig | angehalten | fehler | nicht_faellig
    gelesen         integer,                      -- Datensätze der Quelle (vor dem Auffächern je Wert)
    neu             integer,                      -- Zählung nach dem Quellschlüssel (Antwort 62, E42)
    geaendert       integer,                      -- einschließlich übernommener Zeilen mit anderen Werten
    entfernt        integer,                      -- gelöscht, einschließlich ersetzter Quellschlüssel
    unveraendert    integer,
    uebernommen     integer,                      -- schon vorhandene Zeilen, jetzt in der Obhut der Pipeline;
                                                  -- seit E46 zusätzlich in geaendert bzw. unveraendert gezählt
    zurueckgehalten integer,                      -- nicht gelöscht: Abruf unvollständig, Zeile in diesem Lauf
                                                  -- ausgelassen oder Ziel mit loeschen: false (E35)
    dauer_s         numeric,
    warnungen       jsonb,                        -- Warnungen des Berichts als JSON-Liste von Texten
    fehler          text,                         -- Fehlermeldung bei Status fehler (gekürzt)
    PRIMARY KEY (lauf_id, quelle)
);

-- Je Lauf die einzelnen Änderungen, über den fachlichen Schlüssel der Zeile in der Zieltabelle.
-- Geschrieben von ziel.anwenden in der Transaktion der Quelle; unveränderte Zeilen stehen nicht darin.
-- Ohne Primärschlüssel; ein Zielschlüssel kann in einem Lauf zweimal vorkommen (neu und, mit dem
-- bisherigen Quellschlüssel, entfernt)
CREATE TABLE IF NOT EXISTS pipeline_meta.aenderung (
    lauf_id     text  NOT NULL,
    quelle      text  NOT NULL,
    tabelle     text  NOT NULL,                   -- wie quellenlauf.tabelle
    schluessel  jsonb NOT NULL,                   -- Werte der Schlüsselspalten, als Text
    art         text  NOT NULL                    -- neu | geaendert | entfernt | uebernommen | zurueckgehalten
                                                  -- | uebernommen_geaendert (seit E46: übernommen, Werte abweichend)
);
-- Für Abfragen je Lauf und Quelle; die Pipeline selbst liest die Tabelle nicht, sie ist das Protokoll für
-- Auswertungen und für alles, was über die Karte hinausgeht (docs/betrieb.md)
CREATE INDEX IF NOT EXISTS aenderung_lauf_idx ON pipeline_meta.aenderung (lauf_id, quelle);
-- Vollständiger Quellschlüssel der Zeile (INKAR: Kennziffer|Bereich|Kürzel|Indikator|Zeitbezug,
-- Antworten 31/62), auch wenn die Zieltabelle weniger Schlüsselspalten hat (E40). Seit 05.11.2026;
-- bei älteren Einrichtungen ergänzt, ältere Einträge bleiben leer.
ALTER TABLE pipeline_meta.aenderung ADD COLUMN IF NOT EXISTS quellschluessel text;

-- Bestandsregister: welche Zeilen der Zieltabelle die Pipeline für welche Quelle geschrieben hat.
-- Gelöscht wird nur, was hier steht und im neuen, vollständigen Abruf fehlt. Zeilen, die andere
-- Importe oder Menschen angelegt haben, fasst die Pipeline nicht an.
-- Geschrieben nur von ziel.anwenden (E29: nur bei Änderungen); der Primärschlüssel ist sein einziger
-- Index (E31).
CREATE TABLE IF NOT EXISTS pipeline_meta.bestand (
    quelle        text  NOT NULL,
    tabelle       text  NOT NULL,               -- wie quellenlauf.tabelle
    schluessel    jsonb NOT NULL,               -- Zielschlüssel: Werte der Schlüsselspalten als Text-Array
    erster_lauf   text  NOT NULL,               -- Lauf, in dem die Zeile (mit diesem Quellschlüssel) kam
    letzter_lauf  text  NOT NULL,               -- Lauf der letzten Änderung dieser Zeile
    PRIMARY KEY (quelle, tabelle, schluessel)
);
-- Quellschlüssel je Zeile (E40): Ziel- und Quellschlüssel stehen 1:1, sonst hält der Lauf die Quelle
-- an. Leere Einträge aus der Zeit vor E40 trägt der nächste Lauf nach.
ALTER TABLE pipeline_meta.bestand ADD COLUMN IF NOT EXISTS quellschluessel text;

-- Stand je Quelle: wann zuletzt erfolgreich geladen, für den Rhythmus je Quelle (Antwort 37)
-- Geschrieben von laden.quelle_laden am Ende einer Quelle mit Status ok, in derselben Transaktion wie die
-- Daten (im Probelauf zurückgerollt); laden liest daraus, ob eine Quelle fällig ist
CREATE TABLE IF NOT EXISTS pipeline_meta.quellenstand (
    quelle          text PRIMARY KEY,
    tabelle         text,                         -- wie quellenlauf.tabelle
    rhythmus        text,                         -- aus der Konfiguration, zur Nachvollziehbarkeit
    letzter_lauf    text,                         -- letzter Lauf mit Status ok, auch wenn unvollständig
    letzter_erfolg  timestamptz,                  -- letzter vollständiger Abruf (E32); bleibt sonst stehen
    objekte         integer                       -- Zeilen im neuen Stand dieses Laufs
);
-- Vergleichsstand für das Überspringen einer unveränderten Lieferung (E52, pipeline/unveraendert.py). Gesetzt
-- nur nach einem vollständigen Vollabgleich einer Dateiquelle mit unveraendert_ueberspringen: true; jeder
-- andere Lauf, der den Quellenstand schreibt, leert alle fünf (dann ist der nächste Lauf ein Vollabgleich).
-- Ein übersprungener Lauf ändert sie nicht, nur letzter_lauf und letzter_erfolg. Seit 08.11.2026; bei älteren
-- Einrichtungen ergänzt, ältere Einträge bleiben leer.
ALTER TABLE pipeline_meta.quellenstand ADD COLUMN IF NOT EXISTS datei_sha256 text;      -- SHA-256 der Datei
ALTER TABLE pipeline_meta.quellenstand ADD COLUMN IF NOT EXISTS konfig_sha256 text;     -- Konfiguration + Code
ALTER TABLE pipeline_meta.quellenstand ADD COLUMN IF NOT EXISTS vollabgleich timestamptz; -- Start des Laufs
ALTER TABLE pipeline_meta.quellenstand ADD COLUMN IF NOT EXISTS register_zeilen bigint; -- Zählprüfung: Register
ALTER TABLE pipeline_meta.quellenstand ADD COLUMN IF NOT EXISTS ziel_zeilen bigint;     -- und Zieltabelle (Bereich)
-- Umfang, unter dem die Quelle zuletzt vollständig abgeglichen wurde (E52, pipeline/umfang.py): je
-- fachlich bedeutsamem Schlüssel der Konfiguration eine SHA-256 seines Werts, keine Adressen oder Pfade im
-- Klartext. Ändert er sich und würde der Lauf löschen, hält die Quelle an, bis der neue Umfang bestätigt ist
-- (--umfang-bestaetigen, umfang_bestaetigt). Leer bei älteren Einträgen; der nächste Lauf merkt ihn.
ALTER TABLE pipeline_meta.quellenstand ADD COLUMN IF NOT EXISTS umfang jsonb;

-- Katalog von MOSIDI (Antwort 75, Prüfbericht 05.11., F2, E46): Damit neue Indikatoren im Katalog
-- erscheinen, ist nach einem Lauf neben table_metadata die Materialized View public.source_granularities
-- zu aktualisieren. REFRESH darf nur ihr Eigentümer (ab PostgreSQL 17 auch, wer MAINTAIN hat), die
-- Importrolle nicht. Diese Funktion gehört dem Administrator, der einrichten zuerst ausgeführt hat
-- (CREATE OR REPLACE lässt Eigentümer und Rechte einer vorhandenen Funktion stehen; einrichten prüft
-- deshalb ihren Eigentümer, Nachprüfung zu E46), läuft mit dessen Rechten (SECURITY DEFINER) und kann
-- nur genau diese eine View aktualisieren: keine Parameter, fester search_path, voll qualifizierter
-- Name. Ausführen darf sie nur pipeline_import (Recht aus einrichten). Die Bestandstabellen in public
-- bleiben unverändert; fehlt die View, ändert die Funktion nichts.
-- Rückgabe: aktualisiert_gleichzeitig | aktualisiert | fehlt | keine_materialized_view
-- search_path mit pg_temp am Ende: Bei SECURITY DEFINER dürfen weder ein Schema des Aufrufers noch dessen
-- temporäre Objekte einen Namen in der Funktion überdecken; alle Namen im Körper sind ohnehin qualifiziert.
-- Aufgerufen von laden.katalog_aktualisieren mit lock_timeout und statement_timeout (katalog_sperre_max_s,
-- katalog_zeitlimit_min; E52), damit weder ein Leser der View noch eine lange Berechnung den Lauf beliebig
-- lange aufhält.
--
-- Seit E52 (Mitbewerber-Sichtung 08.11.2026) ohne Sperre für Leser, wo es geht: Hat die View einen
-- eindeutigen Index, den REFRESH … CONCURRENTLY nutzen kann (nur Spalten, kein Ausdruck, kein WHERE,
-- gültig; das Skript von MOSIDI legt einen über source, indikator, granularity an), und ist sie befüllt
-- (CONCURRENTLY verweigert eine View, die mit WITH NO DATA angelegt ist), wird sie gleichzeitig
-- aktualisiert: PostgreSQL berechnet den neuen Stand daneben und übernimmt nur die Unterschiede, die
-- Sperre (EXCLUSIVE) lässt Leser durch. Sonst wie bis E52 mit ACCESS EXCLUSIVE, dann warten Leser bis zum
-- Ende. Kein Rückfall von gleichzeitig auf exklusiv, wenn CONCURRENTLY scheitert: Der Fehler geht an die
-- Pipeline (Warnung, katalog_offen), statt Leser unerwartet doch zu blockieren. Signatur unverändert (keine
-- Parameter, Rückgabe text): CREATE OR REPLACE lässt so Eigentümer und Rechte der vorhandenen Funktion
-- stehen; eine ältere Fassung in der Datenbank liefert weiter 'aktualisiert', laden wertet beides aus.
CREATE OR REPLACE FUNCTION pipeline_meta.katalog_aktualisieren() RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    art "char";
    befuellt boolean;
    gleichzeitig boolean;
BEGIN
    SELECT c.relkind, c.relispopulated INTO art, befuellt FROM pg_catalog.pg_class c
    WHERE c.oid = pg_catalog.to_regclass('public.source_granularities');
    IF art IS NULL THEN
        RETURN 'fehlt';
    ELSIF art <> 'm' THEN
        RETURN 'keine_materialized_view';
    END IF;
    -- Ein eindeutiger Index, wie ihn REFRESH … CONCURRENTLY verlangt: gültig, ohne Bedingung (indpred),
    -- ohne Ausdrücke (indexprs; eine Ausdrucksspalte steht in indkey als 0)
    SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_index i
                   WHERE i.indrelid = pg_catalog.to_regclass('public.source_granularities')
                   AND i.indisunique AND i.indisvalid AND i.indpred IS NULL AND i.indexprs IS NULL)
        INTO gleichzeitig;
    IF gleichzeitig AND befuellt THEN
        REFRESH MATERIALIZED VIEW CONCURRENTLY public.source_granularities;
        RETURN 'aktualisiert_gleichzeitig';
    END IF;
    REFRESH MATERIALIZED VIEW public.source_granularities;
    RETURN 'aktualisiert';
END $$;
-- Funktionen sind in PostgreSQL standardmäßig für PUBLIC ausführbar; ohne diesen Entzug könnte jede Rolle
-- mit USAGE auf pipeline_meta die View mit den Rechten des Eigentümers aktualisieren
REVOKE ALL ON FUNCTION pipeline_meta.katalog_aktualisieren() FROM PUBLIC;

-- Offene Aktualisierung des Katalogs (Nachprüfung zu E46): Jede Quelle mit Änderungen trägt hier
-- ihren Lauf ein, in derselben Transaktion wie ihre Daten. Gelingt der Aufruf oben (oder fehlt die
-- View), leert die Pipeline die Tabelle. Scheitert er, oder bricht der Lauf vorher ab, ruft der nächste
-- Lauf die Funktion auch ohne eigene Änderungen auf, bis es gelingt; --status meldet bis dahin WARNING.
CREATE TABLE IF NOT EXISTS pipeline_meta.katalog_offen (
    lauf_id  text PRIMARY KEY                     -- Lauf mit Änderungen, dessen Aktualisierung noch aussteht
);
