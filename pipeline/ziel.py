"""Zielschreiben in die Bestandstabellen der Plattform MOSIDI.

Welche Quelle in welche Tabelle und Spalten schreibt, steht je Quelle unter `ziel` in der
Konfiguration (config/quellen.yaml), nicht im Code. So lässt sich die Zuordnung in Arbeitspaket 1
an das DDL anpassen, das die TH dann liefert. Die Bestandstabellen werden nie verändert (kein
CREATE, ALTER oder DROP); die Pipeline liest, fügt ein, aktualisiert zugeordnete Spalten und löscht
Zeilen, die sie selbst geschrieben hat.

Stellung im Ablauf: pipeline.laden steuert den Lauf und öffnet je Quelle eine Transaktion,
pipeline.quellen liest die Datensätze beim Anbieter (Adapter je Quelltyp), dieses Modul schreibt sie
in die Datenbank. Es ruft selbst keinen Dienst im Netz ab; alles hier sind Abfragen an PostgreSQL/PostGIS.
Zwischenstände (eingang, neu, ausgelassen, vergleich) sind temporäre Tabellen mit ON COMMIT DROP und
verschwinden mit dem Ende der Transaktion. Die Hilfsfunktionen geom_lesen und geom_ziel liegen ebenfalls
in pg_temp, nur in dieser Sitzung sichtbar; ein Rollback entfernt sie, nach einem Commit bleiben sie bis
zum Ende der Sitzung. Deshalb legt jede Quelle sie mit CREATE OR REPLACE neu an.
Außerdem liefert das Modul die Abfragen für die Änderungskarte (karte_sql, gelesen von laden.quelle_laden
über karte.objekte_lesen) und das Stand-Archiv (archiv_sql, betrieb.archiv_schreiben).

Wichtigste Entscheidungen (docs/entscheidungen.md):
  - E7   eine Transaktion je Quelle; jeder Abbruch lässt den alten Stand stehen
  - E22  Zuordnung Quelle -> Tabelle/Spalten in der Konfiguration, nicht im Code
  - E23  Abgleich je Zeile über das Bestandsregister; gelöscht wird nur, was die Pipeline selbst
         geschrieben hat, und nur bei vollständigem Abruf
  - E3   Geometrie im Vergleich auf 1e-7 Grad gerundet (RASTER)
  - E29  das Register wird nur bei Änderungen geschrieben
  - E35  Raumdaten mit `loeschen: false` werden nie gelöscht (Antwort 74)
  - E40/E42  fester Zielschlüssel, Quellschlüssel im Register, keine Zusammenführung von Datensätzen
  - E46/E47  Geometrie je Objekt umgewandelt, Metadatenkonflikt hält die Quelle an, nichts gekürzt

Ablauf je Quelle, in einer Transaktion (laden.quelle_laden):
 0. planer_einstellen  keine verschachtelten Schleifen in dieser Transaktion (E31)
 1. pruefen       Tabelle, Spalten und Geometriespalte gegen den Katalog der Datenbank
 2. eingang_*     Datensätze der Quelle per COPY in eine temporäre Tabelle
 3. neu_bilden    neuer Stand in den Spaltentypen der Zieltabelle, mit fachlichem Schlüssel;
                  zu lange Texte für varchar(n) werden nicht gekürzt, ihre Zeile wird zurückgehalten
                  (E47; bis E46 gekürzt gespeichert, E31); unlesbare
                  Geometrien werden je Objekt ausgelassen, ungültige korrigiert (E33, E38); auch
                  Reparatur, Transformation und Zieltyp je Objekt (E46)
 4. vergleichen   gegen das Bestandsregister pipeline_meta.bestand: neu, geändert, unverändert,
                  gelöscht (entfernt); eine Zeile, die es schon gab, aber nicht von der Pipeline, zählt
                  fachlich als geändert oder unverändert und zusätzlich als übernommen (E46)
 5. anwenden      UPDATE nur der zugeordneten Spalten (Spalten, die MOSIDI selbst füllt, etwa
                  flood_risk, bleiben stehen), INSERT, DELETE nur für Zeilen aus dem Register und
                  nur bei vollständigem, fehlerfreiem Abruf (Antwort 52)
 6. metadaten_schreiben  table_metadata nach DCAT-AP, in der Form, die MOSIDI selbst verwendet

Konfiguration je Quelle (Beispiele in config/quellen.yaml):
  ziel:
    tabelle: "Gebäude (ALKIS)"     Bestandstabelle (Schema: `schema`, Standard public)
    schluessel: [oid]              Zielspalten, die eine Zeile fachlich bestimmen (Antwort 31)
    spalten: {oid: _id, …}         Zielspalte: Feld der Quelle. Besondere Felder: _id (Objekt-ID der
                                   Quelle), _gebiet (Gebietsschlüssel), bei je_wert _indikator,
                                   _wert, _zeit, _jahr
    geometrie: geom                Geometriespalte, falls die Tabelle eine hat (EPSG:4326)
    fest: {source: INKAR}          feste Werte; kennzeichnen in einer gemeinsamen Tabelle die
                                   Zeilen dieser Quelle (Antwort 27, Spalte source)
    konstant: {data_type: indikator}
                                   feste Werte, die die Zeilen der Quelle NICHT abgrenzen: beim
                                   Anlegen und beim Aktualisieren gesetzt, im Vergleich geprüft
                                   (E40, Codex-Prüfung B11: data_type)
    nur_einfuegen: [id]            Spalten, die nur beim Anlegen gesetzt werden
    pflicht: [wert, zeitbezug]     Pflichtspalten (Antwort 63): Zeilen ohne Wert dort werden mit
                                   Warnung ausgelassen; ihr Schlüssel wird nicht gelöscht
    zusatz: {spalte: indikator, feld: bereich, ausser: [ZOM]}
                                   Feste Regel für Quellschlüssel, die mehr Teile haben als die
                                   Zieltabelle (INKAR: Kennziffer, Bereich, Kürzel, Indikator,
                                   Zeitbezug, Antworten 31/62; dashboard_data_de: kennziffer,
                                   indikator, zeitbezug): `spalte` bekommt den Wert von `feld`
                                   (oder mehrerer Felder, als Liste) in Klammern angehängt, außer
                                   der Wert des ersten Felds steht in `ausser`; dann entfällt nur
                                   dieser Teil (mit [bereich, kuerzel]: ZOM-Zeile „Langtext
                                   (kuerzel)“). Die Regel hängt
                                   nur von den Schlüsselteilen der Zeile selbst ab, nie von Werten
                                   oder davon, welche anderen Zeilen es gibt (E40). Ergeben zwei
                                   Quellschlüssel trotzdem denselben Zielschlüssel, wird die Quelle
                                   angehalten (alter Stand bleibt), nichts wird verworfen.
    loeschen: false                Zeilen, die die Quelle nicht mehr liefert, bleiben stehen und
                                   erscheinen im Bericht (Raumdaten, Antwort 74: Geometrien werden
                                   quellenübergreifend genutzt, gelöscht werden nur Attribute)
    je_wert: {feld: Indikatorname} breite Tabelle in Langform: eine Zeile je Feld
    gebiet: {tabelle, spalte, zielspalte, geometrie, ohne_flaeche: behalten|auslassen}
                                   Prüfung des Gebietsschlüssels gegen eine Geometrietabelle
                                   (Antwort 28: fachlicher Schlüssel, kein Fremdschlüssel);
                                   auslassen: Zeilen ohne Fläche nicht übernehmen, ihr bisheriger
                                   Stand bleibt (Warnung)
      flaeche_pruefen: {wert: wert, faktor_km2: 1, toleranz_prozent: 0.5}
                                   Prüfregel: Wert der Quelle (Fläche) gegen die Fläche der
                                   Geometrie in km²; Abweichungen über der Toleranz sind Warnungen
    metadaten: {je: tabelle|indikator, felder: {dct_…: …}}
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from psycopg import sql
from psycopg.errors import UniqueViolation

# Bezugssystem aller Geometriespalten der Zieltabellen (WGS 84); pruefen lässt daneben nur SRID 0 zu
ZIEL_SRID = 4326
# Geometrien werden für den Vergleich alt/neu auf 1e-7 Grad (rund 1 cm) gerundet (E3)
RASTER = 1e-7
# Metadatentabelle von MOSIDI, immer im Schema public
META_TABELLE = "table_metadata"

# Rhythmus der Quelle als dct:accrualPeriodicity (EU-Vokabular, das DCAT-AP vorsieht)
FREQUENZ = "http://publications.europa.eu/resource/authority/frequency/"
RHYTHMUS_FREQUENZ = {"taeglich": "DAILY", "woechentlich": "WEEKLY", "monatlich": "MONTHLY",
                     "vierteljaehrlich": "QUARTERLY", "jaehrlich": "ANNUAL"}

# Spalten von table_metadata, die die Pipeline setzen kann (für die Rechte der Importrolle). Die
# Schreibweise dct_temporal_startdata (nicht …startdate) ist die von MOSIDI (sql/mosidi/001_bestand.sql)
META_SPALTEN = ["table_name", "dct_title", "dct_description", "dct_catalog_title",
                "dct_catalog_description", "dct_catalog_publisher", "dct_accessurl", "dct_license",
                "dct_identifier", "dct_language", "dct_type", "geometry_type",
                "dcatde_politicalgeocodingleveluri", "dct_accrualperiodicity", "dct_modified",
                "dct_issued", "imported", "dct_bbox", "dct_centroid", "dct_temporal_startdata",
                "dct_temporal_enddate"]
# Kennung der Indikatorzeile im Skript von MOSIDI (db_table_metadata/script.py legt die Spalte an, das
# öffentliche Schema in sql/mosidi/001_bestand.sql hat sie nicht). Die Pipeline setzt sie seit E52 nur, wo sie
# leer ist (nie überschrieben: MOSIDI ersetzt den Wert später durch eine Themenklasse wie SOCI oder ENER, die
# bleiben muss), deshalb nicht in META_SPALTEN: Diese Spalten setzt metadaten_schreiben bei jedem Lauf neu,
# und `felder` der Konfiguration kann sie belegen. Rechte der Importrolle: einrichten vergibt sie wie für
# META_SPALTEN, wenn es die Spalte gibt
DCAT_AP_ID = "dcat_ap_id"
META_SPALTEN_NUR_LEER = [DCAT_AP_ID]
# Schreibweise der Geometrieart in table_metadata.geometry_type (MOSIDI schreibt z. B. 'Polygon')
GEOMETRIEART = {"POINT": "Point", "MULTIPOINT": "MultiPoint", "LINESTRING": "LineString",
                "MULTILINESTRING": "MultiLineString", "POLYGON": "Polygon",
                "MULTIPOLYGON": "MultiPolygon", "GEOMETRY": "Geometry"}


class ZielFehler(RuntimeError):
    """Zuordnung passt nicht zur Datenbank (Tabelle oder Spalte fehlt). In Arbeitspaket 1 heißt
    das: Konfiguration an das gelieferte DDL anpassen, nicht das Schema.

    laden behandelt ZielFehler wie jeden Fehler einer Quelle: Die Transaktion wird zurückgerollt, die
    übrigen Quellen laufen weiter (E7)."""


@dataclass
class Ziel:
    """Zuordnung einer Quelle zu ihrer Zieltabelle, wie sie unter `ziel` in der Konfiguration steht.

    Die Felder bis `konstant` entsprechen den gleichnamigen Schlüsseln (siehe Moduldocstring), angelegt
    von aus_konfiguration. `typen` und `geom_typ` kommen erst aus der Datenbank: pruefen füllt sie aus
    dem Katalog und legt bei Metadaten zusätzlich die vorhandenen Spalten von table_metadata unter
    metadaten["_spalten"] ab. Alle Funktionen, die SQL bauen, setzen voraus, dass pruefen gelaufen ist."""

    tabelle: str
    schluessel: list[str]
    spalten: dict[str, str]
    schema: str = "public"
    geometrie: str | None = None
    fest: dict = field(default_factory=dict)
    nur_einfuegen: list[str] = field(default_factory=list)
    je_wert: dict | None = None
    gebiet: dict | None = None
    metadaten: dict = field(default_factory=dict)
    loeschen: bool = True                                  # False: Raumdaten bleiben (Antwort 74)
    pflicht: list[str] = field(default_factory=list)       # Pflichtspalten (Antwort 63)
    zusatz: dict | None = None                             # {spalte, feld, ausser}: Schlüsselregel (E40)
    konstant: dict = field(default_factory=dict)           # feste Werte ohne Abgrenzung (E40, B11)
    typen: dict[str, str] = field(default_factory=dict)   # Spalte -> Typ laut Datenbank
    geom_typ: str | None = None                            # z. B. MULTIPOLYGON

    @property
    def ident(self) -> sql.Identifier:
        """Schema und Tabelle als SQL-Bezeichner; Namen wie „Gebäude (ALKIS)“ werden so sicher zitiert."""
        return sql.Identifier(self.schema, self.tabelle)

    @property
    def name(self) -> str:
        """Name für Register, Protokoll und Meldungen: ohne Schema, wenn es public ist."""
        return self.tabelle if self.schema == "public" else f"{self.schema}.{self.tabelle}"

    def spalten_neu(self) -> list[str]:
        """Spalten des neuen Stands: zugeordnete, feste, konstante, Geometrie (in dieser Reihenfolge).

        Ein fester Wert für eine Spalte, die auch zugeordnet ist, erscheint nur einmal; es gilt dann die
        Zuordnung. Die Liste bestimmt die Spalten der Tabelle `neu`, das INSERT in anwenden und das
        Spaltenrecht INSERT der Importrolle (einrichten.rechte)."""
        aus = list(self.spalten) + [s for s in self.fest if s not in self.spalten]
        aus += [s for s in self.konstant if s not in aus]
        if self.geometrie:
            aus.append(self.geometrie)
        return aus

    def spalten_aendern(self) -> list[str]:
        """Spalten, die ein UPDATE setzt und die der Vergleich prüft.

        Die Spalten aus `spalten` und `ziel.konstant` (konstant wird also gesetzt und verglichen), ohne
        Schlüsselspalten (die bestimmen die Zeile) und ohne nur_einfuegen. `ziel.fest` fehlt: Es grenzt den
        Bereich der Quelle ab und ist in jeder Zeile des Bereichs gleich. Die Geometrie fügen _anders und
        anwenden selbst hinzu."""
        return [s for s in [*self.spalten, *self.konstant]
                if s not in self.nur_einfuegen and s not in self.schluessel]

    def alle_spalten(self) -> list[str]:
        """Alle Spalten, die es in der Zieltabelle geben muss (pruefen): neuer Stand und Schlüssel,
        ohne Doppelte, Reihenfolge wie spalten_neu."""
        return list(dict.fromkeys([*self.spalten_neu(), *self.schluessel]))


def aus_konfiguration(name: str, qcfg: dict) -> Ziel:
    """Ziel aus der Konfiguration lesen, ohne Datenbank (für Einrichten, Tests, Probelauf).

    Args:
        name: Name der Quelle, nur für die Fehlermeldungen.
        qcfg: Konfiguration der Quelle; gelesen wird der Abschnitt `ziel`.

    Returns:
        Ziel ohne Typen aus der Datenbank (die ergänzt pruefen).

    Raises:
        ZielFehler: Tabelle oder Schlüssel fehlt, eine Schlüsselspalte ist weder zugeordnet noch fest,
            der Schlüssel `unterscheiden` von vor E40 steht noch in der Konfiguration, `zusatz` ist
            unvollständig oder eine Spalte steht zugleich in `konstant` und in `spalten`/`fest`.
    """
    z = qcfg.get("ziel")
    if not isinstance(z, dict) or not z.get("tabelle"):
        raise ZielFehler(f"Quelle {name}: kein Ziel konfiguriert (ziel.tabelle fehlt)")
    if not z.get("schluessel"):
        raise ZielFehler(f"Quelle {name}: ziel.schluessel fehlt (Spalten, die eine Zeile bestimmen)")
    # Listen und Wörterbücher als Kopien: pruefen ergänzt z.metadaten["_spalten"], das soll nicht in der
    # Konfiguration landen, die einrichten und laden mehrfach lesen. Löschen schaltet
    # nur ein ausdrückliches `loeschen: false` ab (Raumdaten, Antwort 74); fehlt der Schlüssel, gilt true
    ziel = Ziel(tabelle=z["tabelle"], schema=z.get("schema", "public"), schluessel=list(z["schluessel"]),
                spalten=dict(z.get("spalten") or {}), geometrie=z.get("geometrie"),
                fest=dict(z.get("fest") or {}), nur_einfuegen=list(z.get("nur_einfuegen") or []),
                je_wert=z.get("je_wert"), gebiet=z.get("gebiet"), metadaten=dict(z.get("metadaten") or {}),
                loeschen=z.get("loeschen", True) is not False, pflicht=list(z.get("pflicht") or []),
                zusatz=z.get("zusatz"), konstant=dict(z.get("konstant") or {}))
    # Jede Schlüsselspalte braucht einen Wert, sonst wäre jede Zeile in neu_bilden „ohne Schlüssel“
    fehlen = [s for s in ziel.schluessel if s not in ziel.spalten and s not in ziel.fest]
    if fehlen:
        raise ZielFehler(f"Quelle {name}: Schlüsselspalte ohne Zuordnung: {', '.join(fehlen)}")
    if "unterscheiden" in z:
        # Bis E39 hing die Kennzeichnung davon ab, ob zwei Zeilen verschiedene Werte hatten; das
        # änderte Zielschlüssel mit den Messwerten (Codex-Prüfung 05.11., B1)
        raise ZielFehler(f"Quelle {name}: ziel.unterscheiden gibt es seit E40 nicht mehr, "
                         "stattdessen ziel.zusatz (feste Regel, docs/entscheidungen.md E40)")
    if ziel.zusatz is not None:
        zs = ziel.zusatz
        felder = zs.get("feld") if isinstance(zs, dict) else None
        if (not isinstance(zs, dict) or zs.get("spalte") not in ziel.spalten
                or not felder or not isinstance(felder, str | list)):
            raise ZielFehler(f"Quelle {name}: ziel.zusatz braucht spalte (eine zugeordnete Spalte) "
                             "und feld (Quellfeld oder Liste von Quellfeldern)")
    # Eine Spalte mit zwei Quellen für ihren Wert wäre mehrdeutig; ein Tippfehler soll hier auffallen,
    # nicht erst als unerklärter Wert in der Zieltabelle
    doppelt = set(ziel.konstant) & (set(ziel.spalten) | set(ziel.fest))
    if doppelt:
        raise ZielFehler(f"Quelle {name}: Spalte in ziel.konstant und zugeordnet/fest: {', '.join(doppelt)}")
    return ziel


def pruefen(cur, z: Ziel) -> None:
    """Tabelle, Spalten und Typen aus dem Katalog lesen. Fehlt etwas, bricht die Quelle mit einer
    klaren Meldung ab, bevor irgendetwas abgerufen oder geschrieben wird.

    Liest nur den Katalog (pg_attribute, geometry_columns), schreibt nichts in die Datenbank.

    Args:
        cur: Cursor in der Transaktion der Quelle.
        z: Ziel aus aus_konfiguration.

    Seiteneffekte:
        Ändert `z`: setzt z.typen (Spalte -> Typ wie format_type()), z.geom_typ und bei Metadaten
        z.metadaten["_spalten"] (vorhandene Spalten von table_metadata) und z.metadaten["_dcat_ap_id"]
        (E52: None ohne Spalte dcat_ap_id, sonst ob die Importrolle sie anlegen und ändern darf).

    Raises:
        ZielFehler: Tabelle, Spalte, Geometriespalte, Gebietstabelle oder table_metadata fehlt, oder
            die Geometriespalte hat ein anderes Bezugssystem als EPSG:4326.
    """
    # to_regclass statt eines Casts auf regclass: Eine fehlende Tabelle gibt NULL und damit eine leere
    # Liste, keinen Fehler, der die Transaktion abbräche; die Meldung unten sagt dann, was fehlt
    cur.execute("""SELECT a.attname, format_type(a.atttypid, a.atttypmod)
                   FROM pg_attribute a WHERE a.attrelid = to_regclass(%s)
                   AND a.attnum > 0 AND NOT a.attisdropped""", (z.ident.as_string(cur),))
    z.typen = dict(cur.fetchall())
    if not z.typen:
        raise ZielFehler(f"Zieltabelle {z.name} fehlt in der Datenbank (oder keine Leserechte)")
    fehlen = [s for s in z.alle_spalten() if s not in z.typen]
    if fehlen:
        raise ZielFehler(f"Spalten fehlen in {z.name}: {', '.join(fehlen)}")
    if z.geometrie:
        cur.execute("""SELECT type, srid FROM geometry_columns WHERE f_table_schema = %s
                       AND f_table_name = %s AND f_geometry_column = %s""",
                    (z.schema, z.tabelle, z.geometrie))
        zeile = cur.fetchone()
        if not zeile:
            raise ZielFehler(f"{z.name}.{z.geometrie} ist keine Geometriespalte")
        z.geom_typ, srid = zeile
        # SRID 0 heißt: Spalte ohne festgelegtes Bezugssystem; geschrieben wird dort trotzdem EPSG:4326,
        # weil _geom_ausdruck jede Geometrie nach ZIEL_SRID transformiert
        if srid not in (0, ZIEL_SRID):
            raise ZielFehler(f"{z.name}.{z.geometrie} hat EPSG:{srid}, erwartet EPSG:{ZIEL_SRID}")
    if z.gebiet:
        # Die Gebietstabelle wird nur gelesen (Antwort 28: fachlicher Schlüssel, kein Fremdschlüssel)
        g = z.gebiet
        cur.execute("SELECT count(*) FROM pg_attribute WHERE attrelid = to_regclass(%s) AND attname = %s",
                    (sql.Identifier(g.get("schema", "public"), g["tabelle"]).as_string(cur), g["spalte"]))
        if not cur.fetchone()[0]:
            raise ZielFehler(f"Gebietstabelle {g['tabelle']} oder Spalte {g['spalte']} fehlt")
        if g.get("zielspalte", z.schluessel[0]) not in z.typen:
            raise ZielFehler(f"gebiet.zielspalte {g.get('zielspalte')} fehlt in {z.name}")
    if z.metadaten:
        cur.execute("""SELECT attname FROM pg_attribute WHERE attrelid = to_regclass(%s)
                       AND attnum > 0 AND NOT attisdropped""",
                    (sql.Identifier("public", META_TABELLE).as_string(cur),))
        vorhanden = {r[0] for r in cur.fetchall()}
        if not vorhanden:
            raise ZielFehler(f"Metadatentabelle {META_TABELLE} fehlt")
        # Öffentliches Schema und Skript von MOSIDI haben verschiedene Spalten (sql/mosidi/001_bestand.sql);
        # _metadaten_zeilen und das INSERT in metadaten_schreiben nehmen nur Felder auf, deren Spalte es hier
        # gibt. Das UPDATE dort setzt imported, dct_bbox, dct_centroid und dct_modified aber ungefiltert;
        # diese Spalten muss table_metadata haben (die Fassung in sql/mosidi/001_bestand.sql hat sie)
        z.metadaten["_spalten"] = vorhanden
        # dcat_ap_id (E52) nur, wenn es die Spalte gibt und die Importrolle sie anlegen und ändern darf:
        # Ist die Spalte erst nach dem letzten einrichten entstanden (etwa durch das Skript von MOSIDI),
        # fehlt das Recht, und ein UPDATE mit dieser Spalte schlüge mit permission denied fehl (die ganze
        # Quelle). Dann bleibt sie leer, metadaten_schreiben nennt es. (Nach einem Update der Pipeline ohne
        # einrichten kommt es hierzu nicht: Dann hält schon laden.meta_pruefen wegen der neuen Spalten von
        # pipeline_meta an.)
        z.metadaten["_dcat_ap_id"] = None
        if DCAT_AP_ID in vorhanden:
            tabelle = sql.Identifier("public", META_TABELLE).as_string(cur)
            cur.execute("SELECT has_column_privilege(%s, %s, 'INSERT') "
                        "AND has_column_privilege(%s, %s, 'UPDATE')",
                        (tabelle, DCAT_AP_ID, tabelle, DCAT_AP_ID))
            z.metadaten["_dcat_ap_id"] = bool(cur.fetchone()[0])


def planer_einstellen(cur) -> None:
    """Abgleich ohne verschachtelte Schleifen, nur für die laufende Transaktion (E31).

    Hat autovacuum eine Zieltabelle noch nicht analysiert, nachdem eben Zeilen desselben Bereichs
    (gleiche feste Werte, z. B. source) hineingeschrieben wurden, schätzt der Planer den Bereich auf
    eine Zeile und wählt eine verschachtelte Schleife: bei 100 000 Zeilen je Seite 10^10 Vergleiche.
    ANALYZE darf die Importrolle nicht (nur der Eigentümer, ab PostgreSQL 17 auch MAINTAIN, das aber
    zugleich LOCK TABLE, VACUUM, REINDEX und CLUSTER erlaubt). Alle Verknüpfungen hier sind
    Gleichheiten über Schlüsselspalten ohne Index in den Bestandstabellen; eine Hash- oder Merge-
    Verknüpfung liest jede Seite einmal und hängt nicht von der Schätzung ab.

    Args:
        cur: Cursor in einer offenen Transaktion (laden.quelle_laden, betrieb.archiv_schreiben); außerhalb
            einer Transaktion hätte SET LOCAL keine Wirkung.

    Seiteneffekt: SET LOCAL gilt bis zum Ende der laufenden Transaktion, also der Transaktion der Quelle in
    laden.quelle_laden (für alle Abfragen dort) bzw. der eigenen Lesetransaktion des Stand-Archivs in
    laden._nachlauf; danach ist der Planer wieder im Ausgangszustand."""
    cur.execute("SET LOCAL enable_nestloop = off")


# Texttypen mit Höchstlänge, so wie format_type() sie schreibt (varchar(n) heißt dort
# „character varying(n)“, char(n) „character(n)“)
TEXTLAENGE = re.compile(r"^(?:character varying|character)\((\d+)\)$")
# Höchstzahl der Schlüssel, die eine Warnung zu langer Texte als Beispiel nennt
KUERZUNG_BEISPIELE = 10
# Die einzige Form, die in eine zu kurze Spalte verlustfrei passt (E47): ein Datum nach ISO 8601 mit der
# Zeitzonenkennung Z (xs:date in UTC), so liefert der ALKIS-WFS der LGB `aktualit` (882 von 882 Gebäuden des
# Ausschnitts, Abruf 05.11.2026). Übernommen wird JJJJ-MM-TT: Der Tag bleibt, weg fällt nur die Angabe, dass
# er in UTC gilt. Dasselbe Muster prüft PostgreSQL (~) und Python (Tests)
DATUM_Z_MUSTER = r"^\d{4}-\d{2}-\d{2}Z$"
DATUM_Z = re.compile(DATUM_Z_MUSTER)


def laengen(z: Ziel) -> dict[str, int]:
    """Spalten mit Höchstlänge (varchar(n), char(n)): Spalte -> n.

    Berücksichtigt zugeordnete Spalten und die Spalten fester Werte (fest, konstant); Typen aus z.typen,
    also erst nach pruefen sinnvoll. Spalten ohne Längengrenze (text, Zahlen) fehlen im Ergebnis.

    Args:
        z: Ziel nach pruefen.

    Returns:
        Spalte -> Höchstzahl der Zeichen."""
    aus = {}
    for s in [*z.spalten, *z.fest, *z.konstant]:
        m = TEXTLAENGE.match(z.typen.get(s, ""))
        if m:
            aus[s] = int(m[1])
    return aus


def _zu_lang(s: str, n: int, alias: str = "e") -> sql.Composable:
    """Wert der Quelle länger als n Zeichen; nur folgende Leerzeichen abzuschneiden ist kein Verlust (so
    behandelt es PostgreSQL auch bei der Zuweisung).

    Args:
        s: Zielspalte, deren Wert in `werte` (jsonb) der Tabelle `eingang` steht.
        n: Höchstlänge der Spalte.
        alias: Alias der Tabelle `eingang` in der umgebenden Abfrage.

    Returns:
        SQL-Bedingung (boolean); Spaltenname und Länge als Literale, nicht als Text eingesetzt."""
    return sql.SQL("char_length(rtrim({} ->> {}, ' ')) > {}").format(
        sql.Identifier(alias, "werte"), sql.Literal(s), sql.Literal(n))


def laengen_pruefen(cur, z: Ziel, prot) -> str | None:
    """Texte, die länger sind als ihre Zielspalte, kürzt PostgreSQL beim Umwandeln ohne Fehler (CAST auf
    varchar(n)). Bis E46 lud die Pipeline sie gekürzt und warnte (E31). Seit E47 (Prüfbericht 05.11. abends,
    Befund 3) kürzt sie nichts mehr:
      - ein Datum der Form JJJJ-MM-TTZ wird ohne Z übernommen, wenn die Spalte dafür zu kurz ist (DATUM_Z,
        Zahl je Spalte unter `normalisiert` und als Hinweis);
      - jede andere zu lange Angabe hält ihre Zeile zurück: ein neues Objekt wird nicht angelegt, ein
        vorhandenes behält seinen bisherigen Stand und wird nicht gelöscht (neu_bilden; Zahl je Spalte unter
        `zu_lang`, Warnung mit den ersten Schlüsseln, ohne die Texte selbst: Berichte werden weitergegeben);
      - ist eine Schlüsselspalte oder ein fester Wert (ziel.fest, ziel.konstant) betroffen, wird die Quelle
        angehalten (Rückgabe: Grund), sonst None.

    Läuft zu Beginn von neu_bilden auf der temporären Tabelle `eingang` (Seiteneffekt: UPDATE der
    Datumswerte dort) und schreibt Zähler und Meldungen in `prot` (info, hinweise, warnungen). Die
    Zieltabelle wird nicht berührt; das Zurückhalten der Zeilen geschieht in neu_bilden über das Merkmal
    _zu_lang.

    Args:
        cur: Cursor in der Transaktion der Quelle, `eingang` ist gefüllt.
        z: Ziel nach pruefen (z.typen bekannt).
        prot: Protokoll der Quelle (pipeline.quellen.Protokoll).

    Returns:
        Grund, die Quelle anzuhalten (zu langer fester Wert oder Schlüssel), sonst None."""
    grenzen = laengen(z)
    zu_lang: dict[str, int] = {}
    feste = {**z.konstant, **z.fest}
    # Feste Werte stehen in der Konfiguration, nicht in der Quelle: zu lang heißt Konfigurationsfehler, und
    # jede Zeile der Quelle wäre betroffen; deshalb vor jeder Abfrage und mit Anhalten statt Zurückhalten
    for s, n in grenzen.items():
        if s in feste and s not in z.spalten and len(str(feste[s]).rstrip(" ")) > n:
            zu_lang[s] = 1
    if zu_lang:
        prot.info["zu_lang"] = zu_lang
        return (f"Fester Wert für {', '.join(zu_lang)} länger als "
                f"{', '.join(str(grenzen[s]) for s in zu_lang)} Zeichen, nicht gekürzt: Konfiguration "
                "anpassen (ziel.fest, ziel.konstant); Quelle angehalten, alter Stand bleibt unverändert")
    spalten = [s for s in grenzen if s in z.spalten]
    if not spalten:
        return None
    normalisiert = {}
    for s in spalten:
        # JJJJ-MM-TT hat 10 Zeichen; in eine kürzere Spalte passt auch das Datum ohne Z nicht
        if grenzen[s] < 10:
            continue
        # Nur Werte, die zu lang sind UND genau dem Muster folgen: left(…, 10) schneidet dann nur das Z ab
        cur.execute(sql.SQL("UPDATE eingang e SET werte = jsonb_set(e.werte, ARRAY[{s}], "
                            "to_jsonb(left(e.werte ->> {s}, 10))) "
                            "WHERE {lang} AND e.werte ->> {s} ~ {m}").format(
            s=sql.Literal(s), lang=_zu_lang(s, grenzen[s]), m=sql.Literal(DATUM_Z_MUSTER)))
        if cur.rowcount:
            normalisiert[s] = cur.rowcount
            prot.hinweise.append(f"{cur.rowcount} Werte in {s} als Datum ohne Zeitzonenkennung Z übernommen "
                                 f"(JJJJ-MM-TTZ, Spalte hat {grenzen[s]} Zeichen; der Tag bleibt, E47)")
    if normalisiert:
        prot.info["normalisiert"] = normalisiert
    # Eine Abfrage für alle Spalten; gezählt werden verschiedene Quellschlüssel (oid), nicht Zeilen
    cur.execute(sql.SQL("SELECT {} FROM eingang e").format(sql.SQL(", ").join(
        sql.SQL("count(DISTINCT e.oid) FILTER (WHERE {})").format(_zu_lang(s, grenzen[s])) for s in spalten)))
    grund = None
    for s, anzahl in zip(spalten, cur.fetchone(), strict=True):
        if not anzahl:
            continue
        zu_lang[s] = anzahl
        cur.execute(sql.SQL("""SELECT max(char_length(e.werte ->> {s})), (array_agg(DISTINCT e.oid))[1:{b}]
                               FROM eingang e WHERE {lang}""").format(
            s=sql.Literal(s), b=sql.Literal(KUERZUNG_BEISPIELE), lang=_zu_lang(s, grenzen[s])))
        laengste, beispiele = cur.fetchone()
        # Nur Länge und Schlüssel in die Meldung, nie den Text selbst: Berichte werden weitergegeben
        mehr = " …" if anzahl > len(beispiele) else ""
        kopf = (f"{anzahl} Objekt{'e' if anzahl != 1 else ''} mit {s} länger als {grenzen[s]} Zeichen "
                f"(bis {laengste})")
        # Eine zu kurze Schlüsselspalte ist ein Konfigurationsfehler (falsche Zielspalte), kein Problem
        # einzelner Objekte: Quelle anhalten statt Zeilen zurückhalten (E32)
        if s in z.schluessel:
            prot.warnungen.append(f"{kopf}, nicht geladen: {', '.join(beispiele)}{mehr}; Schlüsselspalte")
            grund = "Schlüsselspalte zu kurz für Werte der Quelle, alter Stand bleibt unverändert"
        else:
            prot.warnungen.append(f"{kopf}, nicht übernommen, {'sein' if anzahl == 1 else 'ihr'} bisheriger "
                                  f"Stand bleibt: {', '.join(beispiele)}{mehr}")
    if zu_lang:
        prot.info["zu_lang"] = zu_lang
    return grund


# --- Eingang: Datensätze der Quelle --------------------------------------------------------

# oid: Quellschlüssel der Zeile (Objekt-ID, bei je_wert mit dem Feld); leer: Zeile ohne jeden Messwert,
# die der Adapter nur zur Kenntnis gibt (CSV mit leere_auslassen, Codex-Prüfung 05.11., B2)
# nr: laufende Nummer in Lieferreihenfolge (entscheidet bei gleichen Doppelten, welche Zeile bleibt);
# werte: Werte je Zielspalte als JSON, noch ohne Typumwandlung; geom_art/geom_text: Geometrie als Text
# (gml, wkt oder geojson), gelesen erst in geometrien_lesen; gebiet: Gebietsschlüssel bei Kennzahlen.
# ON COMMIT DROP: Die Tabelle verschwindet mit der Transaktion der Quelle, zwei Läufe stören sich nicht
EINGANG_TABELLE = """CREATE TEMP TABLE eingang (nr integer, oid text, werte jsonb, geom_art text,
                     geom_text text, gebiet text, leer boolean) ON COMMIT DROP"""


def _wert(v):
    """Ganze Zahlen als int ablegen, damit sie auch in integer-Spalten passen (73945.0 -> 73945).

    CAST('73945.0' AS integer) schlägt in PostgreSQL fehl; als JSON-Zahl 73945 passt der Wert in
    integer- und numeric-Spalten. Alle anderen Werte kommen unverändert zurück."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def zusatz_anwenden(werte: dict, quelle: dict, zusatz: dict) -> None:
    """Feste Regel aus ziel.zusatz (E40): Zielspalte um Teile des Quellschlüssels ergänzen. Hängt nur
    von diesen Teilen der Zeile selbst ab, nicht von Werten oder anderen Zeilen. Fehlt ein Teil, wird
    die Zielspalte leer (None). Ist sie eine Schlüsselspalte (bei INKAR `indikator`), fällt die Zeile in
    neu_bilden als „ohne Schlüssel“ heraus und der Abruf gilt als unvollständig, statt mit einer anderen
    Zeile zusammenzufallen; aus_konfiguration verlangt nur, dass die Spalte zugeordnet ist.
    `ausser` gilt nur für den ersten Teil (bei INKAR den Bereich): Mit feld: [bereich, kuerzel] bekommt
    eine ZOM-Zeile „Langtext (kuerzel)“, eine LRB-Zeile „Langtext (LRB, kuerzel)“ (E42).

    Args:
        werte: Werte je Zielspalte; wird verändert (werte[zusatz["spalte"]]).
        quelle: Felder der Quellzeile (Werte und besondere Felder wie _indikator).
        zusatz: ziel.zusatz mit spalte, feld (Name oder Liste) und optional ausser.
    """
    spalte = zusatz["spalte"]
    felder = [zusatz["feld"]] if isinstance(zusatz["feld"], str) else list(zusatz["feld"])
    teile = [str(quelle.get(f) or "").strip() for f in felder]
    if werte.get(spalte) is None or not all(teile):
        werte[spalte] = None
        return
    if teile[0] in [str(a) for a in zusatz.get("ausser") or []]:
        teile = teile[1:]
    # Bleibt nach `ausser` nichts übrig (ein einziges Feld), bleibt der Wert wie geliefert
    if teile:
        werte[spalte] = f"{werte[spalte]} ({', '.join(teile)})"


def zeilen(ds: dict, z: Ziel):
    """Ein Datensatz der Quelle als Zeilen der Zieltabelle (meist eine, bei je_wert eine je Feld).
    Liefert (werte je Zielspalte, (geom_art, geom_text) oder None, Gebietsschlüssel oder None).
    Bei je_wert steht in werte["_q"] der Quellschlüssel der Zeile (Objekt-ID und Feld).

    Args:
        ds: Datensatz eines Adapters aus pipeline.quellen (objekt_id, werte, geom, optional zeit).
        z: Ziel mit der Zuordnung Zielspalte -> Feld.

    Yields:
        Tupel (werte, geom, gebiet). Bei je_wert fehlen Felder, die der Datensatz nicht hat; aus einem
        Datensatz können also auch null Zeilen werden.
    """
    # Kennzahlen haben keine eigene Geometrie, sondern einen Gebietsschlüssel (Adapter: Art „gebiet“)
    art, text = ds["geom"]
    geom = None if art == "gebiet" else (art, text)
    gebiet = text if art == "gebiet" else None
    basis = {"_id": ds["objekt_id"], "_gebiet": gebiet, **ds["werte"]}
    zeit = ds.get("zeit") or {}
    if z.je_wert:
        varianten = []
        for feld, indikator in z.je_wert.items():
            if feld not in ds["werte"]:
                continue
            t = zeit.get(feld)
            # _jahr: die ersten vier Zeichen des Zeitbezugs (etwa „2023“ aus „2023-12-31“)
            varianten.append({**basis, "_indikator": indikator, "_wert": ds["werte"][feld],
                              "_zeit": t, "_jahr": str(t)[:4] if t else None,
                              "_q": f"{ds['objekt_id']}|{feld}"})
    else:
        varianten = [basis]
    for v in varianten:
        werte = {spalte: _wert(v.get(feld)) for spalte, feld in z.spalten.items()}
        if z.zusatz:
            zusatz_anwenden(werte, v, z.zusatz)
        if "_q" in v:
            werte["_q"] = v["_q"]
        yield werte, geom, gebiet


def eingang_kopie(cur):
    """COPY-Strom in die temporäre Tabelle `eingang` (als Kontextmanager zu verwenden).

    COPY statt einzelner INSERTs: INKAR bundesweit liefert rund 1,5 Mio. Zeilen (gemessen im
    Deutschland-Lauf, der Anlass von E29 war; beispielberichte/deutschland/).

    Args:
        cur: Cursor in der Transaktion der Quelle; `eingang` ist angelegt (EINGANG_TABELLE).

    Returns:
        Kontextmanager von psycopg (Cursor.copy); `with … as kopie` liefert das Copy-Objekt, in das
        eingang_zeile schreibt. Beim Verlassen des Kontexts ist COPY abgeschlossen."""
    return cur.copy("COPY eingang (nr, oid, werte, geom_art, geom_text, gebiet, leer) FROM STDIN")


def eingang_zeile(kopie, nr: int, oid: str, werte: dict, geom, gebiet, leer: bool = False) -> None:
    """Eine Zeile aus zeilen() in den COPY-Strom schreiben.

    Args:
        kopie: Strom aus eingang_kopie.
        nr: laufende Nummer der Zeile.
        oid: Objekt-ID der Quelle; ersetzt durch werte["_q"], wenn es das gibt (je_wert).
        werte: Werte je Zielspalte; `_q` wird daraus entfernt (verändert das übergebene dict).
        geom: (Art, Text) oder None.
        gebiet: Gebietsschlüssel oder None.
        leer: Zeile ohne jeden Messwert (CSV mit leere_auslassen).
    """
    art, text = geom if geom else (None, None)
    oid = werte.pop("_q", oid)
    kopie.write_row((nr, oid, json.dumps(werte, ensure_ascii=False), art, text, gebiet, leer))


# --- Neuer Stand in den Typen der Zieltabelle ----------------------------------------------

# Dimension für ST_CollectionExtract je Geometrietyp der Zieltabelle (1 Punkt, 2 Linie, 3 Fläche)
DIMENSION = {"POINT": 1, "MULTIPOINT": 1, "LINESTRING": 2, "MULTILINESTRING": 2,
             "POLYGON": 3, "MULTIPOLYGON": 3}

# Geometrie der Quelle, einmal je Zeile gelesen (geometrien_lesen); unlesbare Zeilen haben dann g = NULL
# (Fehler in g_fehler), ein Lesefehler kann die Quelle nicht mehr abbrechen. ST_Force2D: die Zieltabellen
# sind zweidimensional, eine Höhe aus GML würde sonst Vergleich und Zieltyp stören
_ROH = sql.SQL("ST_Force2D(e.g)")

# Liest eine Geometrie; was PostGIS nicht lesen kann (etwa "POLYGON(kaputt)" oder ein Ring mit weniger
# als vier Punkten), gibt NULL und die Fehlermeldung zurück, statt die Transaktion abzubrechen. Der
# EXCEPTION-Block setzt je Zeile einen Sicherungspunkt. ST_IsValid steht vorsorglich mit darin: Ältere
# PostGIS/GEOS-Fassungen warfen bei lesbaren, aber kaputten Ringen einen Fehler statt false. Mit
# PostGIS 3.6.4 und GEOS 3.14.1 (PostgreSQL 16 und 18, 05.11.2026) ließ sich kein solcher Fall finden:
# Offene Ringe, Ringe mit drei Punkten, NaN und Unendlich ergeben false, nicht Fehler. Die Funktion liegt in
# pg_temp (nur diese Sitzung, kein Recht auf ein Schema nötig) und wird bei jeder Quelle neu angelegt,
# weil ein Rollback sie wieder entfernt.
# Arten: gml (SRID aus dem srsName der GML), wkt (als EWKT, ein SRID=…; davor wird beachtet), geojson
# (nach RFC 7946 immer WGS 84, daher fest 4326). Eine unbekannte Art ergibt NULL ohne Fehlermeldung;
# neu_bilden lässt solche Zeilen als „unbrauchbar“ aus und meldet den Abruf als unvollständig.
GEOM_LESEN = """CREATE OR REPLACE FUNCTION pg_temp.geom_lesen(art text, txt text,
                                                OUT g geometry, OUT fehler text)
LANGUAGE plpgsql AS $$
BEGIN
    g := CASE art WHEN 'gml' THEN ST_GeomFromGML(txt)
                  WHEN 'wkt' THEN ST_GeomFromEWKT(txt)
                  WHEN 'geojson' THEN ST_SetSRID(ST_GeomFromGeoJSON(txt), 4326) END;
    PERFORM ST_IsValid(g);
EXCEPTION WHEN OTHERS THEN
    g := NULL;
    fehler := SQLERRM;
END $$"""


def geometrien_lesen(cur, z: Ziel, prot) -> int:
    """Antwort 63 / Codex-Prüfung B3: Geometrien, die PostGIS nicht lesen kann, werden objektweise
    ausgelassen, nicht die ganze Quelle. Der Abruf gilt dann als unvollständig (nichts wird
    gelöscht, E23/E32); der bisherige Stand dieser Objekte bleibt. Rückgabe: Zahl der Objekte.

    Seiteneffekte: legt pg_temp.geom_lesen an, ergänzt `eingang` um die Spalten g (gelesene Geometrie)
    und g_fehler (Meldung von PostGIS) und meldet den Abruf über prot.unvollstaendig_melden als
    unvollständig, sobald ein Objekt betroffen ist.

    Args:
        cur: Cursor in der Transaktion der Quelle, `eingang` ist gefüllt.
        z: Ziel mit Geometriespalte (aufgerufen nur, wenn z.geometrie gesetzt ist).
        prot: Protokoll der Quelle."""
    cur.execute(GEOM_LESEN)
    cur.execute("ALTER TABLE eingang ADD COLUMN g geometry, ADD COLUMN g_fehler text")
    cur.execute("""UPDATE eingang e SET (g, g_fehler) = (SELECT l.g, l.fehler
                                                        FROM pg_temp.geom_lesen(e.geom_art, e.geom_text) l)
                   WHERE e.geom_art IS NOT NULL""")
    # Die Zeilen bleiben im Eingang (Geometrie NULL), damit die Prüfung auf eindeutige Schlüssel in
    # neu_bilden auch sie sieht; ausgelassen werden sie dort nach dieser Prüfung (E42)
    # Für die Meldung: Zahl der Objekte, die ersten zehn Schlüssel und der erste Fehler in Lieferreihenfolge
    cur.execute("""SELECT count(DISTINCT oid), (array_agg(DISTINCT oid))[1:10],
                          (array_agg(g_fehler ORDER BY nr))[1] FROM eingang WHERE g_fehler IS NOT NULL""")
    n, beispiele, fehler = cur.fetchone()
    if n:
        prot.info["geometrie_unlesbar"] = n
        # Fehlermeldung auf eine Zeile und 160 Zeichen gekürzt: Sie steht im Bericht, nicht im Log
        prot.unvollstaendig_melden(
            f"{n} Geometrie{'n' if n != 1 else ''} nicht lesbar, Objekt{'e' if n != 1 else ''} ausgelassen, "
            f"bisheriger Stand bleibt: {', '.join(beispiele)}{' …' if n > len(beispiele) else ''} "
            f"(erster Fehler: {' '.join(str(fehler).split())[:160]})")
    return n


def _geom_ausdruck(z: Ziel, roh: sql.Composable) -> sql.Composable:
    """Geometrie der Quelle in Typ und Bezugssystem der Zieltabelle. Ungültige Geometrien werden
    mit ST_MakeValid korrigiert und auf die Dimension der Zieltabelle beschränkt (Antwort 63);
    bleibt nichts übrig, ist das Ergebnis leer und neu_bilden lässt die Zeile mit Warnung aus.
    Ausgewertet je Objekt in pg_temp.geom_ziel (geometrien_umwandeln), nicht in einer Abfrage über alle.

    Args:
        z: Ziel nach pruefen (geom_typ und Typ der Geometriespalte bekannt).
        roh: SQL-Ausdruck der gelesenen Geometrie.

    Returns:
        SQL-Ausdruck: gültig machen, nach EPSG:4326 transformieren, bei MULTI-Typen ST_Multi, zuletzt
        CAST auf den Typ der Zielspalte (der Typ kommt aus dem Katalog, nicht aus der Konfiguration).
    """
    # Ohne bekannte Dimension (Typ GEOMETRY) bleibt die reparierte Geometrie, wie ST_MakeValid sie liefert
    dim = DIMENSION.get((z.geom_typ or "").upper())
    heil = (sql.SQL("ST_CollectionExtract(ST_MakeValid({}), {})").format(roh, sql.Literal(dim)) if dim
            else sql.SQL("ST_MakeValid({})").format(roh))
    # Gültige Geometrien unverändert lassen: ST_MakeValid kann auch an ihnen Punkte umordnen, und dann
    # erschienen sie im Vergleich als geändert
    gueltig = sql.SQL("CASE WHEN ST_IsValid({r}) THEN {r} ELSE {h} END").format(r=roh, h=heil)
    g = sql.SQL("ST_Transform({}, {})").format(gueltig, sql.Literal(ZIEL_SRID))
    if (z.geom_typ or "").upper().startswith("MULTI"):
        g = sql.SQL("ST_Multi({})").format(g)
    return sql.SQL("CAST({} AS {})").format(g, sql.SQL(z.typen[z.geometrie]))


# Reparatur, Transformation und Umwandlung in den Typ der Zielspalte je Objekt (Prüfbericht 05.11., F4,
# E46). Bis E45 liefen sie in einer Abfrage über alle Zeilen: Ergab etwa ST_MakeValid aus einer Fliege
# ein MULTIPOLYGON für eine POLYGON-Spalte, brach der Cast die ganze Quelle ab. Wie geom_lesen mit
# EXCEPTION-Block (ein Sicherungspunkt je Objekt), der Zieltyp steht im Text der Funktion.
# {ausdruck} setzt geometrien_umwandeln über sql.SQL.format ein (_geom_ausdruck: nur Bezeichner,
# Literale und der Typ aus dem Katalog), nie Text aus der Quelle.
GEOM_ZIEL = """CREATE OR REPLACE FUNCTION pg_temp.geom_ziel(r geometry, OUT g geometry, OUT fehler text)
LANGUAGE plpgsql AS $$
BEGIN
    g := {ausdruck};
EXCEPTION WHEN OTHERS THEN
    g := NULL;
    fehler := SQLERRM;
END $$"""


def geometrien_umwandeln(cur, z: Ziel, prot) -> int:
    """Lesbare Geometrien je Objekt in Typ und Bezugssystem der Zieltabelle (E46). Scheitert das bei einem
    Objekt, wird es ausgelassen wie eine unlesbare Geometrie: Warnung, Abruf unvollständig (nichts wird
    gelöscht), bisheriger Stand bleibt. Rückgabe: Zahl der Objekte.

    Seiteneffekte: legt pg_temp.geom_ziel an, ergänzt `eingang` um gz (Geometrie im Zieltyp) und
    gz_fehler und meldet den Abruf bei Fehlern als unvollständig.

    Args:
        cur: Cursor in der Transaktion der Quelle; geometrien_lesen ist gelaufen (Spalte g).
        z: Ziel nach pruefen (Typ der Geometriespalte bekannt).
        prot: Protokoll der Quelle."""
    # Der Zieltyp wird in den Funktionstext eingesetzt, weil er je Quelle verschieden ist; ST_Force2D wie
    # bei _ROH, damit eine Höhe aus der Quelle den Typ der zweidimensionalen Zielspalte nicht verfehlt
    cur.execute(sql.SQL(GEOM_ZIEL).format(ausdruck=_geom_ausdruck(z, sql.SQL("ST_Force2D(r)"))))
    cur.execute("ALTER TABLE eingang ADD COLUMN gz geometry, ADD COLUMN gz_fehler text")
    # Nur gelesene Geometrien; unlesbare (g IS NULL) hat geometrien_lesen schon gemeldet
    cur.execute("""UPDATE eingang e SET (gz, gz_fehler) = (SELECT u.g, u.fehler FROM pg_temp.geom_ziel(e.g) u)
                   WHERE e.g IS NOT NULL""")
    cur.execute("""SELECT count(DISTINCT oid), (array_agg(DISTINCT oid))[1:10],
                          (array_agg(gz_fehler ORDER BY nr))[1] FROM eingang WHERE gz_fehler IS NOT NULL""")
    n, beispiele, fehler = cur.fetchone()
    if n:
        prot.info["geometrie_nicht_umwandelbar"] = n
        prot.unvollstaendig_melden(
            f"{n} Geometrie{'n' if n != 1 else ''} nicht in den Typ der Zielspalte {z.geometrie} "
            f"({z.typen[z.geometrie]}) überführbar (Reparatur, Transformation oder Typ), "
            f"Objekt{'e' if n != 1 else ''} ausgelassen, bisheriger Stand bleibt: {', '.join(beispiele)}"
            f"{' …' if n > len(beispiele) else ''} (erster Fehler: {' '.join(str(fehler).split())[:160]})")
    return n


def _schluessel_text(alias: str, z: Ziel) -> sql.Composable:
    """Zielschlüssel einer Zeile als jsonb-Array seiner Werte, jeder als Text.

    In dieser Form steht der Schlüssel in neu._s, im Register (pipeline_meta.bestand.schluessel) und im
    Änderungsprotokoll (pipeline_meta.aenderung.schluessel); vergleichen, anwenden und archiv_sql finden
    die Zeile der Zieltabelle darüber wieder. Als Text, damit die Form nicht vom Spaltentyp abhängt.

    Args:
        alias: Alias der Tabelle (`neu` oder Zieltabelle) in der umgebenden Abfrage.
        z: Ziel mit den Schlüsselspalten, deren Reihenfolge die des Arrays ist.

    Returns:
        SQL-Ausdruck vom Typ jsonb."""
    return sql.SQL("jsonb_build_array({})").format(sql.SQL(", ").join(
        sql.SQL("CAST({} AS text)").format(sql.Identifier(alias, s)) for s in z.schluessel))


def _bereich(alias: str, z: Ziel) -> sql.Composable:
    """Zeilen dieser Quelle in einer gemeinsamen Tabelle: die festen Werte (z. B. source).

    Steht in den Abfragen, die Zeilen der Zieltabelle zuordnen (Vergleich, UPDATE, INSERT-Prüfung,
    DELETE, Archiv, verwaiste Metadaten); nicht in der Ausdehnung für table_metadata, die über die ganze
    Tabelle geht. Teilen sich mehrere Quellen eine Tabelle, trennt sie nur dieser Bereich: Mit
    verschiedenen festen Werten fasst die Pipeline Zeilen einer anderen Quelle mit gleichem Schlüssel
    nicht an. Ohne feste Werte trennt nichts; gelöscht wird dann trotzdem nur, was im Register dieser
    Quelle steht. Die Werte werden als Literal eingesetzt und in den Spaltentyp der Zieltabelle
    umgewandelt.

    Args:
        alias: Alias der Zieltabelle in der umgebenden Abfrage.
        z: Ziel nach pruefen (z.typen bekannt).

    Returns:
        SQL-Bedingung; ohne feste Werte `true`."""
    if not z.fest:
        return sql.SQL("true")
    return sql.SQL(" AND ").join(
        sql.SQL("{} = CAST({} AS {})").format(sql.Identifier(alias, s), sql.Literal(str(w)),
                                             sql.SQL(z.typen[s]))
        for s, w in z.fest.items())


def _gleich(a: str, b: str, z: Ziel) -> sql.Composable:
    """Gleichheit zweier Zeilen über alle Schlüsselspalten (a.s = b.s AND …), in den Typen der Zieltabelle.

    Mit `=` statt IS NOT DISTINCT FROM: Ein leerer Schlüssel passt zu nichts. Zeilen ohne Schlüssel hat
    neu_bilden ohnehin entfernt; Zeilen der Zieltabelle mit leerem Schlüssel fasst die Pipeline so nie an.
    Eine reine Gleichheit lässt dem Planer Hash- und Merge-Verknüpfung offen (planer_einstellen).

    Args:
        a: Alias der einen Tabelle (meist `neu`).
        b: Alias der anderen (meist die Zieltabelle).
        z: Ziel mit den Schlüsselspalten.

    Returns:
        SQL-Bedingung."""
    return sql.SQL(" AND ").join(sql.SQL("{} = {}").format(sql.Identifier(a, s), sql.Identifier(b, s))
                                 for s in z.schluessel)


def _anders(a: str, b: str, z: Ziel) -> sql.Composable:
    """Unterscheiden sich zwei Zeilen in den Spalten, die die Pipeline setzt? Geometrie gerundet.

    Verglichen werden spalten_aendern und die Geometrie, nicht Schlüssel, feste Werte und nur_einfuegen.
    ROW(…) IS DISTINCT FROM ROW(…) behandelt zwei leere Werte als gleich und leer gegen gefüllt als
    verschieden; ein einfaches `<>` ergäbe bei NULL kein Ergebnis und die Zeile fiele aus dem Vergleich.
    Die Geometrie wird vorher auf RASTER gerundet (ST_SnapToGrid, E3) und als EWKB verglichen, also mit
    Bezugssystem; Rundungsreste der Transformation zählen so nicht als Änderung.

    Args:
        a: Alias der einen Zeile.
        b: Alias der anderen Zeile.
        z: Ziel nach pruefen.

    Returns:
        SQL-Bedingung; `false`, wenn es keine Spalte zu vergleichen gibt (dann ist nichts zu ändern)."""
    teile = [sql.Identifier(a, s) for s in z.spalten_aendern()], [sql.Identifier(b, s)
                                                                  for s in z.spalten_aendern()]
    if z.geometrie:
        for i, alias in enumerate((a, b)):
            teile[i].append(sql.SQL("ST_AsEWKB(ST_SnapToGrid({}, {}))").format(
                sql.Identifier(alias, z.geometrie), sql.Literal(RASTER)))
    if not teile[0]:
        return sql.SQL("false")
    return sql.SQL("ROW({}) IS DISTINCT FROM ROW({})").format(sql.SQL(", ").join(teile[0]),
                                                           sql.SQL(", ").join(teile[1]))


def neu_bilden(cur, z: Ziel, prot) -> str | None:
    """Tabelle `neu`: Spaltentypen wie in der Zieltabelle (CREATE TABLE AS … WITH NO DATA, damit
    NOT NULL und Vorgabewerte der Zieltabelle hier nicht greifen), dazu der Schlüssel als Text und
    der Quellschlüssel (_oid). Rückgabe: Grund, die Quelle anzuhalten (alter Stand bleibt), sonst None.

    Kein Datensatz wird verworfen, um eine Kollision aufzulösen (E40): Ergeben verschiedene
    Quellschlüssel denselben Zielschlüssel, wird die Quelle angehalten; liefert die Quelle denselben
    Schlüssel zweimal mit verschiedenen Werten, wird er ausgelassen und behält seinen bisherigen Stand; der
    Abruf gilt dann als unvollständig (Prüfung nach E48), nichts wird gelöscht.

    Args:
        cur: Cursor in der Transaktion der Quelle, `eingang` ist gefüllt.
        z: Ziel nach pruefen.
        prot: Protokoll der Quelle; bekommt Warnungen, Hinweise, Zähler in info und gegebenenfalls die
            Meldung „unvollständig“, die das Löschen sperrt.

    Returns:
        Grund, die Quelle anzuhalten (zu langer fester Wert oder Schlüssel, mehrdeutiger Zielschlüssel),
        sonst None.

    Seiteneffekte: legt die temporären Tabellen `neu` und `ausgelassen` an (bei Geometrie zusätzlich die
    Spalten und Funktionen aus geometrien_lesen und geometrien_umwandeln). Die Zieltabelle wird nur als
    Vorlage für die Spaltentypen gelesen, nicht verändert."""
    grund = laengen_pruefen(cur, z, prot)
    if grund:
        return grund
    spalten = z.spalten_neu()
    # Zu lange Werte (laengen_pruefen): in `neu` NULL statt gekürzt, die Zeile trägt _zu_lang und wird nach
    # der Eindeutigkeit zurückgehalten (E47)
    grenzen = {s: n for s, n in laengen(z).items() if s in z.spalten}
    if z.geometrie:
        geometrien_lesen(cur, z, prot)
        # Nur zur Meldung: wie viele lesbare Geometrien ungültig sind und korrigiert werden (E33).
        # Unlesbare (g IS NULL) zählen hier nicht, ST_IsValid(NULL) ist NULL
        cur.execute(sql.SQL("SELECT count(*), (array_agg(e.oid))[1:10] FROM eingang e "
                            "WHERE NOT ST_IsValid({})").format(_ROH))
        n, beispiele = cur.fetchone()
        if n:
            prot.warnungen.append(f"{n} ungültige Geometrie{'n' if n != 1 else ''} mit ST_MakeValid "
                                  f"korrigiert: {', '.join(beispiele)}{' …' if n > len(beispiele) else ''}")
        geometrien_umwandeln(cur, z, prot)
    # Spaltentypen aus der Zieltabelle selbst, nicht aus der Konfiguration: Was dort nicht passt, fällt
    # schon beim Umwandeln in `neu` auf, nicht erst beim Schreiben. Die Spalten mit Unterstrich sind
    # Hilfsspalten des Abgleichs (Lieferreihenfolge, Quellschlüssel, Gebiet, Zielschlüssel als Text und
    # die Merkmale leer, unlesbar, zu lang); sie gelangen nie in die Zieltabelle
    cur.execute(sql.SQL("CREATE TEMP TABLE neu ON COMMIT DROP AS SELECT {} FROM {} WITH NO DATA").format(
        sql.SQL(", ").join(map(sql.Identifier, spalten)), z.ident))
    cur.execute("ALTER TABLE neu ADD COLUMN _nr integer, ADD COLUMN _oid text, "
                "ADD COLUMN _gebiet text, ADD COLUMN _s jsonb, ADD COLUMN _leer boolean, "
                "ADD COLUMN _unlesbar boolean, ADD COLUMN _zu_lang boolean")
    feste = {**z.konstant, **z.fest}
    # Je Spalte ein Ausdruck: Werte der Quelle aus dem jsonb per CAST in den Zieltyp (ein unpassender Wert
    # bricht hier die Quelle ab, E7), feste Werte als Literal. Spaltennamen und feste Werte gehen über
    # sql.Literal ein, der Typ kommt aus dem Katalog; Werte der Quelle stehen nur in `eingang`, nie im SQL
    ausdruecke = []
    for s in spalten:
        if s == z.geometrie:
            ausdruecke.append(sql.SQL("e.gz"))   # schon im Zieltyp (geometrien_umwandeln)
        elif s in grenzen:
            ausdruecke.append(sql.SQL("CASE WHEN {} THEN NULL ELSE CAST(e.werte ->> {} AS {}) END").format(
                _zu_lang(s, grenzen[s]), sql.Literal(s), sql.SQL(z.typen[s])))
        elif s in z.spalten:
            ausdruecke.append(sql.SQL("CAST(e.werte ->> {} AS {})").format(sql.Literal(s),
                                                                             sql.SQL(z.typen[s])))
        else:
            ausdruecke.append(sql.SQL("CAST({} AS {})").format(sql.Literal(str(feste[s])),
                                                                sql.SQL(z.typen[s])))
    unlesbar = sql.SQL("(e.g_fehler IS NOT NULL OR e.gz_fehler IS NOT NULL)" if z.geometrie else "false")
    lang = sql.SQL(" OR ").join(_zu_lang(s, n) for s, n in grenzen.items()) if grenzen else sql.SQL("false")
    cur.execute(sql.SQL("INSERT INTO neu ({}, _nr, _oid, _gebiet, _leer, _unlesbar, _zu_lang) "
                        "SELECT {}, e.nr, e.oid, e.gebiet, coalesce(e.leer, false), {}, coalesce({}, false) "
                        "FROM eingang e").format(
        sql.SQL(", ").join(map(sql.Identifier, spalten)), sql.SQL(", ").join(ausdruecke), unlesbar, lang))
    # Zielschlüssel als Text erst nach dem CAST: so stimmt er mit der Form überein, die vergleichen aus der
    # Zieltabelle bildet (gleicher Typ, gleiche Textdarstellung)
    cur.execute(sql.SQL("UPDATE neu n SET _s = {}").format(_schluessel_text("n", z)))
    leer = sql.SQL(" OR ").join(sql.SQL("{} IS NULL").format(sql.Identifier(s)) for s in z.schluessel)
    # Ausgelassene Zeilen: der Abgleich behandelt sie nicht als gelöscht, ihr bisheriger Stand bleibt.
    # s = Zielschlüssel, q = Quellschlüssel; über q bleibt auch ein Eintrag mit anderem Zielschlüssel
    # stehen, etwa der Wert des Vorjahrs, wenn der Stichtag vorrückt (Prüfung 05.11., Runde 2, E42)
    cur.execute("CREATE TEMP TABLE ausgelassen (s jsonb, q text) ON COMMIT DROP")

    # Reihenfolge (E42): erst der Schlüssel, dann die Eindeutigkeit über ALLE Zeilen mit vollständigem
    # Schlüssel, erst danach die Filter, die von Werten oder Geometrie abhängen (leere Zeilen, unbrauchbare
    # Geometrie, Pflichtfelder). Sonst hinge es an einem leeren Messwert, ob die Quelle anhält und welche
    # von zwei Reihen eine Zielzeile füllt.
    # Zeilen mit leerer Schlüsselspalte (auch leere CSV-Zeilen ohne lesbaren Schlüssel): der Abruf gilt als
    # unvollständig, nichts wird gelöscht
    cur.execute(sql.SQL("DELETE FROM neu WHERE {} RETURNING _oid").format(leer))
    ohne = [r[0] for r in cur.fetchall()]
    if ohne:
        prot.unvollstaendig_melden(f"{len(ohne)} Zeilen ohne Wert in einer Schlüsselspalte "
                                   f"({', '.join(z.schluessel)}) übersprungen: {', '.join(ohne[:10])}")
    # Verschiedene Quellschlüssel, ein Zielschlüssel (E40): die Abbildung in der Konfiguration ist nicht
    # eindeutig. Keine der Zeilen darf gewinnen, keine zusammengeführt werden: Quelle anhalten
    cur.execute("""SELECT count(*), sum(n), (array_agg(beispiel ORDER BY s))[1:3]
                   FROM (SELECT _s AS s, count(DISTINCT _oid) AS n,
                                CAST(_s AS text) || ' <- ' || string_agg(DISTINCT _oid, ' | ') AS beispiel
                         FROM neu GROUP BY _s HAVING count(DISTINCT _oid) > 1) k""")
    n, zeilen_n, beispiele = cur.fetchone()
    if n:
        prot.info["zielschluessel_mehrdeutig"] = n
        return (f"{n} Zielschlüssel aus mehr als einem Quellschlüssel ({zeilen_n} Zeilen), z. B. "
                f"{'; '.join(beispiele)}. Die Abbildung (ziel.schluessel, ziel.zusatz) ist nicht eindeutig; "
                f"Quelle angehalten, alter Stand bleibt unverändert, nichts wurde zusammengeführt")
    # Derselbe Quellschlüssel mehrfach (etwa eine Zeile doppelt in einer CSV): mit gleichen Werten ist es
    # derselbe Datensatz, eine Zeile genügt; mit verschiedenen Werten widerspricht sich die Quelle. Eine
    # Zeile ohne Wert und eine mit Wert gelten als verschieden, ebenso eine Zeile mit zu langem Wert (in `neu`
    # NULL, Merkmal _zu_lang) und eine mit Fehlwert (auch NULL; Nachprüfung zu E47) und eine Zeile mit
    # unlesbarer Geometrie und eine ohne Geometrie: Die Merkmale gehören zum Vergleich, sonst hinge an der
    # Reihenfolge, welche der beiden Zeilen übrig bleibt (E42)
    cur.execute(sql.SQL("DELETE FROM neu n USING neu m WHERE n._s = m._s AND n._nr > m._nr AND NOT ({}) "
                        "AND n._leer = m._leer AND n._zu_lang = m._zu_lang AND n._unlesbar = m._unlesbar "
                        "RETURNING n._oid").format(_anders("n", "m", z)))
    gleich = cur.rowcount
    if gleich:
        prot.hinweise.append(f"{gleich} Zeilen doppelt mit gleichem Schlüssel und gleichen Werten geliefert, "
                             "einmal übernommen")
    cur.execute("""WITH k AS (SELECT _s FROM neu GROUP BY _s HAVING count(*) > 1),
                        weg AS (DELETE FROM neu n USING k WHERE n._s = k._s RETURNING n._s, n._oid),
                        rein AS (INSERT INTO ausgelassen SELECT DISTINCT _s, _oid FROM weg)
                   SELECT (SELECT count(*) FROM k), (array_agg(DISTINCT _oid))[1:10] FROM weg""")
    n, beispiele = cur.fetchone()
    if n:
        # Auch das Löschen sperren (Prüfung nach E48, Pre-existing seit E42): Ein Schlüssel, der doppelt
        # kommt, kann einen anderen überdecken (beim Anbieter geändert); dessen Zeile fehlt dann und würde
        # sonst als gelöscht behandelt
        prot.unvollstaendig_melden(f"{n} Schlüssel mehrfach mit verschiedenen Werten geliefert, ausgelassen, "
                                   f"ihr bisheriger Stand bleibt: {', '.join(beispiele)}; Abruf "
                                   "unvollständig, nichts wird gelöscht")
    # Zeilen mit einem Wert, der nicht in seine Spalte passt (E47, laengen_pruefen hat gewarnt):
    # zurückgehalten, ihr bisheriger Stand bleibt. Erst hier, nach der Eindeutigkeit (E42); in `neu` steht der
    # Wert als NULL statt gekürzt. Dass eine solche Zeile nicht als gleich mit einer Zeile ohne Wert gilt,
    # regelt _zu_lang in der Entdopplung oben. Zwei zu lange Zeilen mit verschiedenem Text gelten dort als
    # gleich; das Ergebnis stimmt trotzdem, die verbliebene Zeile wird hier zurückgehalten
    cur.execute("""WITH weg AS (DELETE FROM neu WHERE _zu_lang RETURNING _s, _oid)
                   INSERT INTO ausgelassen SELECT _s, _oid FROM weg""")
    # Zeilen ohne jeden Messwert (CSV, leere_auslassen; Codex-Prüfung 05.11., B2, Antwort 63): ausgelassen,
    # alter Wert bleibt, Warnung
    cur.execute("""WITH weg AS (DELETE FROM neu WHERE _leer RETURNING _s, _oid),
                        rein AS (INSERT INTO ausgelassen SELECT _s, _oid FROM weg)
                   SELECT count(*), (array_agg(_oid ORDER BY _oid))[1:10] FROM weg""")
    n, beispiele = cur.fetchone()
    if n:
        prot.warnungen.append(f"{n} Zeilen ohne jeden Wert ausgelassen (leere_auslassen), ihr bisheriger "
                              f"Stand bleibt: {', '.join(beispiele)}{' …' if n > len(beispiele) else ''}")
    if z.geometrie:
        # Nicht lesbare oder nicht umwandelbare Geometrien haben geometrien_lesen und geometrien_umwandeln
        # schon gemeldet; hier fallen sie nur heraus. Sie kommen nicht in `ausgelassen`: Jede Zeile, die hier
        # herausfällt, macht den Abruf unvollständig (dort oder unten), damit ist das Löschen ohnehin
        # gesperrt und laden.quelle_laden führt sie als zurückgehalten (zurueckhalten)
        cur.execute(sql.SQL("DELETE FROM neu WHERE _gebiet IS NULL "
                            "AND ({g} IS NULL OR ST_IsEmpty({g})) RETURNING _oid, _unlesbar").format(
            g=sql.Identifier(z.geometrie)))
        ohne_geom = [r[0] for r in cur.fetchall() if not r[1]]
        if ohne_geom:
            prot.unvollstaendig_melden(f"{len(ohne_geom)} Geometrien auch nach ST_MakeValid unbrauchbar, "
                                       f"ausgelassen: {', '.join(ohne_geom[:10])}")
    # Pflichtfelder (Antwort 63): Zeile auslassen, mit Warnung; ihr Schlüssel kommt in `ausgelassen`,
    # damit der Abgleich ihn nicht als gelöscht behandelt (der alte Wert bleibt bis zur Klärung)
    if z.pflicht:
        fehlt = sql.SQL(" OR ").join(sql.SQL("{} IS NULL").format(sql.Identifier(s)) for s in z.pflicht)
        cur.execute(sql.SQL("""WITH weg AS (DELETE FROM neu WHERE {} RETURNING _s, _oid),
                                    rein AS (INSERT INTO ausgelassen SELECT _s, _oid FROM weg)
                               SELECT _oid FROM weg ORDER BY _oid""").format(fehlt))
        ohne_pflicht = cur.fetchall()
        if ohne_pflicht:
            prot.warnungen.append(f"{len(ohne_pflicht)} Zeilen ohne Wert in einem Pflichtfeld "
                                  f"({', '.join(z.pflicht)}) ausgelassen, ihr bisheriger Stand bleibt: "
                                  f"{', '.join(r[0] for r in ohne_pflicht[:10])}")
    # Index und Statistik für die Verknüpfungen in vergleichen und anwenden. ANALYZE ist hier erlaubt, weil
    # `neu` als temporäre Tabelle der Importrolle selbst gehört; die Zieltabellen darf sie nicht analysieren
    # (planer_einstellen, E31)
    cur.execute("CREATE INDEX ON neu (_s)")
    cur.execute("ANALYZE neu")
    return None


def gebiet_pruefen(cur, z: Ziel, prot) -> None:
    """Haben die Gebietsschlüssel (z. B. AGS) eine Fläche in der Geometrietabelle? Antwort 28: die
    Verknüpfung ist ein fachlicher Schlüssel, kein Fremdschlüssel. Ergebnis als Hinweis; mit
    ohne_flaeche: auslassen werden Zeilen ohne Fläche nicht übernommen, ihr bisheriger Stand bleibt
    (Schlüssel in `ausgelassen`, wie bei Pflichtfeldern), mit Warnung.

    Args:
        cur: Cursor in der Transaktion der Quelle; neu_bilden ist gelaufen.
        z: Ziel; ohne ziel.gebiet tut die Funktion nichts.
        prot: Protokoll der Quelle (info["gebiete"], Hinweis oder Warnung).

    Seiteneffekte: liest die Gebietstabelle; bei `auslassen` DELETE in `neu` und INSERT in `ausgelassen`.
    Die Zieltabelle wird nicht berührt."""
    if not z.gebiet:
        return
    g = z.gebiet
    spalte = sql.Identifier("n", g.get("zielspalte", z.schluessel[0]))
    tab = sql.Identifier(g.get("schema", "public"), g["tabelle"])
    # Verglichen wird als Text, damit die Prüfung nicht von den Spaltentypen beider Tabellen abhängt; als
    # fachlicher Schlüssel ohne Fremdschlüssel (Antwort 28) müssen die Typen nicht zusammenpassen
    passt = sql.SQL("EXISTS (SELECT 1 FROM {} g WHERE CAST(g.{} AS text) = CAST({} AS text))").format(
        tab, sql.Identifier(g["spalte"]), spalte)
    # Erst die eindeutigen Schlüssel beider Seiten, dann ein Hash-Abgleich: bundesweit stehen
    # 1,6 Mio. Kennzahlzeilen gegen 11 000 Flächen, eine Unterabfrage je Zeile wäre zu langsam
    cur.execute(sql.SQL("""WITH k AS (SELECT DISTINCT CAST({s} AS text) AS s FROM neu n),
                               f AS (SELECT DISTINCT CAST(g.{gs} AS text) AS s FROM {tab} g)
                           SELECT count(*), count(f.s), array_agg(k.s) FILTER (WHERE f.s IS NULL)
                           FROM k LEFT JOIN f ON f.s = k.s""").format(
        s=spalte, gs=sql.Identifier(g["spalte"]), tab=tab))
    alle, mit, ohne = cur.fetchone()
    ohne = sorted(ohne or [])
    prot.info["gebiete"] = {"schluessel": alle, "mit_flaeche": mit, "tabelle": g["tabelle"]}
    text = f"{mit} von {alle} Gebietsschlüsseln haben eine Fläche in „{g['tabelle']}“ ({g['spalte']})"
    if ohne:
        text += f"; ohne: {', '.join(ohne[:10])}{' …' if len(ohne) > 10 else ''}"
    if ohne and g.get("ohne_flaeche") == "auslassen":
        # Ausgelassen heißt überall: der bisherige Stand bleibt (Prüfung 05.11., Runde 2, E42)
        cur.execute(sql.SQL("""WITH weg AS (DELETE FROM neu n WHERE NOT {} RETURNING n._s, n._oid),
                                    rein AS (INSERT INTO ausgelassen SELECT _s, _oid FROM weg)
                               SELECT count(*) FROM weg""").format(passt))
        prot.warnungen.append(text + f"; {cur.fetchone()[0]} Zeilen ohne Fläche ausgelassen, ihr bisheriger "
                                     "Stand bleibt")
    else:
        prot.hinweise.append(text)


def flaeche_pruefen(cur, z: Ziel, prot) -> None:
    """Plausibilitätsprüfung als Regel je Quelle: eine gemeldete Fläche (z. B. Gebietsfläche der
    Statistik) gegen die Fläche der verknüpften Geometrie, auf dem Ellipsoid gerechnet (geography),
    in km². Ergebnis in info.flaechenpruefung; Abweichungen über der Toleranz als Warnung mit
    Schlüsseln. Hält die Quelle nicht an: die Regel ist ein Hinweis auf Gebietsstände, kein Abbruch.

    Abweichung in Prozent der berechneten Fläche; eine Geometrie mit Fläche 0 ergibt keinen Prozentwert
    (nullif) und zählt nur unter `geprueft`. Zeilen ohne gemeldeten Wert bleiben außen vor.

    Args:
        cur: Cursor in der Transaktion der Quelle; neu_bilden ist gelaufen.
        z: Ziel; ohne ziel.gebiet.flaeche_pruefen tut die Funktion nichts.
        prot: Protokoll der Quelle (info["flaechenpruefung"], Hinweis oder Warnung).

    Liest nur `neu` und die Gebietstabelle, schreibt nichts in die Datenbank."""
    g = (z.gebiet or {})
    regel = g.get("flaeche_pruefen")
    if not regel:
        return
    tol = float(regel.get("toleranz_prozent", 0.5))
    faktor = float(regel.get("faktor_km2", 1))
    wert = sql.Identifier("n", regel.get("wert", "wert"))
    cur.execute(sql.SQL("""
        WITH p AS (
            SELECT CAST(n.{zs} AS text) AS s, CAST({wert} AS double precision) * {faktor} AS gemeldet,
                   ST_Area(CAST(f.{geom} AS geography)) / 1e6 AS berechnet
            FROM neu n JOIN {tab} f ON CAST(f.{gs} AS text) = CAST(n.{zs} AS text)
            WHERE {wert} IS NOT NULL),
        a AS (SELECT s, gemeldet, berechnet,
                     abs(gemeldet - berechnet) / nullif(berechnet, 0) * 100 AS prozent FROM p)
        SELECT count(*), max(prozent),
               percentile_cont(0.5) WITHIN GROUP (ORDER BY prozent),
               count(*) FILTER (WHERE prozent > {tol}),
               (array_agg(s ORDER BY prozent DESC) FILTER (WHERE prozent > {tol}))[1:10]
        FROM a""").format(
        zs=sql.Identifier(g.get("zielspalte", z.schluessel[0])), wert=wert, faktor=sql.Literal(faktor),
        geom=sql.Identifier(g.get("geometrie", "geom")), tab=sql.Identifier(g.get("schema", "public"),
                                                                            g["tabelle"]),
        gs=sql.Identifier(g["spalte"]), tol=sql.Literal(tol)))
    n, maximum, median, ueber, beispiele = cur.fetchone()
    prot.info["flaechenpruefung"] = {"geprueft": n, "toleranz_prozent": tol,
                                     "median_prozent": round(median or 0, 4),
                                     "max_prozent": round(maximum or 0, 4), "ueber_toleranz": ueber}
    if ueber:
        prot.warnungen.append(f"Flächenprüfung: {ueber} von {n} Gebieten weichen mehr als {tol:g} % von "
                              f"der Fläche der Geometrie ab (höchstens {maximum:.2f} %): "
                              f"{', '.join(beispiele)}{' …' if ueber > len(beispiele) else ''}")
    elif n:
        prot.hinweise.append(f"Flächenprüfung: {n} Gebiete, Abweichung im Median {median:.3f} %, "
                             f"höchstens {maximum:.3f} % (Toleranz {tol:g} %)")


# --- Vergleich und Anwenden ----------------------------------------------------------------

def bisher(cur, name: str, z: Ziel) -> int:
    """Zahl der Zeilen, die das Bestandsregister für diese Quelle und Zieltabelle führt.

    Grundlage des Rückgang-Schutzes in laden.quelle_laden (waechter.rueckgang_zu_gross, E4): Gezählt wird
    das Register, nicht die Zieltabelle, weil dort auch Zeilen anderer Importe stehen können.

    Args:
        cur: Cursor in der Transaktion der Quelle.
        name: Name der Quelle.
        z: Ziel (z.name ist der Tabellenname im Register).

    Returns:
        Anzahl der Registerzeilen; 0 beim ersten Lauf."""
    cur.execute("SELECT count(*) FROM pipeline_meta.bestand WHERE quelle = %s AND tabelle = %s",
                (name, z.name))
    return cur.fetchone()[0]


def bereich_zeilen(cur, z: Ziel) -> int:
    """Zahl der Zeilen der Zieltabelle im Bereich der Quelle (_bereich: feste Werte wie source), ohne
    Bereich die ganze Tabelle. Für die Zählprüfung vor dem Überspringen einer unveränderten Lieferung (E52,
    unveraendert.zaehlen): Sie fällt auf, wenn seit dem letzten Vollabgleich Zeilen in diesem Bereich
    hinzugekommen oder verschwunden sind, gleich durch wen. Geänderte Werte bei gleicher Zahl sieht sie nicht.

    Args:
        cur: Cursor in der Transaktion der Quelle; pruefen ist gelaufen (z.typen für den Bereich).
        z: Ziel.

    Returns:
        Anzahl der Zeilen."""
    cur.execute(sql.SQL("SELECT count(*) FROM {} t WHERE {}").format(z.ident, _bereich("t", z)))
    return cur.fetchone()[0]


def vergleichen(cur, name: str, z: Ziel) -> dict:
    """Tabelle `vergleich`: je Schlüssel die Art der Änderung, Geometrie (für die Karte),
    Gebietsschlüssel, Werte und Quellschlüssel (q). Zählt neu, geändert, gelöscht, unverändert,
    übernommen, zurückgehalten und ersetzt. Ziel- und Quellschlüssel stehen in jedem Lauf 1:1
    (neu_bilden hält die Quelle sonst an); das Register führt beide.

    Übernommen (Zeile mit diesem Schlüssel gab es schon, aber nicht im Register) zählt fachlich nach
    Antwort 62: mit abweichenden Werten als geändert, sonst als unverändert; `uebernommen` ist die Summe
    beider, `uebernommen_geaendert` der geänderte Teil, beide zusätzlich (Prüfbericht 05.11., F3, E46).
    In `vergleich` steht art = 'uebernommen' mit `anders` je Zeile.

    Gezählt wird nach dem Quellschlüssel (Antwort 62, E42): Kommt ein Zielschlüssel aus einem anderen
    Quellschlüssel als bisher (etwa wenn die Quelle ein Kürzel umbenennt und der Name gleich bleibt), ist
    der neue Quellschlüssel `neu` und der bisherige `ersetzt`; der Aufrufer zählt `ersetzt` als gelöscht,
    unabhängig von der Löschsperre, denn die Zeile der Zieltabelle trägt danach den neuen Datensatz.
    Physisch bleibt es ein UPDATE derselben Zeile. Gelöschte Schlüssel, deren Ziel- oder Quellschlüssel in
    diesem Lauf ausgelassen wurde, heißen `zurueckgehalten`.

    Args:
        cur: Cursor in der Transaktion der Quelle; neu_bilden (und gebiet_pruefen) sind gelaufen.
        name: Name der Quelle (Register).
        z: Ziel nach pruefen.

    Returns:
        Zähler neu, geaendert, geloescht, unveraendert, zurueckgehalten, ersetzt, uebernommen und
        uebernommen_geaendert; jeweils verschiedene Zielschlüssel.

    Seiteneffekte: legt die temporäre Tabelle `vergleich` an. Zieltabelle und Register werden nur gelesen;
    geschrieben wird erst in anwenden."""
    # Geometrie (für die Karte) aus `neu` bzw. aus der Zieltabelle; ohne Geometriespalte NULL
    g = sql.Identifier("n", z.geometrie) if z.geometrie else sql.SQL("NULL::geometry")
    gt = sql.Identifier("t", z.geometrie) if z.geometrie else sql.SQL("NULL::geometry")
    gs = (z.gebiet or {}).get("zielspalte", z.schluessel[0])
    # `werte` für die Karte: die Zeile als jsonb ohne die hier aufgezählten Hilfsspalten von `neu` und ohne
    # die Geometrie, die als eigene Spalte geom mitkommt
    weg = sql.SQL("").join(sql.SQL(" - {}").format(sql.Literal(s))
                           for s in ["_nr", "_oid", "_gebiet", "_s", "_leer", "_unlesbar",
                                     *([z.geometrie] if z.geometrie else [])])
    weg_t = sql.SQL(" - {}").format(sql.Literal(z.geometrie)) if z.geometrie else sql.SQL("")
    # Drei Teile, über UNION ALL in einer Tabelle:
    #  1. je Zeile von `neu` die Art. treffer zählt die passenden Zeilen der Zieltabelle (im Bereich der
    #     Quelle) und ob eine davon abweicht. Die Reihenfolge der CASE-Zweige zählt: nicht im Register,
    #     aber in der Tabelle vorhanden = übernommen; weder im Register noch in der Tabelle, oder im Register,
    #     aber aus der Tabelle verschwunden = neu; im Register mit anderem Quellschlüssel = neu (E42); erst
    #     danach geändert oder unverändert. q_fehlt markiert Registerzeilen von vor E40 ohne Quellschlüssel
    #  2. `ersetzt`: der bisherige Quellschlüssel einer Zeile, die jetzt aus einem anderen kommt
    #  3. `geloescht`: Registerzeilen, deren Zielschlüssel in `neu` fehlt; LEFT JOIN, weil die Zeile in der
    #     Zieltabelle inzwischen fehlen kann (dann ohne Geometrie und Werte)
    cur.execute(sql.SQL("""
        CREATE TEMP TABLE vergleich ON COMMIT DROP AS
        WITH reg AS (SELECT schluessel, quellschluessel FROM pipeline_meta.bestand
                     WHERE quelle = {q} AND tabelle = {tn}),
        treffer AS (
            SELECT n._s, count(t.{k}) AS anzahl, coalesce(bool_or({anders}), false) AS anders
            FROM neu n LEFT JOIN {ziel} t ON {bereich} AND {gleich}
            GROUP BY n._s)
        SELECT n._s AS s,
               CASE WHEN r.schluessel IS NULL AND tr.anzahl > 0 THEN 'uebernommen'
                    WHEN r.schluessel IS NULL OR tr.anzahl = 0 THEN 'neu'
                    WHEN r.quellschluessel <> n._oid THEN 'neu'
                    WHEN tr.anders THEN 'geaendert'
                    ELSE 'unveraendert' END AS art,
               {g} AS geom, CAST(n.{gs} AS text) AS gebiet, to_jsonb(n){weg} AS werte, n._oid AS q,
               r.quellschluessel IS NULL AND r.schluessel IS NOT NULL AS q_fehlt, tr.anders
        FROM neu n JOIN treffer tr ON tr._s = n._s LEFT JOIN reg r ON r.schluessel = n._s
        UNION ALL
        SELECT r.schluessel, 'ersetzt', NULL::geometry, NULL, NULL::jsonb, r.quellschluessel, false, false
        FROM neu n JOIN reg r ON r.schluessel = n._s WHERE r.quellschluessel <> n._oid
        UNION ALL
        SELECT w.schluessel, 'geloescht', {gt}, CAST(t.{gs} AS text), to_jsonb(t){weg_t}, w.quellschluessel,
               false, false
        FROM (SELECT schluessel, quellschluessel FROM reg
              WHERE NOT EXISTS (SELECT 1 FROM neu n WHERE n._s = reg.schluessel)) w
        LEFT JOIN {ziel} t ON {bereich} AND {st} = w.schluessel""").format(
        q=sql.Literal(name), tn=sql.Literal(z.name), k=sql.Identifier(z.schluessel[0]),
        anders=_anders("n", "t", z), ziel=z.ident, bereich=_bereich("t", z), gleich=_gleich("n", "t", z),
        g=g, gt=gt, gs=sql.Identifier(gs), weg=weg, weg_t=weg_t, st=_schluessel_text("t", z)))
    # Statistik für den Planer: ohne sie schätzt er temporäre Tabellen falsch und wählt bei
    # zehntausenden Zeilen verschachtelte Schleifen statt Hash-Verknüpfungen
    cur.execute("CREATE INDEX ON vergleich (s)")
    cur.execute("ANALYZE vergleich")
    # Was dieser Lauf ausgelassen hat (Doppelte, Pflichtfelder, zu lange Werte, leere Zeilen, Gebiet ohne
    # Fläche), fehlt in `neu`, ist aber nicht gelöscht: bisheriger Stand bleibt. Über q auch dann, wenn
    # sich der Zielschlüssel geändert hat (E42)
    cur.execute("""UPDATE vergleich SET art = 'zurueckgehalten'
                   WHERE art = 'geloescht' AND (s IN (SELECT s FROM ausgelassen)
                                                OR q IN (SELECT q FROM ausgelassen WHERE q IS NOT NULL))""")
    cur.execute("""SELECT CASE WHEN art = 'uebernommen' AND anders THEN 'uebernommen_geaendert' ELSE art END,
                          count(DISTINCT s) FROM vergleich GROUP BY 1""")
    z_ = dict(cur.fetchall())
    aus = {k: z_.get(k, 0) for k in ("neu", "geaendert", "geloescht", "unveraendert", "zurueckgehalten",
                                     "ersetzt")}
    # Fachlich (Antwort 62): Den Schlüssel gab es schon, also nicht neu; geändert, wenn Werte abweichen
    aus["geaendert"] += z_.get("uebernommen_geaendert", 0)
    aus["unveraendert"] += z_.get("uebernommen", 0)
    aus["uebernommen"] = z_.get("uebernommen", 0) + z_.get("uebernommen_geaendert", 0)
    aus["uebernommen_geaendert"] = z_.get("uebernommen_geaendert", 0)
    return aus


def zurueckhalten(cur) -> None:
    """Was nicht gelöscht wird, heißt im Vergleich ab jetzt so; Karte und Protokoll zeigen dann,
    was wirklich geschieht (Codex-Prüfung 04.11., B10).

    laden.quelle_laden ruft sie auf, wenn das Löschen gesperrt ist (unvollständiger Abruf oder
    `loeschen: false`). Danach findet anwenden keine Zeile mit art = 'geloescht' mehr.

    Args:
        cur: Cursor in der Transaktion der Quelle; vergleichen ist gelaufen.

    Seiteneffekt: UPDATE der temporären Tabelle `vergleich`; Zieltabelle und Register bleiben unberührt."""
    cur.execute("UPDATE vergleich SET art = 'zurueckgehalten' WHERE art = 'geloescht'")


def doppelte_im_ziel(cur, z: Ziel) -> int:
    """Schlüssel, die in der Zieltabelle mehrfach vorkommen (die Tabellen haben dafür keine
    Eindeutigkeitsregel). Ein UPDATE trifft dann alle diese Zeilen.

    Nur für den Hinweis im Bericht (laden.quelle_laden); gezählt werden Schlüssel aus `neu`, die im Bereich
    der Quelle mehr als eine Zeile treffen.

    Args:
        cur: Cursor in der Transaktion der Quelle; neu_bilden ist gelaufen.
        z: Ziel nach pruefen.

    Returns:
        Anzahl solcher Schlüssel."""
    cur.execute(sql.SQL("""SELECT count(*) FROM (SELECT 1 FROM {ziel} t JOIN neu n ON {gleich}
                           WHERE {bereich} GROUP BY n._s HAVING count(*) > 1) d""").format(
        ziel=z.ident, gleich=_gleich("n", "t", z), bereich=_bereich("t", z)))
    return cur.fetchone()[0]


def anwenden(cur, name: str, z: Ziel, lauf_id: str, loeschen: bool) -> int:
    """Neuen Stand in die Zieltabelle schreiben. Gibt die Zahl gelöschter Zeilen zurück.

    Der einzige Schritt, der die Zieltabelle verändert, immer im Bereich der Quelle (_bereich):
      - UPDATE der zugeordneten Spalten (spalten_aendern und Geometrie) nur bei Zeilen, die abweichen;
      - INSERT der Zeilen von `neu`, deren Schlüssel es im Bereich noch nicht gibt (spalten_neu);
      - DELETE nur, wenn `loeschen` gilt, und nur für Schlüssel mit art = 'geloescht' in `vergleich`,
        die also im Register stehen (E23).
    Danach Register (pipeline_meta.bestand) und Änderungsprotokoll (pipeline_meta.aenderung). Alles in der
    Transaktion der Quelle: Bricht ein Schritt ab, bleibt der alte Stand vollständig (E7).

    Args:
        cur: Cursor in der Transaktion der Quelle; vergleichen ist gelaufen.
        name: Name der Quelle (Register, Protokoll).
        z: Ziel nach pruefen.
        lauf_id: Kennung des Laufs, z. B. 20261103T120000Z.
        loeschen: Ob gelöscht werden darf (waechter.loeschen_erlaubt und ziel.loeschen, entschieden in
            laden.quelle_laden).

    Returns:
        Zahl der in der Zieltabelle gelöschten Zeilen (rowcount; bei Doppelten im Ziel mehr als Schlüssel)."""
    aendern = z.spalten_aendern() + ([z.geometrie] if z.geometrie else [])
    # Nur Zeilen, die sich wirklich unterscheiden (_anders): Ein UPDATE ohne Änderung schriebe trotzdem eine
    # neue Zeilenfassung, bei großen Quellen bei jedem Lauf die ganze Tabelle. Spalten, die die Quelle nicht
    # setzt (etwa flood_risk), bleiben stehen; das Spaltenrecht UPDATE der Importrolle umfasst nur diese
    if aendern:
        cur.execute(sql.SQL("UPDATE {ziel} t SET {set} FROM neu n WHERE {bereich} AND {gleich} AND {anders}")
                    .format(ziel=z.ident, bereich=_bereich("t", z), gleich=_gleich("n", "t", z),
                            anders=_anders("n", "t", z),
                            set=sql.SQL(", ").join(sql.SQL("{} = {}").format(
                                sql.Identifier(s), sql.Identifier("n", s)) for s in aendern)))
    spalten = sql.SQL(", ").join(map(sql.Identifier, z.spalten_neu()))
    # NOT EXISTS statt ON CONFLICT: Die Bestandstabellen haben auf den fachlichen Schlüsseln keine
    # Eindeutigkeitsregel, an der ein ON CONFLICT ansetzen könnte. Spalten außerhalb von spalten_neu (etwa
    # eine id aus einer Sequenz) bekommen ihren Vorgabewert aus der Zieltabelle
    cur.execute(sql.SQL("""INSERT INTO {ziel} ({sp}) SELECT {nsp} FROM neu n
                           WHERE NOT EXISTS (SELECT 1 FROM {ziel} t WHERE {bereich} AND {gleich})""").format(
        ziel=z.ident, sp=spalten, bereich=_bereich("t", z), gleich=_gleich("n", "t", z),
        nsp=sql.SQL(", ").join(sql.Identifier("n", s) for s in z.spalten_neu())))
    geloescht = 0
    # Gelöscht wird nur, was im Register steht und in diesem Lauf fehlt; Zeilen anderer Importe oder von
    # Menschen stehen nicht im Register und bleiben. Register und Zieltabelle im selben Schritt
    cur.execute("SELECT EXISTS (SELECT 1 FROM vergleich WHERE art = 'geloescht')")
    if loeschen and cur.fetchone()[0]:
        cur.execute(sql.SQL("""DELETE FROM {ziel} t WHERE {bereich}
                               AND {st} IN (SELECT s FROM vergleich WHERE art = 'geloescht')""").format(
            ziel=z.ident, bereich=_bereich("t", z), st=_schluessel_text("t", z)))
        geloescht = cur.rowcount
        cur.execute("""DELETE FROM pipeline_meta.bestand WHERE quelle = %s AND tabelle = %s
                       AND schluessel IN (SELECT s FROM vergleich WHERE art = 'geloescht')""",
                    (name, z.name))
    # Nur Zeilen, die sich in diesem Lauf geändert haben, berühren das Register. Bei 1,5 Mio.
    # unveränderten Zeilen (INKAR bundesweit) erzeugte ein UPDATE aller Zeilen je Lauf ebenso viele
    # tote Zeilen und verdoppelte das Register (gemessen 03.11.2026, docs/entscheidungen.md E29).
    cur.execute("""INSERT INTO pipeline_meta.bestand (quelle, tabelle, schluessel, quellschluessel,
                                                      erster_lauf, letzter_lauf)
                   SELECT %(q)s, %(t)s, s, q, %(l)s, %(l)s FROM vergleich WHERE art IN ('neu', 'uebernommen')
                   ON CONFLICT (quelle, tabelle, schluessel) DO UPDATE
                   SET quellschluessel = EXCLUDED.quellschluessel, letzter_lauf = EXCLUDED.letzter_lauf,
                       erster_lauf = CASE WHEN bestand.quellschluessel <> EXCLUDED.quellschluessel
                                          THEN EXCLUDED.erster_lauf ELSE bestand.erster_lauf END""",
                {"q": name, "t": z.name, "l": lauf_id})
    # Oben: Ein Zielschlüssel, der schon im Register steht, kommt als `neu` hierher, wenn sein Quellschlüssel
    # gewechselt hat (E42). Dann beginnt mit dem neuen Datensatz auch erster_lauf neu; bei gleichem
    # Quellschlüssel (Zeile war aus der Zieltabelle verschwunden und wird neu angelegt) bleibt er
    cur.execute("""UPDATE pipeline_meta.bestand b SET letzter_lauf = %(l)s, quellschluessel = v.q
                   FROM vergleich v WHERE b.quelle = %(q)s AND b.tabelle = %(t)s
                   AND b.schluessel = v.s AND v.art = 'geaendert'""",
                {"q": name, "t": z.name, "l": lauf_id})
    # Register von vor E40 ohne Quellschlüssel: einmal nachtragen, ohne die Zeile als geändert zu zählen
    cur.execute("""UPDATE pipeline_meta.bestand b SET quellschluessel = v.q
                   FROM vergleich v WHERE b.quelle = %(q)s AND b.tabelle = %(t)s
                   AND b.schluessel = v.s AND v.art = 'unveraendert' AND v.q_fehlt""",
                {"q": name, "t": z.name})
    # Änderungsprotokoll je Schlüssel, ohne unveränderte Zeilen. `geloescht` heißt hier `entfernt`, wenn
    # gelöscht werden durfte, sonst `zurueckgehalten`; ein ersetzter Quellschlüssel zählt als entfernt
    # (Antwort 62); eine übernommene Zeile mit abweichenden Werten als uebernommen_geaendert (E46)
    cur.execute("""INSERT INTO pipeline_meta.aenderung
                       (lauf_id, quelle, tabelle, schluessel, quellschluessel, art)
                   SELECT DISTINCT %(l)s, %(q)s, %(t)s, s, q,
                          CASE art WHEN 'geloescht' THEN CASE WHEN %(weg)s THEN 'entfernt'
                                                              ELSE 'zurueckgehalten' END
                                   WHEN 'ersetzt' THEN 'entfernt'
                                   WHEN 'uebernommen' THEN CASE WHEN anders THEN 'uebernommen_geaendert'
                                                                ELSE 'uebernommen' END
                                   ELSE art END
                   FROM vergleich WHERE art <> 'unveraendert'""",
                {"l": lauf_id, "q": name, "t": z.name, "weg": loeschen})
    return geloescht


# --- table_metadata (DCAT-AP) --------------------------------------------------------------

def _zeitstempel(jetzt: datetime) -> datetime:
    """table_metadata hat Zeitstempel ohne Zeitzone; die Pipeline schreibt UTC.

    Args:
        jetzt: Zeitpunkt des Laufs in UTC (von laden).

    Returns:
        Derselbe Zeitpunkt ohne Zeitzonenangabe; die Uhrzeit wird nicht umgerechnet, nur die Angabe
        entfernt. Deshalb muss `jetzt` schon in UTC sein."""
    return jetzt.replace(tzinfo=None)


class MetadatenBelegt(ZielFehler):
    """Ein Metadatensatz der Quelle ließ sich nicht anlegen, weil sein Schlüssel in table_metadata schon
    einer anderen Quelle oder Raumebene gehört. Die Transaktion der Quelle wird zurückgerollt: keine
    Fachdaten ohne ihren Metadatensatz (Prüfbericht 05.11., F2, E46)."""


def _metadaten_zeilen(cur, name: str, qcfg: dict, z: Ziel, prot) -> list[tuple[dict, list[str], str | None]]:
    """Die Zeilen, die metadaten_schreiben in table_metadata pflegt: (Werte, Spalten, die die eigene Zeile
    erkennen, Geometriespalte für die Ausdehnung). Werte nur in Spalten, die es gibt; ohne `imported`.

    Gemeinsame Grundlage von metadaten_belegt (Prüfung vor dem Schreiben) und metadaten_schreiben, damit
    beide dieselben Zeilen sehen. Titel, Beschreibung, Kontakt und Lizenz kommen aus der Konfiguration,
    ersatzweise aus dem, was der Dienst über sich gemeldet hat (prot.info).

    Args:
        cur: Cursor in der Transaktion der Quelle; bei je: indikator wird `neu` gelesen.
        name: Name der Quelle (dct_identifier, Ersatz für den Titel).
        qcfg: Konfiguration der Quelle.
        z: Ziel nach pruefen (z.metadaten["_spalten"] gesetzt).
        prot: Protokoll der Quelle (nur gelesen).

    Returns:
        Liste von (Werte je Spalte, Spalten, die die eigene Zeile erkennen, Geometriespalte oder None)."""
    m = z.metadaten
    vorhanden = m.get("_spalten", set(META_SPALTEN))
    kontakt = qcfg.get("kontakt") or prot.info.get("kontakt") or {}
    basis = {"dct_title": qcfg.get("titel") or prot.info.get("titel") or name,
             "dct_description": qcfg.get("beschreibung") or prot.info.get("beschreibung"),
             "dct_catalog_publisher": kontakt.get("anbieter"),
             "dct_accessurl": qcfg.get("url") or qcfg.get("seite") or qcfg.get("pfad"),
             "dct_license": qcfg.get("lizenz") or prot.info.get("lizenz_laut_dienst"),
             "dct_identifier": name, "dct_language": "de"}
    # Ohne Rhythmus (Quelle lädt bei jedem Lauf) bleibt dct_accrualperiodicity leer
    rhythmus = qcfg.get("rhythmus")
    if rhythmus in RHYTHMUS_FREQUENZ:
        basis["dct_accrualperiodicity"] = FREQUENZ + RHYTHMUS_FREQUENZ[rhythmus]
    zeilen_meta = []
    if m.get("je", "tabelle") == "indikator":
        isp, zsp = m.get("indikator_spalte", "indikator"), m.get("zeit_spalte", "zeitbezug")
        esp, hsp = m.get("ebene_spalte", "granularity"), m.get("herausgeber_spalte", "source")
        # Zeitraum je Indikator aus dem neuen Stand dieser Quelle
        cur.execute(sql.SQL("""SELECT CAST(n.{i} AS text), min(n.{z}), max(n.{z}) FROM neu n
                               GROUP BY 1 ORDER BY 1""").format(i=sql.Identifier(isp), z=sql.Identifier(zsp)))
        for indikator, von, bis in cur.fetchall():
            werte = {**basis, "dct_title": indikator, "dct_type": "indikator",
                     "geometry_type": "Polygon", "table_name": indikator,
                     "dcatde_politicalgeocodingleveluri": z.fest.get(esp),
                     "dct_catalog_publisher": z.fest.get(hsp, basis["dct_catalog_publisher"]),
                     "dct_temporal_startdata": _jahr(von), "dct_temporal_enddate": _jahr(bis)}
            werte.update(m.get("felder") or {})
            # Name und Titel nach den Feldern der Konfiguration: table_name erkennt die Zeile, dct_title soll
            # je Indikator verschieden sein; beide darf `felder` nicht für alle Indikatoren gleich setzen.
            # Raumebene und Herausgeber, die die Zeile mit erkennen, kann `felder` dagegen überschreiben
            werte.update(table_name=indikator, dct_title=indikator)
            # dcat_ap_id nie aus `felder` (Codex-Prüfung E52, Muss 1): sonst bliebe ein dort gesetzter Wert
            # stehen, wenn die Formel unten nicht greift, und COALESCE hielte ihn danach für immer fest
            werte.pop(DCAT_AP_ID, None)
            # Kennung nach der Formel des MOSIDI-Skripts (E52): Indikator, Raumebene und Herausgeber, wie sie
            # in dashboard_data_de stehen (granularity, source; hier die festen Werte der Quelle), mit „_“
            # verbunden. Nicht aus dct_catalog_publisher: Der fällt auf kontakt.anbieter zurück und kann über
            # `felder` überschrieben werden. Fehlt einer der beiden festen Werte, bleibt die Kennung leer
            if z.fest.get(esp) is not None and z.fest.get(hsp) is not None:
                werte[DCAT_AP_ID] = f"{indikator}_{z.fest[esp]}_{z.fest[hsp]}"
            # Herausgeber gehört zur Kennung (Codex-Prüfung B5): gleichnamige Indikatoren auf derselben
            # Raumebene aus verschiedenen Quellen (etwa "Bevölkerung" von INKAR und vom Amt für
            # Statistik) überschreiben einander sonst
            zeilen_meta.append((werte, ["table_name", "dcatde_politicalgeocodingleveluri",
                                        "dct_catalog_publisher"], None))
    else:
        werte = {**basis, "table_name": z.tabelle, "dct_type": "geodaten"}
        if z.geometrie:
            werte["geometry_type"] = GEOMETRIEART.get((z.geom_typ or "").upper(), z.geom_typ)
        werte.update(m.get("felder") or {})
        # table_name erkennt die Zeile; die Konfiguration kann ihn nicht überschreiben. dcat_ap_id bekommen
        # Geometriezeilen nie, auch nicht über `felder` (E52, Codex-Prüfung Muss 1)
        werte["table_name"] = z.tabelle
        werte.pop(DCAT_AP_ID, None)
        zeilen_meta.append((werte, ["table_name"], z.geometrie))
    # Nur Spalten, die es in dieser table_metadata gibt und für die die Importrolle Rechte hat (META_SPALTEN,
    # einrichten.rechte); ein unbekanntes Feld aus der Konfiguration fällt hier still weg. dcat_ap_id (E52)
    # nur aus der Formel oben, nicht aus `felder` (dort fällt sie mit dem Filter weg), und nur mit Spalte und
    # Recht (pruefen setzt _dcat_ap_id)
    dcat = bool(m.get("_dcat_ap_id"))
    return [({**{k: v for k, v in w.items() if k in vorhanden and k in META_SPALTEN},
              **({DCAT_AP_ID: w[DCAT_AP_ID]} if dcat and DCAT_AP_ID in w else {})},
             [k for k in s if k in vorhanden], g) for w, s, g in zeilen_meta]


def _eigene_zeile(werte: dict, schluessel: list[str]) -> sql.Composable:
    """Bedingung für die eigene Zeile in table_metadata: alle erkennenden Spalten gleich den Werten.

    IS NOT DISTINCT FROM statt `=`: Eine leere Raumebene oder ein leerer Herausgeber soll die Zeile
    trotzdem wiederfinden; mit `=` fände das UPDATE in metadaten_schreiben sie nie, und jeder Lauf
    versuchte, sie neu anzulegen.

    Args:
        werte: Werte der Metadatenzeile (aus _metadaten_zeilen).
        schluessel: Spalten, die die eigene Zeile erkennen.

    Returns:
        SQL-Bedingung; die Werte als Literale."""
    return sql.SQL(" AND ").join(
        sql.SQL("{} IS NOT DISTINCT FROM {}").format(sql.Identifier(k), sql.Literal(werte.get(k)))
        for k in schluessel)


def metadaten_belegt(cur, name: str, qcfg: dict, z: Ziel, prot) -> list[str]:
    """Vor dem Schreiben (Prüfbericht 05.11., F2, E46): Namen der Metadatenzeilen dieser Quelle, die sich
    nicht anlegen ließen, weil ein eindeutiger Schlüssel von table_metadata (im öffentlichen Schema
    table_name, im Skript von MOSIDI table_name und Raumebene) schon von einer Zeile belegt ist, die nicht
    die eigene ist (andere Quelle oder Raumebene). Gelesen werden die eindeutigen Indizes der Tabelle,
    nicht angenommen; partielle (mit WHERE) und solche über Ausdrücke zählen nicht, ob eine Zeile unter
    ihre Bedingung fällt, prüft erst das Anlegen (Sicherheitsnetz in metadaten_schreiben; Nachprüfung zu
    E46). Leer: alles anlegbar oder schon vorhanden.

    Args:
        cur: Cursor in der Transaktion der Quelle; neu_bilden ist gelaufen.
        name: Name der Quelle.
        qcfg: Konfiguration der Quelle.
        z: Ziel nach pruefen; ohne ziel.metadaten ist das Ergebnis leer.
        prot: Protokoll der Quelle (nur gelesen).

    Returns:
        table_name der belegten Zeilen; laden.quelle_laden hält die Quelle dann an.

    Liest nur Katalog und table_metadata, schreibt nichts."""
    if not z.metadaten:
        return []
    meta = sql.Identifier("public", META_TABELLE)
    # Je eindeutigem Index seine Spalten in Indexreihenfolge. Ohne partielle Indizes (indpred) und ohne
    # solche über Ausdrücke (attnum 0 in indkey): Für beide lässt sich ohne Auswerten nicht sagen, ob eine
    # Zeile kollidiert
    cur.execute("""SELECT array_agg(a.attname ORDER BY k.n) FROM pg_index i
                   CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k (attnum, n)
                   LEFT JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
                   WHERE i.indrelid = to_regclass(%s) AND i.indisunique AND i.indpred IS NULL
                   GROUP BY i.indexrelid HAVING bool_and(k.attnum > 0)""", (meta.as_string(cur),))
    indizes = [r[0] for r in cur.fetchall()]
    belegt = []
    for werte, schluessel, _ in _metadaten_zeilen(cur, name, qcfg, z, prot):
        cur.execute(sql.SQL("SELECT EXISTS (SELECT 1 FROM {} WHERE {})").format(
            meta, _eigene_zeile(werte, schluessel)))
        if cur.fetchone()[0]:
            continue   # die eigene Zeile: metadaten_schreiben aktualisiert sie
        # Sonst würde die Zeile neu angelegt: belegt, wenn ein eindeutiger Index mit denselben Werten
        # schon eine (fremde) Zeile hat
        for spalten in indizes:
            # Leere Werte sind in einem eindeutigen Index verschieden, sie kollidieren nicht
            if any(werte.get(s) is None for s in spalten):
                continue
            gleich = sql.SQL(" AND ").join(sql.SQL("{} = {}").format(sql.Identifier(s), sql.Literal(werte[s]))
                                           for s in spalten)
            cur.execute(sql.SQL("SELECT EXISTS (SELECT 1 FROM {} WHERE {})").format(meta, gleich))
            if cur.fetchone()[0]:
                belegt.append(werte["table_name"])
                break
    return belegt


def metadaten_schreiben(cur, name: str, qcfg: dict, z: Ziel, prot, jetzt: datetime,
                        geaendert: bool) -> int:
    """Metadaten in table_metadata, so wie MOSIDI sie selbst anlegt (db_table_metadata/script.py):
    je Geometrietabelle eine Zeile (table_name = Tabelle), je Indikator in dashboard_data_de eine
    Zeile (table_name = Indikator, dcatde_politicalgeocodingleveluri = Raumebene, Herausgeber =
    source). Aktualisiert wird die vorhandene Zeile, sonst eine neue angelegt; ohne ON CONFLICT,
    weil das öffentliche Schema und das MOSIDI-Skript verschiedene Primärschlüssel haben.
    Eine Indikatorzeile gilt nur als die eigene, wenn Name, Raumebene und Herausgeber passen (E38). Ist der
    Schlüssel schon von einer anderen Quelle belegt, hält quelle_laden die Quelle vorher an
    (metadaten_belegt, E46); kommt eine solche Zeile erst danach dazu, wirft das Anlegen MetadatenBelegt
    und die Transaktion der Quelle wird zurückgerollt. Rückgabe: Zahl der geschriebenen Zeilen.

    Args:
        cur: Cursor in der Transaktion der Quelle; anwenden ist gelaufen.
        name: Name der Quelle.
        qcfg: Konfiguration der Quelle.
        z: Ziel nach pruefen; ohne ziel.metadaten schreibt die Funktion nichts.
        prot: Protokoll der Quelle (Warnungen, info["metadaten_belegt"]).
        jetzt: Zeitpunkt des Laufs in UTC (imported, dct_modified, dct_issued).
        geaendert: Ob die Quelle in diesem Lauf etwas geändert hat; nur dann wird dct_modified neu gesetzt.

    Raises:
        MetadatenBelegt: Das Anlegen einer Zeile scheitert an einem eindeutigen Schlüssel.

    Seiteneffekte: UPDATE und INSERT in public.table_metadata (nur Spalten aus META_SPALTEN, dazu bei
    Indikatoren dcat_ap_id, E52); bei Indikatoren zusätzlich die Warnung aus verwaiste_melden.

    dcat_ap_id (E52, Mitbewerber-Sichtung 08.11.2026): Gibt es die Spalte (Fassung des MOSIDI-Skripts) und
    darf die Importrolle sie schreiben, bekommt jede Indikatorzeile die Kennung nach der Formel von MOSIDI
    (Indikator_Raumebene_Herausgeber, _metadaten_zeilen): beim Anlegen immer, beim Aktualisieren nur, wo sie
    NULL ist. Ein vorhandener Wert bleibt, ebenso dcat_ap_title (nie geschrieben). Geometriezeilen bekommen
    keine Kennung (MOSIDI setzt sie dort auch nicht). Gibt es die Spalte, fehlt aber das Recht, steht ein
    Hinweis im Bericht der Quelle.

    UPDATE und INSERT setzen nur Spalten, die es in table_metadata gibt (z.metadaten["_spalten"]); fehlen
    imported, dct_modified, dct_bbox oder dct_centroid, bleiben sie weg. Bis E50 setzte das UPDATE diese vier
    ungefiltert und scheiterte an einer Tabelle ohne sie (in E49 benannt, E50 behoben)."""
    m = z.metadaten
    if not m:
        return 0
    vorhanden = m.get("_spalten", set(META_SPALTEN))
    esp, hsp = m.get("ebene_spalte", "granularity"), m.get("herausgeber_spalte", "source")
    isp = m.get("indikator_spalte", "indikator")
    t = _zeitstempel(jetzt)
    zeilen_meta = _metadaten_zeilen(cur, name, qcfg, z, prot)
    if m.get("je", "tabelle") == "indikator" and m.get("_dcat_ap_id") is False:
        prot.hinweise.append(f"{META_TABELLE}.{DCAT_AP_ID} nicht gesetzt: Die Importrolle hat dort keine "
                             "Rechte (nach dem Update einmal einrichten ausführen, E52)")
    for werte, schluessel, geomspalte in zeilen_meta:
        werte = dict(werte, imported=t)
        # Kennung nach MOSIDI (E52) gesondert: beim Anlegen gesetzt, beim Aktualisieren nur, wo sie leer ist
        dcat_ap_id = werte.pop(DCAT_AP_ID, None)
        ausdruecke = {k: sql.Literal(v) for k, v in werte.items()}
        # Ausdehnung und Mittelpunkt der ganzen Zieltabelle nach dem Schreiben, in der Datenbank berechnet;
        # ST_Extent liefert ein box2d ohne Bezugssystem, daher ST_SetSRID
        if geomspalte:
            hulle = sql.SQL("(SELECT ST_SetSRID(CAST(ST_Extent({g}) AS geometry), {srid}) "
                            "FROM {ziel})").format(
                g=sql.Identifier(geomspalte), srid=sql.Literal(ZIEL_SRID), ziel=z.ident)
            ausdruecke["dct_bbox"] = hulle
            ausdruecke["dct_centroid"] = sql.SQL("ST_Centroid({})").format(hulle)
        bedingung = _eigene_zeile(werte, schluessel)
        # Erst aktualisieren, nur ohne Treffer anlegen (kein ON CONFLICT, siehe oben). dct_modified nur bei
        # Änderungen, damit der Katalog zeigt, wann sich die Daten zuletzt geändert haben, nicht wann
        # zuletzt geladen wurde (dafür steht imported)
        setzen = dict(ausdruecke)
        if geaendert:
            setzen["dct_modified"] = sql.Literal(t)
        # Wie beim INSERT unten nur vorhandene Spalten (E50); Werte aus _metadaten_zeilen sind schon gefiltert
        setzen = {k: v for k, v in setzen.items() if k in vorhanden}
        if dcat_ap_id is not None:
            # Vorhandene Werte nie überschreiben (E52): COALESCE behält jeden Wert außer NULL, auch eine
            # Themenklasse, die MOSIDI eingetragen hat, und einen leeren Text
            setzen[DCAT_AP_ID] = sql.SQL("COALESCE({}, {})").format(sql.Identifier(DCAT_AP_ID),
                                                                    sql.Literal(dcat_ap_id))
        cur.execute(sql.SQL("UPDATE {} SET {} WHERE {}").format(
            sql.Identifier("public", META_TABELLE),
            sql.SQL(", ").join(sql.SQL("{} = {}").format(sql.Identifier(k), v) for k, v in setzen.items()),
            bedingung))
        if cur.rowcount == 0:
            # Neue Zeile: dct_issued und dct_modified auf den Zeitpunkt dieses Laufs
            neu = {**ausdruecke, "dct_modified": sql.Literal(t), "dct_issued": sql.Literal(t)}
            neu = {k: v for k, v in neu.items() if k in vorhanden}
            if dcat_ap_id is not None:
                neu[DCAT_AP_ID] = sql.Literal(dcat_ap_id)
            # Ist der Schlüssel inzwischen belegt (metadaten_belegt hat vor dem Schreiben nichts
            # gefunden), gehört die Zeile einer anderen Quelle oder Raumebene: nicht überschreiben, und
            # keine Fachdaten ohne Metadatensatz (E46), die Transaktion der Quelle wird zurückgerollt
            try:
                cur.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier("public", META_TABELLE), sql.SQL(", ").join(map(sql.Identifier, neu)),
                    sql.SQL(", ").join(neu.values())))
            except UniqueViolation as e:
                # Wie die Prüfung vorab: kein Meldungsentwurf an den Anbieter, der Konflikt liegt im
                # eigenen Katalog (waechter.meldung_noetig; Nachprüfung zu E46)
                prot.info["metadaten_belegt"] = [werte["table_name"]]
                raise MetadatenBelegt(f"{META_TABELLE}: Zeile {werte['table_name']} nicht anlegbar, der Name "
                                      "ist schon für eine andere Quelle oder Raumebene eingetragen; Quelle "
                                      "zurückgerollt, alter Stand bleibt") from e
    if m.get("je", "tabelle") == "indikator":
        verwaiste_melden(cur, z, prot, isp, esp, hsp, vorhanden)
    return len(zeilen_meta)


def verwaiste_melden(cur, z: Ziel, prot, isp: str, esp: str, hsp: str, vorhanden: set) -> None:
    """Indikatorzeilen in table_metadata mit Herausgeber und Raumebene dieser Quelle, für die die
    Zieltabelle keine Zeile dieser Quelle mehr hat (umbenannter Indikator, weggefallener Bereich, geänderte
    Regel). Die Importrolle darf in table_metadata nicht löschen (geringste Rechte), und ob eine solche
    Zeile von der Pipeline oder von MOSIDI selbst stammt, steht nirgends; deshalb nur eine Warnung mit
    den Namen (Prüfung 05.11., Runde 2; älter als E40, E42).

    Args:
        cur: Cursor in der Transaktion der Quelle; anwenden ist gelaufen (Zieltabelle im neuen Stand).
        z: Ziel nach pruefen.
        prot: Protokoll der Quelle (Warnung).
        isp: Indikatorspalte der Zieltabelle.
        esp: Spalte der Raumebene; ihr Wert muss in ziel.fest stehen.
        hsp: Spalte des Herausgebers; ihr Wert muss in ziel.fest stehen.
        vorhanden: Spalten von table_metadata (aus pruefen).

    Schreibt nichts; ohne die nötigen Spalten oder festen Werte tut die Funktion nichts."""
    noetig = {"table_name", "dcatde_politicalgeocodingleveluri", "dct_catalog_publisher"}
    if not noetig <= vorhanden or esp not in z.fest or hsp not in z.fest:
        return
    cur.execute(sql.SQL("""SELECT m.table_name FROM {meta} m
                           WHERE m.dct_catalog_publisher = {h} AND m.dcatde_politicalgeocodingleveluri = {e}
                           AND NOT EXISTS (SELECT 1 FROM {ziel} t WHERE {bereich}
                                           AND CAST(t.{i} AS text) = m.table_name)
                           ORDER BY 1""").format(
        meta=sql.Identifier("public", META_TABELLE), h=sql.Literal(str(z.fest[hsp])),
        e=sql.Literal(str(z.fest[esp])), ziel=z.ident, bereich=_bereich("t", z), i=sql.Identifier(isp)))
    namen = [r[0] for r in cur.fetchall()]
    if namen:
        prot.warnungen.append(
            f"{META_TABELLE}: {len(namen)} Indikatorzeile{'n' if len(namen) != 1 else ''} dieser Quelle "
            f"(Herausgeber {z.fest[hsp]}, {z.fest[esp]}) ohne Daten in {z.name}, verwaist; die Pipeline "
            f"löscht dort nicht, bitte prüfen (docs/betrieb.md): "
            f"{', '.join(namen[:10])}{' …' if len(namen) > 10 else ''}")


def _jahr(v) -> datetime | None:
    """Zeitbezug (Jahr) als Zeitstempel 1. Januar, wie im MOSIDI-Skript (TO_TIMESTAMP(…, 'YYYY')).

    Args:
        v: Zeitbezug, etwa 2023 oder „2023-12-31“; maßgeblich sind die ersten vier Ziffern.

    Returns:
        1. Januar dieses Jahres, ohne Zeitzone; None, wenn v leer ist oder nicht mit vier Ziffern beginnt."""
    if v is None:
        return None
    m = re.match(r"(\d{4})", str(v))
    return datetime(int(m[1]), 1, 1) if m else None


# --- Lesen für Karte und Archiv ------------------------------------------------------------

def karte_sql(z: Ziel) -> sql.Composable:
    """Je Objekt Status und Geometrie aus `vergleich`. Ohne eigene Geometrie (Kennzahlen) je
    Gebiet zusammengefasst, Fläche aus der Gebietstabelle.

    Gelesen von karte.objekte_lesen in laden.quelle_laden, nach der Entscheidung über das Löschen und vor
    anwenden. Die Karte kennt nur neu, geändert, gelöscht und unverändert: übernommen zählt nach seinen
    Werten (wie in vergleichen), zurückgehalten als unverändert, ersetzt erscheint nicht (ohne Geometrie).

    Args:
        z: Ziel nach pruefen.

    Returns:
        Abfrage mit den Spalten Kennung, Status, Werte (jsonb), Geometrie als GeoJSON und dem Parameter
        %(max)s für die Höchstzahl der Objekte. Zeilen, die die Karte als unverändert zeigt, kommen zuletzt,
        damit die Grenze zuerst sie abschneidet; sortiert wird in beiden Zweigen nach dem angezeigten Status.
        Bis E50 sortierte der Zweig mit eigener Geometrie nach der Spalte art, und zurückgehaltene oder
        unverändert übernommene Zeilen (angezeigt als unverändert) konnten unter LIMIT echte Änderungen aus
        der Karte drängen (in E49 benannt, E50 behoben). Ohne Geometrie und ohne Gebietsgeometrie eine Abfrage
        ohne
        Ergebnis (und ohne Parameter)."""
    # Geometrien mit mehr als 200 Punkten vereinfacht (Toleranz 0,0002 Grad, in Brandenburg rund 14 bis
    # 22 m), Koordinaten auf 6 Nachkommastellen: Die Karte ist eine Übersicht, die Seite soll klein
    # bleiben; in die Zieltabelle geht die volle Geometrie
    vereinfacht = sql.SQL("""ST_AsGeoJSON(CASE WHEN ST_NPoints(geom) > 200
                             THEN ST_SimplifyPreserveTopology(geom, 0.0002) ELSE geom END, 6)""")
    if z.geometrie:
        # Angezeigter Status in einer Unterabfrage, damit ORDER BY nach ihm sortiert, nicht nach art (E50)
        return sql.SQL("""SELECT k, status, werte, g FROM (
                              SELECT s ->> 0 AS k, CASE WHEN art = 'uebernommen' AND anders THEN 'geaendert'
                                     WHEN art IN ('uebernommen', 'zurueckgehalten') THEN 'unveraendert'
                                     ELSE art END AS status, werte, {v} AS g
                              FROM vergleich WHERE geom IS NOT NULL) a
                          ORDER BY status = 'unveraendert', k LIMIT %(max)s""").format(v=vereinfacht)
    if not z.gebiet or not z.gebiet.get("geometrie"):
        return sql.SQL("SELECT NULL, NULL, NULL, NULL WHERE false")
    g = z.gebiet
    # Kennzahlen: je Gebiet ein Status aus allen seinen Zeilen (alle unverändert, alle neu, alle gelöscht,
    # sonst geändert) mit den Zahlen je Art; die Fläche aus der Gebietstabelle, je Schlüssel eine
    # (DISTINCT ON, falls die Gebietstabelle einen Schlüssel mehrfach hat)
    return sql.SQL("""
        WITH je AS (
            SELECT gebiet,
                   CASE WHEN bool_and(art IN ('unveraendert', 'zurueckgehalten')
                                      OR art = 'uebernommen' AND NOT anders) THEN 'unveraendert'
                        WHEN bool_and(art = 'neu') THEN 'neu'
                        WHEN bool_and(art = 'geloescht') THEN 'geloescht' ELSE 'geaendert' END AS art,
                   jsonb_build_object('zeilen', count(*),
                                      'neu', count(*) FILTER (WHERE art = 'neu'),
                                      'geaendert', count(*) FILTER (WHERE art = 'geaendert'
                                                                    OR art = 'uebernommen' AND anders),
                                      'geloescht', count(*) FILTER (WHERE art = 'geloescht')) AS werte
            FROM vergleich WHERE gebiet IS NOT NULL GROUP BY gebiet),
        f AS (SELECT DISTINCT ON (CAST(t.{sp} AS text)) CAST(t.{sp} AS text) AS gebiet, t.{gg} AS geom
              FROM {tab} t ORDER BY CAST(t.{sp} AS text))
        SELECT je.gebiet, je.art, je.werte, {v}
        FROM je JOIN f ON f.gebiet = je.gebiet
        ORDER BY je.art = 'unveraendert', je.gebiet LIMIT %(max)s""").format(
        sp=sql.Identifier(g["spalte"]), gg=sql.Identifier(g["geometrie"]),
        tab=sql.Identifier(g.get("schema", "public"), g["tabelle"]), v=vereinfacht)


def archiv_sql(name: str, z: Ziel) -> sql.Composable:
    """Stand der Quelle in der Zieltabelle: alle Zeilen aus dem Register, ohne Versionen.

    Für das Stand-Archiv (betrieb.archiv_schreiben, E17), nach dem Laden in einer eigenen Abfrage. Die
    Geometrie mit 7 Nachkommastellen, in der Genauigkeit, mit der auch der Vergleich rechnet (RASTER).
    Verknüpft über Register und Bereich: Zeilen anderer Quellen in derselben Tabelle kommen nicht hinein.

    Args:
        name: Name der Quelle (Register).
        z: Ziel nach pruefen.

    Returns:
        Abfrage mit den Spalten erster Schlüsselwert, Geometrie als GeoJSON (oder NULL) und die Zeile als
        jsonb ohne Geometrie; sortiert nach dem ersten Schlüsselwert."""
    geom = (sql.SQL("ST_AsGeoJSON(t.{}, 7)").format(sql.Identifier(z.geometrie)) if z.geometrie
            else sql.SQL("NULL"))
    weg = sql.SQL(" - {}").format(sql.Literal(z.geometrie)) if z.geometrie else sql.SQL("")
    return sql.SQL("""SELECT b.schluessel ->> 0, {geom}, to_jsonb(t){weg}
                      FROM pipeline_meta.bestand b JOIN {ziel} t ON {bereich} AND {st} = b.schluessel
                      WHERE b.quelle = {q} AND b.tabelle = {tn} ORDER BY 1""").format(
        geom=geom, weg=weg, ziel=z.ident, bereich=_bereich("t", z), st=_schluessel_text("t", z),
        q=sql.Literal(name), tn=sql.Literal(z.name))
