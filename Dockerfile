# Basis-Image über den Digest festgeschrieben, Python-Pakete mit Prüfsummen; Debian-Pakete (unzip) kommen aus dem
# Paketstand zum Bauzeitpunkt, der Build ist also nicht bitgenau wiederholbar.
# Aktualisieren: Digest erneuern (Dependabot macht dazu einen Pull Request), dann pruefen.sh.
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
# Keine .pyc-Dateien (das Dateisystem des Containers ist im Betrieb nur lesbar, siehe docker-compose.yml)
# und Ausgaben ungepuffert, damit Protokollzeilen sofort im Journal bzw. in `docker compose logs` stehen
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# unzip für ZIP-Dateien mit Deflate64 (INKAR), das Pythons zipfile nicht kann. Debian-Paket,
# über die signierten Paketquellen der Distribution geprüft.
RUN apt-get update && apt-get install -y --no-install-recommends unzip \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
# Nur Pakete mit passender Prüfsumme aus requirements.txt. --no-deps: requirements.txt nennt schon alle
# Abhängigkeiten mit fester Version (uv pip compile), pip soll nichts Ungeprüftes nachziehen
RUN pip install --no-cache-dir --require-hashes --no-deps -r requirements.txt
# Nur, was zur Laufzeit gebraucht wird; Tests, Dokumentation und Belegläufe bleiben draußen (.dockerignore
# hält zusätzlich Zugangsdaten und lokale Reste fern)
COPY pipeline/ pipeline/
# Schema pipeline_meta für `python -m pipeline.einrichten`
COPY sql/pipeline_meta.sql sql/pipeline_meta.sql
# Konfigurationen und Beispieldateien als Standard im Image; die Compose-Dateien hängen config/ zur
# Laufzeit nur lesbar vom Host ein
COPY config/ config/
COPY beispiele/ beispiele/
# Eigener Systemnutzer ohne Root-Rechte; in /app sind nur berichte/ und cache/ für ihn beschreibbar.
# Feste UID 1000: Die vom Host eingehängten Ordner berichte/ und cache/ müssen für diese UID
# beschreibbar sein
RUN useradd -r -u 1000 pipeline && mkdir -p /app/berichte /app/cache && chown pipeline /app/berichte /app/cache
USER pipeline
# Standardbefehl ist ein Lauf; Argumente hinter `docker compose run --rm pipeline` gehen an pipeline.laden
# (etwa --alle, --probelauf, --status). Die Einrichtung überschreibt den Entrypoint (pipeline.einrichten).
ENTRYPOINT ["python", "-m", "pipeline.laden"]
