# Output in English / Ausgaben auf Englisch, 2026-11-02

Run with `sprache: en` in `config/quellen.yaml` against an existing database (all sources unchanged since the previous run).

- `20261102T100034Z.txt`: run report. Status lines, counts and labels come from `pipeline/sprachen/en.json`; warnings and notes from the source adapters stay German (decision E21 in `docs/entscheidungen.md`).
- `20261102T100034Z-meldung-kaputte_quelle.txt`: draft report to a provider for the deliberately unreachable sample source. Nothing is sent automatically.
- `quellenverzeichnis.md`: source register.
- `20261102T100034Z.json`: machine-readable report (field names are the same in every language, `"sprache": "en"`).

The change map of the run (`…-karte.html`, 7.5 MB) is left out; it uses the same English labels (base map, legend, pop-ups).

Lauf mit `sprache: en`; Zählungen, Statuszeilen und Beschriftungen aus `pipeline/sprachen/en.json`, Warnungen und Hinweise der Adapter bleiben deutsch.
