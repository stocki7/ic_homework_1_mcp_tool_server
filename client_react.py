"""
ReAct-Agent-Client - Hausübung Teil 1, Option A (Technical Track)

Startet den MCP-Server (server.py) als Hintergrund-Subprozess über stdio
(Muster aus Sample 3 "MCP"), erkennt dessen Tools dynamisch und bindet sie in
eine ReAct-Schleife ein (Reason -> Act -> Observe). Das LLM wird über einen
OpenAI-kompatiblen Endpunkt angesprochen, hier direkt Gemini (Muster aus
Sample 4 "MCP Architecture", client.py).

Voraussetzung: eine .env-Datei (siehe .env.example) mit:
    LITELLM_API_BASE=https://generativelanguage.googleapis.com/v1beta/openai/
    LITELLM_KEY=<Gemini-API-Key>
    LITELLM_DEFAULT_MODEL=gemini-3.6-flash

Aufruf:
    python client_react.py
    python client_react.py "eigene Frage"
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

llm_client = OpenAI(
    base_url=os.environ.get("LITELLM_API_BASE"),
    api_key=os.environ.get("LITELLM_KEY"),
)
MODEL_NAME = os.environ.get("LITELLM_DEFAULT_MODEL", "gemini-3.6-flash")

SERVER_SCRIPT = os.path.join(os.path.dirname(__file__), "server.py")

SYSTEM_PROMPT = (
    "Du bist ein Assistent für die Lagerverwaltung mit Zugriff auf Tools für "
    "Lagerbestand, Preisberechnung und Audit-Logging. Nutze sie immer, wenn eine "
    "Frage echte Lagerdaten oder eine Rabattberechnung erfordert. Wenn die "
    "Berechnungen erledigt sind, rufe log_audit_event mit einer kurzen "
    "Zusammenfassung auf, bevor du die endgültige Antwort gibst. Antworte auf Deutsch."
)

def convert_mcp_to_openai_tools(mcp_tools):
    """Wandelt die vom MCP-Server erkannten Tools in das OpenAI JSON Schema um."""
    openai_tools = []
    for tool in mcp_tools.tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": (
                    getattr(tool, "inputSchema", None)
                    or getattr(tool, "input_schema", None)
                    or {"type": "object", "properties": {}}
                )
            }
        })
    return openai_tools

async def run_react_agent(user_prompt: str):
    print(f"Starte MCP-Server als Subprozess: {SERVER_SCRIPT}")
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[SERVER_SCRIPT, "--server-mode"],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("Mit MCP-Server verbunden.\n")

            mcp_tools = await session.list_tools()
            openai_tools = convert_mcp_to_openai_tools(mcp_tools)
            print(f"Gefundene Tools: {[t['function']['name'] for t in openai_tools]}\n")

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            # ReAct-Schleife: das LLM so lange befragen, bis es keine Tools mehr anfordert
            while True:
                print("[Reasoning] LLM wird abgefragt ...")
                response = llm_client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=messages,
                    tools=openai_tools if openai_tools else None,
                    tool_choice="auto",
                )
                response_message = response.choices[0].message

                # Fall A: das LLM liefert eine fertige Textantwort -> Schleife beendet
                if not response_message.tool_calls:
                    print("\n--- Endgültige Antwort ---")
                    print(response_message.content)
                    break

                # Fall B: das LLM möchte ein oder mehrere Tools aufrufen (Acting)
                # Als dict zurückgeben (model_dump), damit Zusatzfelder wie Geminis
                # thought_signature (extra_content) erhalten bleiben - ohne sie
                # lehnen Gemini-3-Modelle den nächsten Tool-Schritt mit 400 ab.
                messages.append(response_message.model_dump(exclude_none=True))

                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments or "{}")

                    print(f"[Action] Rufe MCP-Tool '{function_name}' auf mit {arguments}")
                    try:
                        result = await session.call_tool(function_name, arguments=arguments)
                        tool_output = (
                            result.content[0].text if result.content else str(result.structured_content)
                        )

                        tool_output = ""
                        if result.content:
                            tool_output = result.content[0].text
                        else:
                            tool_output = str(result.structured_content)

                        print(f"[Observation] Ergebnis vom MCP Server: {tool_output}\n")

                    except Exception as e:
                        tool_output = f"Fehler beim Ausführen des Tools: {e}"
                        print(f"[Observation] Toolaufruf fehlgeschlagen: {tool_output}\n")

                    messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": function_name,
                            "content": str(tool_output),
                        })

if __name__ == "__main__":
    default_prompt = (
        "Wie viele Servomotoren 750W haben wir auf Lager, und wie hoch wären der "
        "Staffelrabatt und der Endpreis, wenn ein Kunde 650 Stück davon bestellt? "
        "Lege danach einen Audit-Eintrag an."
    )
    prompt = sys.argv[1] if len(sys.argv) > 1 else default_prompt
    asyncio.run(run_react_agent(prompt))
