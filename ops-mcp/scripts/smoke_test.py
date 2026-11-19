"""Canlı ops-mcp sunucusunu resmi MCP istemcisiyle dener: araç listesi + her aracın cevabı.

Çalıştırma (proje kökünde, PowerShell):
    $env:MCP_TOKEN = "..."     # sadece terminale yazın
    uv run --project ops-mcp python ops-mcp/scripts/smoke_test.py

İsteğe bağlı: MCP_URL (varsayılan https://ops-mcp.semihcetinkaya.tech/mcp)
"""

import asyncio
import os
import sys
import time

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

URL = os.environ.get("MCP_URL", "https://ops-mcp.semihcetinkaya.tech/mcp")
TOKEN = os.environ.get("MCP_TOKEN", "")

CALLS = [
    ("satis_ozeti", {"saat": 24, "demo_dahil": True}),
    ("odeme_durumu", {"saat": 24}),
    ("etkinlik_doluluk", {}),
    ("yaklasan_etkinlikler", {"gun": 3}),
    ("uyelik_ozeti", {}),
    ("siparis_sorgula", {"kod": "BLT-ZZZZZZ"}),
    ("sistem_sagligi", {}),
    ("aktif_alarmlar", {}),
]


async def main() -> None:
    if not TOKEN:
        sys.exit('MCP_TOKEN yok. Önce: $env:MCP_TOKEN = "..."')
    http = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "Mozilla/5.0 (compatible; ops-mcp-test/1.0)"},
        timeout=30,
    )
    async with Client(streamable_http_client(URL, http_client=http)) as c:
        tools = (await c.list_tools()).tools
        print(f"Bağlandı: {URL}\n{len(tools)} araç: {', '.join(t.name for t in tools)}\n")
        for name, args in CALLS:
            t0 = time.perf_counter()
            r = await c.call_tool(name, args)
            ms = (time.perf_counter() - t0) * 1000
            text = " ".join(getattr(p, "text", "") for p in r.content)
            print(f"[{name}] {ms:.0f} ms{'  HATA' if r.is_error else ''}\n  {text}\n")


asyncio.run(main())
