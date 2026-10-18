# Homework 1 - Option A: Eigener MCP Math- & Datenbank-Tool-Server

**Industrial Computing, MCI - Hausübung Teil 1, Technical Track**

**Stockinger Rene**

Erweitert den FastMCP-Basiscode aus der Lehrveranstaltung (siehe `Sample 3 MCP`
und `Sample 4 MCP Architecture` in [chmaurer/mci_industrial_computing](https://github.com/chmaurer/mci_industrial_computing))
zu einem kleinen MCP-Server mit drei Tools, die in eine lokale, ReAct-basierte
LLM-Agentenschleife eingebunden sind.

## Was umgesetzt wurde

| Tool | Typ | Beschreibung |
|---|---|---|
| `lookup_inventory` | SQL-Abfrage | Durchsucht eine lokale SQLite-Tabelle `products` (wird beim ersten Start automatisch mit 10 Beispielartikeln befüllt) nach SKU oder Teil des Produktnamens. |
| `calculate_tiered_discount` | Formel-Engine | Berechnet einen **marginalen, stufenweisen** Mengenrabatt für eine Großbestellung - jede Einheit wird mit dem Rabattsatz der Mengenstufe rabattiert, in die sie fällt (ähnlich einer progressiven Steuerstufe). Daraus ergeben sich ein effektiver Rabattsatz und der Endpreis. |
| `log_audit_event` | Audit-Log | Hängt einen Eintrag mit Zeitstempel im JSON-Format an die lokale Datei `audit_log.jsonl` an. |

Die Tools sind über eine **OpenAI-kompatible Schnittstelle** mit einem LLM
(Gemini) verbunden und laufen in einer ReAct-Schleife (Reason -> Act -> Observe), nach
dem Muster aus `Sample 4 MCP Architecture/client.py`: Das LLM entscheidet, welche
Tools aufgerufen werden, der Client führt sie über die laufende MCP-Session aus,
gibt das Ergebnis als Beobachtung zurück und wiederholt das, bis das LLM genug
Informationen für die Antwort hat.

## Dateien

```
server.py              MCP-Server (FastMCP) - definiert die 3 Tools
client_react.py        ReAct-Agent-Client - LLM (Gemini, OpenAI-kompatibel) + dynamische Tool-Erkennung
pyproject.toml         Projekt- und Abhängigkeitsdefinition (installierbar mit uv / pip)
.env.example           Vorlage für die benötigten Umgebungsvariablen
logs/execution_log.txt Mitgeschnittene Ausgabe eines Laufs von client_react.py
inventory.db           SQLite-Datenbank (wird beim ersten Start erzeugt, in .gitignore)
audit_log.jsonl        Audit-Log-Datei (wird beim ersten Aufruf von log_audit_event erzeugt, in .gitignore)
```

## Einrichtung

Das Projekt verwendet dieselben Werkzeuge wie das Beispiel-Repo der
Lehrveranstaltung (`uv`), funktioniert aber auch mit `pip`.

**Variante A - uv:**

```bash
uv sync
```

**Variante B - pip:**

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

Danach die LLM-Zugangsdaten konfigurieren:

```bash
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
# .env bearbeiten und den Gemini-API-Key bei LITELLM_KEY eintragen
# (Modell und Gemini-Endpunkt sind in .env.example schon vorbelegt)
```

## Ausführen

**1. ReAct-Agent (benötigt eine konfigurierte `.env`)** - das LLM
erkennt die Tools dynamisch über den laufenden MCP-Server und entscheidet
selbst, welche es zur Beantwortung der Frage aufruft:

```bash
uv run python client_react.py
# oder mit einer eigenen Frage:
uv run python client_react.py "Wie viele SPS sind auf Lager?"
```

**2. Nur den Server starten** (z. B. um einen anderen MCP-Client damit zu verbinden):

```bash
uv run python server.py --server-mode
```

## Ausführungsprotokoll

Für die Abgabe wird die Ausgabe eines Laufs von `client_react.py` in
[`logs/execution_log.txt`](logs/execution_log.txt) mitgeschnitten. Darin sieht man,
wie das LLM die Tools aufruft (`[Action]`), was die Tools zurückliefern
(`[Observation]`) und die endgültige Antwort.

Protokoll erzeugen (Windows PowerShell). Die Umleitung läuft über `cmd`, damit die
Datei als UTF-8 gespeichert wird und Umlaute erhalten bleiben:

```powershell
$env:PYTHONUTF8 = "1"
cmd /c "uv run python client_react.py > logs\execution_log.txt"
Get-Content logs\execution_log.txt -Encoding UTF8
```

Unter Linux / macOS / Git Bash: `uv run python client_react.py | tee logs/execution_log.txt`
