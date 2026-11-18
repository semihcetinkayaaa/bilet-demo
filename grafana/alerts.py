"""semihcetinkaya.tech satış alarmlarını Grafana'ya yükler (ya da günceller).

Gereken: Grafana'da "Editor" rolünde bir service account token'ı.
  Grafana > Administration > Users and access > Service accounts > Add service account
  > rol: Editor > Add service account token

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
        "summary": "Son 1 saatin cirosu normalin {{ humanize $values.B.Value }} katı",
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
        "summary": "Son 1 saatte normalin {{ humanize $values.B.Value }} katı sipariş",
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


# --------------------------------------------------------------------------- Grafana API


def _api(method: str, path: str, body=None, ok_404=False):
    url = os.environ.get("GRAFANA_URL", "https://grafana.semihcetinkaya.tech").rstrip("/") + path
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", f"Bearer {os.environ['GRAFANA_TOKEN']}")
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
            {
                "refId": "A",
                "datasourceUid": ds_uid,
                "relativeTimeRange": {"from": 3600, "to": 0},
                "model": {"refId": "A", "rawSql": rule["sql"].strip(), "format": "table",
                          "rawQuery": True, "editorMode": "code"},
            },
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

    if _api("GET", f"/api/folders/{FOLDER_UID}", ok_404=True) is None:
        _api("POST", "/api/folders", {"uid": FOLDER_UID, "title": FOLDER_TITLE})
        print(f"Klasör oluşturuldu: {FOLDER_TITLE}")

    for rule in RULES:
        body = _rule_body(rule, ds["uid"])
        if _api("GET", f"/api/v1/provisioning/alert-rules/{rule['uid']}", ok_404=True) is None:
            _api("POST", "/api/v1/provisioning/alert-rules", body)
            print(f"  + {rule['title']}")
        else:
            _api("PUT", f"/api/v1/provisioning/alert-rules/{rule['uid']}", body)
            print(f"  ~ {rule['title']} (güncellendi)")

    group = _api("GET", f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/{GROUP}")
    group["interval"] = INTERVAL_SECONDS
    _api("PUT", f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/{GROUP}", group)
    print(f"Tamam: {len(RULES)} alarm, {INTERVAL_SECONDS // 60} dakikada bir kontrol ediliyor.")


if __name__ == "__main__":
    main()
