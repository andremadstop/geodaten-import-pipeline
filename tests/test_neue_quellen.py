"""INKAR, OGC API - Features, Dateiabruf und ZIP-Grenzen, ohne Netz und ohne Datenbank.

Alle Adapter hier gehören zur Stufe quellen (laden → quellen → ziel); Netzabrufe sind durch
Stellvertreter ersetzt. Abgesichert werden: INKAR als gestreamte Gesamtdatei mit Filtern, Breit- und
Langform und fachlichem Schlüssel (E15, E40), der Dateiabruf mit If-Modified-Since und Größengrenze, die
Grenzen beim Lesen von ZIP-Dateien (ZIP-Bombe, entpackte Größe), der OGC-API-Adapter mit Folge-Links nur
auf denselben Rechner und ohne Endlosschleife (E16, E47), unvollständige Abrufe sperren das Löschen
(E23) und INKAR ohne jeden Abruf von www.bbr-server.de, dessen robots.txt automatische Abrufe sperrt
(E48), außer mit der benannten Freigabe der Quelle, und dann nur gegen eine Attrappe (E50). Seit E50 außerdem:
INKAR-Zeilen syntaktisch vor dem Filter (K1), Konfigurationsfehler und leerer Eintrag mit Klartext, geprüfte
Dateinamen im Cache, unlesbares Last-Modified und das Zeitbudget im INKAR-Durchlauf.
"""
import json
import zipfile

import pytest

from pipeline import quellen
from pipeline.quellen import Protokoll, QuellenFehler, gebietsschluessel

KOPF = "Bereich;ID;Kuerzel;Indikator;Raumbezug;Kennziffer;Name;Zeitbezug;Wert\n"


def _zip(pfad, eintraege, methode=zipfile.ZIP_DEFLATED):
    """Schreibt ein ZIP mit den angegebenen Einträgen (Name → Text) und dem gewählten Packverfahren."""
    with zipfile.ZipFile(pfad, "w", methode) as z:
        for name, inhalt in eintraege.items():
            z.writestr(name, inhalt)
    return pfad


def test_gebietsschluessel_auffuellen_und_kuerzen():
    """gebietsschluessel ergänzt führende Nullen (schluessel_laenge), kürzt auf die ersten Stellen
    (schluessel_stellen) und entfernt Leerraum."""
    assert gebietsschluessel("1001", {"schluessel_laenge": 5}) == "01001"
    assert gebietsschluessel("12051000", {"schluessel_stellen": 5}) == "12051"
    assert gebietsschluessel(" 12051 ", {}) == "12051"


def test_zip_liest_genau_einen_eintrag(tmp_path):
    """Ohne Angabe von `eintrag` liest zip_zeilen die einzige CSV im ZIP zeilenweise; andere Dateien (hier
    liesmich.txt) stören nicht."""
    z = _zip(tmp_path / "a.zip", {"daten.csv": "a;b\n1;2\n", "liesmich.txt": "x"})
    assert list(quellen.zip_zeilen(z, None, {}, Protokoll())) == ["a;b\n", "1;2\n"]


def test_zip_mehrere_csv_verlangt_eintrag(tmp_path):
    """Enthält das ZIP mehrere CSV-Dateien, bricht zip_zeilen ab und verlangt die Angabe `eintrag`, statt eine
    zu raten."""
    z = _zip(tmp_path / "a.zip", {"eins.csv": "a\n", "zwei.csv": "b\n"})
    with pytest.raises(QuellenFehler, match="eintrag"):
        list(quellen.zip_zeilen(z, None, {}, Protokoll()))


def test_zip_fehlender_eintrag(tmp_path):
    """Ein angegebener Eintrag, den das ZIP nicht enthält, ergibt QuellenFehler."""
    z = _zip(tmp_path / "a.zip", {"daten.csv": "a\n"})
    with pytest.raises(QuellenFehler, match="fehlt"):
        list(quellen.zip_zeilen(z, "anders.csv", {}, Protokoll()))


def test_zip_bombe_wird_vor_dem_lesen_erkannt(tmp_path):
    """Eine Packrate über max_packrate (Standard 100:1) gilt als mögliche ZIP-Bombe und bricht ab, bevor etwas
    entpackt wird."""
    # 20 MB Nullen packen sich auf wenige KB: Packrate weit über 100:1
    z = _zip(tmp_path / "bombe.zip", {"daten.csv": "0" * (20 * 1024 * 1024)})
    with pytest.raises(QuellenFehler, match="Packrate"):
        list(quellen.zip_zeilen(z, None, {}, Protokoll()))


def test_zip_groessenlimit_entpackt(tmp_path):
    """Ein Eintrag, der entpackt größer ist als max_entpackt_mb, wird nach der Angabe im ZIP-Verzeichnis
    abgelehnt, auch wenn er ungepackt gespeichert ist."""
    z = _zip(tmp_path / "a.zip", {"daten.csv": "x" * (2 * 1024 * 1024)}, zipfile.ZIP_STORED)
    with pytest.raises(QuellenFehler, match="max_entpackt_mb"):
        list(quellen.zip_zeilen(z, None, {"max_entpackt_mb": 1}, Protokoll()))


def _inkar_zip(tmp_path, zeilen):
    """Legt im Cache ein INKAR-ZIP mit Kopfzeile, den übergebenen Datenzeilen und einer Readme-Datei ab und
    gibt den Cache-Ordner zurück."""
    ablage = tmp_path / "cache"
    ablage.mkdir()
    _zip(ablage / "inkar_2025.zip", {"inkar_2025.csv": KOPF + "".join(zeilen), "Readme.txt": "x"})
    return ablage


def _inkar_cfg(ablage, **kw):
    """Konfiguration einer INKAR-Quelle für Brandenburger Gemeinden (Kennziffer beginnt mit 12, acht Stellen)
    mit zwei Indikatoren und Gebietsbezug; Schlüsselwörter überschreiben einzelne Werte."""
    cfg = {"url": "https://bbr.example/inkar_2025.zip", "cache": str(ablage), "raumbezug": "Gemeinden",
           "kennziffer_beginnt": "12", "kennziffer_stellen": 8,
           "indikatoren": {"xbev": "bevoelkerung", "q_bev_fl": "einwohnerdichte"},
           "gebiet": {"geometrie_quelle": "gemeinden", "schluessel_feld": "ags"}}
    cfg.update(kw)
    return cfg


ZEILEN = [
    "Bev;1;xbev;Bevölkerung gesamt;Gemeinden;12051000;Brandenburg an der Havel;2022;72000,00\n",
    "Bev;1;xbev;Bevölkerung gesamt;Gemeinden;12051000;Brandenburg an der Havel;2023;72900,00\n",
    "Bev;2;q_bev_fl;Einwohnerdichte;Gemeinden;12051000;Brandenburg an der Havel;2023;318,7\n",
    "Bev;1;xbev;Bevölkerung gesamt;Gemeinden;12054000;Potsdam;2023;185750,00\n",
    "Bev;2;q_bev_fl;Einwohnerdichte;Gemeinden;12054000;Potsdam;2023;992,1\n",
    "Bev;1;xbev;Bevölkerung gesamt;Gemeinden;09162000;München;2023;1510378,00\n",   # anderes Land
    "Bev;1;xbev;Bevölkerung gesamt;Kreise;12051000;Brandenburg an der Havel;2023;72900,00\n",  # andere Ebene
    "Bev;1;xbev;Bevölkerung gesamt;Arbeitsmarktregionen;120;Biberach;2023;1\n",  # Präfix 12, falsch
    "Bev;3;alo;Arbeitslose;Gemeinden;12054000;Potsdam;2023;6500,00\n",  # nicht angefordert
]


def test_inkar_filtert_und_nimmt_das_neueste_jahr(tmp_path, monkeypatch):
    """In der Breitform bleiben nur Gemeinden in Brandenburg mit acht Stellen und angeforderte Indikatoren; je
    Indikator gilt das jüngste Jahr, das als Zeit-Referenz mitkommt."""
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)
    ablage = _inkar_zip(tmp_path, ZEILEN)
    prot = Protokoll()
    ds = {d["objekt_id"]: d for d in quellen.inkar(_inkar_cfg(ablage), prot)}
    assert set(ds) == {"12051000", "12054000"}
    brb = ds["12051000"]
    assert brb["geom"] == ("gebiet", "12051000")
    assert brb["werte"]["bevoelkerung"] == 72900.0 and brb["zeit"]["bevoelkerung"] == 2023
    assert "bevoelkerung_jahr" not in brb["werte"] and "name" not in brb["zeit"]
    assert brb["werte"]["einwohnerdichte"] == 318.7
    assert "alo" not in ds["12054000"]["werte"]
    assert not prot.info.get("fehlende_felder")


def test_inkar_kreise_auf_fuenf_stellen(tmp_path, monkeypatch):
    """Für Kreise wird der Gebietsschlüssel auf fünf Stellen gekürzt, damit er zum Kreisschlüssel der
    Geometriequelle passt; die Objekt-ID bleibt die volle Kennziffer."""
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)
    ablage = _inkar_zip(tmp_path, ZEILEN)
    cfg = _inkar_cfg(ablage, raumbezug="Kreise", indikatoren=["xbev"],
                     gebiet={"geometrie_quelle": "kreise", "schluessel_feld": "ags", "schluessel_stellen": 5})
    (d,) = list(quellen.inkar(cfg, Protokoll()))
    assert d["objekt_id"] == "12051000" and d["geom"] == ("gebiet", "12051")


def test_inkar_fehlender_indikator_haelt_an(tmp_path, monkeypatch):
    """Ein angeforderter Indikator, den die Datei nicht enthält, steht unter fehlende_felder, damit laden die
    Quelle anhält (E4)."""
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)
    ablage = _inkar_zip(tmp_path, ZEILEN)
    prot = Protokoll()
    list(quellen.inkar(_inkar_cfg(ablage, indikatoren=["xbev", "umbenannt"]), prot))
    assert prot.info["fehlende_felder"] == ["umbenannt"]


class Antwort:
    """Ersatz für requests.Response: Inhalt, Status, Kopfzeilen und Weiterleitungsmerker; iter_content liefert
    den Inhalt in Stücken wie beim Streamen."""
    def __init__(self, inhalt=b"", status=200, kopf=None, weiterleitung=False):
        self.inhalt, self.status_code, self.headers = inhalt, status, kopf or {}
        self.is_redirect = weiterleitung

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, n):
        for i in range(0, len(self.inhalt), n):
            yield self.inhalt[i:i + n]


def test_datei_abrufen_laedt_und_fragt_danach_nur_nach(tmp_path, monkeypatch):
    """Der erste Abruf lädt die Datei über eine Teil-Datei und übernimmt Last-Modified als Dateizeit; der
    zweite fragt mit If-Modified-Since nach und lädt bei 304 nichts (E15)."""
    gesendet = []

    def get(url, **k):
        gesendet.append(k["headers"])
        if "If-Modified-Since" in k["headers"]:
            return Antwort(status=304)
        return Antwort(b"ZIPDATEN", kopf={"Last-Modified": "Wed, 13 Aug 2025 12:59:06 GMT"})
    monkeypatch.setattr(quellen.requests, "get", get)
    ziel = tmp_path / "inkar_2025.zip"
    assert quellen.datei_abrufen("https://bbr.example/inkar_2025.zip", ziel, {}, Protokoll()) is True
    assert ziel.read_bytes() == b"ZIPDATEN" and not (tmp_path / "inkar_2025.zip.teil").exists()
    assert quellen.datei_abrufen("https://bbr.example/inkar_2025.zip", ziel, {}, Protokoll()) is False
    assert gesendet[1]["If-Modified-Since"] == "Wed, 13 Aug 2025 12:59:06 GMT"


def test_datei_abrufen_grenze_und_keine_reste(tmp_path, monkeypatch):
    """Überschreitet die Datei max_mb, bricht der Abruf ab und hinterlässt weder Ziel- noch Teil-Datei."""
    monkeypatch.setattr(quellen.requests, "get", lambda url, **k: Antwort(b"x" * (2 * 1024 * 1024)))
    ziel = tmp_path / "gross.zip"
    with pytest.raises(QuellenFehler, match="größer"):
        quellen.datei_abrufen("https://bbr.example/gross.zip", ziel, {"max_mb": 1}, Protokoll())
    assert not ziel.exists() and not (tmp_path / "gross.zip.teil").exists()


def test_jahresdateisuche_prueft_das_schema_vor_dem_head(monkeypatch):
    """Codex-Prüfung 05.11., B14: Die Suche nach der neuesten Jahresdatei (HEAD je Jahr) prüft das
    URL-Schema vor der ersten Verbindung; http nur mit erlaube_http: true, andere Schemata nie."""
    aufrufe = []

    def head(url, **k):
        aufrufe.append(url)
        return Antwort(status=200)
    monkeypatch.setattr(quellen.requests, "head", head)
    for muster, cfg in (("http://bbr.example/inkar_{jahr}.zip", {}),
                        ("http://bbr.example/inkar_{jahr}.zip", {"erlaube_http": "ja"}),
                        ("ftp://bbr.example/inkar_{jahr}.zip", {"erlaube_http": True}),
                        ("file:///etc/inkar_{jahr}.zip", {})):
        with pytest.raises(QuellenFehler, match="Nur https"):
            quellen.neueste_url(muster, cfg, Protokoll())
    assert aufrufe == []
    assert quellen.neueste_url("http://bbr.example/inkar_{jahr}.zip", {"erlaube_http": True},
                               Protokoll()).startswith("http://bbr.example/inkar_")
    assert quellen.neueste_url("https://bbr.example/inkar_{jahr}.zip", {}, Protokoll()).startswith("https://")
    assert len(aufrufe) == 2


def _ogc(monkeypatch, seiten):
    """seiten: Mapping URL-Anfang -> JSON-Antwort (dict) oder Ausnahme; der längste Anfang gewinnt."""
    seiten.setdefault("https://ogc.example/datasets/vg", {})

    def abrufen(url, params, cfg, prot):
        for anfang, antwort in sorted(seiten.items(), key=lambda kv: -len(kv[0])):
            if url.startswith(anfang):
                if isinstance(antwort, Exception):
                    raise antwort
                return json.dumps(antwort).encode()
        raise AssertionError(f"unerwartete Abfrage {url}")
    monkeypatch.setattr(quellen, "abrufen", abrufen)


def _feat(ags, name):
    """Objekt einer OGC-API-Antwort mit Gemeindeschlüssel, Name und Punktgeometrie."""
    return {"type": "Feature", "id": f"gem_{ags}", "properties": {"ags": ags, "gem_name": name},
            "geometry": {"type": "Point", "coordinates": [12.5, 52.4]}}


BASIS = "https://ogc.example/datasets/vg/collections/gem"


def test_ogcapi_folgt_seiten_und_ordnet_felder_zu(monkeypatch):
    """Der OGC-API-Adapter liest Kontakt und Lizenz von der Startseite, die Feldliste aus queryables, folgt
    rel=next über alle Seiten und benennt die Felder nach `felder` um (E16)."""
    _ogc(monkeypatch, {
        "https://ogc.example/datasets/vg": {
            "contact": {"name": "Landesvermessung", "email": "kundenservice@lgb.example"},
            "links": [{"rel": "license", "title": "Datenlizenz Deutschland Namensnennung 2.0"}]},
        f"{BASIS}/queryables": {"properties": {"ags": {}, "gem_name": {}}},
        f"{BASIS}/items?offset=1": {"features": [_feat("12054000", "Potsdam")], "links": []},
        f"{BASIS}/items": {"numberMatched": 2, "features": [_feat("12051000", "Brandenburg")],
                           "links": [{"rel": "next", "href": f"{BASIS}/items?offset=1"}]},
    })
    prot = Protokoll()
    ds = list(quellen.ogcapi({"url": BASIS, "id_feld": "ags", "felder": {"ags": "ags", "gem_name": "name"}},
                             prot))
    assert [d["objekt_id"] for d in ds] == ["12051000", "12054000"]
    assert ds[0]["werte"] == {"ags": "12051000", "name": "Brandenburg"}
    assert ds[0]["geom"][0] == "geojson"
    assert prot.info["kontakt"]["email"] == "kundenservice@lgb.example"
    assert prot.info["lizenz_laut_dienst"].startswith("Datenlizenz Deutschland")
    assert not prot.warnungen


def test_ogcapi_folgt_keinem_fremden_rechner(monkeypatch):
    """Ein Folge-Link auf einen anderen Rechner wird nicht abgerufen, die Quelle bricht mit QuellenFehler ab
    (E16)."""
    _ogc(monkeypatch, {
        f"{BASIS}/queryables": {"properties": {"ags": {}}},
        f"{BASIS}/items": {"features": [_feat("12051000", "B")],
                           "links": [{"rel": "next", "href": "https://anderswo.example/items?offset=1"}]},
    })
    with pytest.raises(QuellenFehler, match="anderen Rechner"):
        list(quellen.ogcapi({"url": BASIS, "id_feld": "ags"}, Protokoll()))


def test_ogcapi_zyklischer_next_link_endet_unvollstaendig(monkeypatch):
    """Prüfbericht 05.11. abends, Befund 6 (E47): Die Schleife folgte rel=next ohne Blick auf schon besuchte
    Adressen oder ausbleibenden Fortschritt; ein zyklischer Verweis mit nicht leerer Seite endete nie und
    hielt den ganzen Lauf auf. Jetzt beendet eine schon besuchte Adresse oder eine Seite ohne neues Objekt
    den Abruf der Quelle als unvollständig (Warnung, nichts wird gelöscht); die übrigen Quellen laufen
    weiter."""
    def dienst(seiten):
        """Ersetzt quellen.abrufen durch einen Dienst mit den gegebenen Seiten und gibt die Liste der
        abgerufenen Adressen zurück."""
        aufrufe = []

        def abrufen(url, params, cfg, prot):
            aufrufe.append(url)
            if len(aufrufe) > 20:   # Schutz für den roten Lauf: der alte Code liefe endlos
                raise AssertionError("Endlosschleife")
            if url.endswith("/queryables"):
                return json.dumps({"properties": {"ags": {}}}).encode()
            if url == "https://ogc.example/datasets/vg":
                return b"{}"
            return json.dumps(seiten[url]).encode()
        monkeypatch.setattr(quellen, "abrufen", abrufen)
        return aufrufe

    def seite(feats, weiter):
        """Eine Seite mit den Objekten `feats` und einem Folge-Link auf `weiter`."""
        return {"features": [_feat(a, "x") for a in feats], "links": [{"rel": "next", "href": weiter}]}

    # Verweis auf sich selbst: dieselbe Adresse wird nicht noch einmal abgerufen
    aufrufe = dienst({f"{BASIS}/items": seite(["1"], f"{BASIS}/items?s=2"),
                      f"{BASIS}/items?s=2": seite(["2"], f"{BASIS}/items?s=2")})
    prot = Protokoll()
    assert [d["objekt_id"] for d in quellen.ogcapi({"url": BASIS, "id_feld": "ags"}, prot)] == ["1", "2"]
    assert aufrufe.count(f"{BASIS}/items?s=2") == 1
    assert prot.unvollstaendig and any("schon abgerufen" in w for w in prot.warnungen), prot.warnungen

    # Neue Adresse, aber nur bekannte Objekte: kein Fortschritt, Abruf endet
    aufrufe = dienst({f"{BASIS}/items": seite(["1"], f"{BASIS}/items?s=2"),
                      f"{BASIS}/items?s=2": seite(["1"], f"{BASIS}/items?s=3"),
                      f"{BASIS}/items?s=3": seite(["3"], f"{BASIS}/items?s=4")})
    prot = Protokoll()
    assert [d["objekt_id"] for d in quellen.ogcapi({"url": BASIS, "id_feld": "ags"}, prot)] == ["1"]
    assert f"{BASIS}/items?s=3" not in aufrufe
    assert prot.unvollstaendig and any("kein neues Objekt" in w for w in prot.warnungen), prot.warnungen


def test_ogcapi_meldet_fehlendes_feld(monkeypatch):
    """Ein konfiguriertes Feld, das queryables nicht nennt, steht unter fehlende_felder (E4)."""
    _ogc(monkeypatch, {
        f"{BASIS}/queryables": {"properties": {"ags": {}}},
        f"{BASIS}/items": {"features": [_feat("12051000", "B")], "links": []},
    })
    prot = Protokoll()
    list(quellen.ogcapi({"url": BASIS, "id_feld": "ags", "felder": {"gem_name": "name"}}, prot))
    assert prot.info["fehlende_felder"] == ["gem_name"]


def test_inkar_langform_mit_fachlichem_schluessel(tmp_path, monkeypatch):
    """Wie dashboard_data_de: eine Zeile je Indikator, Gemeinde und Jahr, Langtext des Indikators,
    Objekt-ID aus Kennziffer, Bereich, Kürzel, Indikator, Zeitbezug (Antwort 31)."""
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)
    ablage = _inkar_zip(tmp_path, ZEILEN)
    cfg = _inkar_cfg(ablage, form="lang", zeitbezug="alle", indikatoren=["xbev", "q_bev_fl"])
    del cfg["gebiet"]
    ds = {d["objekt_id"]: d for d in quellen.inkar(cfg, Protokoll())}
    assert set(ds) == {"12051000|Bev|xbev|Bevölkerung gesamt|2022",
                       "12051000|Bev|xbev|Bevölkerung gesamt|2023",
                       "12051000|Bev|q_bev_fl|Einwohnerdichte|2023",
                       "12054000|Bev|xbev|Bevölkerung gesamt|2023",
                       "12054000|Bev|q_bev_fl|Einwohnerdichte|2023"}
    d = ds["12051000|Bev|xbev|Bevölkerung gesamt|2022"]
    assert d["werte"]["indikator"] == "Bevölkerung gesamt" and d["werte"]["kennziffer"] == "12051000"
    assert d["werte"]["zeitbezug"] == 2022 and d["werte"]["wert"] == 72000.0
    assert d["geom"] == ("gebiet", "12051000")


def test_inkar_langform_neuester_und_alle_indikatoren(tmp_path, monkeypatch):
    """Langform mit `indikatoren: alle` und `zeitbezug: neuester`: alle Kürzel der Gemeinden, je Reihe nur das
    jüngste Jahr."""
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)
    ablage = _inkar_zip(tmp_path, ZEILEN)
    cfg = _inkar_cfg(ablage, form="lang", zeitbezug="neuester", indikatoren="alle")
    ds = list(quellen.inkar(cfg, Protokoll()))
    jahre = {(d["werte"]["kennziffer"], d["werte"]["kuerzel"]): d["werte"]["zeitbezug"] for d in ds}
    assert jahre == {("12051000", "xbev"): 2023, ("12051000", "q_bev_fl"): 2023,
                     ("12054000", "xbev"): 2023, ("12054000", "q_bev_fl"): 2023, ("12054000", "alo"): 2023}


def test_inkar_neuester_je_reihe_mit_indikator(tmp_path, monkeypatch):
    """INKAR 2025 führt unter einem Kürzel mehrere Indikatoren im selben Bereich (a_bb_4G in LRB:
    Arbeitslosigkeit, Bevölkerung …, beispielberichte/inkar-schluessel/). Mit zeitbezug: neuester fielen
    sie bisher auf das jüngste Jahr einer einzigen Reihe zusammen; jetzt zählt der Quellschlüssel
    ohne Jahr."""
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)
    ablage = _inkar_zip(tmp_path, [
        "LRB;9;a_bb_4G;Arbeitslosigkeit;Gemeinden;12051000;Brandenburg an der Havel;2022;5,0\n",
        "LRB;9;a_bb_4G;Arbeitslosigkeit;Gemeinden;12051000;Brandenburg an der Havel;2023;5,5\n",
        "LRB;9;a_bb_4G;Bevölkerung;Gemeinden;12051000;Brandenburg an der Havel;2021;72000\n",
    ])
    cfg = _inkar_cfg(ablage, form="lang", zeitbezug="neuester", indikatoren="alle")
    ds = list(quellen.inkar(cfg, Protokoll()))
    assert sorted(d["objekt_id"] for d in ds) == [
        "12051000|LRB|a_bb_4G|Arbeitslosigkeit|2023", "12051000|LRB|a_bb_4G|Bevölkerung|2021"]


def test_uebersprungenes_objekt_macht_den_abruf_unvollstaendig(monkeypatch):
    """Antwort 52: Löschen nur bei vollständigem Abruf. Ein übersprungenes Objekt sperrt das Löschen."""
    from pipeline import waechter
    _ogc(monkeypatch, {f"{BASIS}/queryables": {"properties": {"ags": {}}},
                       f"{BASIS}/items": {"features": [_feat("12051000", "Brandenburg"),
                                                        {"type": "Feature", "properties": {"ags": ""},
                                                         "geometry": None}], "links": []}})
    prot = Protokoll()
    list(quellen.ogcapi({"url": BASIS, "id_feld": "ags"}, prot))
    assert prot.unvollstaendig and not waechter.loeschen_erlaubt(prot)
    assert waechter.loeschen_erlaubt(Protokoll())


@pytest.mark.parametrize("art", ["konfiguration", "umgebung"])
def test_inkar_abgelegte_datei_ohne_jeden_netzabruf(tmp_path, monkeypatch, art):
    """E48: robots.txt von www.bbr-server.de sperrt automatische Abrufe (Disallow: /). Mit abgelegter Datei
    (`datei` oder PIPELINE_INKAR_DATEI, Antwort 33) geht keine Anfrage an den Rechner: kein GET, keine
    HEAD-Suche nach dem jüngsten Jahr (`jahr: neuester`), keine Nachfrage mit If-Modified-Since."""
    anfragen = []

    def gesperrt(*a, **k):
        anfragen.append(a)
        raise AssertionError(f"Netzabruf: {a}")
    monkeypatch.setattr(quellen.requests, "get", gesperrt)
    monkeypatch.setattr(quellen.requests, "head", gesperrt)
    ablage = _inkar_zip(tmp_path, ZEILEN)
    zip_ = ablage / "inkar_2025.zip"
    cfg = _inkar_cfg(tmp_path / "anderer-cache", url="https://www.bbr-server.de/imagemap/inkar/download/"
                     "inkar_{jahr}.zip", jahr="neuester")
    if art == "konfiguration":
        cfg["datei"] = str(zip_)
    else:
        monkeypatch.setenv("PIPELINE_INKAR_DATEI", str(zip_))
    prot = Protokoll()
    ds = {d["objekt_id"]: d for d in quellen.inkar(cfg, prot)}
    assert set(ds) == {"12051000", "12054000"} and anfragen == []
    assert prot.info["datei"]["abgelegt"] is True and prot.info["datei"]["name"] == "inkar_2025.zip"
    assert any("Abgelegte Datei, kein Abruf" in h for h in prot.hinweise)
    assert not (tmp_path / "anderer-cache").exists()


def test_inkar_abgelegte_datei_fehlt(tmp_path, monkeypatch):
    """Zeigt `datei` auf eine fehlende Datei, bricht die Quelle mit klarer Meldung ab, ohne auf einen
    Netzabruf auszuweichen."""
    monkeypatch.setattr(quellen.requests, "head", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a)))
    cfg = _inkar_cfg(tmp_path, datei=str(tmp_path / "fehlt.zip"))
    with pytest.raises(QuellenFehler, match="Abgelegte INKAR-Datei fehlt"):
        list(quellen.inkar(cfg, Protokoll()))


def test_ziele_ohne_inkar_rechner_bei_abgelegter_datei(monkeypatch):
    """--ziele nennt den INKAR-Rechner nur, wenn er wirklich abgerufen wird: nicht bei abgelegter Datei
    (Konfiguration oder Umgebung) und nie bei einem per robots.txt gesperrten Rechner (E48)."""
    from pipeline import laden
    cfg = {"quellen": {"inkar": {"typ": "inkar", "url": "https://bbr.example/x/inkar_{jahr}.zip"}}}
    assert laden.ziele(cfg) == ["bbr.example:443"]
    # Prüfung nach E48: ein per robots.txt gesperrter Rechner steht nie in --ziele
    gesperrt = {"quellen": {"inkar": {"typ": "inkar", "url": "https://www.bbr-server.de/x/inkar_{jahr}.zip"}}}
    assert laden.ziele(gesperrt) == []
    monkeypatch.setenv("PIPELINE_INKAR_DATEI", "/app/inkar/inkar_2025.zip")
    assert laden.ziele(cfg) == []
    monkeypatch.delenv("PIPELINE_INKAR_DATEI")
    cfg["quellen"]["inkar"]["datei"] = "/app/inkar/inkar_2025.zip"
    assert laden.ziele(cfg) == []


# --- E50: INKAR per URL mit benannter Freigabe (Befund A1), Zeilen syntaktisch geprüft (K1) -------------

def _ausgeliefert(konfig: str) -> list[dict]:
    """Die INKAR-Quellen der mitgelieferten Konfiguration `konfig` (Dateiname unter config/), wie
    ausgeliefert."""
    from pathlib import Path

    import yaml
    datei = Path(__file__).resolve().parent.parent / "config" / konfig
    return [c for c in yaml.safe_load(datei.read_text(encoding="utf-8"))["quellen"].values()
            if c.get("typ") == "inkar"]


def _bbsr_attrappe(monkeypatch, inhalt: bytes, jahr: int = 2025) -> list[tuple[str, str]]:
    """Ersetzt requests.head und requests.get durch eine Attrappe des BBSR-Servers: HEAD liefert 200 nur für
    die Datei des Jahrs `jahr`, GET liefert `inhalt`. Rückgabe: Liste der Anfragen (Methode, Adresse), die der
    Test auswertet. www.bbr-server.de wird nie wirklich abgerufen (E48, E50)."""
    anfragen = []

    def head(url, **k):
        anfragen.append(("HEAD", url))
        return Antwort(status=200 if url.endswith(f"inkar_{jahr}.zip") else 404)

    def get(url, **k):
        anfragen.append(("GET", url))
        return Antwort(inhalt, kopf={"Last-Modified": "Wed, 13 Aug 2025 12:59:06 GMT"})
    monkeypatch.setattr(quellen.requests, "head", head)
    monkeypatch.setattr(quellen.requests, "get", get)
    return anfragen


def _inkar_zip_bytes(tmp_path, zeilen: list[str]) -> bytes:
    """INKAR-ZIP mit Kopfzeile und den Datenzeilen als Bytes, für die Attrappe des Downloads."""
    datei = _zip(tmp_path / "attrappe.zip", {"inkar_2025.csv": KOPF + "".join(zeilen), "Readme.txt": "x"})
    return datei.read_bytes()


# Je eine Zeile für die fünf Kürzel der mitgelieferten Konfiguration (erfundene Werte, Gemeinde in
# Brandenburg)
FUENF = [f"Bev;{i};{k};Indikator {k};Gemeinden;12054000;Potsdam;2023;{i},5\n"
         for i, k in enumerate(["xbev", "q_bev_fl", "e5_bev", "q_pendlersaldo", "alo"], 1)]


@pytest.mark.parametrize("konfig", ["quellen.yaml", "deutschland.yaml"])
def test_ausgelieferte_inkar_quelle_ruft_per_url_ab_mit_sichtbarer_freigabe(tmp_path, monkeypatch, konfig):
    """E50, Befund A1 (Antwort 33: „Der Abruf der INKAR-Daten erfolgt automatisch per URL“): Die ausgelieferte
    Konfiguration lädt INKAR ohne abgelegte Datei per URL. Der Rechner steht weiter in ROBOTS_GESPERRT; die
    Quelle ruft ihn nur mit ihrer benannten Freigabe (robots_freigabe) ab, und die Freigabe steht im
    Protokoll (Warnung und info). Der BBSR-Server ist eine Attrappe; abgefragt wird nur www.bbr-server.de."""
    monkeypatch.delenv("PIPELINE_INKAR_DATEI", raising=False)
    anfragen = _bbsr_attrappe(monkeypatch, _inkar_zip_bytes(tmp_path, FUENF))
    (cfg,) = _ausgeliefert(konfig)
    assert "www.bbr-server.de" in cfg["url"] and not cfg.get("datei")
    prot = Protokoll()
    ds = list(quellen.inkar({**cfg, "cache": str(tmp_path / "cache")}, prot))
    assert len(ds) == 5 and not prot.unvollstaendig and "fehlende_felder" not in prot.info
    assert anfragen and {quellen.urlsplit(u).hostname for _, u in anfragen} == {"www.bbr-server.de"}
    assert ("GET", "https://www.bbr-server.de/imagemap/inkar/download/inkar_2025.zip") in anfragen
    frei = prot.info["robots_freigabe"]
    assert frei["rechner"] == "www.bbr-server.de" and "Antwort 33" in frei["grund"]
    assert [w for w in prot.warnungen if "robots_freigabe" in w and "Antwort 33" in w]


@pytest.mark.parametrize("konfig", ["quellen.yaml", "deutschland.yaml"])
def test_ohne_freigabe_bleibt_inkar_gesperrt(tmp_path, monkeypatch, konfig):
    """E50: Ohne robots_freigabe (oder mit einer leeren) bleibt der gesperrte Rechner gesperrt: QuellenFehler
    vor jeder Verbindung, kein HEAD, kein GET (wie seit der Prüfung nach E48)."""
    monkeypatch.delenv("PIPELINE_INKAR_DATEI", raising=False)
    anfragen = _bbsr_attrappe(monkeypatch, b"")
    (cfg,) = _ausgeliefert(konfig)
    for frei in ({}, {"robots_freigabe": ""}, {"robots_freigabe": "   "}, {"robots_freigabe": True},
                 {"robots_freigabe": ["Grund"]}):
        ohne = {k: v for k, v in cfg.items() if k != "robots_freigabe"} | frei
        with pytest.raises(QuellenFehler, match="robots.txt.*robots_freigabe"):
            list(quellen.inkar({**ohne, "cache": str(tmp_path)}, Protokoll()))
    assert anfragen == []


def test_ausgelieferte_konfigurationen_haben_genau_die_inkar_freigabe():
    """E50: Die mitgelieferten Konfigurationen setzen robots_freigabe nur für INKAR (www.bbr-server.de), mit
    dem Grund aus Antwort 33; keine andere Quelle hebt eine Sperre auf."""
    from pathlib import Path

    import yaml
    for datei in sorted((Path(__file__).resolve().parent.parent / "config").glob("*.yaml")):
        for name, q in yaml.safe_load(datei.read_text(encoding="utf-8"))["quellen"].items():
            if q.get("typ") == "inkar":
                assert quellen.robots_freigabe(q) and "Antwort 33" in q["robots_freigabe"], (datei, name)
                assert quellen.urlsplit(q["url"]).hostname == "www.bbr-server.de"
            else:
                assert "robots_freigabe" not in q, (datei, name)


def test_freigabe_gilt_nur_fuer_den_rechner_der_quelle(monkeypatch):
    """E50: Die Freigabe gilt nur für den Rechner der eigenen Adresse (url) und nur für diese Quelle: Ein
    anderer gesperrter Rechner bleibt in derselben Quelle gesperrt, und eine Quelle ohne Freigabe kann den
    freigegebenen Rechner nicht abrufen."""
    mit = {"url": "https://www.bbr-server.de/imagemap/inkar/download/inkar_{jahr}.zip",
           "robots_freigabe": "Vorgabe des Auftraggebers (Test)"}
    prot = Protokoll()
    quellen.schema_pruefen("https://www.bbr-server.de/imagemap/inkar/download/inkar_2025.zip", mit, prot)
    assert prot.info["robots_freigabe"]["rechner"] == "www.bbr-server.de"
    for url, cfg in (("https://www.regionalstatistik.de/genesis/online", mit),
                     ("https://www.statistik-berlin-brandenburg.de/scrivito/a.xlsx", mit),
                     ("https://www.bbr-server.de/imagemap/inkar/download/inkar_2025.zip",
                      {"url": "https://andere.example/x.zip"}),
                     ("https://www.bbr-server.de/imagemap/inkar/download/inkar_2025.zip",
                      {"url": "https://andere.example/x.zip", "robots_freigabe": "fremd"})):
        with pytest.raises(QuellenFehler, match="robots.txt"):
            quellen.schema_pruefen(url, cfg, Protokoll())


def test_abgelegte_datei_hat_vorrang_freigabe_ungenutzt(tmp_path, monkeypatch):
    """E50: Mit abgelegter Datei (`datei` oder PIPELINE_INKAR_DATEI) ruft die Quelle trotz Freigabe nichts ab;
    das Protokoll sagt, dass die Freigabe nicht genutzt wurde, und führt sie nicht als genutzt."""
    anfragen = _bbsr_attrappe(monkeypatch, b"")
    ablage = _inkar_zip(tmp_path, FUENF)
    (cfg,) = _ausgeliefert("quellen.yaml")
    monkeypatch.setenv("PIPELINE_INKAR_DATEI", str(ablage / "inkar_2025.zip"))
    prot = Protokoll()
    assert len(list(quellen.inkar({**cfg, "cache": str(tmp_path / "c")}, prot))) == 5
    assert anfragen == [] and "robots_freigabe" not in prot.info
    assert any("robots_freigabe" in h and "nicht genutzt" in h for h in prot.hinweise)


@pytest.mark.parametrize("form", ["breit", "lang"])
@pytest.mark.parametrize("zeile, grund", [
    ('Bev;9;xbev;Bevölkerung gesamt;"Gemeinden";"12053000";Frankfurt (Oder);2023;57000,00\n', None),
    ("Bev;9;xbev;Bevölkerung gesamt;Gemeinden;1205300;Frankfurt (Oder);2023;57000,00\n", "Kennziffer"),
    ("Bev;9;xbev;Bevölkerung gesamt;Gemeinden;12O53000;Frankfurt (Oder);2023;57000,00\n", "Kennziffer"),
    ("Bev;9;xbev;Bevölkerung gesamt; Gemeinden;12053000;Frankfurt (Oder);2023;57000,00\n", "Raumbezug"),
    ("Bev;9;xbev;Bevölkerung gesamt;GEMEINDEN;12053000;Frankfurt (Oder);2023;57000,00\n", "Raumbezug"),
    ("Bev;9;;Bevölkerung gesamt;Gemeinden;12053000;Frankfurt (Oder);2023;57000,00\n", "Pflichtfeld"),
    ("Bev;9;xbev;Bevölkerung gesamt;Gemeinden;;Frankfurt (Oder);2023;57000,00\n", "Pflichtfeld"),
    ("Bev;9;xbev;Bevölkerung gesamt;Gemeinden;12053000;Frankfurt (Oder);2023;57000,00;x\n", "Spalten"),
    ('Bev;9;xbev;"Bevölkerung; gesamt";Gemeinden;12053000;Frankfurt;2023;57000,00\n', None),
], ids=["zitiert", "kurz", "buchstabe", "rand", "gross", "ohne_kuerzel", "ohne_kennziffer", "lang",
        "semikolon_im_feld"])
def test_inkar_zeilen_syntaktisch_vor_dem_filter(tmp_path, monkeypatch, form, zeile, grund):
    """E50, Befund K1: Der Adapter zerlegt jede Zeile mit dem CSV-Parser, bevor er nach Raumbezug, Kennziffer
    und Kürzel filtert. Zulässig zitierte Felder werden gelesen (bis E49 übersprang der Vorfilter
    ";Gemeinden;" die Zeile still). Eine Zeile unserer Raumebene, die sich nicht sicher deuten lässt
    (Raumbezug nur nach Bereinigung, Kennziffer mit falscher Länge oder Buchstabe, leeres Pflichtfeld, falsche
    Spaltenzahl), wird nicht übernommen und macht den Abruf unvollständig: Warnung mit Zeilennummer, nichts
    wird gelöscht. Bis E49 fielen solche Zeilen still weg, und ihr bisheriger Wert konnte gelöscht werden."""
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)   # Datei liegt im Cache
    ablage = _inkar_zip(tmp_path, [*ZEILEN, zeile])
    cfg = _inkar_cfg(ablage, indikatoren=["xbev", "q_bev_fl"], zeitbezug="neuester",
                     **({"form": "lang"} if form == "lang" else {}))
    prot = Protokoll()
    ds = list(quellen.inkar(cfg, prot))
    kennziffern = {d["werte"]["kennziffer"] if form == "lang" else d["objekt_id"] for d in ds}
    if grund is None:
        assert "12053000" in kennziffern and not prot.unvollstaendig, prot.warnungen
    else:
        assert "12053000" not in kennziffern and prot.unvollstaendig
        (w,) = [w for w in prot.warnungen if grund in w]
        assert "Zeile 11" in w and "nichts wird gelöscht" in w
    assert {"12051000", "12054000"} <= kennziffern


def test_inkar_fremde_ebenen_und_laender_bleiben_stumm(tmp_path, monkeypatch):
    """E50, Gegenprobe zu K1: Wohlgeformte Zeilen anderer Raumebenen, anderer Länder und nicht angeforderter
    Kürzel fallen ohne Warnung heraus; der Abruf bleibt vollständig (die mitgelieferten Testzeilen)."""
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)   # Datei liegt im Cache
    ablage = _inkar_zip(tmp_path, ZEILEN)
    for form in ({}, {"form": "lang", "zeitbezug": "alle"}):
        prot = Protokoll()
        assert list(quellen.inkar(_inkar_cfg(ablage, **form), prot))
        assert not prot.unvollstaendig and not prot.warnungen


@pytest.mark.parametrize("aenderung, text", [
    ({"zeitbezug": "alle"}, "zeitbezug"),
    ({"zeitbezug": "2023x"}, "zeitbezug"),
    ({"raumbezug": None}, "raumbezug"),
    ({"url": None}, "url"),
], ids=["alle_breit", "kein_jahr", "ohne_raumbezug", "ohne_url"])
def test_inkar_konfigurationsfehler_mit_klartext(tmp_path, monkeypatch, aenderung, text):
    """E50, Codefehler aus E49 (_inkar_lesen): Ein falscher zeitbezug in der breiten Form, ein fehlender
    raumbezug oder eine fehlende url ohne abgelegte Datei enden als QuellenFehler mit Klartext, nicht als
    ValueError aus int() oder KeyError."""
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)   # Datei liegt im Cache
    ablage = _inkar_zip(tmp_path, ZEILEN)
    cfg = {k: v for k, v in _inkar_cfg(ablage).items() if aenderung.get(k, "") is not None}
    cfg.update({k: v for k, v in aenderung.items() if v is not None})
    with pytest.raises(QuellenFehler, match=text):
        list(quellen.inkar(cfg, Protokoll()))


def test_inkar_leerer_csv_eintrag(tmp_path, monkeypatch):
    """E50, Codefehler aus E49: Ein leerer CSV-Eintrag (nicht einmal ein Kopf) ist ein QuellenFehler mit
    Klartext, kein RuntimeError („generator raised StopIteration“)."""
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)   # Datei liegt im Cache
    ablage = tmp_path / "cache"
    ablage.mkdir()
    _zip(ablage / "inkar_2025.zip", {"inkar_2025.csv": ""})
    with pytest.raises(QuellenFehler, match="leer"):
        list(quellen.inkar(_inkar_cfg(ablage), Protokoll()))


@pytest.mark.parametrize("url", ["https://bbr.example/daten/..", "https://bbr.example/daten/",
                                 "https://bbr.example/daten/.versteckt.zip", "https://bbr.example/a%2F..%2Fb.zip"])
def test_cachename_wird_vor_dem_abruf_geprueft(tmp_path, monkeypatch, url):
    """E50, Codefehler aus E49: Der Dateiname im Cache kommt aus der Adresse. Bei INKAR und GeoJSON wird er
    wie bei XLSX geprüft (einfacher Name, passende Endung), bevor etwas abgerufen wird; „..“ zeigte bis E49
    auf den Ordner über dem Cache, ein leerer Name auf den Cache selbst."""
    _bbsr_attrappe(monkeypatch, b"")
    anfragen = []
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: anfragen.append(a))
    with pytest.raises(QuellenFehler, match="Dateiname"):
        list(quellen.inkar(_inkar_cfg(tmp_path, url=url), Protokoll()))
    with pytest.raises(QuellenFehler, match="Dateiname"):
        list(quellen.geojson({"url": url, "id_feld": "id", "cache": str(tmp_path)}, Protokoll()))
    assert anfragen == []


def test_datei_abrufen_unlesbares_last_modified(tmp_path, monkeypatch):
    """E50, Codefehler aus E49: Ein unlesbares Last-Modified des Servers bricht den Abruf nicht mehr mit
    ValueError ab, nachdem die Datei schon an ihrem Platz liegt; die Datei bleibt, die Änderungszeit ist die
    Abrufzeit, ein Hinweis nennt den Kopf."""
    monkeypatch.setattr(quellen.requests, "get",
                        lambda url, **k: Antwort(b"ZIPDATEN", kopf={"Last-Modified": "gestern abend"}))
    ziel = tmp_path / "inkar_2025.zip"
    prot = Protokoll()
    assert quellen.datei_abrufen("https://bbr.example/inkar_2025.zip", ziel, {}, prot) is True
    assert ziel.read_bytes() == b"ZIPDATEN"
    assert any("Last-Modified" in h and "unlesbar" in h for h in prot.hinweise)


def test_zeitbudget_greift_im_inkar_durchlauf(tmp_path, monkeypatch):
    """E50, Befund W6: Die Langform mit `neuester` liefert erst nach der ganzen Datei Datensätze. Das
    Zeitbudget wird deshalb auch zwischen den Zeilen geprüft, nicht nur bei jedem Datensatz (Uhr als
    Attrappe)."""
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)   # Datei liegt im Cache
    ablage = _inkar_zip(tmp_path, ZEILEN * 20000)
    prot = Protokoll()
    uhr = iter(range(0, 10**9, 60))   # jede Abfrage der Uhr: eine Minute später
    prot.frist_setzen(1, uhr=lambda: next(uhr))
    with pytest.raises(quellen.ZeitbudgetUeberschritten, match="Zeitbudget"):
        list(quellen.inkar(_inkar_cfg(ablage, form="lang", zeitbezug="neuester", max_packrate=10**6), prot))


# --- E50, Nachprüfung (Prüfer zu E50, 06.11.2026) -------------------------------------------------------

# Vier Gemeinde-Zeilen; ein einzelnes Anführungszeichen am Anfang eines Felds der ersten Zeile öffnet ein
# Feld, das erst in der dritten Zeile endet (erfundene Werte). Ohne Prüfung der Zeilenzahl ergab das einen
# Datensatz mit genau neun Feldern: 12051000 mit dem Wert 3 von Cottbus, 12054000 und 12052000 fehlten still
_ZUSAMMENGEZOGEN = {
    "name": ['Bev;1;xbev;Bevölkerung gesamt;Gemeinden;12051000;"Brandenburg;2023;1\n',
             "Bev;1;xbev;Bevölkerung gesamt;Gemeinden;12054000;Potsdam;2023;2\n",
             'Bev;1;xbev;Bevölkerung gesamt;Gemeinden;12052000;Cottbus";2023;3\n',
             "Bev;1;xbev;Bevölkerung gesamt;Gemeinden;12053000;Frankfurt (Oder);2023;4\n"],
    "wert": ['Bev;1;xbev;Bevölkerung gesamt;Gemeinden;12051000;Brandenburg;2023;"1\n',
             "Bev;1;xbev;Bevölkerung gesamt;Gemeinden;12054000;Potsdam;2023;2\n",
             'Bev;1;xbev;Bevölkerung gesamt;Gemeinden;12052000;Cottbus;2023;3"\n',
             "Bev;1;xbev;Bevölkerung gesamt;Gemeinden;12053000;Frankfurt (Oder);2023;4\n"],
}


@pytest.mark.parametrize("form", ["breit", "lang"])
@pytest.mark.parametrize("spalte", ["name", "wert"])
def test_inkar_feld_ueber_mehrere_zeilen_sperrt_das_loeschen(tmp_path, monkeypatch, form, spalte):
    """Nachprüfung zu E50, Befund K1 (kritisch): Seit E50 liest ein csv.reader den ganzen Strom. Ein einzelnes
    Anführungszeichen am Anfang eines Felds zog bis zum nächsten Anführungszeichen mehrere Zeilen zu einem
    Datensatz zusammen; lag das schließende in derselben oder der letzten Spalte, hatte er genau die Breite
    des Kopfs und bestand jede Prüfung. 12051000 bekam den Wert von Cottbus, 12054000 und 12052000 fehlten,
    ohne Warnung und mit vollständigem Abruf (ihre Zeilen durften gelöscht werden). Jetzt ist ein Datensatz
    über mehr als eine Zeile der Datei nicht deutbar, gleich welcher Raumbezug: nicht übernommen, Warnung mit
    der ersten Zeilennummer, Abruf unvollständig (nichts wird gelöscht)."""
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)   # Datei liegt im Cache
    ablage = _inkar_zip(tmp_path, _ZUSAMMENGEZOGEN[spalte])
    cfg = _inkar_cfg(ablage, indikatoren=["xbev"], zeitbezug="neuester",
                     **({"form": "lang"} if form == "lang" else {}))
    prot = Protokoll()
    ds = list(quellen.inkar(cfg, prot))
    kennziffern = {d["werte"]["kennziffer"] if form == "lang" else d["objekt_id"] for d in ds}
    assert kennziffern == {"12053000"}
    assert prot.unvollstaendig
    (w,) = [w for w in prot.warnungen if "mehrere Zeilen" in w]
    assert "Zeile 2" in w and "nichts wird gelöscht" in w


def test_inkar_meldung_nennt_nur_den_dateinamen(tmp_path, monkeypatch):
    """Nachprüfung zu E50 (waechter, Pfade im Meldungsentwurf): Die Meldung „Abgelegte INKAR-Datei fehlt“
    nennt nur den Dateinamen, nicht den Pfad. Ein relativer Pfad oder einer mit Leerzeichen gelangte sonst in
    den Entwurf an den Anbieter, weil das allgemeine Muster ihn nicht ganz erfasst."""
    monkeypatch.setenv("PIPELINE_INKAR_DATEI", str(tmp_path / "geo daten" / "inkar_2025.zip"))
    with pytest.raises(QuellenFehler, match="fehlt: inkar_2025.zip") as e:
        list(quellen.inkar(_inkar_cfg(tmp_path), Protokoll()))
    assert "geo daten" not in str(e.value) and str(tmp_path) not in str(e.value)


def test_freigabe_nicht_ueber_anderen_rechnernamen_erschleichbar(monkeypatch):
    """Nachprüfung zu E50, Befund zu freigabe_fuer: urlsplit und urllib3 lesen den Rechner von
    `https://www.regionalstatistik.de\\@www.bbr-server.de/genesis` verschieden (urlsplit: www.bbr-server.de,
    requests verbindet zu www.regionalstatistik.de). Bis zur Nachprüfung hob die Freigabe der INKAR-Quelle die
    Sperre des anderen Rechners auf. Jetzt gilt überall der Rechner, den requests anwählt, und eine Adresse
    mit Rückstrich oder „@“ vor dem Rechner wird vor jeder Verbindung abgelehnt. Kein Abruf (requests als
    Attrappe, die jeden Aufruf ablehnt)."""
    monkeypatch.setattr(quellen.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a)))
    cfg = {"url": "https://www.bbr-server.de/imagemap/inkar/download/inkar_{jahr}.zip",
           "robots_freigabe": "Vorgabe des Auftraggebers (Test)"}
    for url in ("https://www.regionalstatistik.de\\@www.bbr-server.de/genesis",
                "https://www.regionalstatistik.de%5C@www.bbr-server.de/genesis",
                "https://nutzer@www.bbr-server.de/imagemap/inkar/download/inkar_2025.zip"):
        assert quellen.freigabe_fuer(url, cfg) is None, url
        with pytest.raises(QuellenFehler):
            quellen.schema_pruefen(url, cfg, Protokoll())
        with pytest.raises(QuellenFehler):
            quellen.abrufen(url, None, cfg, Protokoll())
    # Auch als eigene Adresse der Quelle trägt so eine Adresse keine Freigabe
    zweideutig = {"url": "https://www.regionalstatistik.de\\@www.bbr-server.de/x.zip"}
    assert quellen.quell_rechner(zweideutig) is None
    with pytest.raises(QuellenFehler, match="Rückstrich"):
        quellen.rechner_wie_gesendet("https://www.regionalstatistik.de\\@www.bbr-server.de/x")
    assert quellen.rechner_wie_gesendet("https://WWW.BBR-Server.de./a") == "www.bbr-server.de"


def test_freigabe_gilt_fuer_den_ganzen_rechner_der_eigenen_adresse():
    """Nachprüfung zu E50 (Wortlaut der Doku an den Code angeglichen): Eine Freigabe gilt für den ganzen
    Rechner der eigenen Adresse der Quelle, also auch für andere Pfade und Folge-Links auf diesem Rechner, nie
    für einen anderen. Die eigene Adresse ist `url`, sonst `seite`, sonst `pfad`, wenn er eine Adresse ist."""
    cfg = {"url": "https://www.bbr-server.de/imagemap/inkar/download/inkar_{jahr}.zip",
           "robots_freigabe": "T"}
    assert quellen.freigabe_fuer("https://www.bbr-server.de/anderer/pfad?seite=2", cfg) == "T"
    assert quellen.freigabe_fuer("https://WWW.BBR-SERVER.DE./x", cfg) == "T"
    assert quellen.freigabe_fuer("https://www.regionalstatistik.de/x", cfg) is None
    assert quellen.quell_rechner({"pfad": "https://www.bbr-server.de/a.xlsx"}) == "www.bbr-server.de"
    assert quellen.quell_rechner({"pfad": "/app/config/a.xlsx"}) is None


def test_ogcapi_folge_link_mit_anderem_rechner_vor_dem_at(monkeypatch):
    """Nachprüfung zu E50, Pre-existing seit E47 (ogcapi, innere Funktion hole): Ein rel=next
    `https://fremd.example\\@ogc.example/…` bestand die Rechnerprüfung, weil urlsplit ogc.example liest;
    requests verbindet aber zu fremd.example. Jetzt vergleicht hole den Rechner, den requests anwählt, und
    lehnt Adressen mit Rückstrich oder „@“ vor dem Rechner ab; der Link wird nicht abgerufen."""
    weiter = "https://fremd.example\\@ogc.example/datasets/vg/collections/gem/items?offset=1"
    _ogc(monkeypatch, {
        f"{BASIS}/queryables": {"properties": {"ags": {}}},
        f"{BASIS}/items": {"features": [_feat("12051000", "B")], "links": [{"rel": "next", "href": weiter}]},
        "https://fremd.example": AssertionError("fremder Rechner abgerufen"),
    })
    with pytest.raises(QuellenFehler, match="Rechner"):
        list(quellen.ogcapi({"url": BASIS, "id_feld": "ags"}, Protokoll()))


@pytest.mark.parametrize("konfig", ["pruefkonfiguration.yaml", "deutschland.yaml"])
def test_inkar_hat_ein_eigenes_zeitbudget_fuer_den_download(konfig):
    """Nachprüfung zu E50 (Zeitbudget): Im Regelbetrieb zählen der Download von rund 430 MB, das Lesen und das
    Schreiben in dasselbe Zeitbudget; der Standard von 30 Minuten ist an Läufen mit abgelegter Datei bemessen.
    Die INKAR-Quellen mit fünf Kürzeln setzen deshalb ein eigenes, größeres Budget (90 Minuten); seit E51 sind
    das Prüfkonfiguration und deutschland.yaml, die Lieferkonfiguration im Vollumfang hat 240 Minuten
    (test_ausgelieferte_inkar_quelle_im_vollumfang_und_pruefkonfiguration)."""
    (cfg,) = _ausgeliefert(konfig)
    assert cfg["zeitbudget_min"] == 90


# --- E51: Prüfbericht vom 07.11.2026, 03:13 (K2 für INKAR, W2 Vollumfang als Lieferkonfiguration) -----------

@pytest.mark.parametrize("form", ["breit", "lang"])
@pytest.mark.parametrize("zeile", ["Bev;9;xbev;Bevölk\n", "12053000;Frankfurt (Oder);2023;57000,00\n",
                                   ";;;;;;;;;;\n"],
                         ids=["abgeschnitten", "vorn_abgeschnitten", "nur_trenner"])
def test_inkar_zeile_mit_falscher_breite_ist_unlesbar_auch_ohne_raumbezug(tmp_path, monkeypatch, form, zeile):
    """E51, Befund K2 sinngemäß für INKAR: Eine Zeile mit falscher Spaltenzahl war nur unlesbar, wenn ein Feld
    unser Raumbezug sein konnte; eine abgeschnittene Zeile ohne dieses Feld blieb stumm, obwohl sie zu unserer
    Raumebene gehören kann. Die Gesamtdatei hat keinen Kopf- oder Fußblock (INKAR 2025: alle 63 426 864
    Zeilen mit 9 Feldern, keine Leerzeile, gezählt am 07.11.2026 aus der abgelegten Datei). Jetzt ist jede
    nicht leere Zeile mit falscher Spaltenzahl unlesbar, der Abruf unvollständig; Leerzeilen (auch nur aus
    Trennern) bleiben stumm."""
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)   # Datei liegt im Cache
    ablage = _inkar_zip(tmp_path, [*ZEILEN, zeile])
    cfg = _inkar_cfg(ablage, indikatoren=["xbev", "q_bev_fl"], zeitbezug="neuester",
                     **({"form": "lang"} if form == "lang" else {}))
    prot = Protokoll()
    assert list(quellen.inkar(cfg, prot))
    if zeile.strip(";\n"):
        assert prot.unvollstaendig
        (w,) = [w for w in prot.warnungen if "Spalten" in w]
        assert "Zeile 11" in w and "nichts wird gelöscht" in w
    else:
        assert not prot.unvollstaendig and not prot.warnungen, prot.warnungen


def test_ausgelieferte_inkar_quelle_im_vollumfang_und_pruefkonfiguration():
    """E51, Befund W2 (Antwort 33: Umfang „aus den bestehenden Skripten und deren Konfiguration“): Die
    ausgelieferte config/quellen.yaml lädt INKAR im Vollumfang wie der Import der TH, also alle Indikatoren,
    alle Gemeinden Deutschlands, alle Jahre, Raumbezug Gemeinden; Zeitbudget aus dem gemessenen Vollumfang
    (146,5 min) mit Zuschlag. Die bisherige reduzierte Fassung (fünf Kürzel, Brandenburg) ist die ausdrücklich
    benannte Prüfkonfiguration config/pruefkonfiguration.yaml."""
    (voll,) = _ausgeliefert("quellen.yaml")
    assert (voll["indikatoren"], voll["kennziffer_beginnt"], voll["raumbezug"], voll["zeitbezug"],
            voll["form"], voll["kennziffer_stellen"]) == ("alle", "", "Gemeinden", "alle", "lang", 8)
    assert voll["zeitbudget_min"] >= 1.5 * 146.5 and voll.get("karte") is False
    (pruef,) = _ausgeliefert("pruefkonfiguration.yaml")
    assert pruef["indikatoren"] == ["xbev", "q_bev_fl", "e5_bev", "q_pendlersaldo", "alo"]
    assert pruef["kennziffer_beginnt"] == "12" and pruef["zeitbudget_min"] == 90
