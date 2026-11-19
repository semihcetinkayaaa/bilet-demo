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
    ("bugunku_satis", {"demo_dahil": True}),
    ("en_cok_satanlar", {"saat": 168, "demo_dahil": True}),
    ("satis_kirilimi", {"saat": 168, "gore": "kategori", "demo_dahil": True}),
    ("satis_kirilimi", {"saat": 168, "gore": "sehir", "demo_dahil": True}),
    ("etkinlik_satisi", {"ad": "konser"}),
    ("bekleyen_siparisler", {}),
    ("son_siparisler", {"adet": 3, "demo_dahil": True}),
    ("tukenen_biletler", {"saat": 168}),
    ("servis_durumu", {}),
    ("servis_durumu", {"servis": "backend"}),
    ("disk_tahmini", {}),
    ("son_hatalar", {"dakika": 60}),
    ("api_performansi", {"dakika": 60}),
    ("giris_durumu", {"saat": 24}),
]


def precheck() -> None:
    """MCP istemcisinden önce düz bir istekle durum kodunu göster (hata nedenini anlamak için)."""
    import httpx

    print(f"Anahtar uzunluğu: {len(TOKEN)} karakter"
          + ("  (başında/sonunda boşluk ya da tırnak var!)" if TOKEN != TOKEN.strip().strip('"\'') else ""))
    r = httpx.post(
        URL,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream",
                 "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (compatible; ops-mcp-test/1.0)"},
        timeout=20,
    )
    print(f"Ön kontrol: HTTP {r.status_code}  {r.text[:300]}")
    hints = {
        401: "Anahtar Coolify'daki MCP_TOKEN ile aynı değil (boşluk/tırnak olabilir).",
        421: "Host başlığı reddedildi: Coolify'da ALLOWED_HOSTS ayarı gerekiyor.",
        403: "Cloudflare ya da sunucu isteği engelledi.",
    }
    if r.status_code in hints:
        sys.exit("→ " + hints[r.status_code])
    print()


async def main() -> None:
    if not TOKEN:
        sys.exit('MCP_TOKEN yok. Önce: $env:MCP_TOKEN = "..."')
    precheck()
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
