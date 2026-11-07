#!/bin/sh
# Prüfungen vor jedem Commit und in der CI. Bricht beim ersten Fehler ab.
#   ruff        Stil und typische Fehler, inkl. Sicherheitsregeln (S)
#   bandit      Sicherheitsprüfung des Codes
#   pip-audit   bekannte Lücken in den festgeschriebenen Abhängigkeiten
#   pytest      Tests ohne Netz und ohne Datenbank
#   Secrets     Zugangsdaten im Repository: gitleaks, sonst detect-secrets
#   sbom        Stückliste der Abhängigkeiten (CycloneDX) nach sbom.cdx.json
# Braucht uv (https://docs.astral.sh/uv/); uvx holt jedes Werkzeug je Aufruf in eine eigene, kurzlebige
# Umgebung. Seit E51 (Befund G2) in fester Version (werkzeug@version, --from paket==version, pytest==version;
# Stand 07.11.2026), damit ein späterer Prüflauf dieselben Werkzeuge nutzt. Festgeschrieben ist nur die
# Version des Werkzeugs selbst, nicht die seiner Abhängigkeiten und ohne Prüfsummen (anders als die
# Laufzeitabhängigkeiten in requirements.txt); aktualisiert wird von Hand, Dependabot sieht diese Zeilen
# nicht. gitleaks nimmt die installierte Version. Nicht festgelegt ist auch uv selbst (die installierte
# Version, in der CI die von setup-uv ohne version:) und damit der Python-Interpreter, den uv für die
# Prüfumgebung wählt (lokal 3.13, das Image 3.12; Nachprüfung zu E51). Für den Ersatz detect-secrets
# zusätzlich python3 (Auswertung unten); gitleaks wird genutzt, wenn es installiert ist. Pakete kommen über die Index-API
# von PyPI (/simple, die Schnittstelle für Installer), Lückendaten für pip-audit über die JSON-API von
# PyPI (/pypi/<name>/<version>/json); E49.
# -e: beim ersten Fehler abbrechen, -u: unbekannte Variable ist ein Fehler
set -eu
# Immer im Wurzelverzeichnis des Repositorys, egal von wo aus aufgerufen
cd "$(dirname "$0")"

echo "== ruff";      uvx ruff@0.17.4 check --no-cache .
echo "== bandit";    uvx -q bandit@1.9.4 -q -r pipeline
# --require-hashes: nur die festgeschriebenen Fassungen prüfen; --disable-pip: die Abhängigkeiten
# nicht erst installieren, sondern direkt aus requirements.txt lesen
echo "== pip-audit"; uvx -q pip-audit@2.10.1 -r requirements.txt --require-hashes --disable-pip
# Ohne Projektinstallation, mit den festgeschriebenen Abhängigkeiten und pytest; Tests gegen die Datenbank
# laufen nur mit DATENBANK_TEST=1 (in der CI eigener Job, siehe .github/workflows/pruefen.yml)
echo "== pytest";    uv run -q --no-project --with-requirements requirements.txt --with pytest==9.2.0 python -m pytest -q
if command -v gitleaks >/dev/null 2>&1; then
  echo "== gitleaks"; gitleaks git --no-banner --redact .
else
  echo "== detect-secrets"
  # Gibt jeden Fund mit Datei, Zeile und Art aus (nie den Wert selbst) und scheitert, wenn es einen gibt
  # Commit-Hashes (40 Hex-Zeichen) in Metadaten und die SHA-256-Prüfsumme einer Quelldatei in den Laufberichten
  # (64 Hex-Zeichen, seit E52) sind keine Geheimnisse, nur genau diese Felder ausnehmen.
  uvx -q detect-secrets@1.5.0 scan --exclude-lines '"(gitCommitHash|commit)": "[0-9a-f]{40}"|"(datei_)?sha256": "[0-9a-f]{64}"' | python3 -c '
import json, sys
funde = json.load(sys.stdin)["results"]
for datei, liste in funde.items():
    for f in liste:
        zeile, art = f["line_number"], f["type"]
        print(f"  {datei}:{zeile} {art}")
sys.exit(1 if funde else 0)'
fi
# Stückliste aus requirements.txt; sbom.cdx.json ist ein Erzeugnis und steht nicht im Repository
echo "== sbom";      uvx -q --from cyclonedx-bom==8.0.1 cyclonedx-py requirements requirements.txt \
                       --of JSON -o sbom.cdx.json
echo "Alles in Ordnung."
