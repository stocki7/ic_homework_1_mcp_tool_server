"""
MCP-Server - Hausübung Teil 1, Option A (Technical Track)
Eigener MCP Math- & Datenbank-Tool-Server

Stellt drei MCP-Tools auf Basis des FastMCP-Basiscodes der Lehrveranstaltung
bereit (siehe Sample 3 "MCP" und Sample 4 "MCP Architecture" im Kurs-Repo):

1. lookup_inventory          - SQL-Abfrage (sqlite3) auf eine Produkt-Lagertabelle
2. calculate_tiered_discount - Formel-Engine für komplexe, marginale
                                (stufenweise) Mengenrabatte bei Großbestellungen
3. log_audit_event           - hängt strukturierte Ereignisse an eine lokale
                                Audit-Log-Datei an

Startmodi:
    python server.py --server-mode   -> läuft als eigenständiger MCP-Server (stdio)
    python server.py                 -> gibt eine Kurzanleitung aus

Normalerweise wird diese Datei nicht direkt gestartet - `client_react.py`
startet sie als Hintergrund-Subprozess über stdio, genau nach dem Muster aus
Sample 3.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Pfade / Konstanten
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "inventory.db"
AUDIT_LOG_PATH = BASE_DIR / "audit_log.jsonl"
DISCOUNT_TIERS: list[tuple[int, float]] = [
    (0, 0.00),
    (50, 0.05),
    (200, 0.10),
    (500, 0.15),
    (1000, 0.20),
]

server_mcp = FastMCP("Industrial-Computing-Homework-1")

# ---------------------------------------------------------------------------
# Datenbank-Initialisierung (Beispiel-Lagerbestand)
# ---------------------------------------------------------------------------
def _init_db() -> None:
    """Legt die SQLite-Lagerdatenbank beim ersten Start an und befüllt sie."""
    if DB_PATH.exists():
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE products (
            sku               TEXT PRIMARY KEY,
            name              TEXT NOT NULL,
            category          TEXT NOT NULL,
            quantity_on_hand  INTEGER NOT NULL,
            unit_price        REAL NOT NULL
        )
        """
    )
    sample_products = [
        ("SKU-1001", "Rillenkugellager 6205", "Mechanik", 4200, 3.45),
        ("SKU-1002", "SPS-Modul CPU-1214C", "Automatisierung", 150, 289.00),
        ("SKU-1003", "Näherungsschalter M18", "Sensorik", 1800, 14.90),
        ("SKU-1004", "Servomotor 750W", "Automatisierung", 65, 412.50),
        ("SKU-1005", "Hydraulikschlauch 10m", "Mechanik", 320, 58.20),
        ("SKU-1006", "Sicherheitslichtvorhang", "Sicherheit", 42, 610.00),
        ("SKU-1007", "Frequenzumrichter 5,5kW", "Automatisierung", 97, 340.75),
        ("SKU-1008", "Förderbandrolle", "Mechanik", 510, 22.10),
        ("SKU-1009", "Temperaturmessumformer", "Sensorik", 730, 76.30),
        ("SKU-1010", "Not-Halt-Taster", "Sicherheit", 1250, 9.85),
    ]
    conn.executemany(
        "INSERT INTO products (sku, name, category, quantity_on_hand, unit_price) "
        "VALUES (?, ?, ?, ?, ?)",
        sample_products,
    )
    conn.commit()
    conn.close()

_init_db()

# ---------------------------------------------------------------------------
# TOOL 1: SQL-Datenbankabfrage (sqlite3) - Produkt-Lagerbestand
# ---------------------------------------------------------------------------
@server_mcp.tool()
def lookup_inventory(query: str) -> list[dict]:
    """Sucht den Lagerbestand eines Produkts in der SQLite-Datenbank.

    Findet Treffer über die exakte SKU (z. B. "SKU-1004") oder einen Teil des
    Produktnamens, ohne Beachtung der Groß-/Kleinschreibung (z. B. "servo").

    Args:
        query: SKU oder Teil des Produktnamens.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT sku, name, category, quantity_on_hand, unit_price FROM products "
        "WHERE sku = ? OR name LIKE ?",
        (query, f"%{query}%"),
    ).fetchall()
    conn.close()

    results = [dict(row) for row in rows]
    if not results:
        return [{"message": f"Keine Produkte gefunden, die zu '{query}' passen."}]
    return results

# ---------------------------------------------------------------------------
# TOOL 2: Formel-Engine - komplexe, stufenweise (marginale) Mengenrabatte
# ---------------------------------------------------------------------------
@server_mcp.tool()
def calculate_tiered_discount(order_volume: int, unit_price: float) -> dict:
    """Berechnet einen komplexen, marginalen (stufenweisen) Mengenrabatt für eine Großbestellung.

    Statt beim Überschreiten einer Mengenschwelle einen einzigen Rabattsatz
    auf die ganze Bestellung anzuwenden, wird jede Einheit mit dem Satz der
    Stufe rabattiert, in die sie fällt (wie bei einer progressiven
    Steuerstufe). Daraus ergeben sich ein effektiver Rabattsatz und der Endpreis.

    Args:
        order_volume: Bestellte Stückzahl, muss größer als 0 sein.
        unit_price: Listenpreis pro Stück vor Rabatt.
    """
    if order_volume <= 0 or unit_price < 0:
        return {"error": "order_volume muss > 0 und unit_price muss >= 0 sein."}

    breakdown = []
    total_discount_amount = 0.0

    for index, (lower, rate) in enumerate(DISCOUNT_TIERS):
        if order_volume <= lower:
            break
        upper = DISCOUNT_TIERS[index + 1][0] if index + 1 < len(DISCOUNT_TIERS) else None
        units_in_tier = (min(order_volume, upper) if upper is not None else order_volume) - lower
        if units_in_tier <= 0:
            continue

        band_value = units_in_tier * unit_price
        band_discount = band_value * rate
        total_discount_amount += band_discount
        breakdown.append(
            {
                "tier_range": f"{lower}-{upper - 1 if upper is not None else 'inf'}",
                "rate": rate,
                "units_in_tier": units_in_tier,
                "discount_amount": round(band_discount, 2),
            }
        )

    subtotal = order_volume * unit_price
    final_price = subtotal - total_discount_amount
    effective_rate = (total_discount_amount / subtotal) if subtotal else 0.0

    return {
        "order_volume": order_volume,
        "unit_price": unit_price,
        "subtotal": round(subtotal, 2),
        "total_discount_amount": round(total_discount_amount, 2),
        "effective_discount_rate": round(effective_rate, 4),
        "final_price": round(final_price, 2),
        "tier_breakdown": breakdown,
    }

# ---------------------------------------------------------------------------
# TOOL 3: Audit-Log-Tool, das Ereignisse an eine lokale Datei anhängt
# ---------------------------------------------------------------------------
@server_mcp.tool()
def log_audit_event(event_type: str, details: str) -> dict:
    """Hängt ein strukturiertes Audit-Ereignis an die lokale Audit-Log-Datei an.

    Jeder Aufruf wird als eine JSON-Zeile mit UTC-Zeitstempel in
    audit_log.jsonl geschrieben, sodass sich genau nachvollziehen lässt, was
    in einer Session passiert ist.

    Args:
        event_type: Kurze Kategorie, z. B. "INVENTORY_LOOKUP",
            "DISCOUNT_CALCULATED", "AGENT_RUN".
        details: Freitext-Beschreibung des Ereignisses.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "details": details,
    }
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "protokolliert", "entry": entry}

# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if "--server-mode" in sys.argv:
        server_mcp.run()
    else:
        print(
            "Diese Datei definiert den MCP-Server und ist nicht zum direkten Start gedacht.\n"
            "Stattdessen den Client verwenden:\n"
            "  python client_react.py        # vollständige ReAct-Agentenschleife mit Gemini\n"
            "Oder den MCP-Server selbst starten mit:\n"
            "  python server.py --server-mode"
        )
