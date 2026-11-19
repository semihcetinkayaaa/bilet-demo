"""semihcetinkaya.tech log panosu (Loki) — Grafana dashboard JSON üretici.

Çalıştırma (proje kökünde):
    python grafana/build_logs_dashboard.py
Çıktı: grafana/bilet-log-dashboard.json -> Grafana > Dashboards > New > Import

Container adları Coolify'da her yayında değişen bir zaman eki alır
(ör. lhaabzf16e1csryupsbapana-20261118T215738); bu yüzden sabit ön ek ile eşleştirilir.
"""

import json
from pathlib import Path

DS = {"type": "loki", "uid": "${DS_LOKI}"}

BACKEND = '{container=~"lhaabzf16e1csryupsbapana.*"}'
# Backend JSON satırlarından sadece gereken alanları çıkar (request_id gibi alanlar
# etiket olursa her satır ayrı seri olur ve sorgular şişer).
HTTP = f'{BACKEND} | json logger, status, route, duration_ms | __error__="" | logger="bilet_api.http"'
ORDERS = f'{BACKEND} | json logger, msg | __error__="" | logger="bilet_api.orders"'
AUTH = f'{BACKEND} | json logger, msg | __error__="" | logger="bilet_api.auth"'
ERROR_RE = '(?i)(error|exception|traceback|fatal|panic)'

_ids = iter(range(1, 1000))


def target(expr: str, *, instant: bool = False, legend: str = "", fmt: str = "time_series") -> dict:
    return {"refId": "A", "datasource": DS, "editorMode": "code", "expr": expr,
            "queryType": "instant" if instant else "range", "legendFormat": legend, "format": fmt}


def panel(kind, title, expr, grid, *, instant=False, legend="", unit=None, description="",
          options=None, field_config=None, overrides=None, fmt="time_series"):
    x, y, w, h = grid
    defaults = {"unit": unit} if unit else {}
    defaults.update(field_config or {})
    return {
        "id": next(_ids), "type": kind, "title": title, "description": description, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [target(expr, instant=instant, legend=legend, fmt=fmt)],
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": options or {},
    }


def stat(title, expr, grid, *, unit="none", color="blue", description="", decimals=None, thresholds=None):
    fc = {"color": {"mode": "fixed", "fixedColor": color}}
    if thresholds:
        fc = {"color": {"mode": "thresholds"},
              "thresholds": {"mode": "absolute", "steps": thresholds}}
    if decimals is not None:
        fc["decimals"] = decimals
    return panel("stat", title, expr, grid, instant=True, unit=unit, description=description, field_config=fc,
                 options={"reduceOptions": {"calcs": ["lastNotNull"], "values": False},
                          "colorMode": "background", "graphMode": "none", "textMode": "value"})


LOGS_OPTS = {"showTime": True, "wrapLogMessage": True, "prettifyLogMessage": False,
             "enableLogDetails": True, "sortOrder": "Descending", "dedupStrategy": "none"}

panels = [
    # --- Özet (seçili zaman aralığı)
    stat("API istekleri", f"sum(count_over_time({HTTP} [$__range]))", (0, 0, 6, 4), color="blue",
         description="Seçili aralıkta backend'e gelen istekler (/health hariç)."),
    stat("5xx hataları", f"sum(count_over_time({HTTP} | status >= 500 [$__range]))", (6, 0, 6, 4),
         thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
         description="Sunucu hataları. 0 olmalı."),
    stat("4xx yanıtlar", f"sum(count_over_time({HTTP} | status >= 400 | status < 500 [$__range]))", (12, 0, 6, 4),
         color="orange", description="Geçersiz istekler, bulunamayan sayfalar, reddedilen ödemeler."),
    stat("Yanıt süresi (p95)",
         f"quantile_over_time(0.95, {HTTP} | unwrap duration_ms | __error__=\"\" [$__range]) by ()",
         (18, 0, 6, 4), unit="ms", decimals=0,
         thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 500}, {"color": "red", "value": 1500}],
         description="İsteklerin %95'i bu süreden kısa sürdü."),

    # --- Zaman serileri
    panel("timeseries", "İstekler (durum koduna göre)",
          f"sum by (status) (count_over_time({HTTP} [$__auto]))", (0, 4, 12, 8), legend="{{status}}",
          field_config={"custom": {"drawStyle": "bars", "fillOpacity": 80, "stacking": {"mode": "normal"}, "lineWidth": 0}},
          options={"legend": {"showLegend": True, "placement": "bottom"}, "tooltip": {"mode": "multi", "sort": "desc"}},
          overrides=[{"matcher": {"id": "byRegexp", "options": "5.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
                     {"matcher": {"id": "byRegexp", "options": "4.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]},
                     {"matcher": {"id": "byRegexp", "options": "2.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]}]),
    panel("timeseries", "Yanıt süresi (p95, zaman içinde)",
          f"quantile_over_time(0.95, {HTTP} | unwrap duration_ms | __error__=\"\" [$__auto]) by ()",
          (12, 4, 12, 8), unit="ms", legend="p95",
          options={"legend": {"showLegend": True, "placement": "bottom"}, "tooltip": {"mode": "multi"}}),
    panel("timeseries", "Sipariş ve ödeme olayları",
          f"sum by (msg) (count_over_time({ORDERS} [$__auto]))", (0, 12, 12, 8), legend="{{msg}}",
          field_config={"custom": {"drawStyle": "bars", "fillOpacity": 80, "stacking": {"mode": "normal"}, "lineWidth": 0}},
          options={"legend": {"showLegend": True, "placement": "bottom"}, "tooltip": {"mode": "multi", "sort": "desc"}},
          overrides=[{"matcher": {"id": "byName", "options": n}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]}
                     for n, c in [("payment_succeeded", "green"), ("payment_declined", "red"),
                                  ("payment_sold_out", "orange"), ("order_created", "blue"),
                                  ("payment_event_started", "gray")]]),
    panel("timeseries", "Hata içeren log satırları (tüm sistem)",
          f'sum by (container) (count_over_time({{container=~".+"}} |~ "{ERROR_RE}" [$__auto]))',
          (12, 12, 12, 8), legend="{{container}}",
          description="Tüm container'larda 'error', 'exception', 'traceback' vb. geçen satırlar.",
          options={"legend": {"showLegend": True, "placement": "bottom", "displayMode": "list"},
                   "tooltip": {"mode": "multi", "sort": "desc"}}),

    # --- Tablolar ve log akışları
    panel("table", "En yavaş API uçları (ortalama)",
          f"sort_desc(avg_over_time({HTTP} | unwrap duration_ms | __error__=\"\" [$__range]) by (route))",
          (0, 20, 8, 10), instant=True, fmt="table", unit="ms",
          options={"showHeader": True, "cellHeight": "sm", "sortBy": [{"displayName": "Value #A", "desc": True}]},
          overrides=[{"matcher": {"id": "byName", "options": "Time"}, "properties": [{"id": "custom.hidden", "value": True}]}]),
    panel("logs", "Backend uyarı ve hataları",
          f'{BACKEND} | json | __error__="" | level=~"warning|error"', (8, 20, 16, 10),
          options=LOGS_OPTS),
    panel("logs", "Canlı log akışı ($container)",
          '{container=~"$container"}', (0, 30, 24, 12), options=LOGS_OPTS,
          description="Üstteki 'Container' seçiminden izlemek istediğiniz servisleri seçin."),

    # --- Üyelik / giriş güvenliği
    stat("Başarısız giriş", f'sum(count_over_time({AUTH} | msg=~"login_failed|login_locked" [$__range]))',
         (0, 42, 6, 4), thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 20},
                                     {"color": "red", "value": 100}],
         description="Yanlış şifre, olmayan e-posta ve kilitli hesaba deneme."),
    stat("Kilitlenen hesap", f'sum(count_over_time({AUTH} | msg="login_locked_now" [$__range]))',
         (6, 42, 6, 4), thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1},
                                     {"color": "red", "value": 5}],
         description="5 hatalı denemeden sonra 15 dakika kilitlenen hesaplar."),
    stat("Başarılı giriş", f'sum(count_over_time({AUTH} | msg="login_succeeded" [$__range]))',
         (12, 42, 6, 4), color="green"),
    stat("Yeni kayıt", f'sum(count_over_time({AUTH} | msg="user_registered" [$__range]))',
         (18, 42, 6, 4), color="purple"),
    panel("timeseries", "Giriş olayları",
          f"sum by (msg) (count_over_time({AUTH} [$__auto]))", (0, 46, 24, 8), legend="{{msg}}",
          field_config={"custom": {"drawStyle": "bars", "fillOpacity": 80, "stacking": {"mode": "normal"}, "lineWidth": 0}},
          options={"legend": {"showLegend": True, "placement": "bottom"}, "tooltip": {"mode": "multi", "sort": "desc"}},
          overrides=[{"matcher": {"id": "byName", "options": n}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]}
                     for n, c in [("login_succeeded", "green"), ("user_registered", "purple"), ("login_failed", "orange"),
                                  ("login_locked", "red"), ("login_locked_now", "dark-red")]]),
]

templating = [{
    "name": "container", "label": "Container", "type": "query", "datasource": DS,
    "query": {"label": "container", "stream": "", "type": 1, "refId": "LokiVariableQueryEditor-VariableQuery"},
    "definition": "label_values(container)", "refresh": 2, "multi": True, "includeAll": True, "allValue": ".+",
    "current": {"text": "All", "value": "$__all"}, "sort": 1,
}]

dashboard = {
    "__inputs": [{"name": "DS_LOKI", "label": "loki", "type": "datasource", "pluginId": "loki", "pluginName": "Loki"}],
    "__requires": [{"type": "datasource", "id": "loki", "name": "Loki", "version": "1.0.0"}],
    "title": "semihcetinkaya.tech · Loglar",
    "uid": "bilet-loglar",
    "tags": ["bilet", "log"],
    "timezone": "browser",
    "time": {"from": "now-6h", "to": "now"},
    "refresh": "30s",
    "schemaVersion": 39,
    "editable": True,
    "graphTooltip": 1,
    "templating": {"list": templating},
    "panels": panels,
}

if __name__ == "__main__":
    out = Path(__file__).with_name("bilet-log-dashboard.json")
    out.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{out} yazıldı ({len(panels)} panel)")
