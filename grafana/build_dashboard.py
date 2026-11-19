"""semihcetinkaya.tech satış panosu (Grafana dashboard JSON üretici).

Çalıştırma (proje kökünde):
    python grafana/build_dashboard.py
Çıktı: grafana/bilet-satis-dashboard.json -> Grafana > Dashboards > New > Import

Panodaki "Demo siparişler" seçimi, @example.com e-postalı sahte siparişleri
dahil eder ya da hariç tutar.
"""

import json
from pathlib import Path

DS = {"type": "grafana-postgresql-datasource", "uid": "${DS_BILET}"}

# Ortak SQL parçaları --------------------------------------------------------
DEMO = "('$demo' = 'dahil' OR o.buyer_email NOT LIKE '%@example.com')"
PAID = f"o.status = 'paid' AND {DEMO}"
JOIN_ALL = """
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN ticket_types tt ON tt.id = oi.ticket_type_id
JOIN events e ON e.id = tt.event_id
JOIN venues v ON v.id = e.venue_id"""
CAT_FILTER = "e.category IN ($kategori) AND v.city IN ($sehir)"
CAT_LABEL = """CASE e.category WHEN 'concert' THEN 'Konser' WHEN 'match' THEN 'Maç'
  WHEN 'cinema' THEN 'Sinema' WHEN 'theater' THEN 'Tiyatro' END"""

_next_id = iter(range(1, 1000))


def target(sql: str, fmt: str = "table") -> dict:
    return {"refId": "A", "datasource": DS, "editorMode": "code", "format": fmt, "rawQuery": True, "rawSql": sql.strip()}


def panel(kind: str, title: str, sql: str, grid: tuple[int, int, int, int], *, fmt="table",
          unit=None, description="", options=None, field_config=None, overrides=None) -> dict:
    x, y, w, h = grid
    defaults = {"unit": unit} if unit else {}
    if field_config:
        defaults.update(field_config)
    return {
        "id": next(_next_id),
        "type": kind,
        "title": title,
        "description": description,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [target(sql, fmt)],
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": options or {},
    }


def stat(title, sql, grid, unit=None, description="", decimals=None, color="blue"):
    fc = {"color": {"mode": "fixed", "fixedColor": color}}
    if decimals is not None:
        fc["decimals"] = decimals
    return panel("stat", title, sql, grid, unit=unit, description=description, field_config=fc,
                 options={"reduceOptions": {"calcs": ["lastNotNull"], "values": False},
                          "colorMode": "background", "graphMode": "none", "textMode": "value"})


TL = "currencyTRY"

# Paneller -------------------------------------------------------------------
panels = [
    # --- Üst satır: özet kutuları
    stat("Ciro", f"""
SELECT COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS "Ciro"
{JOIN_ALL}
WHERE {PAID} AND $__timeFilter(o.paid_at) AND {CAT_FILTER}""", (0, 0, 5, 4), TL,
         "Seçili zaman aralığında ödenmiş siparişlerin toplam tutarı.", 0, "purple"),
    stat("Satılan bilet", f"""
SELECT COALESCE(SUM(oi.quantity), 0) AS "Bilet"
{JOIN_ALL}
WHERE {PAID} AND $__timeFilter(o.paid_at) AND {CAT_FILTER}""", (5, 0, 4, 4), "none", color="green"),
    stat("Ödenmiş sipariş", f"""
SELECT COUNT(DISTINCT o.id) AS "Sipariş"
{JOIN_ALL}
WHERE {PAID} AND $__timeFilter(o.paid_at) AND {CAT_FILTER}""", (9, 0, 4, 4), "none", color="blue"),
    stat("Ortalama sepet", f"""
SELECT COALESCE(SUM(oi.quantity * oi.unit_price) / NULLIF(COUNT(DISTINCT o.id), 0), 0) AS "Ortalama"
{JOIN_ALL}
WHERE {PAID} AND $__timeFilter(o.paid_at) AND {CAT_FILTER}""", (13, 0, 4, 4), TL, decimals=0, color="orange"),
    stat("Ödeme başarı oranı", f"""
SELECT COALESCE(
  COUNT(DISTINCT o.id) FILTER (WHERE o.status = 'paid')::float
  / NULLIF(COUNT(DISTINCT o.id) FILTER (WHERE o.status IN ('paid', 'failed')), 0), 0) AS "Başarı"
{JOIN_ALL}
WHERE {DEMO} AND $__timeFilter(o.created_at) AND {CAT_FILTER}""", (17, 0, 4, 4), "percentunit",
         "Ödenen / (ödenen + reddedilen). Bekleyen ve iptal edilenler hariç.", 1, "teal"),
    stat("Bekleyen ödeme", f"""
SELECT COUNT(*) AS "Bekleyen" FROM orders o
WHERE o.status = 'pending' AND {DEMO}""", (21, 0, 3, 4), "none",
         "Şu an ödeme adımında bekleyen siparişler (zaman aralığından bağımsız).", color="yellow"),

    # --- Zaman serileri
    panel("timeseries", "Günlük ciro", f"""
SELECT $__timeGroupAlias(o.paid_at, 1d), SUM(oi.quantity * oi.unit_price) AS "Ciro"
{JOIN_ALL}
WHERE {PAID} AND $__timeFilter(o.paid_at) AND {CAT_FILTER}
GROUP BY 1 ORDER BY 1""", (0, 4, 14, 9), fmt="time_series", unit=TL,
          field_config={"custom": {"drawStyle": "bars", "fillOpacity": 80, "barAlignment": 0, "lineWidth": 1},
                        "color": {"mode": "fixed", "fixedColor": "purple"}},
          options={"legend": {"showLegend": False}, "tooltip": {"mode": "single"}}),
    panel("piechart", "Kategoriye göre ciro", f"""
SELECT {CAT_LABEL} AS "Kategori", SUM(oi.quantity * oi.unit_price) AS "Ciro"
{JOIN_ALL}
WHERE {PAID} AND $__timeFilter(o.paid_at) AND {CAT_FILTER}
GROUP BY 1 ORDER BY 2 DESC""", (14, 4, 10, 9), unit=TL,
          options={"pieType": "donut", "reduceOptions": {"calcs": ["lastNotNull"], "values": True},
                   "legend": {"displayMode": "table", "placement": "right", "values": ["value", "percent"]},
                   "displayLabels": []}),
    panel("timeseries", "Günlük satılan bilet (kategoriye göre)", f"""
SELECT $__timeGroupAlias(o.paid_at, 1d), {CAT_LABEL} AS metric, SUM(oi.quantity) AS value
{JOIN_ALL}
WHERE {PAID} AND $__timeFilter(o.paid_at) AND {CAT_FILTER}
GROUP BY 1, 2 ORDER BY 1""", (0, 13, 14, 9), fmt="time_series", unit="none",
          field_config={"custom": {"drawStyle": "bars", "fillOpacity": 85, "stacking": {"mode": "normal"}, "lineWidth": 0}},
          options={"legend": {"showLegend": True, "placement": "bottom"}, "tooltip": {"mode": "multi", "sort": "desc"}}),
    panel("barchart", "Şehirlere göre ciro", f"""
SELECT v.city AS "Şehir", SUM(oi.quantity * oi.unit_price) AS "Ciro"
{JOIN_ALL}
WHERE {PAID} AND $__timeFilter(o.paid_at) AND {CAT_FILTER}
GROUP BY 1 ORDER BY 2 DESC""", (14, 13, 10, 9), unit=TL,
          field_config={"color": {"mode": "fixed", "fixedColor": "blue"}},
          options={"orientation": "horizontal", "showValue": "auto", "legend": {"showLegend": False},
                   "xTickLabelRotation": 0}),

    # --- Etkinlik bazlı
    panel("bargauge", "En çok ciro getiren 10 etkinlik", f"""
SELECT e.title || ' · ' || v.city || ' · ' || to_char(e.starts_at AT TIME ZONE 'Europe/Istanbul', 'DD.MM HH24:MI') AS "Etkinlik",
       SUM(oi.quantity * oi.unit_price) AS "Ciro"
{JOIN_ALL}
WHERE {PAID} AND $__timeFilter(o.paid_at) AND {CAT_FILTER}
GROUP BY e.id, e.title, v.city, e.starts_at ORDER BY 2 DESC LIMIT 10""", (0, 22, 12, 10), unit=TL,
          field_config={"color": {"mode": "continuous-BlPu"}, "min": 0},
          options={"orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                   "reduceOptions": {"calcs": ["lastNotNull"], "values": True}, "valueMode": "color",
                   "namePlacement": "top"}),
    panel("table", "Yaklaşan etkinliklerde doluluk", f"""
SELECT e.title AS "Etkinlik", {CAT_LABEL} AS "Kategori", v.city AS "Şehir",
       e.starts_at AS "Tarih",
       SUM(tt.sold) AS "Satılan", SUM(tt.quota) AS "Kontenjan",
       SUM(tt.sold)::float / NULLIF(SUM(tt.quota), 0) AS "Doluluk"
FROM events e
JOIN venues v ON v.id = e.venue_id
JOIN ticket_types tt ON tt.event_id = e.id
WHERE e.starts_at >= now() AND {CAT_FILTER}
GROUP BY e.id, e.title, e.category, v.city, e.starts_at
ORDER BY "Doluluk" DESC, e.starts_at
LIMIT 50""", (12, 22, 12, 10),
          description="Satılan adetler tüm zamanlar içindir (zaman aralığından bağımsız; demo siparişler dahil).",
          options={"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
          overrides=[
              {"matcher": {"id": "byName", "options": "Doluluk"},
               "properties": [{"id": "unit", "value": "percentunit"}, {"id": "min", "value": 0}, {"id": "max", "value": 1},
                              {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "gradient"}},
                              {"id": "color", "value": {"mode": "continuous-GrYlRd"}}]},
              {"matcher": {"id": "byName", "options": "Tarih"},
               "properties": [{"id": "unit", "value": "dateTimeAsLocal"}]},
          ]),

    # --- Davranış
    panel("barchart", "Günün saatine göre siparişler", f"""
SELECT lpad(extract(hour FROM o.created_at AT TIME ZONE 'Europe/Istanbul')::text, 2, '0') || ':00' AS "Saat",
       COUNT(DISTINCT o.id) AS "Sipariş"
{JOIN_ALL}
WHERE {DEMO} AND $__timeFilter(o.created_at) AND {CAT_FILTER}
GROUP BY 1 ORDER BY 1""", (0, 32, 12, 8),
          field_config={"color": {"mode": "fixed", "fixedColor": "orange"}},
          options={"showValue": "never", "legend": {"showLegend": False}, "xTickLabelRotation": -45}),
    panel("piechart", "Sipariş durumları", f"""
SELECT CASE o.status WHEN 'paid' THEN 'Ödendi' WHEN 'failed' THEN 'Reddedildi'
         WHEN 'cancelled' THEN 'İptal' ELSE 'Bekliyor' END AS "Durum",
       COUNT(*) AS "Sipariş"
FROM orders o
WHERE {DEMO} AND $__timeFilter(o.created_at)
GROUP BY 1 ORDER BY 2 DESC""", (12, 32, 12, 8),
          options={"pieType": "pie", "reduceOptions": {"calcs": ["lastNotNull"], "values": True},
                   "legend": {"displayMode": "table", "placement": "right", "values": ["value", "percent"]}},
          overrides=[{"matcher": {"id": "byName", "options": n}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]}
                     for n, c in [("Ödendi", "green"), ("Reddedildi", "red"), ("İptal", "gray"), ("Bekliyor", "yellow")]]),
    panel("table", "Son siparişler", f"""
SELECT o.created_at AS "Zaman", o.code AS "Kod", o.buyer_name AS "Alıcı",
       CASE o.status WHEN 'paid' THEN 'Ödendi' WHEN 'failed' THEN 'Reddedildi'
         WHEN 'cancelled' THEN 'İptal' ELSE 'Bekliyor' END AS "Durum",
       o.total_amount AS "Tutar",
       (SELECT e.title FROM order_items oi JOIN ticket_types tt ON tt.id = oi.ticket_type_id
          JOIN events e ON e.id = tt.event_id WHERE oi.order_id = o.id LIMIT 1) AS "Etkinlik",
       CASE WHEN o.buyer_email LIKE '%@example.com' THEN 'demo' ELSE 'gerçek' END AS "Kaynak"
FROM orders o
WHERE {DEMO} AND $__timeFilter(o.created_at)
ORDER BY o.created_at DESC
LIMIT 25""", (0, 40, 24, 10),
          options={"showHeader": True, "cellHeight": "sm"},
          overrides=[{"matcher": {"id": "byName", "options": "Tutar"}, "properties": [{"id": "unit", "value": TL}]},
                     {"matcher": {"id": "byName", "options": "Zaman"}, "properties": [{"id": "unit", "value": "dateTimeAsLocal"}]}]),
]

# --- Üyelik ------------------------------------------------------------------
# Grafana kullanıcısı users tablosundan SADECE id, created_at, last_login_at ve
# email_verified_at sütunlarını okuyabilir (e-posta, isim ve şifre özeti kapalı).
USER_COLS = ("id", "created_at", "last_login_at", "email_verified_at")
MEMBER = "CASE WHEN o.user_id IS NULL THEN 'Misafir' ELSE 'Üye' END"

panels += [
    {"id": next(_next_id), "type": "row", "title": "Üyelik", "collapsed": False,
     "gridPos": {"x": 0, "y": 50, "w": 24, "h": 1}, "panels": []},
    stat("Toplam üye", "SELECT count(u.id) AS \"Üye\" FROM users u", (0, 51, 6, 4), "none", color="purple"),
    stat("Yeni üye", "SELECT count(u.id) AS \"Yeni\" FROM users u WHERE $__timeFilter(u.created_at)",
         (6, 51, 6, 4), "none", "Seçili zaman aralığında kayıt olanlar.", color="green"),
    stat("Aktif üye", "SELECT count(u.id) AS \"Aktif\" FROM users u WHERE $__timeFilter(u.last_login_at)",
         (12, 51, 6, 4), "none", "Seçili zaman aralığında giriş yapan üyeler.", color="blue"),
    stat("Üye siparişi oranı", f"""
SELECT COALESCE(COUNT(*) FILTER (WHERE o.user_id IS NOT NULL)::float / NULLIF(COUNT(*), 0), 0) AS "Oran"
FROM orders o
WHERE {PAID} AND $__timeFilter(o.paid_at)""", (18, 51, 6, 4), "percentunit",
         "Ödenmiş siparişlerin ne kadarı giriş yapmış üyelerden geldi.", 1, "orange"),
    panel("timeseries", "Günlük yeni üye", """
SELECT $__timeGroupAlias(u.created_at, 1d), count(u.id) AS "Yeni üye"
FROM users u
WHERE $__timeFilter(u.created_at)
GROUP BY 1 ORDER BY 1""", (0, 55, 12, 8), fmt="time_series", unit="none",
          field_config={"custom": {"drawStyle": "bars", "fillOpacity": 80, "lineWidth": 1},
                        "color": {"mode": "fixed", "fixedColor": "green"}},
          options={"legend": {"showLegend": False}, "tooltip": {"mode": "single"}}),
    panel("piechart", "Üye / misafir cirosu", f"""
SELECT {MEMBER} AS "Alıcı", SUM(o.total_amount) AS "Ciro"
FROM orders o
WHERE {PAID} AND $__timeFilter(o.paid_at)
GROUP BY 1 ORDER BY 2 DESC""", (12, 55, 12, 8), unit=TL,
          options={"pieType": "donut", "reduceOptions": {"calcs": ["lastNotNull"], "values": True},
                   "legend": {"displayMode": "table", "placement": "right", "values": ["value", "percent"]}},
          overrides=[{"matcher": {"id": "byName", "options": n}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]}
                     for n, c in [("Üye", "purple"), ("Misafir", "gray")]]),
]

# Değişkenler (panonun üstündeki seçimler) ------------------------------------
templating = [
    {
        "name": "demo", "label": "Demo siparişler", "type": "custom",
        "query": "dahil,hariç", "current": {"text": "dahil", "value": "dahil"},
        "options": [{"text": "dahil", "value": "dahil", "selected": True},
                    {"text": "hariç", "value": "hariç", "selected": False}],
    },
    {
        "name": "kategori", "label": "Kategori", "type": "custom", "multi": True, "includeAll": True,
        "query": "Konser : concert,Maç : match,Sinema : cinema,Tiyatro : theater",
        "current": {"text": "All", "value": "$__all"},
    },
    {
        "name": "sehir", "label": "Şehir", "type": "query", "datasource": DS, "multi": True, "includeAll": True,
        "query": "SELECT DISTINCT city FROM venues ORDER BY 1", "refresh": 1,
        "definition": "SELECT DISTINCT city FROM venues ORDER BY 1",
        "current": {"text": "All", "value": "$__all"},
    },
]

dashboard = {
    "__inputs": [{
        "name": "DS_BILET", "label": "bilet veritabanı", "type": "datasource",
        "pluginId": "grafana-postgresql-datasource", "pluginName": "PostgreSQL",
        "description": "semihcetinkaya.tech bilet veritabanı (sadece okuma kullanıcısı)",
    }],
    "__requires": [{"type": "datasource", "id": "grafana-postgresql-datasource", "name": "PostgreSQL", "version": "1.0.0"}],
    "title": "semihcetinkaya.tech · Bilet satışları",
    "uid": "bilet-satis",
    "tags": ["bilet", "satış"],
    "timezone": "browser",
    "time": {"from": "now-30d", "to": "now"},
    "refresh": "1m",
    "schemaVersion": 39,
    "editable": True,
    "graphTooltip": 1,
    "templating": {"list": templating},
    "panels": panels,
}

if __name__ == "__main__":
    out = Path(__file__).with_name("bilet-satis-dashboard.json")
    out.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{out} yazıldı ({len(panels)} panel)")
