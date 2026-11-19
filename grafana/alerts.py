"""semihcetinkaya.tech satış alarmlarını Grafana'ya yükler (ya da günceller).

Gereken: Grafana'da "Admin" rolünde bir service account token'ı (alarm provisioning API'si
çoğu kurulumda Admin ister). İş bitince token'ı silebilirsiniz.
  Grafana > Administration > Users and access > Service accounts > Add service account
  > rol: Admin > Add service account token

Çalıştırma (proje kökünde, PowerShell):
    $env:GRAFANA_TOKEN = "glsa_..."        # token'ı sadece terminale yaz
    uv run --project backend python grafana/alerts.py

İsteğe bağlı ortam değişkenleri:
    GRAFANA_URL         (varsayılan https://grafana.semihcetinkaya.tech)
    GRAFANA_DATASOURCE  (varsayılan "bilet", veri kaynağının adı)

Betik tekrar çalıştırılabilir: aynı uid'li kurallar varsa günceller.
Satış alarmları sadece gerçek siparişlere bakar (@example.com demo siparişleri hariç).
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

FOLDER_UID = "bilet-alarmlar"
FOLDER_TITLE = "Bilet satış alarmları"
GROUP = "bilet-satis"
INTERVAL_SECONDS = 300  # 5 dakikada bir kontrol

REAL = "o.buyer_email NOT LIKE '%@example.com'"


def _baseline(expr: str, window: str) -> str:
    """Geçen 7 günün aynı saat aralığındaki günlük ortalama (ör. dün 14:00-15:00, önceki gün 14:00-15:00...)."""
    return f"""
SELECT COALESCE({expr}, 0) / 7.0 AS v
FROM generate_series(1, 7) AS d
JOIN orders o
  ON o.paid_at >= now() - make_interval(days => d) - interval '{window}'
 AND o.paid_at <  now() - make_interval(days => d)
WHERE o.status = 'paid' AND {REAL}"""


def _current(expr: str, window: str) -> str:
    return f"""
SELECT COALESCE({expr}, 0) AS v FROM orders o
WHERE o.status = 'paid' AND {REAL} AND o.paid_at >= now() - interval '{window}'"""


# Her kural: (uid, başlık, SQL, karşılaştırma, eşik, süre, önem, özet, açıklama)
# SQL tek satır, tek sayısal sütun ("deger") döndürür.
RULES = [
    {
        "uid": "bilet-ciro-dusus",
        "title": "Ciro düşüşü",
        "sql": f"""
WITH cur AS ({_current("SUM(o.total_amount)", "1 hour")}),
     base AS ({_baseline("SUM(o.total_amount)", "1 hour")})
SELECT CASE WHEN base.v < 500 THEN 1.0 ELSE cur.v / base.v END AS deger FROM cur, base""",
        "op": "lt", "threshold": 0.5, "for": "10m", "severity": "kritik",
        "summary": "Son 1 saatin cirosu normalin altında (normale oranı: {{ humanizePercentage $values.B.Value }})",
        "description": "Son 1 saatteki ciro, geçen 7 günün aynı saatlerindeki ortalamanın yarısının altında. "
                       "Ödeme sistemi, site erişimi veya bir hata olabilir.",
    },
    {
        "uid": "bilet-ciro-artis",
        "title": "Ciro artışı",
        "sql": f"""
WITH cur AS ({_current("SUM(o.total_amount)", "1 hour")}),
     base AS ({_baseline("SUM(o.total_amount)", "1 hour")})
SELECT CASE WHEN cur.v < 1000 THEN 0.0 WHEN base.v < 500 THEN 99.0 ELSE cur.v / base.v END AS deger FROM cur, base""",
        "op": "gt", "threshold": 2.0, "for": "0s", "severity": "bilgi",
        # 99 = karşılaştırılacak geçmiş satış yok (SQL'deki işaret değeri)
        "summary": "{{ if ge $values.B.Value 99.0 }}Son 1 saatte 1.000 TL'yi aşan ciro var; karşılaştırılacak geçmiş satış yok"
                   "{{ else }}Son 1 saatin cirosu normalin {{ humanize $values.B.Value }} katı{{ end }}",
        "description": "Son 1 saatteki ciro, geçen 7 günün aynı saatlerindeki ortalamanın 2 katını aştı. "
                       "Yeni bir etkinlik ya da kampanya etkisi olabilir.",
    },
    {
        "uid": "bilet-siparis-patlamasi",
        "title": "Sipariş patlaması",
        "sql": f"""
WITH cur AS ({_current("COUNT(*)", "1 hour")}),
     base AS ({_baseline("COUNT(*)", "1 hour")})
SELECT CASE WHEN cur.v < 10 THEN 0.0 WHEN base.v < 1 THEN 99.0 ELSE cur.v / base.v END AS deger FROM cur, base""",
        "op": "gt", "threshold": 2.0, "for": "0s", "severity": "uyari",
        "summary": "{{ if ge $values.B.Value 99.0 }}Son 1 saatte en az 10 sipariş var; karşılaştırılacak geçmiş satış yok"
                   "{{ else }}Son 1 saatte normalin {{ humanize $values.B.Value }} katı sipariş{{ end }}",
        "description": "Ödenen sipariş sayısı olağanın 2 katını aştı. Kampanya olabilir; "
                       "beklenmiyorsa bot / kötüye kullanım açısından kontrol edin.",
    },
    {
        "uid": "bilet-odeme-basarisi",
        "title": "Ödeme başarısı düştü",
        "sql": f"""
SELECT CASE WHEN COUNT(*) < 10 THEN 0.0
            ELSE COUNT(*) FILTER (WHERE o.status = 'failed')::float / COUNT(*) END AS deger
FROM orders o
WHERE {REAL} AND o.status IN ('paid', 'failed') AND o.created_at >= now() - interval '1 hour'""",
        "op": "gt", "threshold": 0.3, "for": "5m", "severity": "kritik",
        "summary": "Son 1 saatte reddedilen ödeme oranı: {{ humanizePercentage $values.B.Value }}",
        "description": "Reddedilen ödeme oranı %30'u geçti (en az 10 deneme). Ödeme altyapısını kontrol edin.",
    },
    {
        "uid": "bilet-satis-durdu",
        "title": "Satış durdu",
        "sql": f"""
WITH cur AS ({_current("COUNT(*)", "2 hours")}),
     base AS ({_baseline("COUNT(*)", "2 hours")})
SELECT CASE WHEN cur.v = 0 AND base.v >= 3 THEN 1.0 ELSE 0.0 END AS deger FROM cur, base""",
        "op": "gt", "threshold": 0.5, "for": "15m", "severity": "kritik",
        "summary": "Son 2 saatte hiç ödeme alınmadı",
        "description": "Geçen hafta aynı saatlerde ortalama 3+ ödeme varken son 2 saatte hiç yok. "
                       "Site, backend ve veritabanı erişimini kontrol edin.",
    },
    {
        "uid": "bilet-bekleyen-odeme",
        "title": "Bekleyen ödemeler birikti",
        "sql": f"""
SELECT COUNT(*)::float AS deger FROM orders o
WHERE {REAL} AND o.status = 'pending' AND o.created_at < now() - interval '15 minutes'
  AND o.created_at >= now() - interval '1 day'""",
        "op": "gt", "threshold": 15, "for": "10m", "severity": "uyari",
        "summary": "{{ $values.B.Value }} sipariş 15 dakikadan uzun süredir ödeme bekliyor",
        "description": "Kullanıcılar ödeme adımında takılıyor olabilir. Ödeme sayfasını ve backend loglarını kontrol edin.",
    },
    {
        "uid": "bilet-tukenmek-uzere",
        "title": "Tükenmek üzere olan biletler",
        "sql": """
SELECT COUNT(*)::float AS deger
FROM ticket_types tt JOIN events e ON e.id = tt.event_id
WHERE e.is_published AND e.starts_at >= now() AND tt.quota > 0
  AND tt.sold::float / tt.quota >= 0.9""",
        "op": "gt", "threshold": 0, "for": "0s", "severity": "bilgi",
        "summary": "Yaklaşan etkinliklerde {{ $values.B.Value }} bilet tipinin %90'ından fazlası satıldı",
        "description": "Ek kontenjan açmak ya da yeni seans eklemek isteyebilirsiniz. "
                       "Hangi etkinlikler olduğunu panodaki 'Yaklaşan etkinliklerde doluluk' tablosunda görebilirsiniz.",
    },
]


# Log alarmları (Loki). LogQL ifadesi tek bir sayı döndürür; sonuç yoksa (hiç hata yoksa) "OK".
BACKEND = '{container=~"lhaabzf16e1csryupsbapana.*"}'
HTTP = f'{BACKEND} | json logger, status, duration_ms | __error__="" | logger="bilet_api.http"'

LOG_RULES = [
    {
        "uid": "bilet-log-5xx",
        "title": "Backend 5xx hataları",
        "expr": f"sum(count_over_time({HTTP} | status >= 500 [5m]))",
        "op": "gt", "threshold": 5, "for": "0s", "severity": "kritik",
        "summary": "Son 5 dakikada {{ $values.B.Value }} sunucu hatası (5xx)",
        "description": "Backend 500 hatası veriyor. Grafana > Loglar panosundaki 'Backend uyarı ve hataları' "
                       "bölümünden ayrıntıya bakın.",
    },
    {
        "uid": "bilet-log-yavas",
        "title": "API yavaşladı",
        "expr": f'quantile_over_time(0.95, {HTTP} | unwrap duration_ms | __error__="" [10m]) by ()',
        "op": "gt", "threshold": 1500, "for": "10m", "severity": "uyari",
        "summary": "Son 10 dakikada isteklerin %5'i {{ humanize $values.B.Value }} ms'den uzun sürdü",
        "description": "API yanıt süresi (p95) 1,5 saniyeyi aştı. Veritabanı ya da sunucu yükünü kontrol edin.",
    },
    {
        "uid": "bilet-log-veritabani",
        "title": "Veritabanı bağlantı hatası",
        "expr": f'sum(count_over_time({BACKEND} |~ "OperationalError|connection timeout expired|could not connect|Connection refused" [5m]))',
        "op": "gt", "threshold": 0, "for": "0s", "severity": "kritik",
        "summary": "Backend son 5 dakikada {{ $values.B.Value }} kez veritabanına bağlanamadı",
        "description": "bilet-db container'ı çalışıyor mu? Coolify'da veritabanının durumunu kontrol edin.",
    },
    {
        "uid": "bilet-log-kaba-kuvvet",
        "title": "Olası kaba kuvvet saldırısı",
        "expr": f'sum(count_over_time({BACKEND} | json logger, msg | __error__="" | logger="bilet_api.auth" '
                f'| msg=~"login_failed|login_locked" [5m]))',
        "op": "gt", "threshold": 30, "for": "0s", "severity": "kritik",
        "summary": "Son 5 dakikada {{ $values.B.Value }} başarısız giriş denemesi",
        "description": "Olağandışı sayıda hatalı giriş var; şifre deneme saldırısı olabilir. Hesaplar 5 hatada "
                       "15 dk kilitleniyor, ama kaynak IP'yi Cloudflare'de engellemeyi düşünün.",
    },
    {
        "uid": "bilet-log-hesap-kilidi",
        "title": "Çok sayıda hesap kilitlendi",
        "expr": f'sum(count_over_time({BACKEND} | json logger, msg | __error__="" | logger="bilet_api.auth" '
                f'| msg="login_locked_now" [15m]))',
        "op": "gt", "threshold": 3, "for": "0s", "severity": "uyari",
        "summary": "Son 15 dakikada {{ $values.B.Value }} hesap kilitlendi",
        "description": "Birden fazla hesaba şifre denemesi yapılıyor olabilir (credential stuffing).",
    },
    {
        "uid": "bilet-log-eposta",
        "title": "Onay e-postası gönderilemedi",
        "expr": f'sum(count_over_time({BACKEND} |= "e-posta gönderilemedi" [15m]))',
        "op": "gt", "threshold": 0, "for": "0s", "severity": "uyari",
        "summary": "Son 15 dakikada {{ $values.B.Value }} onay e-postası gönderilemedi",
        "description": "SMTP ayarlarını ve e-posta servisini kontrol edin.",
    },
]


# Sunucu alarmları (Prometheus: node-exporter + cAdvisor)
SERVER_RULES = [
    {
        "uid": "sunucu-disk",
        "title": "Disk doluyor",
        "promql": '100 * (1 - node_filesystem_avail_bytes{job="node", mountpoint="/"} '
                  '/ node_filesystem_size_bytes{job="node", mountpoint="/"})',
        "op": "gt", "threshold": 85, "for": "10m", "severity": "kritik",
        "summary": "Sunucu diski %{{ humanize $values.B.Value }} dolu",
        "description": "Disk %85'i geçti. Docker imajlarını temizlemek için sunucuda: docker system prune -a "
                       "(dikkat: kullanılmayan tüm imajları siler). Log ve metrik saklama sürelerini de gözden geçirin.",
    },
    {
        "uid": "sunucu-ram",
        "title": "Bellek tükeniyor",
        "promql": '100 * (1 - node_memory_MemAvailable_bytes{job="node"} / node_memory_MemTotal_bytes{job="node"})',
        "op": "gt", "threshold": 90, "for": "10m", "severity": "uyari",
        "summary": "Sunucu belleğinin %{{ humanize $values.B.Value }}'ı kullanımda",
        "description": "Kullanılabilir bellek %10'un altında; swap olmadığı için bir servis kapatılabilir. "
                       "Sunucu panosundaki 'Container bellek kullanımı' grafiğinden hangi servisin şiştiğine bakın.",
    },
    {
        "uid": "sunucu-cpu",
        "title": "CPU uzun süre yüksek",
        "promql": '100 * (1 - avg(rate(node_cpu_seconds_total{job="node", mode="idle"}[5m])))',
        "op": "gt", "threshold": 90, "for": "15m", "severity": "uyari",
        "summary": "CPU 15 dakikadır %{{ humanize $values.B.Value }} seviyesinde",
        "description": "İşlemci 15 dakikadır %90'ın üzerinde. Sunucu panosundaki 'Container CPU kullanımı' grafiğine bakın.",
    },
    {
        "uid": "sunucu-metrik-yok",
        "title": "Sunucu metrikleri gelmiyor",
        # max() etiketleri siler; böylece "or vector(0)" sadece hiç veri yokken devreye girer.
        "promql": 'max(up{job="node"}) or vector(0)',
        "op": "lt", "threshold": 1, "for": "5m", "severity": "kritik",
        "summary": "node-exporter'dan 5 dakikadır veri alınamıyor",
        "description": "Sunucu ya da 'metrikler' servisi çalışmıyor olabilir. Coolify'da durumunu kontrol edin.",
    },
]


# --------------------------------------------------------------------------- Grafana API


def _api(method: str, path: str, body=None, ok_404=False):
    url = os.environ.get("GRAFANA_URL", "https://grafana.semihcetinkaya.tech").rstrip("/") + path
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", f"Bearer {os.environ['GRAFANA_TOKEN']}")
    # Cloudflare, Python'un varsayılan "Python-urllib" kimliğini bot sayıp engelliyor (hata 1010).
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; bilet-alarm-yukleyici/1.0)")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Disable-Provenance", "true")  # kurallar Grafana arayüzünden de düzenlenebilsin
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        if ok_404 and e.code == 404:
            return None
        detail = e.read().decode("utf-8", "replace")[:500]
        sys.exit(f"HATA: {method} {path} -> {e.code}\n{detail}")


def _query(rule: dict, ds_uid: str) -> dict:
    if "promql" in rule:  # Prometheus
        return {
            "refId": "A",
            "datasourceUid": ds_uid,
            "relativeTimeRange": {"from": 600, "to": 0},
            "model": {"refId": "A", "expr": rule["promql"], "instant": True, "range": False, "editorMode": "code"},
        }
    if "expr" in rule:  # Loki
        return {
            "refId": "A",
            "datasourceUid": ds_uid,
            "relativeTimeRange": {"from": 900, "to": 0},
            "model": {"refId": "A", "expr": rule["expr"], "queryType": "instant", "editorMode": "code"},
        }
    return {  # PostgreSQL
        "refId": "A",
        "datasourceUid": ds_uid,
        "relativeTimeRange": {"from": 3600, "to": 0},
        "model": {"refId": "A", "rawSql": rule["sql"].strip(), "format": "table",
                  "rawQuery": True, "editorMode": "code"},
    }


def _rule_body(rule: dict, ds_uid: str) -> dict:
    return {
        "uid": rule["uid"],
        "title": rule["title"],
        "folderUID": FOLDER_UID,
        "ruleGroup": GROUP,
        "orgID": 1,
        "condition": "C",
        "for": rule["for"],
        "noDataState": "OK",
        "execErrState": "Error",
        "labels": {"proje": "bilet", "onem": rule["severity"]},
        "annotations": {"summary": rule["summary"], "description": rule["description"]},
        "data": [
            _query(rule, ds_uid),
            {
                "refId": "B",
                "datasourceUid": "__expr__",
                "model": {"refId": "B", "type": "reduce", "expression": "A", "reducer": "last",
                          "datasource": {"type": "__expr__", "uid": "__expr__"}},
            },
            {
                "refId": "C",
                "datasourceUid": "__expr__",
                "model": {"refId": "C", "type": "threshold", "expression": "B",
                          "conditions": [{"evaluator": {"type": rule["op"], "params": [rule["threshold"]]}}],
                          "datasource": {"type": "__expr__", "uid": "__expr__"}},
            },
        ],
    }


def main() -> None:
    if not os.environ.get("GRAFANA_TOKEN"):
        sys.exit("GRAFANA_TOKEN ortam değişkeni yok. Önce: $env:GRAFANA_TOKEN = \"glsa_...\"")

    ds_name = os.environ.get("GRAFANA_DATASOURCE", "bilet")
    ds = _api("GET", f"/api/datasources/name/{urllib.parse.quote(ds_name)}")
    print(f"Veri kaynağı: {ds['name']} ({ds['uid']})")
    loki_name = os.environ.get("GRAFANA_LOKI_DATASOURCE", "loki")
    loki = _api("GET", f"/api/datasources/name/{urllib.parse.quote(loki_name)}", ok_404=True)
    if loki:
        print(f"Log veri kaynağı: {loki['name']} ({loki['uid']})")
    else:
        print(f"'{loki_name}' veri kaynağı yok; log alarmları atlanıyor.")
    prom_name = os.environ.get("GRAFANA_PROMETHEUS_DATASOURCE", "prometheus")
    prom = _api("GET", f"/api/datasources/name/{urllib.parse.quote(prom_name)}", ok_404=True)
    if prom:
        print(f"Metrik veri kaynağı: {prom['name']} ({prom['uid']})")
    else:
        print(f"'{prom_name}' veri kaynağı yok; sunucu alarmları atlanıyor.")
    rules = (
        [(r, ds["uid"]) for r in RULES]
        + [(r, loki["uid"]) for r in LOG_RULES if loki]
        + [(r, prom["uid"]) for r in SERVER_RULES if prom]
    )

    # Olmayan bir klasörü uid ile sormak bazı Grafana sürümlerinde 403 döndürüyor; listeye bakıyoruz.
    folders = _api("GET", "/api/folders?limit=1000") or []
    if not any(f.get("uid") == FOLDER_UID for f in folders):
        _api("POST", "/api/folders", {"uid": FOLDER_UID, "title": FOLDER_TITLE})
        print(f"Klasör oluşturuldu: {FOLDER_TITLE}")

    for rule, ds_uid in rules:
        body = _rule_body(rule, ds_uid)
        if _api("GET", f"/api/v1/provisioning/alert-rules/{rule['uid']}", ok_404=True) is None:
            _api("POST", "/api/v1/provisioning/alert-rules", body)
            print(f"  + {rule['title']}")
        else:
            _api("PUT", f"/api/v1/provisioning/alert-rules/{rule['uid']}", body)
            print(f"  ~ {rule['title']} (güncellendi)")

    group = _api("GET", f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/{GROUP}")
    group["interval"] = INTERVAL_SECONDS
    _api("PUT", f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/{GROUP}", group)
    print(f"Tamam: {len(rules)} alarm, {INTERVAL_SECONDS // 60} dakikada bir kontrol ediliyor.")


if __name__ == "__main__":
    main()
