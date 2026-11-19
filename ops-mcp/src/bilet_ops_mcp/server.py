"""semihcetinkaya.tech operasyon MCP sunucusu.

Sadece OKUMA yapan araçlar; cevaplar telefonda sesli okunacak kısa Türkçe metinlerdir.
Veri kaynakları: bilet veritabanı (salt okunur), Prometheus, Grafana alarmları, backend sağlık ucu.
"""

import asyncio
import functools
import logging
import re
import secrets
from datetime import datetime

import anyio
import httpx
import psycopg
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from bilet_ops_mcp import speak as s
from bilet_ops_mcp.config import settings

log = logging.getLogger("bilet_ops_mcp")
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
REAL = "o.buyer_email NOT LIKE '%%@example.com'"  # demo siparişleri hariç (psycopg için % kaçışlı)
UA = {"User-Agent": "Mozilla/5.0 (compatible; bilet-ops-mcp/1.0)"}

mcp = MCPServer(
    name="bilet-operasyon",
    title="semihcetinkaya.tech operasyon",
    instructions=(
        "semihcetinkaya.tech bilet satış sisteminin operasyon araçları. Sadece okuma yapar. "
        "Cevaplar Türkçe ve telefonda okunacak kadar kısadır; sayıları olduğu gibi söyleyebilirsin. "
        "Kullanıcı satışları sorarsa satis_ozeti, ödeme sorunlarını sorarsa odeme_durumu, "
        "sunucuyu sorarsa sistem_sagligi, alarmları sorarsa aktif_alarmlar aracını kullan."
    ),
    version="1.0.0",
)


# --------------------------------------------------------------------------- veri erişimi


def friendly(fn):
    """Araç hata verirse istemciye teknik hata yerine sesli okunabilir bir cümle döndür."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except psycopg.Error:
            log.exception("db_error", extra={"tool": fn.__name__})
            return "Veritabanına şu an ulaşamıyorum, bu bilgiyi getiremedim. Biraz sonra tekrar deneyebilirim."
        except Exception:
            log.exception("tool_error", extra={"tool": fn.__name__})
            return "Bu bilgiyi getirirken beklenmeyen bir sorun oldu."

    return wrapper


def _query_sync(sql: str, params: dict | None = None) -> list[tuple]:
    with psycopg.connect(
        settings.database_url,
        connect_timeout=3,  # telefonda uzun sessizlik olmasın
        options="-c statement_timeout=5000 -c default_transaction_read_only=on",
        autocommit=True,
    ) as conn:
        return conn.execute(sql, params or {}).fetchall()


async def query(sql: str, params: dict | None = None) -> list[tuple]:
    return await anyio.to_thread.run_sync(lambda: _query_sync(sql, params))


async def prom(expr: str) -> float | None:
    """Prometheus anlık sorgusu; tek sayı döndürür (yoksa None)."""
    if not settings.prometheus_url:
        return None
    async with httpx.AsyncClient(timeout=4, headers=UA) as c:
        r = await c.get(f"{settings.prometheus_url.rstrip('/')}/api/v1/query", params={"query": expr})
        r.raise_for_status()
        res = r.json()["data"]["result"]
        return float(res[0]["value"][1]) if res else None


def _baseline(expr: str, hours: int, real: str) -> str:
    """Karşılaştırma tabanı.

    < 24 saat: geçen 7 günün aynı saat aralığının ortalaması (günün saatine göre adil).
    >= 24 saat: hemen önceki eşit uzunluktaki dönem (ör. son 7 gün vs. ondan önceki 7 gün).
    """
    if hours < 24:
        return f"""
SELECT COALESCE({expr}, 0) / 7.0 FROM generate_series(1, 7) AS d
JOIN orders o ON o.paid_at >= now() - make_interval(days => d, hours => %(h)s)
             AND o.paid_at <  now() - make_interval(days => d)
WHERE o.status = 'paid' AND {real}"""
    return f"""
SELECT COALESCE({expr}, 0) FROM orders o
WHERE o.status = 'paid' AND {real}
  AND o.paid_at >= now() - make_interval(hours => 2 * %(h)s)
  AND o.paid_at <  now() - make_interval(hours => %(h)s)"""


def _hours(h: int) -> int:
    return max(1, min(int(h), 24 * 7))


# --------------------------------------------------------------------------- araçlar


@mcp.tool(annotations=READ_ONLY)
@friendly
async def satis_ozeti(saat: int = 1, demo_dahil: bool = False) -> str:
    """Son N saatin satışları: ciro, bilet ve sipariş sayısı, normale göre karşılaştırma.

    saat: kaç saatlik dönem (1-168; ör. bugün için 24, bu hafta için 168).
    demo_dahil: @example.com demo siparişlerini de say (varsayılan hayır).
    """
    h = _hours(saat)
    real = "TRUE" if demo_dahil else REAL
    cur = await query(f"""
        SELECT COALESCE(SUM(o.total_amount), 0), COUNT(*),
               COALESCE((SELECT SUM(oi.quantity) FROM order_items oi JOIN orders o2 ON o2.id = oi.order_id
                         WHERE o2.status = 'paid' AND o2.paid_at >= now() - make_interval(hours => %(h)s)
                           AND {real.replace('o.', 'o2.')}), 0)
        FROM orders o
        WHERE o.status = 'paid' AND o.paid_at >= now() - make_interval(hours => %(h)s) AND {real}""", {"h": h})
    base = await query(_baseline("SUM(o.total_amount)", h, real), {"h": h})
    revenue, orders, tickets = float(cur[0][0]), int(cur[0][1]), int(cur[0][2])
    period = s.period(h).capitalize()
    if orders == 0:
        note = "" if demo_dahil else " Demo siparişleri saymadım."
        return f"{period} hiç ödenmiş sipariş yok.{note}"
    return (f"{period} {s.num(orders)} sipariş, {s.num(tickets)} bilet ve {s.tl(revenue)} ciro var. "
            f"Ciro {s.compare(revenue, float(base[0][0]), s.baseline_label(h))}.")


@mcp.tool(annotations=READ_ONLY)
@friendly
async def odeme_durumu(saat: int = 1) -> str:
    """Son N saatteki ödemelerin durumu: başarılı, reddedilen, bekleyen ve başarı oranı (demo siparişleri hariç)."""
    h = _hours(saat)
    rows = await query(f"""
        SELECT o.status, COUNT(*) FROM orders o
        WHERE {REAL} AND o.created_at >= now() - make_interval(hours => %(h)s) GROUP BY 1""", {"h": h})
    c = {status: n for status, n in rows}
    paid, failed = c.get("paid", 0), c.get("failed", 0)
    stuck = (await query(f"""
        SELECT COUNT(*) FROM orders o WHERE {REAL} AND o.status = 'pending'
          AND o.created_at < now() - interval '15 minutes' AND o.created_at >= now() - interval '1 day'"""))[0][0]
    period = s.period(h).capitalize()
    if paid + failed == 0:
        msg = f"{period} hiç ödeme denemesi olmadı."
    else:
        rate = paid / (paid + failed)
        verdict = "durum normal" if rate >= 0.8 else "başarı oranı düşük, kontrol etmek gerekebilir"
        msg = (f"{period} {s.num(paid + failed)} ödeme denemesinin {s.num(paid)} tanesi başarılı, "
               f"{s.num(failed)} tanesi reddedildi; başarı oranı {s.pct(rate)}, {verdict}.")
    if stuck:
        msg += f" Ayrıca {s.num(stuck)} sipariş 15 dakikadan uzun süredir ödeme adımında bekliyor."
    return msg


@mcp.tool(annotations=READ_ONLY)
@friendly
async def etkinlik_doluluk(esik: float = 0.8, adet: int = 5) -> str:
    """Yaklaşan etkinliklerden doluluğu en yüksek olanlar ve tükenmiş bilet tipleri.

    esik: bu oranın (0-1) üstündeki etkinlikleri listele. adet: en fazla kaç etkinlik.
    """
    esik = max(0.0, min(esik, 1.0))
    limit = max(1, min(adet, 10))
    rows = await query("""
        SELECT e.title, v.city, e.starts_at, SUM(tt.sold)::float / NULLIF(SUM(tt.quota), 0) AS fill,
               array_remove(array_agg(CASE WHEN tt.sold >= tt.quota THEN tt.name END ORDER BY tt.price), NULL)
        FROM events e JOIN venues v ON v.id = e.venue_id JOIN ticket_types tt ON tt.event_id = e.id
        WHERE e.is_published AND e.starts_at >= now()
        GROUP BY e.id, e.title, v.city, e.starts_at
        HAVING SUM(tt.sold)::float / NULLIF(SUM(tt.quota), 0) >= %(esik)s
            OR COUNT(*) FILTER (WHERE tt.sold >= tt.quota) > 0
        ORDER BY fill DESC, e.starts_at""", {"esik": esik})
    full = [r for r in rows if (r[3] or 0) >= esik]
    partial = [r for r in rows if (r[3] or 0) < esik]
    if not rows:
        return f"Doluluğu {s.pct(esik)} üstünde olan ya da bileti tükenmiş yaklaşan etkinlik yok."

    def where(title, city, starts):
        return f"{title}, {city}, {s.when(starts)}"

    def sold_out_text(names):
        return f"{', '.join(names)} biletleri tükendi" if names else ""

    sentences = []
    if full:
        items = [f"{where(t, c, st)}, {s.pct(f)} dolu" + (f", {sold_out_text(n)}" if n else "")
                 for t, c, st, f, n in full[:limit]]
        sentences.append(f"Doluluğu {s.pct(esik)} üstünde {len(full)} etkinlik var: " + "; ".join(items))
    else:
        sentences.append(f"Doluluğu {s.pct(esik)} üstünde etkinlik yok")
    if partial:
        items = [f"{where(t, c, st)}: {sold_out_text(n)}" for t, c, st, f, n in partial[:limit]]
        more = f", toplam {len(partial)} etkinlikte durum böyle" if len(partial) > limit else ""
        sentences.append("Bazı etkinliklerde ise bir bilet tipi tükendi: " + "; ".join(items) + more)
    return ". ".join(sentences) + "."


@mcp.tool(annotations=READ_ONLY)
@friendly
async def yaklasan_etkinlikler(gun: int = 7, sehir: str = "", kategori: str = "", adet: int = 5) -> str:
    """Önümüzdeki N gündeki etkinlikler (isteğe bağlı şehir ve kategori: konser, maç, sinema, tiyatro)."""
    cat_map = {v: k for k, v in s.CATEGORY.items()} | {"mac": "match"}
    cat = cat_map.get(kategori.strip().lower(), kategori.strip().lower()) if kategori else ""
    rows = await query("""
        SELECT e.title, e.category, v.name, v.city, e.starts_at,
               SUM(tt.quota - tt.sold) AS remaining
        FROM events e JOIN venues v ON v.id = e.venue_id JOIN ticket_types tt ON tt.event_id = e.id
        WHERE e.is_published AND e.starts_at >= now() AND e.starts_at < now() + make_interval(days => %(gun)s)
          AND (%(sehir)s = '' OR lower(v.city) = lower(%(sehir)s))
          AND (%(cat)s = '' OR e.category = %(cat)s)
        GROUP BY e.id, e.title, e.category, v.name, v.city, e.starts_at
        ORDER BY e.starts_at LIMIT %(adet)s""",
        {"gun": max(1, min(gun, 90)), "sehir": sehir.strip(), "cat": cat, "adet": max(1, min(adet, 10))})
    if not rows:
        return "Bu kriterlere uyan yaklaşan etkinlik yok."
    parts = [f"{s.when(st)} {city} {s.CATEGORY.get(c, c)}: {t}, {s.num(rem)} bilet kaldı"
             for t, c, _venue, city, st, rem in rows]
    return f"Önümüzdeki {gun} gün içinde ilk {len(rows)} etkinlik: " + "; ".join(parts) + "."


@mcp.tool(annotations=READ_ONLY)
@friendly
async def uyelik_ozeti() -> str:
    """Üye sayıları: toplam, son 24 saatte kayıt olan ve giriş yapan üyeler."""
    row = (await query("""
        SELECT count(u.id),
               count(u.id) FILTER (WHERE u.created_at >= now() - interval '24 hours'),
               count(u.id) FILTER (WHERE u.last_login_at >= now() - interval '24 hours')
        FROM users u"""))[0]
    total, new, active = row
    return (f"Toplam {s.num(total)} üye var. Son 24 saatte {s.num(new)} yeni kayıt oldu "
            f"ve {s.num(active)} üye giriş yaptı.")


_CODE = re.compile(r"[^0-9A-Z]")


@mcp.tool(annotations=READ_ONLY)
@friendly
async def siparis_sorgula(kod: str) -> str:
    """Sipariş koduyla (ör. BLT-7K3QX9) siparişin durumu, etkinliği ve tutarı. Alıcı adı baş harfleriyle verilir."""
    raw = _CODE.sub("", kod.upper())
    raw = raw[3:] if raw.startswith("BLT") and len(raw) == 9 else raw
    if len(raw) != 6:
        return "Sipariş kodu BLT tire ve altı karakterden oluşmalı. Kodu tekrar söyler misin?"
    code = f"BLT-{raw}"
    rows = await query("""
        SELECT o.status, o.total_amount, o.buyer_name, o.created_at, o.user_id IS NOT NULL,
               e.title, v.city, e.starts_at, SUM(oi.quantity)
        FROM orders o JOIN order_items oi ON oi.order_id = o.id
        JOIN ticket_types tt ON tt.id = oi.ticket_type_id JOIN events e ON e.id = tt.event_id
        JOIN venues v ON v.id = e.venue_id
        WHERE o.code = %(code)s
        GROUP BY o.id, e.id, v.id""", {"code": code})
    if not rows:
        return f"{s.spell_code(code)} koduyla bir sipariş bulamadım. Kodu tekrar kontrol eder misin?"
    status, total, name, created, member, title, city, starts, tickets = rows[0]
    who = "üye" if member else "misafir"
    return (f"Sipariş {s.STATUS.get(status, status)}. {title}, {city}, {s.when(starts)} için {s.num(tickets)} bilet, "
            f"toplam {s.tl(total)}. {s.ago(created)} {who} olarak {s.mask_name(name)} tarafından verildi.")


KEY_CONTAINERS = {"site": "j4ov4fqpvovjdqf38rj56ldg.*", "backend": "lhaabzf16e1csryupsbapana.*",
                  "veritabanı": "whtf1pa3ezbbm82btp8aeu2o.*"}


@mcp.tool(annotations=READ_ONLY)
@friendly
async def sistem_sagligi() -> str:
    """Sunucu ve servislerin durumu: CPU, bellek, disk, site/backend/veritabanı ayakta mı."""
    async def backend_ok() -> bool:
        async with httpx.AsyncClient(timeout=4, headers=UA) as c:
            return (await c.get(f"{settings.backend_url.rstrip('/')}/health/db")).status_code == 200

    async def safe(coro):
        try:
            return await coro
        except Exception:
            return None

    exprs = {
        "cpu": '100 * (1 - avg(rate(node_cpu_seconds_total{job="node", mode="idle"}[5m])))',
        "ram": '100 * (1 - node_memory_MemAvailable_bytes{job="node"} / node_memory_MemTotal_bytes{job="node"})',
        "disk": '100 * (1 - node_filesystem_avail_bytes{job="node", mountpoint="/"} '
                '/ node_filesystem_size_bytes{job="node", mountpoint="/"})',
    } | {k: f'count(container_last_seen{{job="cadvisor", name=~"{rx}"}})' for k, rx in KEY_CONTAINERS.items()}
    keys = list(exprs)
    results = await asyncio.gather(*(safe(prom(exprs[k])) for k in keys), safe(backend_ok()))
    v = dict(zip(keys, results[:-1]))
    api_ok = results[-1]

    parts = []
    if v["cpu"] is None and v["ram"] is None:
        parts.append("Sunucu metriklerine şu an ulaşamıyorum")
    else:
        level = lambda x, warn, crit: "kritik" if x >= crit else "yüksek" if x >= warn else "normal"  # noqa: E731
        parts.append(f"İşlemci yüzde {round(v['cpu'] or 0)} ({level(v['cpu'] or 0, 75, 90)}), "
                     f"bellek yüzde {round(v['ram'] or 0)} ({level(v['ram'] or 0, 80, 90)}), "
                     f"disk yüzde {round(v['disk'] or 0)} dolu ({level(v['disk'] or 0, 75, 85)})")
    down = [k for k in KEY_CONTAINERS if v[k] is not None and v[k] == 0]
    if api_ok is True:
        parts.append("backend ve veritabanı yanıt veriyor")
    elif api_ok is False:
        parts.append("DİKKAT: backend ya da veritabanı sağlık kontrolüne yanıt vermiyor")
    else:
        parts.append("backend'e ulaşamadım")
    if down:
        parts.append("çalışmayan servis: " + ", ".join(down))
    return ". ".join(p[0].upper() + p[1:] for p in parts) + "."


@mcp.tool(annotations=READ_ONLY)
@friendly
async def aktif_alarmlar() -> str:
    """Grafana'da şu an tetiklenmiş (firing) alarmlar, önem derecesiyle."""
    if not (settings.grafana_url and settings.grafana_token):
        return "Grafana bağlantısı ayarlanmamış, alarmları göremiyorum."
    try:
        async with httpx.AsyncClient(timeout=5, headers=UA | {"Authorization": f"Bearer {settings.grafana_token}"}) as c:
            r = await c.get(f"{settings.grafana_url.rstrip('/')}/api/alertmanager/grafana/api/v2/alerts",
                            params={"active": "true", "silenced": "false", "inhibited": "false"})
            r.raise_for_status()
            alerts = r.json()
    except Exception:
        log.exception("grafana_alerts_failed")
        return "Grafana'ya şu an ulaşamıyorum, alarmları kontrol edemedim."
    if not alerts:
        return "Şu an tetiklenmiş alarm yok, her şey normal görünüyor."
    order = {"kritik": 0, "uyari": 1, "bilgi": 2}
    alerts.sort(key=lambda a: order.get(a.get("labels", {}).get("onem", ""), 9))
    sev = {"kritik": "kritik", "uyari": "uyarı", "bilgi": "bilgi"}
    parts = []
    for a in alerts[:5]:
        lab, ann = a.get("labels", {}), a.get("annotations", {})
        since = s.ago(datetime.fromisoformat(a["startsAt"].replace("Z", "+00:00"))) if a.get("startsAt") else ""
        parts.append(f"{sev.get(lab.get('onem'), lab.get('onem', ''))}: {lab.get('alertname', 'alarm')}, "
                     f"{ann.get('summary', '')}, {since} başladı")
    more = f" Toplam {len(alerts)} alarm var, ilk beşini söyledim." if len(alerts) > 5 else ""
    return f"{len(alerts)} tetiklenmiş alarm var. " + "; ".join(parts) + "." + more


# --------------------------------------------------------------------------- HTTP uygulaması


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _auth_problem(got: bytes) -> str:
    """Reddedilen başlığın NEDENİNİ anlatır; anahtarın kendisini asla yazmaz."""
    if not got:
        return "authorization başlığı yok"
    text = got.decode("latin-1")
    if not text.startswith("Bearer "):
        first = text.split(" ", 1)[0]
        # Sadece bilinen şema adlarını yaz; başında 'Bearer' olmayan çıplak anahtarın parçası loglara düşmesin
        scheme = f"şema {first!r}" if first.lower() in {"basic", "token", "bearer:", "apikey", "api-key"} else "şema yok"
        return f"'Bearer ' ile başlamıyor ({scheme}, toplam uzunluk {len(text)})"
    token = text[7:]
    if token.startswith("Bearer "):
        return "'Bearer' iki kez yazılmış"
    if token != token.strip():
        return "anahtarın başında/sonunda boşluk var"
    return f"anahtar uyuşmuyor (gelen uzunluk {len(token)}, beklenen {len(settings.mcp_token)})"


class BearerAuth:
    """/mcp için 'Authorization: Bearer <MCP_TOKEN>' ya da 'X-Api-Key: <MCP_TOKEN>' zorunlu (sabit zamanlı).

    /health ve tarayıcı ön kontrolü (OPTIONS) anahtarsız geçer; OPTIONS'a CORS katmanı cevap verir.
    """

    def __init__(self, app):
        self.app = app
        self.expected = f"Bearer {settings.mcp_token}".encode()
        self.expected_key = settings.mcp_token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] != "/health" and scope["method"] != "OPTIONS":
            headers = dict(scope.get("headers") or [])
            got = headers.get(b"authorization", b"")
            # Alternatif: bazı istemciler (ör. ElevenLabs secret başlıkları) Authorization göndermeyebiliyor
            api_key = headers.get(b"x-api-key", b"")
            ok = secrets.compare_digest(got, self.expected) or (
                bool(api_key) and secrets.compare_digest(api_key.strip(), self.expected_key)
            )
            if not ok:
                if api_key:
                    reason = f"x-api-key uyuşmuyor (gelen uzunluk {len(api_key)}, beklenen {len(self.expected_key)})"
                else:
                    reason = _auth_problem(got)
                log.warning("auth_failed: %s", reason)
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_app():
    if len(settings.mcp_token) < 32:
        raise RuntimeError("MCP_TOKEN en az 32 karakter olmalı")
    app = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        host="0.0.0.0",
        # DNS rebinding koruması yereldeki (localhost) sunucular içindir; burada asıl koruma
        # zorunlu Bearer anahtarı. Origin kontrolü ElevenLabs gibi istemcileri gereksiz yere reddediyordu.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    # Bağlantı testi tarayıcıdan yapılırsa diye: sadece ElevenLabs alan adlarına CORS izni
    return CORSMiddleware(
        BearerAuth(app),
        allow_origin_regex=r"https://([a-z0-9-]+\.)*elevenlabs\.io",
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id"],
    )
