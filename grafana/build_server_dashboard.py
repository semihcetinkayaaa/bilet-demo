"""VPS sunucu metrikleri panosu (Prometheus) — Grafana dashboard JSON üretici.

Çalıştırma (proje kökünde):
    python grafana/build_server_dashboard.py
Çıktı: grafana/sunucu-dashboard.json -> Grafana > Dashboards > New > Import

Veri: node-exporter (sunucu) + cAdvisor (container'lar), bkz. infra/metrics/docker-compose.yml
"""

import json
from pathlib import Path

DS = {"type": "prometheus", "uid": "${DS_PROM}"}
NODE = 'job="node"'
CONT = 'job="cadvisor", name!=""'
ROOT_FS = f'{NODE}, mountpoint="/"'

# Coolify container adları -> okunur adlar (adların sonundaki yayın zamanı eki her yayında değişir)
CONTAINER_NAMES = [
    ("lhaabzf16e1csryupsbapana.*", "bilet-api"),
    ("j4ov4fqpvovjdqf38rj56ldg.*", "bilet-web"),
    ("whtf1pa3ezbbm82btp8aeu2o.*", "bilet-db"),
    ("grafana-.*", "grafana"),
    ("loki-.*", "loki"),
    ("alloy-.*", "alloy"),
    ("prometheus-.*", "prometheus"),
    ("node-exporter-.*", "node-exporter"),
    ("cadvisor-.*", "cadvisor"),
    ("n8n-.*", "n8n"),
    ("postgresql-spukwajggo9rswlyhov4f49k.*", "n8n-db"),
    ("task-runners-.*", "n8n-runners"),
]
RENAME = [{"id": "renameByRegex", "options": {"regex": f"^{rx}$", "renamePattern": nice}}
          for rx, nice in CONTAINER_NAMES]
VALUE_MAP = [{"type": "regex", "options": {"pattern": f"^{rx}$", "result": {"text": nice}}}
             for rx, nice in CONTAINER_NAMES]

_ids = iter(range(1, 1000))


def target(expr, legend="", instant=False, fmt="time_series"):
    return {"refId": "A", "datasource": DS, "editorMode": "code", "expr": expr, "legendFormat": legend,
            "instant": instant, "range": not instant, "format": fmt}


def panel(kind, title, targets, grid, *, unit=None, description="", options=None, field_config=None,
          overrides=None, transformations=None):
    x, y, w, h = grid
    defaults = {"unit": unit} if unit else {}
    defaults.update(field_config or {})
    for i, t in enumerate(targets):
        t["refId"] = chr(ord("A") + i)
    return {"id": next(_ids), "type": kind, "title": title, "description": description, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": targets,
            "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
            "options": options or {}, "transformations": transformations or []}


def gauge(title, expr, grid, *, description=""):
    return panel("gauge", title, [target(expr, instant=True)], grid, unit="percent", description=description,
                 field_config={"min": 0, "max": 100, "decimals": 0,
                               "thresholds": {"mode": "absolute", "steps": [
                                   {"color": "green", "value": None}, {"color": "orange", "value": 75},
                                   {"color": "red", "value": 90}]}},
                 options={"reduceOptions": {"calcs": ["lastNotNull"]}, "showThresholdMarkers": True})


def stat(title, expr, grid, *, unit="none", color="blue", decimals=None, description=""):
    fc = {"color": {"mode": "fixed", "fixedColor": color}}
    if decimals is not None:
        fc["decimals"] = decimals
    return panel("stat", title, [target(expr, instant=True)], grid, unit=unit, description=description,
                 field_config=fc, options={"reduceOptions": {"calcs": ["lastNotNull"]},
                                           "colorMode": "value", "graphMode": "none", "textMode": "value"})


TS_OPTS = {"legend": {"showLegend": True, "placement": "bottom", "displayMode": "list"},
           "tooltip": {"mode": "multi", "sort": "desc"}}
CPU_CORES = f'count(node_cpu_seconds_total{{{NODE}, mode="idle"}})'

panels = [
    # --- Anlık durum
    # Anlık (instant) sorgularda sabit 5m pencere: $__rate_interval burada 30 sn'lik ölçüm aralığına göre çok kısa kalıyor.
    gauge("CPU", f'100 * (1 - avg(rate(node_cpu_seconds_total{{{NODE}, mode="idle"}}[5m])))', (0, 0, 4, 6)),
    gauge("RAM", f"100 * (1 - node_memory_MemAvailable_bytes{{{NODE}}} / node_memory_MemTotal_bytes{{{NODE}}})", (4, 0, 4, 6),
          description="Kullanılan bellek (önbellek hariç; Linux boş belleği önbellek için kullanır, bu normaldir)."),
    gauge("Disk (/)", f"100 * (1 - node_filesystem_avail_bytes{{{ROOT_FS}}} / node_filesystem_size_bytes{{{ROOT_FS}}})", (8, 0, 4, 6)),
    stat("Yük (1 dk) / çekirdek", f"node_load1{{{NODE}}} / scalar({CPU_CORES})", (12, 0, 4, 3), unit="percentunit", decimals=0,
         color="purple", description="1'in (100%) üstü: işlemciler yetişemiyor, işler sırada bekliyor."),
    stat("Çekirdek", CPU_CORES, (12, 3, 4, 3), color="blue"),
    stat("Açık kalma süresi", f"time() - node_boot_time_seconds{{{NODE}}}", (16, 0, 4, 3), unit="s", decimals=0, color="green"),
    stat("Çalışan container", f"count(count by (name) (container_last_seen{{{CONT}}}))", (16, 3, 4, 3), color="teal"),
    stat("Toplam RAM", f"node_memory_MemTotal_bytes{{{NODE}}}", (20, 0, 4, 3), unit="bytes", decimals=1, color="blue"),
    stat("Boş disk (/)", f"node_filesystem_avail_bytes{{{ROOT_FS}}}", (20, 3, 4, 3), unit="bytes", decimals=1, color="green"),

    # --- Sunucu zaman serileri
    panel("timeseries", "CPU kullanımı (türe göre)",
          [target(f'100 * sum by (mode) (rate(node_cpu_seconds_total{{{NODE}, mode!="idle"}}[$__rate_interval])) / scalar({CPU_CORES})', "{{mode}}")],
          (0, 6, 12, 8), unit="percent", options=TS_OPTS,
          field_config={"min": 0, "custom": {"stacking": {"mode": "normal"}, "fillOpacity": 60, "lineWidth": 1}},
          description="user: uygulamalar, system: çekirdek, iowait: diski bekleme (yüksekse disk yavaş)."),
    panel("timeseries", "Bellek",
          [target(f"node_memory_MemTotal_bytes{{{NODE}}} - node_memory_MemAvailable_bytes{{{NODE}}}", "Kullanılan"),
           target(f"node_memory_Buffers_bytes{{{NODE}}} + node_memory_Cached_bytes{{{NODE}}}", "Önbellek"),
           target(f"node_memory_MemAvailable_bytes{{{NODE}}}", "Kullanılabilir")],
          (12, 6, 12, 8), unit="bytes", options=TS_OPTS, field_config={"min": 0, "custom": {"fillOpacity": 15}},
          overrides=[{"matcher": {"id": "byName", "options": n}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]}
                     for n, c in [("Kullanılan", "red"), ("Önbellek", "blue"), ("Kullanılabilir", "green")]]),
    panel("timeseries", "Sistem yükü",
          [target(f"node_load1{{{NODE}}}", "1 dk"), target(f"node_load5{{{NODE}}}", "5 dk"),
           target(f"node_load15{{{NODE}}}", "15 dk"), target(f"scalar({CPU_CORES})", "Çekirdek sayısı")],
          (0, 14, 8, 8), options=TS_OPTS, field_config={"min": 0},
          overrides=[{"matcher": {"id": "byName", "options": "Çekirdek sayısı"},
                      "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
                                     {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]}]),
    panel("timeseries", "Disk okuma / yazma",
          [target(f'sum(rate(node_disk_read_bytes_total{{{NODE}, device!~"loop.*|ram.*"}}[$__rate_interval]))', "Okuma"),
           target(f'-sum(rate(node_disk_written_bytes_total{{{NODE}, device!~"loop.*|ram.*"}}[$__rate_interval]))', "Yazma")],
          (8, 14, 8, 8), unit="Bps", options=TS_OPTS, description="Yazma aşağı yönde gösterilir."),
    panel("timeseries", "Ağ trafiği (container'lar toplamı)",
          [target(f"sum(rate(container_network_receive_bytes_total{{{CONT}}}[$__rate_interval]))", "Gelen"),
           target(f"-sum(rate(container_network_transmit_bytes_total{{{CONT}}}[$__rate_interval]))", "Giden")],
          (16, 14, 8, 8), unit="Bps", options=TS_OPTS, description="Giden trafik aşağı yönde gösterilir."),
    panel("bargauge", "Disk doluluğu (bölümler)",
          [target(f"100 * (1 - node_filesystem_avail_bytes{{{NODE}}} / node_filesystem_size_bytes{{{NODE}}})", "{{mountpoint}}", instant=True)],
          (0, 22, 8, 7), unit="percent",
          field_config={"min": 0, "max": 100, "thresholds": {"mode": "absolute", "steps": [
              {"color": "green", "value": None}, {"color": "orange", "value": 75}, {"color": "red", "value": 90}]}},
          options={"orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                   "reduceOptions": {"calcs": ["lastNotNull"], "values": False}}),

    # --- Container'lar
    panel("timeseries", "Container CPU kullanımı (en yüksek 8)",
          [target(f"topk(8, 100 * sum by (name) (rate(container_cpu_usage_seconds_total{{{CONT}}}[$__rate_interval])))", "{{name}}")],
          (8, 22, 16, 7), unit="percent", options=TS_OPTS, transformations=RENAME,
          description="100% = bir işlemci çekirdeğinin tamamı."),
    panel("timeseries", "Container bellek kullanımı (en yüksek 8)",
          [target(f"topk(8, sum by (name) (container_memory_working_set_bytes{{{CONT}}}))", "{{name}}")],
          (0, 29, 12, 9), unit="bytes", options=TS_OPTS, transformations=RENAME, field_config={"min": 0}),
    panel("table", "Container'lar",
          [target(f"sum by (name) (rate(container_cpu_usage_seconds_total{{{CONT}}}[5m])) * 100", instant=True, fmt="table"),
           target(f"sum by (name) (container_memory_working_set_bytes{{{CONT}}})", instant=True, fmt="table"),
           target(f"sum by (name) (rate(container_network_receive_bytes_total{{{CONT}}}[5m]) + rate(container_network_transmit_bytes_total{{{CONT}}}[5m]))", instant=True, fmt="table"),
           target(f"max by (name) (time() - container_start_time_seconds{{{CONT}}})", instant=True, fmt="table")],
          (12, 29, 12, 9),
          transformations=[
              {"id": "merge", "options": {}},
              {"id": "organize", "options": {
                  "excludeByName": {"Time": True},
                  "renameByName": {"name": "Container", "Value #A": "CPU %", "Value #B": "Bellek",
                                   "Value #C": "Ağ", "Value #D": "Çalışma süresi"}}},
              {"id": "sortBy", "options": {"sort": [{"field": "Bellek", "desc": True}]}},
          ],
          options={"showHeader": True, "cellHeight": "sm"},
          overrides=[
              {"matcher": {"id": "byName", "options": "Container"}, "properties": [{"id": "mappings", "value": VALUE_MAP}]},
              {"matcher": {"id": "byName", "options": "CPU %"}, "properties": [{"id": "unit", "value": "percent"}, {"id": "decimals", "value": 1}]},
              {"matcher": {"id": "byName", "options": "Bellek"}, "properties": [{"id": "unit", "value": "bytes"},
                  {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic"}}, {"id": "max", "value": 2 * 1024**3}]},
              {"matcher": {"id": "byName", "options": "Ağ"}, "properties": [{"id": "unit", "value": "Bps"}]},
              {"matcher": {"id": "byName", "options": "Çalışma süresi"}, "properties": [{"id": "unit", "value": "s"}, {"id": "decimals", "value": 0}]},
          ]),
]

dashboard = {
    "__inputs": [{"name": "DS_PROM", "label": "prometheus", "type": "datasource",
                  "pluginId": "prometheus", "pluginName": "Prometheus"}],
    "__requires": [{"type": "datasource", "id": "prometheus", "name": "Prometheus", "version": "1.0.0"}],
    "title": "semihcetinkaya.tech · Sunucu",
    "uid": "bilet-sunucu",
    "tags": ["sunucu", "vps"],
    "timezone": "browser",
    "time": {"from": "now-3h", "to": "now"},
    "refresh": "30s",
    "schemaVersion": 39,
    "editable": True,
    "graphTooltip": 1,
    "templating": {"list": []},
    "panels": panels,
}

if __name__ == "__main__":
    out = Path(__file__).with_name("sunucu-dashboard.json")
    out.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{out} yazıldı ({len(panels)} panel)")
