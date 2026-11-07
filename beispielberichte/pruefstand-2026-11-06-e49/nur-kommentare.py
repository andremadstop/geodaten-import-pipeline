#!/usr/bin/env python3
"""Prüft maschinell, dass sich zwischen zwei Ständen nur Kommentare und Docstrings ändern (E49).

Verglichen werden zwei Git-Bäume (Tree-ish, z. B. ein Tag, ein Commit oder ein Baum aus ``git write-tree``).
Beide werden über ``git ls-tree -r`` und ``git cat-file --batch`` gelesen (nicht über ``git archive``, das
``export-ignore`` und ``export-subst`` aus ``.gitattributes`` anwenden würde); geprüft wird also genau der
Inhalt der Bäume, nicht der Arbeitsbaum. Ohne ``--neu`` gilt der aktuelle Index (``git write-tree``), also der
Stand nach ``git add -A``.

Je Eintrag zuerst Art und Modus: Ein geänderter Modus (etwa 100755 -> 100644) ist eine ABWEICHUNG, ebenso
jeder geänderte Eintrag, der keine reguläre Datei ist (Symlink, Gitlink). Danach Regeln je Dateiart (je Datei
eine Zeile OK, ABWEICHUNG, BEABSICHTIGT oder HINWEIS):

* ``.py``: Syntaxbaum (``ast.dump``) nach Entfernen aller Docstrings gleich; die Codezeilen ohne Kommentare
  und ohne Docstrings byte-gleich (fängt auch verschluckte Leerzeichen, die der Syntaxbaum nicht sieht); jeder
  Kommentar, den ein Werkzeug auswertet (``noqa``, ``nosec``, ``type:``, ``pragma``, ``ruff:``, ``pyright:``,
  ``mypy:``, ``fmt:``, ``isort:``, ``pylint:``), steht alt und neu an derselben Codezeile; Shebang (Zeile 1)
  und Kodierungsangabe (Zeile 1 oder 2) sind gleich. Liest ein Modul Docstrings zur Laufzeit (``__doc__`` als
  Name oder Attribut, die Zeichenkette ``"__doc__"``, ``getdoc``, ``help()``, ``click``/``typer``), müssen
  alle seine Docstrings gleich bleiben; nur wenn die einzige Nutzung ``__doc__.splitlines()[0]`` ist (die
  argparse-Beschreibung), genügt die erste Zeile des Moduldocstrings.
* ``.yaml``/``.yml``: ``yaml.safe_load_all`` gleich, typ- und reihenfolgetreu (Vergleich über ``repr``, damit
  ``True``, ``1`` und ``1.0`` verschieden sind und vertauschte Schlüssel auffallen). ``.toml``: ``tomllib``
  ebenso.
* ``.sql``: Inhalt ohne ``--``- und ``/* */``-Kommentare und mit vereinheitlichtem Leerraum gleich;
  Zeichenketten (``'…'``, ``E'…'`` mit Backslash-Escapes), zitierte Bezeichner (``"…"``) und Körper in
  Dollar-Quotes (``$$…$$``, ``$tag$…$tag$``) werden byte-gleich verglichen, Kommentare in Dollar-Körpern
  gesondert gemeldet.
* ``Dockerfile``, ``.service``, ``.timer``, ``.sh``: Zeilen ohne reine Kommentarzeilen und ohne Leerzeilen
  gleich; Heredocs (auch ``<<\\EOF``) und mehrzeilige Zeichenketten bleiben dabei Zeile für Zeile erhalten
  (dort ist ``#`` kein Kommentar). Ein ``#`` beginnt einen Kommentar am Zeilenanfang, nach Leerraum und nach
  den Shell-Metazeichen ``; & | ( ) < >``. ``.sh`` zusätzlich ``bash -n`` (bei ``#!/bin/sh`` auch ``sh -n``).
* alle anderen Dateien: byte-gleich. Neue und entfernte Dateien werden gemeldet.

Dazu: ``python -m pipeline.laden --help`` und ``python -m pipeline.einrichten --help`` alt und neu gleich.

Vor dem Vergleich läuft ein Selbsttest (``SELBSTTEST``): Gegenbeispiele, die als ABWEICHUNG erkannt werden
müssen, darunter jede Lücke, die die Prüfung von E49 an früheren Fassungen dieses Skripts gefunden hat, und
Fälle, die OK bleiben müssen. Schlägt einer fehl, ist das Ergebnis ABWEICHUNG. ``--selbsttest`` führt nur ihn
aus.

Aufruf aus dem Wurzelverzeichnis des Repositorys, mit den Abhängigkeiten der Pipeline (PyYAML, für ``--help``
auch psycopg usw.)::

    uv run --no-project --with-requirements requirements.txt python \\
        beispielberichte/pruefstand-2026-11-06-e49/nur-kommentare.py --alt efbd6f6a \\
        --zwischen 8e0e8b47 --zwischen-grund "Namensnennung basemap.de" --log <datei>

Nur Standardbibliothek und PyYAML. Rückgabe 0, wenn der Selbsttest besteht und keine Datei ABWEICHUNG hat,
sonst 1.

Grenzen: Der Vergleich belegt, dass sich der Code nicht geändert hat, nicht, dass jeder Kommentar stimmt.
Die Regeln für Shell und SQL sind Zustandsautomaten, keine vollständigen Parser (etwa ``$'…'`` in der Shell,
``U&'…'`` in SQL, nicht geprüft). Die Lücken, die bekannt wurden, sind behoben und stehen als Gegenbeispiel
im Selbsttest; weitere sind nicht ausgeschlossen.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import io
import os
import re
import subprocess  # nosec B404 - nur git, bash/sh -n und der eigene Interpreter, ohne Shell
import sys
import tempfile
import tokenize
import tomllib
from pathlib import Path

import yaml

# Ordner dieses Prüfstands: Skript und Protokoll liegen im geprüften Baum, gehören aber nicht zum Vergleich
# (sonst prüfte sich das Protokoll gegen sich selbst).
EIGENER_ORDNER = "beispielberichte/pruefstand-2026-11-06-e49/"

# Absichtliche Änderungen der Dokumentation in E49, je mit Grund. Weicht eine dieser Dateien ab, lautet das
# Ergebnis BEABSICHTIGT statt ABWEICHUNG; jede andere Abweichung bleibt ein Befund. "entfernt" heißt: die
# Datei darf im neuen Stand fehlen.
BEABSICHTIGT = {
    "docs/entscheidungen.md": "E49 neu; E48-Aussagen zu PyPI als überholt markiert",
    "beispielberichte/pruefstand-2026-11-06-e48/ZUERST-LESEN.md": "Inhalt steht in der README dort",
    "beispielberichte/pruefstand-2026-11-06-e48/README.md": "PyPI-Aussage als überholt markiert (E49)",
}

# Module, deren erste Docstring-Zeile ausdrücklich gleich bleiben muss (argparse-Beschreibung von --help).
# Zusätzlich gilt eine Regel für jedes Modul, das Docstrings im Code liest (siehe ``docstring_zur_laufzeit``).
ERSTE_ZEILE_FEST = ("pipeline/laden.py", "pipeline/einrichten.py")

# Kommentare, die Werkzeuge auswerten. Nur ein '#' am Anfang des Kommentars oder nach Leerraum zählt, damit
# Prosa, die ein Pragma in Backticks zitiert, nicht als Pragma gilt.
# ``\b`` steht je Alternative, weil hinter ``type:`` meist ein Leerzeichen folgt (dort keine Wortgrenze).
PRAGMA = re.compile(r"(?:^|(?<=\s))#\s*(noqa\b|nosec\b|type:|pragma\b"
                    r"|ruff:|pyright:|mypy:|fmt:|isort:|pylint:)", re.IGNORECASE)
# Kodierungsangabe nach PEP 263 (nur in Zeile 1 oder 2 wirksam); sie bestimmt, wie Python die Datei dekodiert
KODIERUNG = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")

# Git-Modi regulärer Dateien; alles andere (120000 Symlink, 160000 Gitlink) prüft das Skript nicht inhaltlich
REGULAER = ("100644", "100755")


# ----------------------------------------------------------------------------------------------------------
# Stände bereitstellen


def git(*args: str) -> str:
    """Ruft git im aktuellen Verzeichnis auf und gibt die Ausgabe ohne Zeilenende zurück."""
    r = subprocess.run(["git", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607  # nosec
    return r.stdout.strip()


def baum_lesen(baum: str, ziel: Path) -> dict[str, tuple[str, bytes]]:
    """Liest den Git-Baum ``baum`` und gibt {Pfad: (Modus, Inhalt)} aller Einträge zurück.

    ``git ls-tree -r -z`` liefert Modus, Art, Objekt und Pfad je Eintrag, ``git cat-file --batch`` die
    Inhalte der Blobs. Ein Symlink (120000) hat sein Ziel als Inhalt, ein Gitlink (160000) die Kennung des
    Commits. Reguläre Dateien werden zusätzlich nach ``ziel`` geschrieben, nur für den --help-Aufruf; Symlinks
    und Gitlinks dort nicht.
    """
    roh = subprocess.run(["git", "ls-tree", "-r", "-z", "--full-tree", baum],  # noqa: S603, S607  # nosec
                         check=True, capture_output=True).stdout
    eintraege: list[tuple[str, str, str, str]] = []
    for satz in roh.split(b"\0"):
        if not satz:
            continue
        kopf, pfad = satz.split(b"\t", 1)
        modus, art, objekt = kopf.decode().split()
        eintraege.append((modus, art, objekt, pfad.decode("utf-8")))
    blobs = [objekt for _, art, objekt, _ in eintraege if art == "blob"]
    anfrage = "".join(f"{b}\n" for b in blobs).encode()
    stapel = subprocess.run(["git", "cat-file", "--batch"], input=anfrage,  # noqa: S603, S607  # nosec
                            check=True, capture_output=True).stdout
    inhalte: dict[str, bytes] = {}
    pos = 0
    for b in blobs:
        ende = stapel.index(b"\n", pos)
        kennung, _, groesse = stapel[pos:ende].decode().split()
        if kennung != b:
            raise RuntimeError(f"git cat-file: {kennung} statt {b}")
        inhalte[b] = stapel[ende + 1:ende + 1 + int(groesse)]
        pos = ende + 1 + int(groesse) + 1  # Inhalt, dann ein Zeilenende
    dateien: dict[str, tuple[str, bytes]] = {}
    for modus, art, objekt, pfad in eintraege:
        inhalt = inhalte[objekt] if art == "blob" else objekt.encode()
        dateien[pfad] = (modus, inhalt)
        if modus in REGULAER:
            datei = ziel / pfad
            datei.parent.mkdir(parents=True, exist_ok=True)
            datei.write_bytes(inhalt)
    return dateien


# ----------------------------------------------------------------------------------------------------------
# Python


def ohne_docstrings(quelle: str) -> ast.AST:
    """Syntaxbaum ohne Docstrings: Modul, Klassen, Funktionen (auch innere), je das erste Ausdrucks-Statement
    mit einer str-Konstante. Ein dadurch leerer Klassen- oder Funktionskörper bekommt ein ``pass`` (ein Körper
    darf dort nicht leer sein, also hatte der Code ohne Docstring genau das); ein Modul darf leer bleiben, so
    gleicht ein leeres ``__init__.py`` einem, das nur einen Docstring hat."""
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if isinstance(knoten, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) \
                and docstring_knoten(knoten) is not None:
            rest = knoten.body[1:]
            knoten.body = rest if rest or isinstance(knoten, ast.Module) else [ast.Pass()]
    return baum


def docstring_knoten(knoten: ast.AST) -> ast.Expr | None:
    """Gibt das Docstring-Statement eines Moduls, einer Klasse oder Funktion zurück, sonst None."""
    body = getattr(knoten, "body", None)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        return body[0]
    return None


def docstring_zeilen(quelle: str) -> set[int]:
    """Alle Zeilennummern (ab 1), die zu einem Docstring gehören."""
    zeilen: set[int] = set()
    for knoten in ast.walk(ast.parse(quelle)):
        if isinstance(knoten, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            d = docstring_knoten(knoten)
            if d is not None:
                zeilen.update(range(d.lineno, d.end_lineno + 1))
    return zeilen


def codezeilen_und_pragmas(quelle: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Zerlegt die Quelle mit ``tokenize``.

    Rückgabe:
      * die Codezeilen in Reihenfolge, je ohne angehängten Kommentar und rechts ohne Leerraum; Zeilen, die nur
        Kommentar, Leerraum oder Docstring sind, fehlen;
      * die Pragma-Kommentare als (Pragma-Text, zugehörige Codezeile). Ein angehängter Kommentar gehört zur
        Codezeile, an der er steht; eine reine Kommentarzeile gehört zur nächsten Codezeile.
    """
    zeilen = quelle.splitlines()
    doc = docstring_zeilen(quelle)
    kommentar_spalte: dict[int, int] = {}  # Zeile -> Spalte, an der der Kommentar beginnt
    kommentare: list[tuple[int, str]] = []
    code: set[int] = set()  # Zeilen mit mindestens einem bedeutsamen Token außerhalb eines Docstrings
    nicht_code = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
                  tokenize.ENDMARKER, tokenize.ENCODING}
    for tok in tokenize.generate_tokens(io.StringIO(quelle).readline):
        if tok.type == tokenize.COMMENT:
            kommentar_spalte[tok.start[0]] = tok.start[1]
            kommentare.append((tok.start[0], tok.string))
        elif tok.type not in nicht_code:
            for nr in range(tok.start[0], tok.end[0] + 1):
                if nr not in doc:
                    code.add(nr)

    def text(nr: int) -> str:
        z = zeilen[nr - 1]
        if nr in kommentar_spalte:
            z = z[:kommentar_spalte[nr]]
        return z.rstrip()

    codezeilen = [text(nr) for nr in sorted(code)]
    pragmas: list[tuple[str, str]] = []
    for nr, kommentar in kommentare:
        treffer = [m.group(0) for m in PRAGMA.finditer(kommentar)]
        if not treffer:
            continue
        # zugehörige Codezeile: dieselbe, wenn dort Code steht, sonst die nächste
        ziel = nr if nr in code else next((n for n in sorted(code) if n > nr), None)
        bezug = text(ziel).strip() if ziel else "<Dateiende>"
        # der Pragma-Teil ab dem ersten Treffer, Leerraum vereinheitlicht
        teil = kommentar[kommentar.find(treffer[0]):]
        pragmas.append((" ".join(teil.split()), bezug))
    return codezeilen, pragmas


def _ist_erste_zeile(knoten: ast.Name, eltern: dict[ast.AST, ast.AST]) -> bool:
    """True, wenn der Name ``__doc__`` genau in ``__doc__.splitlines()[0]`` steht."""
    attr = eltern.get(knoten)
    aufruf = eltern.get(attr) if attr is not None else None
    index = eltern.get(aufruf) if aufruf is not None else None
    return (isinstance(attr, ast.Attribute) and attr.attr == "splitlines" and attr.value is knoten
            and isinstance(aufruf, ast.Call) and aufruf.func is attr and not aufruf.args
            and not aufruf.keywords and isinstance(index, ast.Subscript) and index.value is aufruf
            and isinstance(index.slice, ast.Constant) and index.slice.value == 0)


def docstring_zur_laufzeit(quelle: str) -> str | None:
    """Liest das Modul Docstrings zur Laufzeit? Dann sind sie Verhalten, kein Kommentar.

    Rückgabe: None (keine Nutzung gefunden), "erste_zeile" (einzige Nutzung ist ``__doc__.splitlines()[0]``
    auf dem Moduldocstring, etwa als argparse-Beschreibung) oder "alle" (jede andere Nutzung: ``__doc__`` als
    Name oder Attribut, die Zeichenkette ``"__doc__"`` etwa in getattr, ``getdoc``, ``help()``, ein Import von
    click oder typer, die Hilfetexte aus Docstrings lesen).
    """
    baum = ast.parse(quelle)
    eltern = {kind: k for k in ast.walk(baum) for kind in ast.iter_child_nodes(k)}
    art: str | None = None
    for k in ast.walk(baum):
        if isinstance(k, ast.Name) and k.id == "__doc__":
            art = art or "erste_zeile"
            if not _ist_erste_zeile(k, eltern):
                return "alle"
        elif (isinstance(k, ast.Attribute) and k.attr in ("__doc__", "getdoc")
              or isinstance(k, ast.Name) and k.id in ("getdoc", "help")
              and isinstance(eltern.get(k), ast.Call)
              or isinstance(k, ast.Constant) and k.value == "__doc__"):
            return "alle"
        elif isinstance(k, (ast.Import, ast.ImportFrom)):
            module = [a.name for a in k.names]
            if isinstance(k, ast.ImportFrom) and k.module:
                module.append(k.module)
            if any(m.split(".")[0] in ("click", "typer") for m in module):
                return "alle"
    return art


def alle_docstrings(quelle: str) -> list[str | None]:
    """Docstrings von Modul, Klassen und Funktionen in der Reihenfolge von ``ast.walk``, wörtlich."""
    return [ast.get_docstring(k, clean=False) for k in ast.walk(ast.parse(quelle))
            if isinstance(k, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]


def erste_docstring_zeile(quelle: str) -> str | None:
    """Erste Zeile des Moduldocstrings, so wie ``__doc__.splitlines()[0]`` sie liefert."""
    d = ast.get_docstring(ast.parse(quelle), clean=False)
    return d.splitlines()[0] if d else None


def kopfzeilen(quelle: str) -> list[str]:
    """Shebang (Zeile 1) und Kodierungsangabe (Zeile 1 oder 2): Kommentare, die Interpreter auswerten."""
    zeilen = quelle.splitlines()[:2]
    return [z for nr, z in enumerate(zeilen, 1) if (nr == 1 and z.startswith("#!")) or KODIERUNG.match(z)]


def python_pruefen(pfad: str, alt: bytes, neu: bytes) -> tuple[str, str]:
    """Vergleicht eine Python-Datei; Rückgabe (Status, Erläuterung)."""
    try:
        qa, qn = alt.decode("utf-8"), neu.decode("utf-8")
    except UnicodeDecodeError as fehler:
        return "ABWEICHUNG", f"nicht als UTF-8 lesbar: {fehler}"
    befunde: list[str] = []
    if kopfzeilen(qa) != kopfzeilen(qn):
        befunde.append(f"Shebang oder Kodierungsangabe verschieden: {kopfzeilen(qa)} -> {kopfzeilen(qn)}")
    try:
        if ast.dump(ohne_docstrings(qa)) != ast.dump(ohne_docstrings(qn)):
            befunde.append("Syntaxbaum ohne Docstrings verschieden")
    except SyntaxError as fehler:
        return "ABWEICHUNG", f"nicht lesbar: {fehler}"
    za, pa = codezeilen_und_pragmas(qa)
    zn, pn = codezeilen_und_pragmas(qn)
    if za != zn:
        paare = enumerate(zip(za, zn, strict=False))  # ungleich lang erlaubt: dann zählt das kürzere Ende
        erste = next((i for i, (a, b) in paare if a != b), min(len(za), len(zn)))
        befunde.append(f"Codezeilen ohne Kommentare nicht byte-gleich (ab Codezeile {erste + 1})")
    if sorted(pa) != sorted(pn):
        befunde.append(f"Pragma-Kommentare verschieden: alt {sorted(set(pa) - set(pn))}, "
                       f"neu {sorted(set(pn) - set(pa))}")
    arten = {docstring_zur_laufzeit(qa), docstring_zur_laufzeit(qn)}
    laufzeit = "alle" if "alle" in arten else (
        "erste_zeile" if "erste_zeile" in arten or pfad in ERSTE_ZEILE_FEST else None)
    if laufzeit == "alle" and alle_docstrings(qa) != alle_docstrings(qn):
        befunde.append("Docstrings verschieden, das Modul liest Docstrings zur Laufzeit")
    if laufzeit and erste_docstring_zeile(qa) != erste_docstring_zeile(qn):
        befunde.append("erste Docstring-Zeile verschieden (wird zur Laufzeit gelesen)")
    if befunde:
        return "ABWEICHUNG", "; ".join(befunde)
    zusatz = f"{len(pa)} Pragma-Kommentar(e) an gleicher Stelle" if pa else "keine Pragma-Kommentare"
    if laufzeit == "alle":
        zusatz += ", alle Docstrings gleich (zur Laufzeit gelesen)"
    elif laufzeit:
        zusatz += ", erste Docstring-Zeile gleich"
    return "OK", f"Syntaxbaum ohne Docstrings gleich, Codezeilen byte-gleich, {zusatz}"


# ----------------------------------------------------------------------------------------------------------
# YAML und TOML


def treu(daten: object) -> str:
    """Typ- und reihenfolgetreue Darstellung geladener Daten für den Vergleich.

    ``==`` reicht nicht: In Python gilt ``True == 1 == 1.0``, und dicts sind ohne Rücksicht auf die
    Reihenfolge gleich. Die Reihenfolge ist aber Verhalten (laden._lauf arbeitet die Quellen in der
    Reihenfolge der Konfiguration ab). ``repr`` schreibt Schlüssel in Einfügereihenfolge und unterscheidet
    True, 1 und 1.0; die Typen geladener YAML- und TOML-Werte (dict, list, str, int, float, bool, None,
    date, datetime) haben ein eindeutiges ``repr``.
    """
    return repr(daten)


def yaml_pruefen(alt: bytes, neu: bytes) -> tuple[str, str]:
    """Vergleicht die geladenen YAML-Dokumente typ- und reihenfolgetreu (Kommentare spielen beim Laden keine
    Rolle)."""
    a = list(yaml.safe_load_all(alt.decode("utf-8")))
    n = list(yaml.safe_load_all(neu.decode("utf-8")))
    return (("OK", "yaml.safe_load gleich (typ- und reihenfolgetreu)") if treu(a) == treu(n)
            else ("ABWEICHUNG", "geladener Inhalt verschieden (Wert, Typ oder Reihenfolge)"))


def toml_pruefen(alt: bytes, neu: bytes) -> tuple[str, str]:
    """Vergleicht die geladenen TOML-Daten typ- und reihenfolgetreu."""
    gleich = treu(tomllib.loads(alt.decode("utf-8"))) == treu(tomllib.loads(neu.decode("utf-8")))
    return (("OK", "tomllib gleich (typ- und reihenfolgetreu)") if gleich
            else ("ABWEICHUNG", "geladener Inhalt verschieden (Wert, Typ oder Reihenfolge)"))


# ----------------------------------------------------------------------------------------------------------
# SQL

DOLLAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")


def sql_zerlegen(text: str) -> tuple[str, list[str], list[str], int]:
    """Zerlegt SQL in (Code ohne Kommentare, Leerraum vereinheitlicht; Literale; Dollar-Körper; Zahl der
    Kommentare).

    Beachtet Zeichenketten ('…' mit '' als Escape, E'…' zusätzlich mit Backslash-Escapes), Bezeichner ("…")
    und Dollar-Quotes, damit ein ``--`` oder ``/*`` darin nicht als Kommentar gilt. Blockkommentare dürfen in
    PostgreSQL geschachtelt sein. Zeichenketten, Bezeichner und Dollar-Körper erscheinen im Code als
    Platzhalter und werden gesondert und unverändert zurückgegeben (der Leerraum wird nur außerhalb davon
    vereinheitlicht).
    """
    aus: list[str] = []
    literale: list[str] = []
    koerper: list[str] = []
    kommentare = 0
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        # E'…' bzw. e'…': nur, wenn das E keinen Bezeichner fortsetzt (sonst wäre es etwa „name'…“)
        e_string = (c in "eE" and text.startswith("'", i + 1)
                    and not (i and (text[i - 1].isalnum() or text[i - 1] in "_$")))
        if text.startswith("--", i):  # Zeilenkommentar bis Zeilenende
            ende = text.find("\n", i)
            i = n if ende < 0 else ende
            aus.append(" ")
            kommentare += 1
        elif text.startswith("/*", i):  # Blockkommentar, geschachtelt
            tiefe, i = 1, i + 2
            while i < n and tiefe:
                if text.startswith("/*", i):
                    tiefe, i = tiefe + 1, i + 2
                elif text.startswith("*/", i):
                    tiefe, i = tiefe - 1, i + 2
                else:
                    i += 1
            aus.append(" ")
            kommentare += 1
        elif c in "'\"" or e_string:  # Zeichenkette oder Bezeichner; verdoppeltes Zeichen ist das Escape
            q = "'" if e_string else c
            j = i + (2 if e_string else 1)
            while j < n:
                if e_string and text[j] == "\\":
                    j += 2  # Backslash-Escape: das nächste Zeichen gehört zur Zeichenkette
                    continue
                if text[j] == q:
                    if j + 1 < n and text[j + 1] == q:
                        j += 2
                        continue
                    break
                j += 1
            literale.append(text[i:j + 1])
            aus.append(f"<Literal{len(literale)}>")
            i = j + 1
        elif c == "$" and (m := DOLLAR.match(text, i)) \
                and not (i and (text[i - 1].isalnum() or text[i - 1] == "_")):
            marke = m.group(0)
            ende = text.find(marke, m.end())
            ende = n if ende < 0 else ende
            koerper.append(text[m.end():ende])
            aus.append(f"{marke}<Körper {len(koerper)}>{marke}")
            i = ende + len(marke)
        else:
            aus.append(c)
            i += 1
    return " ".join("".join(aus).split()), literale, koerper, kommentare


def sql_pruefen(alt: bytes, neu: bytes) -> tuple[str, str]:
    """Vergleicht SQL ohne Kommentare; Literale und Dollar-Körper byte-gleich, Kommentare in Dollar-Körpern
    gesondert gemeldet."""
    ca, la, ka, na = sql_zerlegen(alt.decode("utf-8"))
    cn, ln, kn, nn = sql_zerlegen(neu.decode("utf-8"))
    if ca != cn:
        return "ABWEICHUNG", "Code ohne Kommentare verschieden"
    if la != ln:
        return "ABWEICHUNG", "Zeichenketten oder zitierte Bezeichner verschieden"
    if len(ka) != len(kn):
        return "ABWEICHUNG", "Zahl der $$-Körper verschieden"
    kom_a = sum(sql_zerlegen(k)[3] for k in ka)
    kom_n = sum(sql_zerlegen(k)[3] for k in kn)
    info = (f"Kommentare {na} -> {nn}; {len(ln)} Literale außerhalb von $$-Körpern byte-gleich; "
            f"{len(kn)} $$-Körper, darin Kommentare alt {kom_a}, neu {kom_n}")
    for a, b in zip(ka, kn, strict=True):
        if a != b:
            if sql_zerlegen(a)[:3] == sql_zerlegen(b)[:3]:
                # nur Kommentare im Körper geändert: landet im Katalog (prosrc), deshalb gesondert
                return "HINWEIS", "nur Kommentare in einem $$-Körper geändert; " + info
            return "ABWEICHUNG", "$$-Körper verschieden; " + info
    return "OK", "Code ohne Kommentare gleich, $$-Körper byte-gleich; " + info


# ----------------------------------------------------------------------------------------------------------
# Shell, Dockerfile, systemd

# Heredoc-Anfang: <<WORT, <<-WORT, <<'WORT', <<"WORT" und <<\WORT (Backslash vor der Marke quotet sie wie '')
HEREDOC = re.compile(r"<<(-?)\s*\\?(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
# Shell-Metazeichen: Danach beginnt ein neues Wort, ein '#' dort ist also ein Kommentar (wie nach Leerraum)
METAZEICHEN = ";&|()<>"
DIREKTIVE = re.compile(r"#\s*(syntax|escape|check)\s*=", re.IGNORECASE)


def zeilen_ohne_kommentare(text: str, art: str) -> tuple[list[str], int]:
    """Zeilen ohne reine Kommentarzeilen und ohne Leerzeilen; Rückgabe (Zeilen, Zahl der Heredocs).

    Ein kleiner Zustandsautomat verfolgt über die Zeilen hinweg einfache und doppelte Anführungszeichen sowie
    Heredocs. Zeilen darin bleiben unverändert erhalten, auch wenn sie mit '#' beginnen oder leer sind
    (dort ist '#' Inhalt, z. B. Python-Kommentare im ``python3 -c '…'``-Block von pruefen.sh). ``art``:
      * "sh": Shebang in Zeile 1 bleibt; Kommentarzeile = '#' am Zeilenanfang außerhalb von Quotes/Heredocs.
        Ein angehängter Kommentar ('#' nach Leerraum oder einem Metazeichen) bleibt in der Zeile, zählt aber
        nicht für den Quote-Zustand (ein Apostroph darin öffnet keine Zeichenkette).
      * "docker": Parser-Direktiven (``# syntax=`` usw.) am Dateianfang bleiben.
      * "systemd": Kommentarzeichen sind '#' und ';'.
    """
    behalten: list[str] = []
    einfach = doppelt = False
    offen: list[tuple[str, bool]] = []  # erwartete Heredoc-Enden (Marke, Tabs erlaubt)
    im_heredoc: tuple[str, bool] | None = None
    heredocs = 0
    direktiven_moeglich = art == "docker"
    for nr, zeile in enumerate(text.splitlines(), 1):
        if im_heredoc:  # Heredoc-Inhalt: unverändert, bis die Endmarke kommt
            behalten.append(zeile)
            marke, tabs = im_heredoc
            if (zeile.lstrip("\t") if tabs else zeile) == marke:
                im_heredoc = offen.pop(0) if offen else None
            continue
        s = zeile.strip()
        in_quote = einfach or doppelt
        if not in_quote:
            if art == "sh" and nr == 1 and s.startswith("#!"):
                behalten.append(zeile)
                continue
            if direktiven_moeglich and DIREKTIVE.match(s):
                behalten.append(zeile)
                continue
            direktiven_moeglich = False
            kommentarzeichen = ("#", ";") if art == "systemd" else ("#",)
            if not s or s.startswith(kommentarzeichen):
                continue
        behalten.append(zeile)
        if art == "systemd":
            continue  # systemd kennt keine mehrzeiligen Quotes oder Heredocs
        # Zeile Zeichen für Zeichen lesen, um den Quote-Zustand und Heredoc-Anfänge zu finden
        i = 0
        while i < len(zeile):
            c = zeile[i]
            if einfach:
                einfach = c != "'"
            elif doppelt:
                if c == "\\":
                    i += 1
                elif c == '"':
                    doppelt = False
            elif c == "\\":
                i += 1
            elif c == "'":
                einfach = True
            elif c == '"':
                doppelt = True
            elif c == "#" and (i == 0 or zeile[i - 1].isspace() or zeile[i - 1] in METAZEICHEN):
                break  # angehängter Kommentar (auch direkt nach ; & | ( ) < >): Rest der Zeile ist kein Code
            elif c == "<" and (m := HEREDOC.match(zeile, i)):
                offen.append((m.group(3), m.group(1) == "-"))
                heredocs += 1
                i = m.end()
                continue
            i += 1
        if offen and not (einfach or doppelt):
            im_heredoc = offen.pop(0)
    return behalten, heredocs


def zeilen_pruefen(pfad: str, alt: bytes, neu: bytes, art: str) -> tuple[str, str]:
    """Vergleicht Shell, Dockerfile oder systemd-Unit ohne reine Kommentar- und Leerzeilen."""
    za, ha = zeilen_ohne_kommentare(alt.decode("utf-8"), art)
    zn, hn = zeilen_ohne_kommentare(neu.decode("utf-8"), art)
    befunde = []
    if za != zn:
        paare = enumerate(zip(za, zn, strict=False))  # ungleich lang erlaubt: dann zählt das kürzere Ende
        erste = next((i for i, (a, b) in paare if a != b), min(len(za), len(zn)))
        befunde.append(f"Zeilen ohne Kommentare verschieden (ab Zeile {erste + 1} der gefilterten Fassung)")
    info = f"{len(zn)} Zeilen gleich"
    if hn:
        info += f", {hn} Heredoc(s) unverändert" if ha == hn and za == zn else f", Heredocs {ha} -> {hn}"
    if art == "sh":
        syntax = syntax_pruefen(neu)
        if syntax:
            befunde.append(syntax)
        else:
            info += ", bash -n" + (" und sh -n" if neu.startswith(b"#!/bin/sh") else "") + " ohne Fehler"
    return ("ABWEICHUNG", "; ".join(befunde)) if befunde else ("OK", info)


def syntax_pruefen(inhalt: bytes) -> str | None:
    """``bash -n`` (bei ``#!/bin/sh`` zusätzlich ``sh -n``) auf den neuen Inhalt; Fehlertext oder None."""
    shells = ["bash"] + (["sh"] if inhalt.startswith(b"#!/bin/sh") else [])
    for shell in shells:
        r = subprocess.run([shell, "-n"], input=inhalt, capture_output=True)  # noqa: S603, S607  # nosec
        if r.returncode:
            return f"{shell} -n: {r.stderr.decode(errors='replace').strip()}"
    return None


# ----------------------------------------------------------------------------------------------------------
# Eine Datei


def datei_pruefen(pfad: str, alt: bytes, neu: bytes) -> tuple[str, str]:
    """Wählt die Regel nach Dateiart; byte-gleiche Dateien sind immer OK."""
    name = pfad.rsplit("/", 1)[-1]
    if alt == neu:
        return "OK", "byte-gleich"
    if name.endswith(".py"):
        return python_pruefen(pfad, alt, neu)
    if name.endswith((".yaml", ".yml")):
        return yaml_pruefen(alt, neu)
    if name.endswith(".toml"):
        return toml_pruefen(alt, neu)
    if name.endswith(".sql"):
        return sql_pruefen(alt, neu)
    if name == "Dockerfile":
        return zeilen_pruefen(pfad, alt, neu, "docker")
    if name.endswith((".service", ".timer")):
        return zeilen_pruefen(pfad, alt, neu, "systemd")
    if name.endswith(".sh"):
        return zeilen_pruefen(pfad, alt, neu, "sh")
    if pfad in BEABSICHTIGT:
        return "BEABSICHTIGT", BEABSICHTIGT[pfad]
    return "ABWEICHUNG", "nicht byte-gleich (Dateiart ohne Kommentarregel)"


def eintrag_pruefen(pfad: str, alt: tuple[str, bytes], neu: tuple[str, bytes]) -> tuple[str, str]:
    """Prüft einen Baumeintrag (Modus, Inhalt): erst Modus und Art, dann den Inhalt nach Dateiart.

    Ein geänderter Modus ist immer eine ABWEICHUNG (etwa ein Skript, das nicht mehr ausführbar ist), auch
    bei einer Datei aus BEABSICHTIGT. Symlinks und Gitlinks prüft das Skript nicht inhaltlich: unverändert
    OK (mit eigener Zeile im Protokoll), sonst ABWEICHUNG.
    """
    (ma, ia), (mn, inh) = alt, neu
    if ma != mn:
        return "ABWEICHUNG", f"Modus {ma} -> {mn}"
    if ma not in REGULAER:
        art = {"120000": "Symlink", "160000": "Gitlink"}.get(ma, f"Eintrag mit Modus {ma}")
        return ("OK", f"{art} unverändert") if ia == inh else ("ABWEICHUNG", f"{art} geändert")
    return datei_pruefen(pfad, ia, inh)


def bereich(pfad: str) -> str:
    """Bereich für die Zusammenfassung: erstes Verzeichnis, Dateien im Wurzelverzeichnis als „(Wurzel)“."""
    return pfad.split("/", 1)[0] + "/" if "/" in pfad else "(Wurzel)"


# ----------------------------------------------------------------------------------------------------------
# Selbsttest: Gegenbeispiele, die als ABWEICHUNG erkannt werden müssen, und Fälle, die OK bleiben müssen.
# Die mit „Prüfung zu E49“ markierten Fälle lieferten in einer früheren Fassung dieses Skripts OK.

R, X = "100644", "100755"  # Modi regulärer Dateien (normal, ausführbar)
# Moduldocstring als argparse-Beschreibung: nur die erste Zeile bzw. der ganze Docstring
ERSTE = "import argparse\n\nargparse.ArgumentParser(description=__doc__.splitlines()[0])\n"
GANZ = "import argparse\n\nargparse.ArgumentParser(description=__doc__)\n"
SELBSTTEST: list[tuple[str, str, tuple[str, str], tuple[str, str], str]] = [
    # (Name, Pfad, (Modus, alt), (Modus, neu), erwarteter Status)
    ("YAML: Schlüssel vertauscht (Prüfung zu E49)", "a.yaml",
     (R, "quellen:\n  a: 1\n  b: 2\n"), (R, "quellen:\n  b: 2\n  a: 1\n"), "ABWEICHUNG"),
    ("YAML: 1 -> true (Prüfung zu E49)", "a.yaml", (R, "archiv: 1\n"), (R, "archiv: true\n"), "ABWEICHUNG"),
    ("YAML: nur Kommentare", "a.yaml", (R, "a: 1\n"), (R, "# k\na: 1  # k\n"), "OK"),
    ("TOML: 1 -> 1.0 (Prüfung zu E49)", "a.toml", (R, "a = 1\n"), (R, "a = 1.0\n"), "ABWEICHUNG"),
    ("TOML: nur Kommentare", "a.toml", (R, "a = 1\n"), (R, "# k\na = 1  # k\n"), "OK"),
    ("SQL: Leerraum in Zeichenkette (Prüfung zu E49)", "a.sql",
     (R, "SELECT 'a  b';\n"), (R, "SELECT 'a b';\n"), "ABWEICHUNG"),
    ("SQL: Leerraum in zitiertem Bezeichner (Prüfung zu E49)", "a.sql",
     (R, 'SELECT 1 AS "a  b";\n'), (R, 'SELECT 1 AS "a b";\n'), "ABWEICHUNG"),
    ("SQL: E-String mit Backslash-Escape (Prüfung zu E49)", "a.sql",
     (R, "SELECT E'x\\' -- y', 1;\n"), (R, "SELECT E'x\\' -- z', 1;\n"), "ABWEICHUNG"),
    ("SQL: nur Kommentare und Leerraum außerhalb von Literalen", "a.sql",
     (R, "SELECT 'a  b' ,1;\n"), (R, "-- k\nSELECT   'a  b' ,1; /* k */\n"), "OK"),
    ("SQL: Kommentar in einem $$-Körper", "a.sql",
     (R, "CREATE FUNCTION f() RETURNS int AS $$ SELECT 1 $$;\n"),
     (R, "CREATE FUNCTION f() RETURNS int AS $$ SELECT 1 -- x\n $$;\n"), "HINWEIS"),
    ("Shell: Heredoc mit <<\\EOF (Prüfung zu E49)", "a.sh",
     (R, "#!/bin/sh\ncat <<\\EOF\n# wert=1\nEOF\n"), (R, "#!/bin/sh\ncat <<\\EOF\n# wert=2\nEOF\n"),
     "ABWEICHUNG"),
    ("Shell: Kommentar direkt nach ; mit Apostroph (Prüfung zu E49)", "a.sh",
     (R, "#!/bin/sh\necho a;# don't\npython3 -c '\n# x=1\nprint(1)'\n"),
     (R, "#!/bin/sh\necho a;# don't\npython3 -c '\n# x=2\nprint(1)'\n"), "ABWEICHUNG"),
    ("Shell: Zeile in python3 -c '…'", "a.sh",
     (R, "#!/bin/sh\npython3 -c '\n# a\nprint(1)'\n"), (R, "#!/bin/sh\npython3 -c '\n# b\nprint(1)'\n"),
     "ABWEICHUNG"),
    ("Shell: nur Kommentar- und Leerzeilen", "a.sh",
     (R, "#!/bin/sh\necho 1\n"), (R, "#!/bin/sh\n# k\n\necho 1\n"), "OK"),
    ("Python: f.__doc__ gelesen (Prüfung zu E49)", "x.py",
     (R, 'def f():\n    """A."""\n\n\nprint(f.__doc__)\n'),
     (R, 'def f():\n    """B."""\n\n\nprint(f.__doc__)\n'), "ABWEICHUNG"),
    ("Python: inspect.getdoc gelesen (Prüfung zu E49)", "x.py",
     (R, 'import inspect\n\n\ndef f():\n    """A."""\n\n\nprint(inspect.getdoc(f))\n'),
     (R, 'import inspect\n\n\ndef f():\n    """B."""\n\n\nprint(inspect.getdoc(f))\n'), "ABWEICHUNG"),
    ("Python: description=__doc__, zweite Zeile geändert (Prüfung zu E49)", "x.py",
     (R, '"""A\nB"""\n' + GANZ),
     (R, '"""A\nC"""\n' + GANZ), "ABWEICHUNG"),
    ("Python: __doc__.splitlines()[0], zweite Zeile geändert", "x.py",
     (R, '"""A\nB"""\n' + ERSTE),
     (R, '"""A\nC"""\n' + ERSTE), "OK"),
    ("Python: __doc__.splitlines()[0], erste Zeile geändert", "x.py",
     (R, '"""A\nB"""\n' + ERSTE),
     (R, '"""Z\nB"""\n' + ERSTE),
     "ABWEICHUNG"),
    ("Python: Kodierungsangabe neu (Prüfung zu E49)", "x.py",
     (R, "x = 1\n"), (R, "# -*- coding: latin-1 -*-\nx = 1\n"), "ABWEICHUNG"),
    ("Python: Shebang geändert (Prüfung zu E49)", "x.py",
     (R, "#!/usr/bin/env python3\nx = 1\n"), (R, "#!/usr/bin/python2\nx = 1\n"), "ABWEICHUNG"),
    ("Python: # ruff: noqa neu (Prüfung zu E49)", "x.py",
     (R, "x = 1\n"), (R, "# ruff: noqa\nx = 1\n"), "ABWEICHUNG"),
    ("Python: noqa an andere Codezeile verschoben", "x.py",
     (R, "x = 1  # noqa: S1\ny = 2\n"), (R, "x = 1\ny = 2  # noqa: S1\n"), "ABWEICHUNG"),
    ("Python: Leerzeichen im Code", "x.py", (R, "x = 1\n"), (R, "x =1\n"), "ABWEICHUNG"),
    ("Python: Zeichenkette mit # geändert", "x.py", (R, "x = '# a'\n"), (R, "x = '# b'\n"), "ABWEICHUNG"),
    ("Python: Docstring und Kommentar neu", "x.py",
     (R, "def f():\n    pass\n"), (R, 'def f():\n    """D."""\n    pass  # k\n'), "OK"),
    ("Modus 100755 -> 100644 (Prüfung zu E49)", "a.sh",
     (X, "#!/bin/sh\necho 1\n"), (R, "#!/bin/sh\necho 1\n"), "ABWEICHUNG"),
    ("Symlink-Ziel geändert (Prüfung zu E49)", "a", ("120000", "x"), ("120000", "y"), "ABWEICHUNG"),
    ("Gitlink geändert (Prüfung zu E49)", "a", ("160000", "1" * 40), ("160000", "2" * 40), "ABWEICHUNG"),
    ("Markdown geändert", "a.md", (R, "a\n"), (R, "b\n"), "ABWEICHUNG"),
]


def selbsttest() -> list[tuple[bool, str]]:
    """Führt SELBSTTEST aus; Rückgabe je Fall (bestanden, Protokollzeile)."""
    aus: list[tuple[bool, str]] = []
    for name, pfad, (ma, a), (mn, n), erwartet in SELBSTTEST:
        status, _ = eintrag_pruefen(pfad, (ma, a.encode()), (mn, n.encode()))
        aus.append((status == erwartet, f"{name}: erwartet {erwartet}, erhalten {status}"))
    return aus


# ----------------------------------------------------------------------------------------------------------
# --help alt und neu


def hilfe(wurzel: Path, modul: str) -> str:
    """Ausgabe von ``python -m <modul> --help`` mit dem Paket aus ``wurzel``.

    ``-P`` und ein leeres Arbeitsverzeichnis sorgen dafür, dass nur ``PYTHONPATH`` das Paket liefert,
    nicht das Repository, aus dem das Skript läuft. ``COLUMNS`` fest, damit argparse gleich umbricht.
    """
    with tempfile.TemporaryDirectory() as leer:
        env = {**os.environ, "PYTHONPATH": str(wurzel), "COLUMNS": "100", "PYTHONDONTWRITEBYTECODE": "1"}
        r = subprocess.run([sys.executable, "-P", "-m", modul, "--help"], cwd=leer, env=env,  # noqa: S603  # nosec
                           capture_output=True, text=True)
    return f"rc={r.returncode}\n{r.stdout}{r.stderr}"


# ----------------------------------------------------------------------------------------------------------


def main() -> int:
    """Vergleicht die Stände, schreibt das Protokoll und gibt 0 (alles OK) oder 1 (ABWEICHUNG) zurück."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selbsttest", action="store_true", help="nur den Selbsttest ausführen")
    ap.add_argument("--alt", help="Tree-ish des alten Stands (z. B. efbd6f6a); nötig ohne --selbsttest")
    ap.add_argument("--alt-name", default="Stand vor E49", help="Bezeichnung des alten Stands im Protokoll")
    ap.add_argument("--neu", help="Tree-ish des neuen Stands; ohne Angabe der Index (git write-tree)")
    ap.add_argument("--zwischen", help="Tree-ish eines Zwischenstands (Änderungen außerhalb dieser Prüfung)")
    ap.add_argument("--zwischen-grund", default="", help="Grund der Änderungen im Zwischenstand")
    ap.add_argument("--log", type=Path, help="Protokolldatei (zusätzlich zur Ausgabe)")
    args = ap.parse_args()
    test = selbsttest()
    test_ok = all(b for b, _ in test)
    if args.selbsttest:
        for b, zeile in test:
            print(f"{'OK' if b else 'FEHLER':<12} {zeile}")
        print(f"{sum(b for b, _ in test)} von {len(test)} Fällen wie erwartet")
        return 0 if test_ok else 1
    if not args.alt:
        ap.error("--alt fehlt")

    baum_alt = git("rev-parse", args.alt + "^{tree}")
    baum_neu = git("rev-parse", (args.neu or git("write-tree")) + "^{tree}")
    baum_zw = git("rev-parse", args.zwischen + "^{tree}") if args.zwischen else None

    zeilen: list[str] = []

    def aus(text: str = "") -> None:
        print(text)
        zeilen.append(text)

    aus("# Nur Kommentare? Maschineller Vergleich zweier Stände (E49, nur-kommentare.py)")
    aus(f"Datum: {dt.datetime.now(dt.UTC).astimezone().isoformat(timespec='seconds')}")
    aus(f"Baum alt: {args.alt_name} (Baum {baum_alt})")
    aus(f"Baum neu: {baum_neu} (git write-tree nach git add -A)" if not args.neu else f"Baum neu: {baum_neu}")
    if baum_zw:
        aus(f"Zwischenstand: Baum {baum_zw} ({args.zwischen_grund})")
    aus(f"Python {sys.version.split()[0]}, PyYAML {yaml.__version__}")
    aus(f"Ausgenommen: {EIGENER_ORDNER} (Skript und Protokoll dieses Prüfstands)")
    aus()
    aus("## Selbsttest")
    for b, zeile in test:
        aus(f"{'OK' if b else 'FEHLER':<12} {zeile}")
    aus(f"{sum(b for b, _ in test)} von {len(test)} Fällen wie erwartet")
    aus()

    with tempfile.TemporaryDirectory() as tmp:
        wa, wn, wz = Path(tmp, "alt"), Path(tmp, "neu"), Path(tmp, "zwischen")
        alt = baum_lesen(baum_alt, wa)
        neu = baum_lesen(baum_neu, wn)
        zw = baum_lesen(baum_zw, wz) if baum_zw else None

        ergebnisse: list[tuple[str, str, str]] = []
        for pfad in sorted(set(alt) | set(neu)):
            if pfad.startswith(EIGENER_ORDNER):
                continue
            # Im Zwischenstand außerhalb dieser Prüfung geändert: dann ist der Zwischenstand die Basis.
            basis, vermerk = alt, ""
            if zw is not None and alt.get(pfad) != zw.get(pfad):
                vermerk = f"AUSSERHALB E49 geändert ({args.zwischen_grund}), geprüft gegen Zwischenstand: "
                basis = zw
            if pfad not in neu:
                status, text = (("BEABSICHTIGT", "entfernt: " + BEABSICHTIGT[pfad]) if pfad in BEABSICHTIGT
                                else ("ABWEICHUNG", "entfernt"))
            elif pfad not in basis:
                status, text = "ABWEICHUNG", "neu hinzugekommen"
            else:
                status, text = eintrag_pruefen(pfad, basis[pfad], neu[pfad])
            ergebnisse.append((pfad, status, vermerk + text))

        # Je Datei eine Zeile; byte-gleiche Dateien nur gezählt, damit das Protokoll lesbar bleibt
        aus("## Geänderte, neue und entfernte Dateien")
        for pfad, status, text in ergebnisse:
            if text != "byte-gleich":
                aus(f"{status:<12} {pfad}: {text}")
        aus()
        aus("## Je Bereich")
        bereiche: dict[str, dict[str, int]] = {}
        for pfad, status, text in ergebnisse:
            zaehler = bereiche.setdefault(bereich(pfad), {})
            schluessel = "byte-gleich" if text == "byte-gleich" else status
            zaehler[schluessel] = zaehler.get(schluessel, 0) + 1
        for name in sorted(bereiche):
            aus(f"{name:<20} " + ", ".join(f"{k} {v}" for k, v in sorted(bereiche[name].items())))
        bestand = "sql/mosidi/001_bestand.sql"
        aus(f"{bestand}: " + ("byte-gleich" if alt.get(bestand) == neu.get(bestand) else "VERÄNDERT"))
        aus()

        # --help alt == neu: die Beschreibung kommt aus der ersten Docstring-Zeile
        aus("## --help")
        hilfe_gleich = True
        for modul in ("pipeline.laden", "pipeline.einrichten"):
            ha, hn = hilfe(wa, modul), hilfe(wn, modul)
            gleich = ha == hn and ha.startswith("rc=0")
            hilfe_gleich &= gleich
            aus(f"{'OK' if gleich else 'ABWEICHUNG':<12} python -m {modul} --help: "
                + (f"alt == neu ({len(hn.splitlines()) - 1} Zeilen)" if gleich
                   else "verschieden oder Fehler"))
        aus()

    abweichungen = [e for e in ergebnisse if e[1] == "ABWEICHUNG"]
    aus("## Ergebnis")
    zaehlung: dict[str, int] = {}
    for _, status, _ in ergebnisse:
        zaehlung[status] = zaehlung.get(status, 0) + 1
    aus(f"{len(ergebnisse)} Dateien: " + ", ".join(f"{k} {v}" for k, v in sorted(zaehlung.items())))
    ok = not abweichungen and hilfe_gleich and test_ok
    aus("Nur Kommentare und Docstrings geändert." if ok
        else "ABWEICHUNG gefunden (oder Selbsttest nicht bestanden), siehe oben.")
    if args.log:
        args.log.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
