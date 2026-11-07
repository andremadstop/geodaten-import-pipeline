"""Tests des Quellen-Wächters: Schemavergleich, Schutz vor Einbrüchen, Meldungsentwurf.

pipeline.waechter bewertet nach dem Abruf (quellen), ob eine Quelle in die Zieltabellen (ziel)
übernommen werden darf, und am Ende der Quelle, ob der Anbieter eine Meldung bekommen sollte.
Abgesichert werden der Rückgang-Schutz (E4), dass updateSequence kein Änderungssignal ist (E5), dass
Meldungen nur als Entwurf mit nachstellbarer Abfrage und ohne interne Angaben entstehen (E8) und dass
ein Konflikt im eigenen Metadatenkatalog keine Meldung an den Anbieter auslöst (E46).
"""
import json

from pipeline import waechter


def test_feldliste_geaendert():
    """Eine geänderte Feldliste der Quelle ergibt genau einen Hinweis, der neue und entfallene Felder getrennt
    nennt."""
    vorher = {"info": {"felder": ["ags", "gen", "bez"]}}
    hinweise = waechter.schema_vergleichen(vorher, {"felder": ["ags", "gen", "name_neu"]})
    assert hinweise == ["Feldliste der Quelle geändert: neu name_neu; entfallen bez"]


def test_update_sequence_allein_ist_kein_hinweis():
    """Eine neue updateSequence bei gleicher Feldliste ergibt keinen Hinweis; sie wird nur mitgeschrieben,
    nicht ausgewertet (E5)."""
    vorher = {"info": {"felder": ["a"], "update_sequence": "128464"}}
    assert waechter.schema_vergleichen(vorher, {"felder": ["a"], "update_sequence": "129155"}) == []


def test_rueckgang():
    """Rückgang-Schutz (E4) bei max_rueckgang 0,5: 882 auf 400 ist zu viel, 882 auf 441 (genau die Hälfte)
    noch nicht; ohne bisherigen Bestand (0) oder ohne Grenze (None) greift er nie."""
    assert waechter.rueckgang_zu_gross(882, 400, 0.5)
    assert not waechter.rueckgang_zu_gross(882, 441, 0.5)
    assert not waechter.rueckgang_zu_gross(0, 0, 0.5)
    assert not waechter.rueckgang_zu_gross(882, 1, None)


def test_letzter_bericht_nimmt_juengsten_davor(tmp_path):
    """letzter_bericht liefert je Quelle den jüngsten Bericht vor dem laufenden Lauf, nicht den Bericht des
    Laufs selbst."""
    for lauf, n in (("20261029T000000Z", 1), ("20261030T000000Z", 2), ("20261031T000000Z", 3)):
        (tmp_path / f"{lauf}.json").write_text(json.dumps({"quellen": [{"quelle": "q", "n": n}]}))
    assert waechter.letzter_bericht(tmp_path, "20261031T000000Z")["q"]["n"] == 2


def test_meldung_enthaelt_nachstellbare_abfrage_und_keine_zugangsdaten():
    """Der Meldungsentwurf an den Anbieter (E8) nennt dessen Kontakt, die nachstellbare Abfrage-URL und den
    Zeitpunkt in UTC, aber keine Zugangsdaten zur Datenbank."""
    eintrag = {"status": "angehalten", "warnungen": ["Quelle lieferte 10 statt bisher 882 Objekte"],
               "letzte_abfrage": "https://dienst.example/ows?REQUEST=GetFeature",
               "info": {"kontakt": {"anbieter": "Amt", "email": "service@amt.example"}}}
    text = waechter.meldung_text("q", {"typename": "x:y"}, eintrag, "20261030T074334Z")
    assert "An: service@amt.example" in text
    assert "https://dienst.example/ows?REQUEST=GetFeature" in text
    assert "30.10.2026, 07:43 UTC" in text
    assert "PASSWORD" not in text and "PGUSER" not in text


def test_meldung_an_anbieter_ohne_interne_fehlertexte():
    """Fehler der Quelle (hier QuellenFehler) gehen wörtlich in die Meldung; ein interner Fehler (hier der
    Datenbank) erscheint nur mit seiner Art, ohne Rechneradresse und ohne Text zur Anmeldung."""
    assert waechter.befund_fuer_anbieter("QuellenFehler: Nur https ist erlaubt") == \
        "QuellenFehler: Nur https ist erlaubt"
    intern = waechter.befund_fuer_anbieter('OperationalError: connection to server at "db" (10.0.0.5), '
                                           'port 5432 failed: password authentication failed for user "x"')
    assert "10.0.0.5" not in intern and "password" not in intern and "OperationalError" in intern


def test_kein_meldungsentwurf_bei_belegtem_metadatensatz():
    """E46: Hält ein Konflikt in table_metadata die Quelle an, liegt das im eigenen Katalog; der Anbieter
    der Daten bekommt keinen Meldungsentwurf. Andere angehaltene Quellen weiterhin."""
    belegt = {"status": "angehalten", "info": {"metadaten_belegt": ["Bevölkerung"]}}
    assert not waechter.meldung_noetig(belegt)
    assert waechter.meldung_noetig({"status": "angehalten", "info": {}})


def test_meldungsentwurf_ohne_lokale_pfade():
    """E50, Codefehler aus E49 (waechter.meldung_text): Texte von QuellenFehler können lokale Pfade nennen,
    und ohne Netzabruf fiel die Zeile „Abfrage“ auf `pfad` der Konfiguration zurück. Beides kommt jetzt nicht
    mehr in den Entwurf an Dritte: Pfade werden zu „<lokaler Pfad>“, eine lokale Datei erscheint nur mit
    ihrem Namen. Adressen (https://…) bleiben, damit der Anbieter nachstellen kann."""
    eintrag = {"status": "fehler", "info": {},
               "fehler": "QuellenFehler: Abgelegte INKAR-Datei fehlt: /app/cache/inkar_2025.zip (datei bzw. "
                         "PIPELINE_INKAR_DATEI); siehe https://dienst.example/ows/a.zip"}
    text = waechter.meldung_text("inkar", {"url": "https://bbr.example/inkar_{jahr}.zip"}, eintrag,
                                 "20261106T120000Z")
    assert "/app/cache" not in text and "<lokaler Pfad>" in text
    assert "https://dienst.example/ows/a.zip" in text and "https://bbr.example/inkar_{jahr}.zip" in text
    angehalten = {"status": "angehalten", "info": {},
                  "warnungen": ["Datei /srv/daten/werte.csv: Kopfzeile 8"]}
    text = waechter.meldung_text("csv", {"pfad": "/srv/daten/werte.csv"}, angehalten, "20261106T120000Z")
    assert "/srv/daten" not in text and "werte.csv" in text


def test_kein_meldungsentwurf_beim_zeitbudget():
    """E50, Befund W6: Ein überschrittenes Zeitbudget liegt an Menge oder eigener Einstellung, nicht
    nachweislich am Anbieter; es gibt keinen Meldungsentwurf. Andere Fehler weiterhin."""
    assert not waechter.meldung_noetig({"status": "fehler", "info": {},
                                        "fehler": "ZeitbudgetUeberschritten: Zeitbudget von 30 min …"})
    assert waechter.meldung_noetig({"status": "fehler", "info": {}, "fehler": "QuellenFehler: x"})


def test_meldungsentwurf_ersetzt_konfigurierte_pfade_ganz(monkeypatch):
    """Nachprüfung zu E50: Das allgemeine Muster erfasste nur absolute Pfade bis zum ersten Leerzeichen; ein
    relativer Pfad (`cache/inkar.zip`), einer mit `~/` und der Rest eines Pfads mit Leerzeichen blieben im
    Entwurf an den Anbieter stehen. Jetzt werden die konfigurierten Pfade (datei, pfad, cache,
    PIPELINE_INKAR_DATEI, PIPELINE_CACHE, soweit sie einen Schrägstrich enthalten) ausdrücklich ersetzt, bevor
    das Muster greift, und `~/…` gilt als lokaler Pfad."""
    monkeypatch.setenv("PIPELINE_INKAR_DATEI", "/srv/geo daten/inkar.zip")
    monkeypatch.setenv("PIPELINE_CACHE", "/var/zwischen speicher")
    fehler = ("QuellenFehler: Datei /srv/geo daten/inkar.zip nicht lesbar; Kopie cache/inkar.zip; Ablage "
              "~/geheim/inkar.zip; Cache /var/zwischen speicher/x.zip; siehe https://dienst.example/a.zip")
    text = waechter.meldung_text("inkar", {"url": "https://bbr.example/inkar_{jahr}.zip",
                                           "datei": "cache/inkar.zip", "cache": "c"},
                                 {"status": "fehler", "info": {}, "fehler": fehler}, "20261106T120000Z")
    for rest in ("geo daten", "daten/inkar", "cache/inkar", "~/geheim", "geheim/", "zwischen speicher"):
        assert rest not in text, rest
    # Ein kurzer Name ohne Schrägstrich (hier cache: c) wird nicht ersetzt, der übrige Text bleibt lesbar
    assert "https://dienst.example/a.zip" in text and "Kopie" in text and "Cache" in text
