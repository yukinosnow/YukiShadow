#!/usr/bin/env python
"""
YukiShadow CLI Chat

Interactive terminal interface that talks to the orchestrator agent.
Each session has its own conversation history (keyed by session ID).

Usage:
  python cli_chat.py                       # default session
  python cli_chat.py --session debug_01    # named session (isolated history)
  python cli_chat.py --url http://...      # custom orchestrator URL

Built-in commands:
  /clear      clear conversation history for this session
  /skills     list loaded skills
  /status     show orchestrator + Discord service health
  /quit       exit  (also: Ctrl-C or Ctrl-D)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

import httpx

# ── ANSI colours ─────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
GREY   = "\033[90m"


def _c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get(client: httpx.AsyncClient, url: str) -> dict | None:
    try:
        r = await client.get(url, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


async def _post(client: httpx.AsyncClient, url: str, body: dict) -> dict | None:
    try:
        r = await client.post(url, json=body, timeout=60)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        return {"error": "Cannot connect to orchestrator. Is it running?  →  python main.py orchestrator"}
    except Exception as e:
        return {"error": str(e)}


def _print_result(result: dict) -> None:
    """Pretty-print an agent response."""
    reply = result.get("reply", "")
    if reply:
        print(_c(CYAN, f"\nYukiShadow › ") + reply)

    # Show skill execution details
    if result.get("type") == "skill_call":
        skill  = result.get("skill", "?")
        action = result.get("action", "?")
        sr     = result.get("skill_result", {})

        if sr.get("success"):
            tag = _c(GREEN, "✓")
            detail = sr.get("message") or json.dumps(sr.get("data"), ensure_ascii=False)
        else:
            tag = _c(RED, "✗")
            detail = sr.get("error", "unknown error")

        print(_c(GREY, f"  [{tag}{GREY} {skill}.{action} → {detail}]{RESET}"))

    print()


# ── Main loop ─────────────────────────────────────────────────────────────────

async def run(base_url: str, session_id: str) -> None:
    print(_c(BOLD, "\n╭─ YukiShadow CLI Chat ──────────────────────────────╮"))
    print(f"│  Orchestrator : {_c(CYAN, base_url):<44}│")
    print(f"│  Session      : {_c(YELLOW, session_id):<44}│")
    print(_c(BOLD, "│  Commands     : /clear  /skills  /status  /quit   │"))
    print(_c(BOLD, "╰────────────────────────────────────────────────────╯\n"))

    loop = asyncio.get_event_loop()

    async with httpx.AsyncClient() as client:
        while True:
            # Async-friendly input (doesn't block the event loop)
            try:
                line: str = await loop.run_in_executor(
                    None, lambda: input(_c(BOLD + YELLOW, "You › "))
                )
            except (KeyboardInterrupt, EOFError):
                print(_c(DIM, "\nGoodbye!"))
                break

            text = line.strip()
            if not text:
                continue

            # ── Built-in commands ─────────────────────────────────────────
            if text.lower() in ("/quit", "/exit", "/q"):
                print(_c(DIM, "Goodbye!"))
                break

            if text.lower() == "/clear":
                r = await _get(client, f"{base_url}/chat/history/{session_id}")
                if "error" not in (r or {}):
                    print(_c(DIM, f"  History cleared for session '{session_id}'\n"))
                else:
                    print(_c(RED, f"  {r.get('error')}\n"))
                continue

            if text.lower() == "/skills":
                data = await _get(client, f"{base_url}/skills")
                if "error" in (data or {}):
                    print(_c(RED, f"  {data['error']}\n"))
                else:
                    print(_c(BOLD, "\n  Available Skills"))
                    for s in data.get("skills", []):
                        actions = ", ".join(s.get("actions", []))
                        print(f"  • {_c(CYAN, s['name']):<30} {s['description']}")
                        print(_c(GREY, f"    actions: {actions}"))
                    print()
                continue

            if text.lower() == "/status":
                orch = await _get(client, f"{base_url}/health")
                print(f"\n  Orchestrator  {_c(GREEN, '✓ ' + orch.get('status','?')) if 'error' not in orch else _c(RED, '✗ ' + orch.get('error',''))}")

                try:
                    from core.config import settings
                    discord_url = settings.discord_service_url
                except Exception:
                    discord_url = "http://localhost:8090"
                disc = await _get(client, f"{discord_url}/health")
                if "error" not in disc:
                    bot_user = disc.get("bot_user") or "not ready"
                    latency  = disc.get("latency_ms", "?")
                    redis_ok = "✓" if disc.get("redis_connected") else "✗"
                    print(f"  Discord svc   {_c(GREEN, '✓')} {bot_user}  {latency} ms  Redis:{redis_ok}")
                else:
                    print(f"  Discord svc   {_c(RED, '✗ ' + disc.get('error',''))}")
                print()
                continue

            # ── Send to agent ─────────────────────────────────────────────
            print(_c(DIM, "  …thinking"), end="\r", flush=True)

            result = await _post(client, f"{base_url}/chat", {
                "content": text,
                "channel_id": session_id,
            })

            # Clear the "…thinking" line
            print(" " * 30, end="\r")

            if result is None or "error" in result:
                print(_c(RED, f"\n  Error: {(result or {}).get('error', 'no response')}\n"))
                continue

            _print_result(result)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="YukiShadow CLI Chat")
    parser.add_argument(
        "--url",
        default="http://localhost:8080",
        help="Orchestrator base URL (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--session",
        default=f"cli_{uuid.uuid4().hex[:8]}",
        help="Session ID for conversation history (default: random)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run(args.url.rstrip("/"), args.session))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
