"""GeoJSON-Datei als Quelle (Typ geojson, z. B. Eurostat GISCO LAU), ohne Netz und ohne Datenbank.

Der Adapter gehört zur Stufe quellen: er liest die Datei aus dem Cache, Objekt für Objekt, und gibt
Datensätze an ziel weiter (E30). Abgesichert werden das blockweise Lesen (auch über Blockgrenzen und mit
Grenze je Objekt), die Ablehnung fremder Koordinatensysteme, unvollständige Abrufe bei Objekten ohne ID
oder Geometrie (E23, E32), das Anhalten bei fehlenden Feldern (E4) und dass doppelte IDs nicht im Adapter
verworfen werden (E40).
"""
import json

import pytest

from pipeline import quellen
from pipeline.quellen import Protokoll, QuellenFehler


def _feat(i, name="Ort", geom=True):
    """LAU-Objekt nach dem Muster von GISCO: ID DE_<i>, einfache Eigenschaften, eine Liste (keine einfache
    Eigenschaft) und eine Dreiecksfläche; mit geom=False ohne Geometrie."""
    return {"type": "Feature",
            "properties": {"GISCO_ID": f"DE_{i:08d}", "CNTR_CODE": "DE", "LAU_NAME": name,
                           "POP_2024": 100.0 + i, "liste": [1, 2]},
            "geometry": {"type": "Polygon", "coordinates": [[[13, 52], [13.1, 52], [13, 52.1], [13, 52]]]}
            if geom else None}


def _sammlung(feats, crs="urn:ogc:def:crs:EPSG::4326"):
    """FeatureCollection als JSON-Text, mit Angabe des Koordinatensystems; crs=None lässt sie weg."""
    kopf = {"type": "FeatureCollection", "name": "LAU"}
    if crs:
        kopf["crs"] = {"type": "name", "properties": {"name": crs}}
    kopf["features"] = feats
    return json.dumps(kopf, ensure_ascii=False)


def _datei(tmp_path, text, name="lau.geojson"):
    """Schreibt den Text als UTF-8-Datei in tmp_path und gibt den Pfad zurück."""
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_liest_alle_objekte_auch_ueber_blockgrenzen(tmp_path):
    """Auch mit sehr kleinen Leseblöcken (37 Zeichen) kommen alle 50 Objekte vollständig und in ihrer
    Reihenfolge an."""
    feats = [_feat(i, name="Groß Köris" * (i % 5 + 1)) for i in range(50)]
    p = _datei(tmp_path, _sammlung(feats))
    # Kleine Blöcke: fast jedes Objekt liegt über einer Blockgrenze
    gelesen = list(quellen.geojson_objekte(p, 1024 * 1024, block=37))
    assert gelesen == feats


def test_leere_sammlung_und_zeilenumbrueche(tmp_path):
    """Eine leere FeatureCollection liefert keine Objekte, und Zeilenumbrüche zwischen den Objekten stören das
    Lesen nicht."""
    assert list(quellen.geojson_objekte(_datei(tmp_path, _sammlung([])), 1024)) == []
    text = '{"type": "FeatureCollection",\n "features": [\n' + ",\n".join(
        json.dumps(_feat(i)) for i in range(3)) + "\n]\n}\n"
    assert len(list(quellen.geojson_objekte(_datei(tmp_path, text, "b.geojson"), 1024 * 1024))) == 3


def test_kaputtes_json_bricht_ab(tmp_path):
    """Eine mitten im Objekt abgeschnittene Datei bricht mit QuellenFehler ab, statt das angefangene Objekt
    still zu verwerfen."""
    text = _sammlung([_feat(1), _feat(2)])
    p = _datei(tmp_path, text[: len(text) // 2 + 40])  # mitten im zweiten Objekt abgeschnitten
    with pytest.raises(QuellenFehler, match="mitten in einem Objekt|fehlerhaft"):
        list(quellen.geojson_objekte(p, 1024 * 1024, block=64))


def test_objekt_groesser_als_grenze(tmp_path):
    """Ein Objekt, das länger ist als die Grenze je Objekt (hier 1000), bricht mit QuellenFehler ab, statt den
    Lesepuffer unbegrenzt wachsen zu lassen."""
    p = _datei(tmp_path, _sammlung([_feat(1, name="x" * 5000)]))
    with pytest.raises(QuellenFehler, match="größer"):
        list(quellen.geojson_objekte(p, 1000, block=256))


def test_keine_featurecollection(tmp_path):
    """Eine Datei ohne Array `features` (hier ein einzelnes Feature) wird als Quelle abgelehnt."""
    with pytest.raises(QuellenFehler, match="features"):
        list(quellen.geojson_objekte(_datei(tmp_path, '{"type": "Feature"}'), 1024))


def test_anderes_koordinatensystem_wird_abgelehnt(tmp_path):
    """Ein angegebenes Koordinatensystem außer EPSG:4326/CRS84 (hier EPSG:3035) wird abgelehnt; eine Datei
    ohne Angabe gilt als Länge/Breite und wird gelesen (E30)."""
    p = _datei(tmp_path, _sammlung([_feat(1)], crs="urn:ogc:def:crs:EPSG::3035"))
    with pytest.raises(QuellenFehler, match="3035"):
        list(quellen.geojson_objekte(p, 1024 * 1024))
    p = _datei(tmp_path, _sammlung([_feat(1)], crs=None), "ohne.geojson")
    assert len(list(quellen.geojson_objekte(p, 1024 * 1024))) == 1


def _quelle(tmp_path, monkeypatch, feats, **cfg):
    """Führt den Adapter geojson ohne Netz aus: legt die Datei in den Cache, ersetzt datei_abrufen durch einen
    Stellvertreter, der nur den Zielpfad festhält und „nicht neu geladen“ meldet, und gibt Datensätze,
    Protokoll und die Abrufe zurück."""
    _datei(tmp_path, _sammlung(feats), "LAU_RG_01M_2024_4326.geojson")
    abrufe = []
    monkeypatch.setattr(quellen, "datei_abrufen", lambda url, ziel, c, prot: abrufe.append(ziel) or False)
    cfg = {"url": "https://gisco.example/lau/geojson/LAU_RG_01M_2024_4326.geojson", "cache": str(tmp_path),
           "id_feld": "GISCO_ID", **cfg}
    prot = Protokoll()
    return list(quellen.ADAPTER["geojson"](cfg, prot)), prot, abrufe


def test_adapter_liefert_datensaetze_aus_dem_cache(tmp_path, monkeypatch):
    """Der Adapter fragt die Datei unter dem Namen aus der URL im Cache an und liefert je Objekt die ID, die
    umbenannten Felder und die Geometrie als GeoJSON-Text; der Dateiname steht im Protokoll."""
    ds, prot, abrufe = _quelle(tmp_path, monkeypatch, [_feat(1), _feat(2)],
                               felder={"LAU_NAME": "name", "CNTR_CODE": "land"})
    assert abrufe == [tmp_path / "LAU_RG_01M_2024_4326.geojson"]
    assert [d["objekt_id"] for d in ds] == ["DE_00000001", "DE_00000002"]
    assert ds[0]["werte"] == {"name": "Ort", "land": "DE"}
    art, text = ds[0]["geom"]
    assert art == "geojson" and json.loads(text)["type"] == "Polygon"
    assert not prot.unvollstaendig and prot.info["datei"]["name"] == "LAU_RG_01M_2024_4326.geojson"


def test_adapter_ohne_felder_nimmt_einfache_eigenschaften(tmp_path, monkeypatch):
    """Ohne `felder` übernimmt der Adapter alle einfachen Eigenschaften unter ihrem Namen, Listen und Objekte
    nicht."""
    ds, _, _ = _quelle(tmp_path, monkeypatch, [_feat(1)])
    assert "liste" not in ds[0]["werte"] and ds[0]["werte"]["POP_2024"] == 101.0


def test_adapter_fehlende_id_oder_geometrie_macht_unvollstaendig(tmp_path, monkeypatch):
    """Objekte ohne Geometrie oder mit leerer ID werden übersprungen und machen den Abruf unvollständig, damit
    nichts gelöscht wird (E23, E32)."""
    ohne_id = _feat(3)
    ohne_id["properties"]["GISCO_ID"] = ""
    ds, prot, _ = _quelle(tmp_path, monkeypatch, [_feat(1), _feat(2, geom=False), ohne_id])
    assert [d["objekt_id"] for d in ds] == ["DE_00000001"]
    assert prot.unvollstaendig


def test_adapter_doppelte_id_geht_ans_ziel_statt_das_erste_zaehlt(tmp_path, monkeypatch):
    """E40: Der Adapter verwirft keine zweite Fassung derselben ID; ob sie gleich ist (einmal übernehmen)
    oder sich widerspricht (auslassen, bisheriger Stand bleibt), entscheidet ziel.neu_bilden."""
    ds, prot, _ = _quelle(tmp_path, monkeypatch, [_feat(1), _feat(1, name="anders")])
    assert [d["werte"]["LAU_NAME"] for d in ds] == ["Ort", "anders"]
    assert any("schon gelesener ID weitergegeben" in h for h in prot.hinweise) and not prot.warnungen


def test_adapter_fehlendes_feld_haelt_an(tmp_path, monkeypatch):
    """Fehlt ein konfiguriertes Feld schon im ersten Objekt, liefert der Adapter nichts und meldet das Feld
    unter fehlende_felder; laden hält die Quelle dann an (E4)."""
    ds, prot, _ = _quelle(tmp_path, monkeypatch, [_feat(1)], felder={"NUTS3": "nuts"})
    assert ds == [] and prot.info.get("fehlende_felder") == ["NUTS3"]


# --- E50: Koordinatensystem auch nach dem Array und je Objekt (Codefehler aus E49) ---------------------

def test_koordinatensystem_nach_den_objekten_wird_abgelehnt(tmp_path):
    """E50, Codefehler aus E49: JSON legt die Reihenfolge der Mitglieder nicht fest; "crs" darf nach
    "features" stehen. Bis E49 prüfte der Adapter es nur davor und las eine Datei in EPSG:3035 als
    Länge/Breite. Jetzt wird auch der Rest der Sammlung nach dem Array geprüft (die Quelle bricht ab, ihre
    Transaktion wird zurückgerollt) und ein "crs" in einem Objekt oder seiner Geometrie (GeoJSON 2008)."""
    hinten = ('{"type": "FeatureCollection", "features": [' + json.dumps(_feat(1)) + '], '
              '"crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3035"}}}')
    with pytest.raises(QuellenFehler, match="3035"):
        list(quellen.geojson_objekte(_datei(tmp_path, hinten), 1024 * 1024, block=16))
    objekt = {**_feat(2), "crs": {"type": "name", "properties": {"name": "EPSG:25833"}}}
    with pytest.raises(QuellenFehler, match="25833"):
        list(quellen.geojson_objekte(_datei(tmp_path, _sammlung([objekt]), "o.geojson"), 1024 * 1024))
    geom = _feat(3)
    geom["geometry"]["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
    with pytest.raises(QuellenFehler, match="3857"):
        list(quellen.geojson_objekte(_datei(tmp_path, _sammlung([geom]), "g.geojson"), 1024 * 1024))
    # Gegenprobe: Länge/Breite hinten, ein weiteres Mitglied hinten, kein "crs"
    gut = ('{"type": "FeatureCollection", "features": [' + json.dumps(_feat(4)) + '], "name": "LAU", '
           '"crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}}\n')
    datei = _datei(tmp_path, gut, "gut.geojson")
    assert len(list(quellen.geojson_objekte(datei, 1024 * 1024, block=16))) == 1


def test_crs_nicht_als_name_wird_abgelehnt(tmp_path):
    """E50: Ein "crs", das sich nicht als Name eines erlaubten Systems lesen lässt (etwa type link), wird
    abgelehnt statt still als Länge/Breite gelesen."""
    text = json.dumps({"type": "FeatureCollection", "features": [_feat(1)],
                       "crs": {"type": "link", "properties": {"href": "https://example.org/crs"}}})
    with pytest.raises(QuellenFehler, match="crs"):
        list(quellen.geojson_objekte(_datei(tmp_path, text), 1024 * 1024))
