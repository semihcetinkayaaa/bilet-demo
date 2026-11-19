"""Ek operasyon araçları: satış detayları, sipariş operasyonu, servisler (container), hatalar/loglar, girişler.

Hepsi SADECE OKUR. Cevaplar telefonda okunacak kısa Türkçe cümlelerdir; kişisel veri (e-posta, tam ad)
söylenmez, isimler baş harfle maskelenir.
"""

import asyncio
import functools
import json
import re
import time
from datetime import UTC, datetime

import httpx

from bilet_ops_mcp import speak as s
from bilet_ops_mcp.config import settings
from bilet_ops_mcp.server import KEY_CONTAINERS, READ_ONLY, REAL, UA, friendly, mcp, prom, query

# --------------------------------------------------------------------------- yardımcılar

# Coolify container adları -> okunur adlar (sondaki yayın zamanı eki her deploy'da değişir)
CONTAINER_NAMES = [
    (KEY_CONTAINERS["backend"], "backend"),
    (KEY_CONTAINERS["site"], "site"),
    (KEY_CONTAINERS["veritabanı"], "veritabanı"),
    ("grafana-.*", "Grafana"),
    ("loki-.*", "Loki"),
    ("alloy-.*", "Alloy"),
    ("prometheus-.*", "Prometheus"),
    ("node-exporter-.*", "node-exporter"),
    ("cadvisor-.*", "cAdvisor"),
    ("n8n-.*", "n8n"),
    ("postgresql-spukwajggo9rswlyhov4f49k.*", "n8n veritabanı"),
    ("task-runners-.*", "n8n çalıştırıcıları"),
]
_COMPILED = [(re.compile(f"^{rx}$"), nice) for rx, nice in CONTAINER_NAMES]
BACKEND = f'{{container=~"{KEY_CONTAINERS["backend"]}"}}'
HTTP = f'{BACKEND} | json logger, status, route, method, duration_ms, test | __error__="" | logger="bilet_api.http"'
AUTH = f'{BACKEND} | json logger, msg, reason, test | __error__="" | logger="bilet_api.auth"'
ERROR_RE = "(?i)(error|exception|traceback|fatal|panic)"
CONT = 'job="cadvisor", name!=""'


def nice_name(raw: str) -> str:
    for rx, nice in _COMPILED:
        if rx.match(raw):
            return nice
    return "diğer servisler"  # Coolify'ın rastgele adları telefonda okunamaz


# Backend uçları -> telefonda anlaşılır adlar
ROUTES = {
    "/events": "etkinlik listesi", "/events/cities": "şehir listesi", "/events/{event_id}": "etkinlik detayı",
    "/orders": "sipariş oluşturma", "/orders/{code}": "sipariş sorgulama", "/orders/{code}/pay": "ödeme",
    "/me/orders": "siparişlerim sayfası", "/auth/login": "giriş", "/auth/register": "üye kaydı",
    "/auth/logout": "çıkış", "/auth/me": "üye bilgisi", "/health": "sağlık kontrolü",
    "/health/db": "veritabanı sağlık kontrolü", "/test/alarm": "alarm testi", "/test/alarm/{senaryo}": "alarm testi",
}


def route_name(route: str | None) -> str:
    if not route:
        return "bilinmeyen uç"
    return ROUTES.get(route) or re.sub(r"\{[^}]*\}", "", route).strip("/").replace("/", " ") or route


def dec(x: float) -> str:
    """1.25 -> '1,3', 4.0 -> '4' (Türkçe ondalık, gereksiz ',0' yok)."""
    t = f"{x:.1f}".replace(".", ",")
    return t[:-2] if t.endswith(",0") else t


def _minutes(m: int) -> int:
    return max(1, min(int(m), 24 * 60))


def _window(minutes: int) -> str:
    return f"{minutes}m"


def _period_min(minutes: int) -> str:
    if minutes % 60 == 0:
        return s.period(minutes // 60)
    return f"son {minutes} dakikada"


def fold(text: str) -> str:
    """Türkçe harfleri sadeleştirip küçültür (arama için): 'İstanbul Şenliği' -> 'istanbul senligi'."""
    return text.translate(str.maketrans("ÇĞİIÖŞÜçğıöşü", "CGIIOSUcgiosu")).lower().strip()


SQL_FOLD = "lower(translate({col}, 'ÇĞİIÖŞÜçğıöşü', 'CGIIOSUcgiosu'))"


async def prom_vec(expr: str) -> list[tuple[dict, float]]:
    """Prometheus anlık sorgusu; (etiketler, değer) listesi."""
    if not settings.prometheus_url:
        return []
    async with httpx.AsyncClient(timeout=4, headers=UA) as c:
        r = await c.get(f"{settings.prometheus_url.rstrip('/')}/api/v1/query", params={"query": expr})
        r.raise_for_status()
        return [(x["metric"], float(x["value"][1])) for x in r.json()["data"]["result"]]


class LokiYok(Exception):
    pass


async def loki_vec(expr: str) -> list[tuple[dict, float]]:
    """Loki metrik sorgusu (count_over_time vb.); (etiketler, değer) listesi."""
    if not settings.loki_url:
        raise LokiYok
    async with httpx.AsyncClient(timeout=6, headers=UA) as c:
        r = await c.get(f"{settings.loki_url.rstrip('/')}/loki/api/v1/query", params={"query": expr})
        r.raise_for_status()
        return [(x["metric"], float(x["value"][1])) for x in r.json()["data"]["result"]]


async def loki_total(expr: str) -> float:
    rows = await loki_vec(expr)
    return sum(v for _, v in rows)


async def loki_lines(expr: str, minutes: int, limit: int = 3) -> list[tuple[datetime, str, dict]]:
    """Son log satırları (en yeni önce)."""
    if not settings.loki_url:
        raise LokiYok
    now = time.time_ns()
    async with httpx.AsyncClient(timeout=6, headers=UA) as c:
        r = await c.get(f"{settings.loki_url.rstrip('/')}/loki/api/v1/query_range", params={
            "query": expr, "start": now - minutes * 60 * 10**9, "end": now, "limit": limit, "direction": "backward"})
        r.raise_for_status()
    out = []
    for stream in r.json()["data"]["result"]:
        for ts, line in stream["values"]:
            out.append((datetime.fromtimestamp(int(ts) / 1e9, UTC), line, stream.get("stream", {})))
    out.sort(key=lambda x: x[0], reverse=True)
    return out[:limit]


LOKI_YOK = "Log deposuna (Loki) bağlantı ayarlanmamış, logları okuyamıyorum."


def loki_tool(fn):
    """Loki'ye ulaşılamazsa sesli okunabilir cümle döndür."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except LokiYok:
            return LOKI_YOK
        except httpx.HTTPError:
            return "Log deposuna (Loki) şu an ulaşamıyorum, logları okuyamadım."

    return wrapper


def _hours(h: int) -> int:
    return max(1, min(int(h), 24 * 7))


def _real(demo_dahil: bool) -> str:
    return "TRUE" if demo_dahil else REAL


def _demo_note(demo_dahil: bool) -> str:
    return "" if demo_dahil else " Demo siparişlerini saymadım."


# =========================================================================== SATIŞ DETAYLARI


@mcp.tool(annotations=READ_ONLY)
@friendly
async def en_cok_satanlar(saat: int = 24, adet: int = 5, demo_dahil: bool = False) -> str:
    """Son N saatte en çok ciro yapan etkinlikler (bilet sayısı ve ciro ile).

    saat: 1-168 (bugün için 24, bu hafta için 168). adet: en fazla kaç etkinlik (1-10).
    """
    h = _hours(saat)
    rows = await query(f"""
        SELECT e.title, v.city, SUM(oi.quantity), SUM(oi.quantity * oi.unit_price)
        FROM orders o JOIN order_items oi ON oi.order_id = o.id
        JOIN ticket_types tt ON tt.id = oi.ticket_type_id JOIN events e ON e.id = tt.event_id
        JOIN venues v ON v.id = e.venue_id
        WHERE o.status = 'paid' AND o.paid_at >= now() - make_interval(hours => %(h)s) AND {_real(demo_dahil)}
        GROUP BY e.id, e.title, v.city ORDER BY 4 DESC LIMIT %(n)s""", {"h": h, "n": max(1, min(adet, 10))})
    period = s.period(h).capitalize()
    if not rows:
        return f"{period} satış yapılmadı.{_demo_note(demo_dahil)}"
    items = [f"{i}. {t}, {city}: {s.num(q)} bilet, {s.tl(rev)}" for i, (t, city, q, rev) in enumerate(rows, 1)]
    return f"{period} en çok satan {len(rows)} etkinlik: " + "; ".join(items) + "."


@mcp.tool(annotations=READ_ONLY)
@friendly
async def satis_kirilimi(saat: int = 24, gore: str = "kategori", demo_dahil: bool = False) -> str:
    """Son N saatin satışlarının dağılımı: kategoriye (konser, maç, sinema, tiyatro) ya da şehre göre.

    gore: 'kategori' ya da 'sehir'.
    """
    h = _hours(saat)
    by_city = fold(gore).startswith("sehir")
    col = "v.city" if by_city else "e.category::text"
    rows = await query(f"""
        SELECT {col}, SUM(oi.quantity), SUM(oi.quantity * oi.unit_price)
        FROM orders o JOIN order_items oi ON oi.order_id = o.id
        JOIN ticket_types tt ON tt.id = oi.ticket_type_id JOIN events e ON e.id = tt.event_id
        JOIN venues v ON v.id = e.venue_id
        WHERE o.status = 'paid' AND o.paid_at >= now() - make_interval(hours => %(h)s) AND {_real(demo_dahil)}
        GROUP BY 1 ORDER BY 3 DESC""", {"h": h})
    period = s.period(h).capitalize()
    if not rows:
        return f"{period} satış yapılmadı.{_demo_note(demo_dahil)}"
    total = sum(float(r[2]) for r in rows) or 1
    label = (lambda x: x) if by_city else (lambda x: s.CATEGORY.get(x, x))
    items = [f"{label(k)} {s.tl(rev)} ({s.pct(float(rev) / total)}, {s.num(q)} bilet)" for k, q, rev in rows[:6]]
    more = f"; diğer {len(rows) - 6} şehir de satış yaptı" if len(rows) > 6 else ""
    return (f"{period} toplam {s.tl(total)} ciro, {'şehre' if by_city else 'kategoriye'} göre: "
            + "; ".join(items) + more + ".")


@mcp.tool(annotations=READ_ONLY)
@friendly
async def bugunku_satis(demo_dahil: bool = False) -> str:
    """Bugün (gece yarısından beri) satışlar ve dünün aynı saatine kadarki satışlarla karşılaştırma; en yoğun saat."""
    real = _real(demo_dahil)
    day0 = "(date_trunc('day', now() AT TIME ZONE 'Europe/Istanbul') AT TIME ZONE 'Europe/Istanbul')"
    row = (await query(f"""
        SELECT COUNT(*) FILTER (WHERE o.paid_at >= {day0}),
               COALESCE(SUM(o.total_amount) FILTER (WHERE o.paid_at >= {day0}), 0),
               COUNT(*) FILTER (WHERE o.paid_at >= {day0} - interval '1 day' AND o.paid_at < now() - interval '1 day'),
               COALESCE(SUM(o.total_amount) FILTER (
                   WHERE o.paid_at >= {day0} - interval '1 day' AND o.paid_at < now() - interval '1 day'), 0),
               COUNT(*) FILTER (WHERE o.paid_at >= now() - interval '1 hour')
        FROM orders o WHERE o.status = 'paid' AND o.paid_at >= {day0} - interval '1 day' AND {real}"""))[0]
    n_today, rev_today, n_yday, rev_yday, n_hour = int(row[0]), float(row[1]), int(row[2]), float(row[3]), int(row[4])
    clock = datetime.now(s.TZ).strftime("%H:%M")
    if n_today == 0:
        msg = f"Bugün saat {clock} itibarıyla hiç ödenmiş sipariş yok."
    else:
        msg = f"Bugün saat {clock} itibarıyla {s.num(n_today)} sipariş ve {s.tl(rev_today)} ciro var."
    if n_yday:
        trend = s.compare(rev_today, rev_yday, "düne").removeprefix("düne göre ")
        msg += f" Dün aynı saate kadar {s.num(n_yday)} sipariş, {s.tl(rev_yday)} vardı; bugünkü ciro {trend}."
    else:
        msg += " Dün aynı saate kadar satış yoktu."
    peak = await query(f"""
        SELECT extract(hour FROM o.paid_at AT TIME ZONE 'Europe/Istanbul')::int, COUNT(*)
        FROM orders o WHERE o.status = 'paid' AND o.paid_at >= {day0} AND {real}
        GROUP BY 1 ORDER BY 2 DESC, 1 DESC LIMIT 1""")
    if peak:
        hr, cnt = peak[0]
        msg += f" En yoğun saat {hr} ile {(hr + 1) % 24} arası, {s.num(cnt)} sipariş."
    msg += f" Son bir saatte {s.num(n_hour)} sipariş geldi." if n_hour else " Son bir saatte hiç sipariş gelmedi."
    return msg + _demo_note(demo_dahil)


@mcp.tool(annotations=READ_ONLY)
@friendly
async def etkinlik_satisi(ad: str) -> str:
    """Bir etkinliğin satış durumu (adının bir kısmı yeterli): bilet tiplerine göre satılan/kalan, doluluk, ciro, son 24 saat."""
    q = fold(ad)
    if len(q) < 2:
        return "Etkinliğin adını söyler misin?"
    events = await query(f"""
        SELECT e.id, e.title, v.city, e.starts_at FROM events e JOIN venues v ON v.id = e.venue_id
        WHERE {SQL_FOLD.format(col='e.title')} LIKE %(q)s
        ORDER BY (e.starts_at >= now()) DESC, abs(extract(epoch FROM e.starts_at - now())) LIMIT 4""",
        {"q": f"%{q}%"})
    if not events:
        return f"Adında '{ad}' geçen bir etkinlik bulamadım."
    eid, title, city, starts = events[0]
    types = await query("""
        SELECT tt.name, tt.sold, tt.quota, tt.price FROM ticket_types tt WHERE tt.event_id = %(id)s ORDER BY tt.price DESC""",
        {"id": eid})
    money = (await query("""
        SELECT COALESCE(SUM(oi.quantity * oi.unit_price), 0),
               COALESCE(SUM(oi.quantity) FILTER (WHERE o.paid_at >= now() - interval '24 hours'), 0)
        FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN ticket_types tt ON tt.id = oi.ticket_type_id
        WHERE tt.event_id = %(id)s AND o.status = 'paid'""", {"id": eid}))[0]
    sold, quota = sum(t[1] for t in types), sum(t[2] for t in types)
    past = starts < datetime.now(UTC)
    parts = [f"{title}, {city}, {s.when(starts)}{' (geçmiş etkinlik)' if past else ''}."]
    if quota:
        fill = s.pct(sold / quota) + " dolu" if sold / quota >= 0.01 or sold == 0 else "yüzde 1'in altında dolu"
        parts.append(f"{s.num(quota)} biletin {s.num(sold)} tanesi satıldı, {fill}.")
    tparts = [f"{n} {'tükendi' if so >= qu else f'{s.num(so)} satıldı, {s.num(qu - so)} kaldı'}"
              for n, so, qu, _p in types]
    if tparts:
        parts.append("Bilet tipleri: " + "; ".join(tparts) + ".")
    parts.append(f"Toplam ciro {s.tl(money[0])}, son 24 saatte {s.num(money[1])} bilet satıldı.")
    if len(events) > 1:
        others = ", ".join(e[1] for e in events[1:])
        parts.append(f"Bu adla eşleşen başka etkinlikler de var: {others}.")
    return " ".join(parts)


# =========================================================================== SİPARİŞ OPERASYONU


@mcp.tool(annotations=READ_ONLY)
@friendly
async def bekleyen_siparisler(dakika: int = 15, adet: int = 5) -> str:
    """Ödeme adımında N dakikadan uzun süredir bekleyen (takılı kalmış) siparişler, son 24 saat (demo hariç)."""
    m = _minutes(dakika)
    rows = await query(f"""
        SELECT o.code, o.total_amount, o.created_at, MIN(e.title)
        FROM orders o JOIN order_items oi ON oi.order_id = o.id
        JOIN ticket_types tt ON tt.id = oi.ticket_type_id JOIN events e ON e.id = tt.event_id
        WHERE {REAL} AND o.status = 'pending' AND o.created_at < now() - make_interval(mins => %(m)s)
          AND o.created_at >= now() - interval '1 day'
        GROUP BY o.id ORDER BY o.created_at DESC""", {"m": m})
    if not rows:
        return f"{m} dakikadan uzun süredir ödeme bekleyen sipariş yok."
    total = sum(float(r[1]) for r in rows)
    items = [f"{s.spell_code(code)}, {title}, {s.tl(amt)}, {s.ago(created)}"
             for code, amt, created, title in rows[:max(1, min(adet, 10))]]
    return (f"{s.num(len(rows))} sipariş {m} dakikadan uzun süredir ödeme bekliyor, toplam {s.tl(total)}. "
            f"En yenileri: " + "; ".join(items) + ".")


@mcp.tool(annotations=READ_ONLY)
@friendly
async def son_siparisler(adet: int = 5, demo_dahil: bool = False) -> str:
    """En son verilen siparişler: kod, durum, etkinlik, tutar, ne zaman. Alıcı adı baş harfleriyle."""
    rows = await query(f"""
        SELECT o.code, o.status, o.total_amount, o.created_at, o.buyer_name, MIN(e.title)
        FROM orders o JOIN order_items oi ON oi.order_id = o.id
        JOIN ticket_types tt ON tt.id = oi.ticket_type_id JOIN events e ON e.id = tt.event_id
        WHERE {_real(demo_dahil)}
        GROUP BY o.id ORDER BY o.created_at DESC LIMIT %(n)s""", {"n": max(1, min(adet, 10))})
    if not rows:
        return "Hiç sipariş yok." + _demo_note(demo_dahil)
    items = [f"{s.ago(created)}, {s.spell_code(code)}, {s.STATUS.get(st, st)}, {title}, {s.tl(amt)}, {s.mask_name(name)}"
             for code, st, amt, created, name, title in rows]
    return f"Son {len(rows)} sipariş: " + "; ".join(items).rstrip(".") + "."


@mcp.tool(annotations=READ_ONLY)
@friendly
async def tukenen_biletler(saat: int = 24) -> str:
    """Son N saatte tükenen bilet tipleri (son bileti bu sürede satılanlar)."""
    h = _hours(saat)
    rows = await query("""
        SELECT e.title, v.city, e.starts_at, tt.name, MAX(o.paid_at)
        FROM ticket_types tt JOIN events e ON e.id = tt.event_id JOIN venues v ON v.id = e.venue_id
        JOIN order_items oi ON oi.ticket_type_id = tt.id JOIN orders o ON o.id = oi.order_id AND o.status = 'paid'
        WHERE tt.sold >= tt.quota
        GROUP BY tt.id, e.title, v.city, e.starts_at, tt.name
        HAVING MAX(o.paid_at) >= now() - make_interval(hours => %(h)s)
        ORDER BY 5 DESC""", {"h": h})
    period = s.period(h).capitalize()
    if not rows:
        return f"{period} tükenen bilet tipi olmadı."
    items = [f"{t}, {city}, {s.when(st)}: {name}, {s.ago(last)} tükendi" for t, city, st, name, last in rows[:8]]
    more = f" Toplam {len(rows)} bilet tipi tükendi." if len(rows) > 8 else ""
    return f"{period} {len(rows)} bilet tipi tükendi: " + "; ".join(items) + "." + more


# =========================================================================== SERVİSLER (CONTAINER)


@mcp.tool(annotations=READ_ONLY)
@friendly
async def servis_durumu(servis: str = "") -> str:
    """Sunucudaki servislerin (backend, site, veritabanı, n8n, Grafana...) işlemci ve bellek kullanımı, ne zamandır çalıştıkları.

    servis: tek bir servisi sormak için adı (ör. 'backend', 'n8n'); boşsa genel özet.
    """
    cpu, mem, up = await asyncio.gather(
        prom_vec(f"sum by (name) (rate(container_cpu_usage_seconds_total{{{CONT}}}[5m])) * 100"),
        prom_vec(f"sum by (name) (container_memory_working_set_bytes{{{CONT}}})"),
        prom_vec(f"max by (name) (time() - container_start_time_seconds{{{CONT}}})"),
    )
    if not (cpu or mem):
        return "Servis metriklerine şu an ulaşamıyorum."
    agg: dict[str, dict] = {}
    for rows, key in ((cpu, "cpu"), (mem, "mem")):
        for lab, val in rows:
            a = agg.setdefault(nice_name(lab.get("name", "")), {"cpu": 0.0, "mem": 0.0, "up": None})
            a[key] += val
    for lab, val in up:
        a = agg.setdefault(nice_name(lab.get("name", "")), {"cpu": 0.0, "mem": 0.0, "up": None})
        a["up"] = val if a["up"] is None else min(a["up"], val)

    def mb(b: float) -> str:
        return f"{dec(b / 1024**3)} gigabayt" if b >= 1024**3 else f"{s.num(b / 1024**2)} megabayt"

    def uptime(sec: float | None) -> str:
        if sec is None:
            return "başlangıç zamanı bilinmiyor"
        m = int(sec // 60)
        if m < 60:
            return f"{m} dakikadır çalışıyor"
        if m < 60 * 48:
            return f"{m // 60} saattir çalışıyor"
        return f"{m // 1440} gündür çalışıyor"

    if servis.strip():
        want = fold(servis)
        hits = [k for k in agg if want in fold(k)]
        if not hits:
            known = sorted(k for k in agg if k != "diğer servisler")
            return f"'{servis}' adında bir servis bulamadım. Tanıdığım servisler: {', '.join(known)}."
        k = hits[0]
        a = agg[k]
        return f"{k}: işlemci yüzde {dec(a['cpu'])}, bellek {mb(a['mem'])}, {uptime(a['up'])}."

    by_cpu = sorted(agg.items(), key=lambda kv: kv[1]["cpu"], reverse=True)[:3]
    by_mem = sorted(agg.items(), key=lambda kv: kv[1]["mem"], reverse=True)[:3]
    recent = sorted((k, a["up"]) for k, a in agg.items() if a["up"] is not None and a["up"] < 3600)
    running = len({lab.get("name") for lab, _ in cpu + mem})
    msg = (f"{running} servis çalışıyor. En çok işlemci kullananlar: "
           + ", ".join(f"{k} yüzde {dec(a['cpu'])}" for k, a in by_cpu)
           + ". En çok bellek kullananlar: " + ", ".join(f"{k} {mb(a['mem'])}" for k, a in by_mem) + ".")
    if recent:
        msg += " Son bir saatte yeniden başlayan: " + ", ".join(f"{k}, {int(u // 60)} dakika önce" for k, u in recent) + "."
    else:
        msg += " Son bir saatte yeniden başlayan servis yok."
    return msg


@mcp.tool(annotations=READ_ONLY)
@friendly
async def disk_tahmini() -> str:
    """Sunucu diskinin doluluğu ve son 6 saatteki hıza göre ne zaman dolacağı tahmini."""
    fs = 'job="node", mountpoint="/"'
    avail, size, slope = await asyncio.gather(
        prom(f"node_filesystem_avail_bytes{{{fs}}}"),
        prom(f"node_filesystem_size_bytes{{{fs}}}"),
        prom(f"deriv(node_filesystem_avail_bytes{{{fs}}}[6h])"),
    )
    if avail is None or not size:
        return "Disk metriklerine şu an ulaşamıyorum."
    gb = lambda b: f"{round(b / 1024**3)} gigabayt"  # noqa: E731
    msg = f"Disk {s.pct(1 - avail / size)} dolu, {gb(avail)} boş yer var."
    if slope is None or slope >= 0:
        return msg + " Son 6 saatte disk dolma eğiliminde değil."
    days = avail / -slope / 86400
    if days < 1:
        when = f"yaklaşık {max(1, round(days * 24))} saat içinde"
    elif days < 60:
        when = f"yaklaşık {round(days)} gün içinde"
    else:
        return msg + " Doluluk çok yavaş artıyor, yakın zamanda dolmaz."
    return msg + f" Son 6 saatteki hızla giderse {when} dolar."


# =========================================================================== HATALAR VE LOGLAR


@mcp.tool(annotations=READ_ONLY)
@friendly
@loki_tool
async def son_hatalar(dakika: int = 15) -> str:
    """Son N dakikadaki hatalar: backend 500 hataları ve hangi uçta oldukları, diğer servislerdeki hata logları, en son hata."""
    m = _minutes(dakika)
    w = _window(m)
    by_route, test_5xx, be_err, others, last = await asyncio.gather(
        loki_vec(f"sum by (route) (count_over_time({HTTP} | status >= 500 [{w}]))"),
        loki_total(f'sum(count_over_time({HTTP} | status >= 500 | test="true" [{w}]))'),
        loki_total(f'sum(count_over_time({BACKEND} | json level | __error__="" | level="error" [{w}]))'),
        loki_vec(f'topk(3, sum by (container) (count_over_time({{container=~".+", '
                 f'container!~"{KEY_CONTAINERS["backend"]}"}} |~ "{ERROR_RE}" [{w}])))'),
        loki_lines(f'{BACKEND} | json level, logger, msg, route, path, status | __error__="" | level="error"', m, 1),
    )
    period = _period_min(m).capitalize()
    n5xx = int(sum(v for _, v in by_route))
    parts = []
    if n5xx:
        routes = sorted(by_route, key=lambda x: x[1], reverse=True)[:3]
        rs = ", ".join(f"{route_name(lab.get('route'))} {s.num(v)} kez" for lab, v in routes)
        test = f" Bunların {s.num(test_5xx)} tanesi alarm testinden." if test_5xx else ""
        parts.append(f"{period} backend {s.num(n5xx)} kez 500 hatası verdi: {rs}.{test}")
    else:
        parts.append(f"{period} backend hiç 500 hatası vermedi.")
    if be_err > n5xx:
        parts.append(f"Backend loglarında toplam {s.num(be_err)} hata satırı var.")
    noisy = [(nice_name(lab.get("container", "")), v) for lab, v in others if v > 0]
    if noisy:
        parts.append("Diğer servislerde hata içeren log satırları: "
                     + ", ".join(f"{k} {s.num(v)}" for k, v in noisy) + ".")
    if last:
        ts, line, lab = last[0]
        try:
            d = json.loads(line)
        except ValueError:
            d = {}
        if d.get("logger") == "bilet_api.http":
            what = f"{route_name(d.get('route') or d.get('path'))} isteği {d.get('status', '')} hatası verdi"
        else:
            what = str(d.get("msg") or line)[:120]
        parts.append(f"En son hata {s.ago(ts)}: {what}.")
    return " ".join(parts)


@mcp.tool(annotations=READ_ONLY)
@friendly
@loki_tool
async def api_performansi(dakika: int = 15) -> str:
    """Son N dakikada API: istek sayısı, yanıt süreleri (ortanca ve yüzde 95), en yavaş uçlar, 4xx/5xx oranı."""
    m = _minutes(dakika)
    w = _window(m)
    total, p50, p95, slow, by_class = await asyncio.gather(
        loki_total(f"sum(count_over_time({HTTP} [{w}]))"),
        loki_total(f'quantile_over_time(0.5, {HTTP} | unwrap duration_ms | __error__="" [{w}]) by ()'),
        loki_total(f'quantile_over_time(0.95, {HTTP} | unwrap duration_ms | __error__="" [{w}]) by ()'),
        loki_vec(f'topk(3, quantile_over_time(0.95, {HTTP} | route!="" | unwrap duration_ms | __error__="" [{w}]) by (route))'),
        loki_vec(f'sum by (status) (count_over_time({HTTP} | status >= 400 [{w}]))'),
    )
    period = _period_min(m).capitalize()
    if not total:
        return f"{period} API'ye hiç istek gelmedi."
    c4 = sum(v for lab, v in by_class if str(lab.get("status", "")).startswith("4"))
    c5 = sum(v for lab, v in by_class if str(lab.get("status", "")).startswith("5"))
    verdict = "normal" if p95 < 1000 else "yavaş" if p95 < 3000 else "çok yavaş"
    msg = (f"{period} {s.num(total)} istek geldi. İsteklerin yarısı {s.num(p50)} milisaniyenin altında, "
           f"yüzde 95'i {s.num(p95)} milisaniyenin altında yanıtlandı; bu {verdict}.")
    slow = [(lab.get("route"), v) for lab, v in sorted(slow, key=lambda x: x[1], reverse=True) if lab.get("route")]
    if slow and p95 >= 500:
        msg += " En yavaş uçlar: " + ", ".join(f"{route_name(r)} {s.num(v)} milisaniye" for r, v in slow) + "."
    msg += (f" Hata oranı: istemci hataları (4xx) {s.pct(c4 / total)}, sunucu hataları (5xx) {s.pct(c5 / total)}.")
    return msg


# =========================================================================== ÜYE GİRİŞLERİ


@mcp.tool(annotations=READ_ONLY)
@friendly
@loki_tool
async def giris_durumu(saat: int = 1) -> str:
    """Son N saatteki üye girişleri: başarılı/başarısız girişler ve nedenleri, kilitlenen hesaplar, yeni kayıtlar, saldırı belirtisi."""
    h = max(1, min(int(saat), 24 * 7))
    w = f"{h}h"
    by_msg, by_reason, tests, uniq = await asyncio.gather(
        loki_vec(f"sum by (msg) (count_over_time({AUTH} [{w}]))"),
        loki_vec(f'sum by (reason) (count_over_time({AUTH} | msg="login_failed" [{w}]))'),
        loki_total(f'sum(count_over_time({AUTH} | test="true" [{w}]))'),
        query("SELECT count(*) FROM users u WHERE u.last_login_at >= now() - make_interval(hours => %(h)s)", {"h": h}),
    )
    c = {lab.get("msg", ""): int(v) for lab, v in by_msg}
    ok, failed = c.get("login_succeeded", 0), c.get("login_failed", 0)
    blocked, locked_now, new = c.get("login_locked", 0), c.get("login_locked_now", 0), c.get("user_registered", 0)
    period = s.period(h).capitalize()
    parts = [f"{period} {s.num(ok)} başarılı giriş oldu ({s.num(uniq[0][0])} farklı üye)."]
    if failed:
        reasons = {lab.get("reason", ""): int(v) for lab, v in by_reason}
        rtxt = ", ".join(x for x in (
            f"{s.num(reasons['wrong_password'])} yanlış şifre" if reasons.get("wrong_password") else "",
            f"{s.num(reasons['unknown_email'])} kayıtlı olmayan e-posta" if reasons.get("unknown_email") else "",
        ) if x)
        parts.append(f"{s.num(failed)} başarısız giriş denemesi var" + (f": {rtxt}." if rtxt else "."))
    else:
        parts.append("Başarısız giriş denemesi yok.")
    if locked_now:
        parts.append(f"{s.num(locked_now)} hesap çok fazla hatalı deneme yüzünden kilitlendi.")
    if blocked:
        parts.append(f"Kilitli hesaplara {s.num(blocked)} giriş denemesi yapıldı.")
    parts.append(f"{s.num(new)} yeni üye kaydı var." if new else "Yeni üye kaydı yok.")
    real_failed = failed - (tests if tests else 0)
    if real_failed > 30 * h or locked_now > 3:
        parts.append("Bu olağandışı; şifre deneme saldırısı olabilir.")
    if tests:
        parts.append(f"Not: {s.num(tests)} kayıt alarm testinden geliyor.")
    return " ".join(parts)
