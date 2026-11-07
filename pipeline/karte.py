"""Änderungskarte je Lauf: zeigt auf einer Karte, was der Lauf je Quelle neu angelegt, geändert und
gelöscht hat (unverändert blass im Hintergrund). Eine einzelne HTML-Datei neben dem Bericht.

Leaflet 1.9.4 (BSD-2-Clause) liegt im Repository (pipeline/vendor/) und steht eingebettet in der Seite;
ohne weitere Einstellung lädt die Seite nichts nach, auch keine Kartenkacheln. Hintergrundkarten von
Dritten (basemap.de des BKG, Luftbild der LGB) nur, wenn die Konfiguration sie ausdrücklich nennt:

    karte:
      hintergrund: [basemap, luftbild]

`karte: false` (oben in der Konfiguration) schaltet die Karte ganz ab: keine Datei. `karte: false` bei
einer Quelle lässt nur deren Objekte weg. Inhalte aus den Quellen werden nur als Text in die Seite
gesetzt, nie als HTML.

Stellung im Ablauf: Die Objekte liest `laden.quelle_laden` je Quelle mit `objekte_lesen` in der
Transaktion der Quelle, nach der Löschentscheidung und vor dem Schreiben in die Zieltabelle (E37), also
aus dem Zwischenstand `vergleich` von pipeline.ziel. Am Ende des Laufs schreibt `laden._lauf` mit
`schreiben` die Seite <lauf>-karte.html (im Probelauf <lauf>-probelauf-karte.html). Das Modul ruft
selbst kein Netz ab.

Wichtige Entscheidungen:
- Status nicht nur über die Farbe: Strichmuster für geändert und gelöscht, Farben nach Okabe und Ito (E12).
- Leaflet im Repository, keine Drittverbindungen ohne ausdrückliche Einstellung (E38).
- Datenblöcke so maskiert, dass Werte der Quelle den HTML-Parser nicht aus dem Tritt bringen (E39).
- Ergebnis je Quelle wie überall über `verzeichnis.ergebnis`: unvollständig ist nicht „ok“ (E44, F4).
- Die Karte ist eine Übersicht: höchstens `karte_max_objekte` Objekte je Quelle (docs/betrieb.md).
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

from . import sprache
from .verzeichnis import ergebnis

# Leaflet liegt im Paket (pipeline/vendor/); die Seite bettet CSS, JS und Lizenztext ein
LEAFLET = Path(__file__).resolve().parent / "vendor" / "leaflet-1.9.4"
# Prüfsummen der Dateien, wie sie Leaflet für 1.9.4 veröffentlicht (dieselben Werte standen bis E38
# als Subresource Integrity im Verweis auf unpkg.com); tests/test_karte.py prüft sie.
LEAFLET_SHA256 = {"leaflet.js": "20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=",  # pragma: allowlist secret
                  "leaflet.css": "p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="}  # pragma: allowlist secret

# Hintergrundkarten Dritter; beim Öffnen der Seite sieht der Anbieter IP-Adresse und Kartenausschnitt.
# Abgerufen werden die Kacheln vom Browser dessen, der die Seite öffnet, nicht von der Pipeline.
# Schlüssel: art (kacheln = XYZ-Kacheln, wms = WMS-Dienst), text (Schlüssel des Beschriftungstexts in
# der Sprachdatei), url und optionen (unverändert an Leaflet weitergegeben, samt Quellenvermerk).
HINTERGRUND = {
    "basemap": {"art": "kacheln", "text": "karte",
                "url": "https://sgx.geodatenzentrum.de/wmts_basemapde/tile/1.0.0/de_basemapde_web_raster_grau/"
                       "default/GLOBAL_WEBMERCATOR/{z}/{y}/{x}.png",
                "optionen": {"maxZoom": 19,
                             "attribution": "© <a href=\"https://www.bkg.bund.de\">GeoBasis-DE / BKG</a> (2026), "
                                            "<a href=\"https://www.govdata.de/dl-de/by-2-0\">dl-de/by-2-0</a>"}},
    "luftbild": {"art": "wms", "text": "luftbild", "url": "https://isk.geobasis-bb.de/mapproxy/dop20c/service/wms",
                 "optionen": {"layers": "bebb_dop20c", "format": "image/jpeg", "maxZoom": 20,
                              "attribution": "Luftbild © GeoBasis-DE/LGB, dl-de/by-2-0"}},
}


def aktiv(cfg: dict) -> bool:
    """Karte schreiben? Nur `karte: false` oben in der Konfiguration schaltet sie ab.

    Args:
        cfg: gesamte Konfiguration.

    Returns:
        False nur bei ausdrücklichem `karte: false`; fehlt der Schlüssel oder ist er ein Abschnitt
        (`karte: {hintergrund: …}`), wird die Karte geschrieben.
    """
    return cfg.get("karte", True) is not False


def hintergruende(cfg: dict) -> list[str]:
    """Ausdrücklich eingeschaltete Hintergrundkarten; ohne Angabe keine (keine Drittverbindung).

    Args:
        cfg: gesamte Konfiguration; gelesen wird `karte.hintergrund` (ein Name oder eine Liste).

    Returns:
        Namen aus HINTERGRUND in der angegebenen Reihenfolge, doppelte nur einmal. Der erste ist beim
        Öffnen der Seite eingeschaltet, sofern der Link nichts anderes nennt (#grund=…).

    Raises:
        ValueError bei einem Namen, den HINTERGRUND nicht kennt. `laden._lauf` ruft die Funktion schon
        vor dem Laden der Quellen auf, damit ein Tippfehler den Lauf (als technischen Abbruch mit
        Bericht) beendet, bevor eine Quelle abgerufen wird.
    """
    k = cfg.get("karte")
    namen = (k.get("hintergrund") or []) if isinstance(k, dict) else []
    if isinstance(namen, str):
        namen = [namen]
    falsch = [n for n in namen if n not in HINTERGRUND]
    if falsch:
        raise ValueError(f"karte.hintergrund: unbekannt {', '.join(map(str, falsch))} "
                         f"(möglich: {', '.join(HINTERGRUND)})")
    return list(dict.fromkeys(namen))

# Abfrage je Ziel: ziel.karte_sql (Status aus dem Vergleich alt/neu, Geometrie als GeoJSON, große
# Flächen vereinfacht; geänderte, neue und gelöschte Objekte zuerst, damit sie beim Limit nicht
# fehlen). Kennzahlen ohne eigene Geometrie erscheinen je Gebiet mit dessen Fläche.
# Genauer: Je Objekt sortiert die Abfrage nach der Art im Vergleich; vor den unveränderten stehen
# deshalb auch zurückgehaltene und übernommene Zeilen ohne Abweichung, die die Karte als unverändert zeigt.
MAX_OBJEKTE_STANDARD = 20000


def objekte_lesen(cur, abfrage, max_objekte: int) -> list[dict]:
    """Objekte einer Quelle für die Karte als GeoJSON-Features.

    Args:
        cur: Cursor in der Transaktion der Quelle (dort liegt die temporäre Tabelle `vergleich`).
        abfrage: Abfrage aus `ziel.karte_sql`; sie liefert je Zeile Objekt-ID, Status, Werte und die
            Geometrie als GeoJSON-Text.
        max_objekte: Höchstzahl der Objekte (Parameter %(max)s der Abfrage).

    Returns:
        Liste von Features mit properties id, status (neu, geaendert, geloescht, unveraendert) und werte.

    Seiteneffekte:
        Nur lesende Abfrage in der laufenden Transaktion; ein Fehler hier lässt die Quelle scheitern.
    """
    cur.execute(abfrage, {"max": max_objekte})
    return [{"type": "Feature", "geometry": json.loads(g),
             "properties": {"id": oid, "status": status, "werte": werte}}
            for oid, status, werte, g in cur.fetchall()]


def _json_im_html(daten) -> str:
    """JSON für einen <script type="application/json">-Block (E39). Jedes "<", ">" und "&" wird als
    Unicode-Escape geschrieben: Ein "</script" würde den Block beenden, und schon "<!--<script" aus
    einem Attributwert der Quelle versetzt den HTML-Parser in einen Zustand, in dem das "</script>"
    des Blocks ihn nicht mehr beendet; der Block schluckte dann das Anwendungsskript und die Karte
    bliebe leer. JSON.parse liest die Escapes als dieselben Zeichen."""
    return (json.dumps(daten, ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def _lizenz_als_kommentar() -> str:
    """Lizenztext von Leaflet für den HTML-Kommentar der Seite: BSD-2-Clause verlangt, dass auch eine
    einzeln weitergegebene Kartenseite Bedingungen und Haftungsausschluss mitbringt.

    Returns:
        Lizenztext ohne Leerraum an den Rändern, jedes „--“ als „- -“."""
    # Ein „--“ ist in einem HTML-Kommentar nicht erlaubt, „-->“ beendete ihn vorzeitig und der Rest des
    # Lizenztexts stünde sichtbar in der Seite
    return (LEAFLET / "LICENSE").read_text(encoding="utf-8").strip().replace("--", "- -")


def schreiben(datei: Path, bericht: dict, objekte: dict[str, list[dict]],
              hintergrund: list[str] | tuple = ()) -> None:
    """Änderungskarte eines Laufs als eine HTML-Datei ohne externe Abhängigkeiten schreiben.

    Die Seite entsteht aus VORLAGE durch Ersetzen von Marken (@@…@@): Texte für HTML-Inhalt mit
    html.escape, Daten als JSON-Blöcke über `_json_im_html`, dann Leaflet (CSS, JS, Lizenz) eingebettet.
    Je Quelle des Berichts erscheint ein Eintrag mit Ergebnis, Zählern, Fehler und den ersten drei
    Warnungen, auch für Quellen ohne Objekte in `objekte`.

    Args:
        datei: Zieldatei (<lauf>-karte.html bzw. <lauf>-probelauf-karte.html).
        bericht: Laufbericht (lauf_id, probelauf, sprache, quellen, gegebenenfalls abbruch).
        objekte: Quellname -> Features aus `objekte_lesen`.
        hintergrund: Namen aus `hintergruende`; leer = Seite ohne jede Netzverbindung.

    Seiteneffekte:
        Schreibt die Datei (nicht atomar, anders als die Berichte; die Karte liest später kein Lauf).
        Liest Leaflet und dessen Lizenztext aus pipeline/vendor/.
    """
    quellen = []
    for q in bericht["quellen"]:
        # Ergebnis wie im Textbericht und im Quellenverzeichnis: ein unvollständiger Abruf ist nicht „ok“
        # (E44, F4); der JSON-Bericht führt ihn weiter als status ok mit unvollstaendig true
        quellen.append({"name": q["quelle"], "status": ergebnis(q), "zaehler": q.get("zaehler"),
                        "fehler": q.get("fehler"), "warnungen": q.get("warnungen", []),
                        "objekte": {"type": "FeatureCollection", "features": objekte.get(q["quelle"], [])}})
    daten = _json_im_html({"lauf": bericht["lauf_id"], "probelauf": bericht.get("probelauf", False),
                           "quellen": quellen})
    t = sprache.texte(bericht.get("sprache", sprache.STANDARD))["karte"]
    art = t["art_probelauf"] if bericht.get("probelauf") else t["art_import"]
    titel = f"{art} {sprache.zeit(bericht['lauf_id'], t['zeit'])}"
    seite = VORLAGE
    # Ein technischer Abbruch steht wie im Textbericht über allem (E45). Titel und Untertitel gehen
    # durch html.escape, denn der Abbruchtext kann Fehlermeldungen mit beliebigen Zeichen enthalten
    unter = t["unter"]
    if bericht.get("abbruch"):
        unter = f"{t['abbruch'].format(fehler=bericht['abbruch'])} {unter}"
    for marke, text in (("@@LANG@@", t["lang"]), ("@@TITEL@@", titel), ("@@UNTER@@", unter)):
        seite = seite.replace(marke, escape(text))
    # Je Hintergrund seine Einstellungen für Leaflet und die Beschriftung in der gewählten Sprache
    grund = [{**HINTERGRUND[n], "name": n, "text": t[HINTERGRUND[n]["text"]]} for n in hintergrund]
    texte = _json_im_html({k: t[k] for k in ("aenderung", "status", "objekt", "spalte_aenderung", "springen",
                                             "grundkarte", "ohne_grund")})
    # Leaflet eingebettet: die Seite braucht kein Netz. Ersetzt wird zuletzt und nur je einmal, damit
    # nichts aus Leaflet oder den Daten als Marke gelesen wird.
    css = (LEAFLET / "leaflet.css").read_text(encoding="utf-8")
    js = (LEAFLET / "leaflet.js").read_text(encoding="utf-8")
    # Zerlegen statt Ersetzen: Leaflet geht durch keinen Ersetzungsschritt, die Daten erst durch den
    # letzten; eine Marke in ihrem Text wird so nie ersetzt
    kopf, rest = seite.split("@@LEAFLET_CSS@@")
    kopf = kopf.replace("@@LEAFLET_LIZENZ@@", _lizenz_als_kommentar())
    mitte, rest = rest.split("@@LEAFLET_JS@@")
    rest = (rest.replace("@@TEXTE@@", texte).replace("@@GRUND@@", _json_im_html(grund))
            .replace("@@DATEN@@", daten))
    datei.write_text(kopf + css + mitte + js + rest, encoding="utf-8")


VORLAGE = r"""<!doctype html>
<html lang="@@LANG@@">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITEL@@</title>
<!-- Leaflet 1.9.4, (c) 2010-2023 Volodymyr Agafonkin, (c) 2010-2011 CloudMade, BSD-2-Clause.
     Eingebettet, die Seite lädt nichts nach. Lizenztext von Leaflet (pipeline/vendor/leaflet-1.9.4/LICENSE):

@@LEAFLET_LIZENZ@@
-->
<style>@@LEAFLET_CSS@@</style>
<script>@@LEAFLET_JS@@</script>
<style>
  :root { --text:#1d2327; --leise:#5f6b73; --flaeche:rgba(255,255,255,.94); --linie:#d5dade;
          --neu:#0072b2; --geaendert:#cc79a7; --geloescht:#d55e00; --unveraendert:#8a959c; }
  html, body { height:100%; margin:0; }
  body { font:14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; color:var(--text); background:#eef1f3; }
  #karte { position:absolute; inset:0; }
  #tafel { position:absolute; z-index:1000; top:12px; left:12px; width:320px; max-width:calc(100% - 24px);
           max-height:calc(100% - 24px); overflow:auto; background:var(--flaeche); border:1px solid var(--linie);
           border-radius:8px; box-shadow:0 2px 12px rgba(0,0,0,.08); }
  #tafel header { padding:12px 14px 8px; border-bottom:1px solid var(--linie); cursor:pointer; }
  #tafel h1 { font-size:15px; margin:0; font-weight:600; letter-spacing:.01em; }
  #tafel .unter { color:var(--leise); font-size:12px; margin-top:2px; }
  #tafel .inhalt { padding:6px 14px 12px; }
  #tafel.zu .inhalt { display:none; }
  .quelle { padding:8px 0; border-bottom:1px solid var(--linie); }
  .quelle:last-child { border-bottom:0; }
  .quelle label { display:flex; gap:8px; align-items:center; font-weight:600; cursor:pointer; }
  .quelle .name { cursor:zoom-in; text-decoration:underline dotted #b8c0c5; text-underline-offset:3px; }
  .quelle .status { margin-left:auto; font-weight:400; font-size:12px; color:var(--leise); }
  .quelle .status.fehler, .quelle .status.angehalten, .quelle .status.unvollstaendig { color:var(--geloescht); }
  .zahlen { display:flex; flex-wrap:wrap; gap:4px 12px; margin:4px 0 0 24px; font-size:12px; color:var(--leise); }
  .punkt { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:4px; vertical-align:middle; }
  .hinweis { margin:4px 0 0 24px; font-size:12px; color:var(--leise); }
  .grund { margin-top:10px; font-size:12px; color:var(--leise); }
  .grund label { margin-right:12px; cursor:pointer; }
  .leaflet-popup-content { font-size:12px; }
  .leaflet-popup-content table { border-collapse:collapse; }
  .leaflet-popup-content td { padding:1px 8px 1px 0; vertical-align:top; }
  .leaflet-popup-content td:first-child { color:var(--leise); }
  @media (max-width:600px) { #tafel { width:auto; right:56px; } }  /* 10 Rand + 34 Zoomleiste + 12 Abstand: Zoom bleibt frei */
</style>
</head>
<body>
<div id="karte"></div>
<section id="tafel">
  <header><h1 id="titel"></h1><div class="unter">@@UNTER@@</div></header>
  <div class="inhalt">
    <div id="quellen"></div>
    <div class="grund" id="grund"></div>
  </div>
</section>
<script id="texte" type="application/json">@@TEXTE@@</script>
<script id="grundkarten" type="application/json">@@GRUND@@</script>
<script id="daten" type="application/json">@@DATEN@@</script>
<script>
(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("daten").textContent);
  var CSS = getComputedStyle(document.documentElement);
  function farbe(s) { return CSS.getPropertyValue("--" + s).trim(); }
  var T = JSON.parse(document.getElementById("texte").textContent);  // Texte der gewählten Sprache
  var NAME = T.aenderung;

  function el(tag, text, klasse) {
    var e = document.createElement(tag);
    if (text != null) e.textContent = text;
    if (klasse) e.className = klasse;
    return e;
  }
  document.getElementById("titel").textContent = document.title;

  var karte = L.map("karte", { preferCanvas: true, attributionControl: false, zoomControl: false });
  L.control.zoom({ position: "topright" }).addTo(karte);
  L.control.attribution({ prefix: "Leaflet" }).addTo(karte);
  // Ansicht als Link teilbar: #quelle=NAME&grund=luftbild
  var HASH = {};
  location.hash.replace(/^#/, "").split("&").forEach(function (t) {
    var kv = t.split("="); if (kv[0]) HASH[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || "");
  });
  // Hintergrundkarten nur, wenn die Konfiguration sie nennt (karte.hintergrund); sonst kein Netzzugriff
  var G = JSON.parse(document.getElementById("grundkarten").textContent);
  var grund = {}, grundBox = document.getElementById("grund");
  G.forEach(function (h) {
    grund[h.name] = h.art === "wms" ? L.tileLayer.wms(h.url, h.optionen) : L.tileLayer(h.url, h.optionen);
  });
  var ebenen = [], aufLuftbild = false;
  function grundWaehlen(wert) {
    Object.keys(grund).forEach(function (k) { karte.removeLayer(grund[k]); });
    grund[wert].addTo(karte).bringToBack();
    aufLuftbild = wert === "luftbild";
    ebenen.forEach(function (e) { e.setStyle(stil); });  // Unverändertes auf dem Luftbild hell zeichnen
  }
  if (G.length) {
    grundBox.appendChild(document.createTextNode(T.grundkarte + " "));
    var startGrund = grund[HASH.grund] ? HASH.grund : G[0].name;
    G.forEach(function (h) {
      var lab = el("label"), r = el("input");
      r.type = "radio"; r.name = "grund"; r.value = h.name; r.checked = h.name === startGrund;
      r.addEventListener("change", function () { grundWaehlen(r.value); });
      lab.appendChild(r); lab.appendChild(document.createTextNode(" " + h.text));
      grundBox.appendChild(lab);
    });
    grundWaehlen(startGrund);
  } else {
    grundBox.textContent = T.ohne_grund;
  }

  function popup(f) {
    var p = f.properties, t = el("table");
    function zeile(k, v) { var tr = el("tr"); tr.appendChild(el("td", k)); tr.appendChild(el("td", String(v))); t.appendChild(tr); }
    zeile(T.objekt, p.id); zeile(T.spalte_aenderung, NAME[p.status]);
    Object.keys(p.werte || {}).forEach(function (k) { zeile(k, p.werte[k]); });
    return t;
  }
  function stil(f) {
    var s = f.properties.status, leise = s === "unveraendert";
    var c = leise && aufLuftbild ? "#ffffff" : farbe(s);
    return { color: c, weight: leise ? 0.8 : 1.6, opacity: leise ? 0.7 : 1,
             fillColor: c, fillOpacity: leise ? 0.08 : 0.35, dashArray: { geloescht: "4 3", geaendert: "8 3 2 3" }[s] || null };  // nicht nur über die Farbe unterscheiden
  }

  var gesamt = L.latLngBounds([]), geaendert = L.latLngBounds([]), ausschnitt = {};
  var liste = document.getElementById("quellen");
  D.quellen.forEach(function (q) {
    var eigenAlle = L.latLngBounds([]), eigenGeaendert = L.latLngBounds([]);
    var ebene = L.geoJSON(q.objekte, {
      style: stil,
      pointToLayer: function (f, ll) { var s = stil(f); s.radius = 5; s.fillOpacity = 0.8; return L.circleMarker(ll, s); },
      onEachFeature: function (f, l) {
        l.bindPopup(function () { return popup(f); });
        var b = l.getBounds ? l.getBounds() : L.latLngBounds([l.getLatLng(), l.getLatLng()]);
        gesamt.extend(b); eigenAlle.extend(b);
        if (f.properties.status !== "unveraendert") { geaendert.extend(b); eigenGeaendert.extend(b); }
      }
    }).addTo(karte);
    ausschnitt[q.name] = eigenGeaendert.isValid() ? eigenGeaendert : eigenAlle;
    ebenen.push(ebene);

    var box = el("div", null, "quelle"), lab = el("label"), cb = el("input");
    cb.type = "checkbox"; cb.checked = true;
    cb.addEventListener("change", function () { cb.checked ? ebene.addTo(karte) : karte.removeLayer(ebene); });
    var nameEl = el("span", q.name, "name");
    nameEl.title = T.springen;
    nameEl.addEventListener("click", function (ev) {
      ev.preventDefault();
      if (ausschnitt[q.name] && ausschnitt[q.name].isValid()) karte.fitBounds(ausschnitt[q.name], { padding: [30, 30] });
    });
    lab.appendChild(cb); lab.appendChild(nameEl);
    var statusText = T.status[q.status] || q.status;
    lab.appendChild(el("span", statusText, "status " + q.status));
    box.appendChild(lab);
    if (q.zaehler && (q.status === "ok" || q.status === "unvollstaendig")) {
      var z = el("div", null, "zahlen");
      [["neu", q.zaehler.neu], ["geaendert", q.zaehler.geaendert], ["geloescht", q.zaehler.geloescht],
       ["unveraendert", q.zaehler.unveraendert]].forEach(function (e) {
        var s = el("span"), pkt = el("span", null, "punkt");
        pkt.style.background = farbe(e[0]);
        s.appendChild(pkt); s.appendChild(document.createTextNode(e[1] + " " + NAME[e[0]]));
        z.appendChild(s);
      });
      box.appendChild(z);
    }
    if (q.fehler) box.appendChild(el("div", q.fehler.length > 90 ? q.fehler.slice(0, 90) + " …" : q.fehler, "hinweis"));
    (q.warnungen || []).slice(0, 3).forEach(function (w) { box.appendChild(el("div", w, "hinweis")); });
    liste.appendChild(box);
  });

  var ziel = (HASH.quelle && ausschnitt[HASH.quelle] && ausschnitt[HASH.quelle].isValid())
    ? ausschnitt[HASH.quelle] : (geaendert.isValid() ? geaendert : gesamt);
  if (ziel.isValid()) karte.fitBounds(ziel, { padding: [30, 30] }); else karte.setView([52.4, 13.0], 8);
  var tafel = document.getElementById("tafel");
  tafel.querySelector("header").addEventListener("click", function () { tafel.classList.toggle("zu"); });
  if (window.innerWidth < 600) tafel.classList.add("zu");
})();
</script>
</body>
</html>
"""
