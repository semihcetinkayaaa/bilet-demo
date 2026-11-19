"""Alarm deneme uçları: Grafana alarmlarını (ve n8n → telefon aramasını) bilerek tetiklemek için.

İki tür senaryo vardır:
- Log senaryoları: gerçek bir arıza yaratmaz; alarmların baktığı log satırlarının AYNISINI üretir.
  Her satırda "test": true alanı vardır, Loki'de ayırt edilebilir (| json | test="true").
- Sipariş senaryoları: satış/ödeme alarmları veritabanına baktığı için İŞARETLİ TEST SİPARİŞLERİ oluşturur
  (alıcı "Alarm Testi", e-posta ...@alarm-test.invalid, sipariş kalemi yok, stok değişmez, e-posta gitmez).
  Bunlar satış panolarında da görünür; işiniz bitince menüdeki "Test siparişlerini sil" ile silin.

Güvenlik:
- ALARM_TEST_KEY ortam değişkeni boşsa (ya da 32 karakterden kısaysa) uçlar hiç yokmuş gibi 404 döner.
- Her istekte anahtar gerekir: X-Test-Key başlığı ya da (telefon tarayıcısı için) ?anahtar=... parametresi.
  Backend logları sadece yolu (path) yazar, ?anahtar kısmı loglara düşmez. Telefonun tarayıcı geçmişinde
  kalır; anahtarı ara sıra değiştirin.

Örnek (PowerShell):
    $h = @{ "X-Test-Key" = $env:ALARM_TEST_KEY }
    Invoke-RestMethod https://api.../test/alarm -Headers $h                 # senaryo listesi
    Invoke-RestMethod https://api.../test/alarm/5xx?adet=10 -Headers $h     # 10 adet 500 hatası
Telefondan: https://api.../test/alarm?anahtar=...  (tıklanabilir menü)
"""

import html
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import delete, func, select

from bilet_api.codes import new_order_code
from bilet_api.config import settings
from bilet_api.db import SessionLocal
from bilet_api.models import Order, OrderStatus

router = APIRouter(prefix="/test/alarm", tags=["alarm testi"], include_in_schema=False)

_http = logging.getLogger("bilet_api.http")
_auth = logging.getLogger("bilet_api.auth")
_mail = logging.getLogger("bilet_api.mailer")
_db = logging.getLogger("bilet_api.db")
_log = logging.getLogger("bilet_api.alarm_test")
TEST = {"test": True}

TEST_DOMAIN = "@alarm-test.invalid"  # .invalid alan adı hiçbir zaman gerçek olamaz (RFC 2606)
TEST_NAME = "Alarm Testi"
MAX_TEST_ORDERS = 400  # yanlışlıkla defalarca dokunulursa veritabanı şişmesin


@dataclass(frozen=True)
class Senaryo:
    alarm: str
    onem: str  # kritik | uyari | bilgi
    aciklama: str
    bekleme: str  # alarm ne kadar sürede tetiklenir
    tur: str = "log"  # log | siparis | temizle
    varsayilan_adet: int = 1


SENARYOLAR: dict[str, Senaryo] = {
    # ---- Log senaryoları
    "5xx": Senaryo("Backend 5xx hataları", "kritik", "1 dakikada 5'ten fazla 500 hatası.",
                   "yaklaşık 30 saniye", varsayilan_adet=10),
    "veritabani": Senaryo("Veritabanı bağlantı hatası", "kritik", "Veritabanına bağlanılamadı log satırı.",
                          "yaklaşık 30 saniye"),
    "kaba-kuvvet": Senaryo("Olası kaba kuvvet saldırısı", "kritik", "1 dakikada 15'ten fazla başarısız giriş.",
                           "yaklaşık 30 saniye", varsayilan_adet=40),
    "hesap-kilidi": Senaryo("Çok sayıda hesap kilitlendi", "uyari", "5 dakikada 3'ten fazla hesap kilidi.",
                            "yaklaşık 30 saniye", varsayilan_adet=5),
    "eposta": Senaryo("Onay e-postası gönderilemedi", "uyari", "E-posta gönderilemedi log satırı.",
                      "yaklaşık 30 saniye"),
    "yavas": Senaryo("API yavaşladı", "uyari",
                     "Yanıt süresi 3 sn olan istekler. Alarm 10 dk sürmesini bekler: 12 dk boyunca 2-3 dakikada "
                     "bir dokunun.", "en az 10 dakika", varsayilan_adet=100),
    # ---- Sipariş senaryoları (işaretli test siparişleri)
    "odeme-basarisi": Senaryo("Ödeme başarısı düştü", "kritik",
                              "11 test ödemesi, 7'si reddedilmiş (yüzde 64). Alarm 5 dk sürmesini bekler.",
                              "yaklaşık 5-6 dakika", tur="siparis"),
    "bekleyen-odeme": Senaryo("Bekleyen ödemeler birikti", "uyari",
                              "20 dakikadır ödeme bekleyen 16 test siparişi. Alarm 10 dk sürmesini bekler.",
                              "yaklaşık 10-11 dakika", tur="siparis"),
    "siparis-patlamasi": Senaryo("Sipariş patlaması", "uyari", "Son bir saatte 12 ödenmiş test siparişi (50'şer lira).",
                                 "yaklaşık 30 saniye", tur="siparis"),
    "ciro-artisi": Senaryo("Ciro artışı", "bilgi", "Son bir saatte 1.500 liralık test satışı.",
                           "yaklaşık 30 saniye", tur="siparis"),
    "ciro-dusus": Senaryo("Ciro düşüşü", "kritik",
                          "Geçen 7 günün bu saatine 2.000'er liralık test satışı ekler; bugün satış olmadığı için "
                          "ciro normalin altında görünür. Önceki test siparişleri silinir. Alarm 10 dk bekler.",
                          "yaklaşık 10-11 dakika", tur="siparis"),
    "satis-durdu": Senaryo("Satış durdu", "kritik",
                           "Geçen 7 günün bu saatlerine 3'er test satışı ekler; son 2 saatte satış yoksa alarm verir. "
                           "Önceki test siparişleri silinir. Alarm 15 dk bekler.",
                           "yaklaşık 15-16 dakika", tur="siparis"),
    "temizle": Senaryo("Test siparişlerini sil", "temizle",
                       "Bu sayfanın oluşturduğu tüm test siparişlerini siler; satış alarmları normale döner.",
                       "hemen", tur="temizle"),
}
# Bu senaryolar önce eski test siparişlerini siler (diğer testlerin satışları sonucu bozmasın)
TEMIZ_BASLA = {"ciro-dusus", "satis-durdu"}


def _kontrol(anahtar: str | None) -> None:
    beklenen = settings.alarm_test_key
    if len(beklenen) < 32:
        raise HTTPException(status_code=404, detail="Not Found")
    if not anahtar or not secrets.compare_digest(anahtar.encode(), beklenen.encode()):
        raise HTTPException(status_code=401, detail="X-Test-Key başlığı eksik ya da yanlış")


def _uret_log(senaryo: str, adet: int) -> None:
    for _ in range(adet):
        if senaryo == "5xx":
            _http.error("request", extra={"method": "GET", "path": "/test/alarm/5xx", "route": "/test/alarm/{senaryo}",
                                          "status": 500, "duration_ms": 5.0, **TEST})
        elif senaryo == "yavas":
            _http.info("request", extra={"method": "GET", "path": "/test/alarm/yavas", "route": "/test/alarm/{senaryo}",
                                         "status": 200, "duration_ms": 3000.0, **TEST})
        elif senaryo == "veritabani":
            _db.error("TEST: OperationalError simülasyonu, gerçek bir bağlantı sorunu değil", extra=TEST)
        elif senaryo == "kaba-kuvvet":
            _auth.warning("login_failed", extra={"reason": "test", **TEST})
        elif senaryo == "hesap-kilidi":
            _auth.warning("login_locked_now", extra={"reason": "test", **TEST})
        elif senaryo == "eposta":
            _mail.error("TEST-000 için e-posta gönderilemedi", extra=TEST)


def _test_filtre():
    return Order.buyer_email.like(f"%{TEST_DOMAIN}")


def _test_siparis_sayisi() -> int | None:
    try:
        with SessionLocal() as db:
            return db.scalar(select(func.count()).select_from(Order).where(_test_filtre()))
    except Exception:
        return None


def _test_siparislerini_sil() -> int:
    with SessionLocal() as db:
        n = db.execute(delete(Order).where(_test_filtre())).rowcount
        db.commit()
    _log.info("alarm_test_orders_deleted", extra={"count": n, **TEST})
    return n


def _siparis_planla(senaryo: str, now: datetime) -> list[tuple[OrderStatus, int, datetime, datetime | None]]:
    """(durum, tutar, oluşturulma, ödenme) listesi."""
    P, F, W = OrderStatus.PAID, OrderStatus.FAILED, OrderStatus.PENDING
    if senaryo == "odeme-basarisi":
        return [(F, 100, now, None)] * 7 + [(P, 100, now, now)] * 4
    if senaryo == "bekleyen-odeme":
        t = now - timedelta(minutes=20)
        return [(W, 150, t, None)] * 16
    if senaryo == "siparis-patlamasi":
        return [(P, 50, now, now)] * 12
    if senaryo == "ciro-artisi":
        return [(P, 500, now, now)] * 3
    if senaryo == "ciro-dusus":
        return [(P, 2000, t, t) for d in range(1, 8) for t in [now - timedelta(days=d, minutes=20)]]
    if senaryo == "satis-durdu":
        return [(P, 100, t, t) for d in range(1, 8) for m in (30, 50, 70)
                for t in [now - timedelta(days=d, minutes=m)]]
    return []


def _uret_siparis(senaryo: str) -> int:
    if senaryo in TEMIZ_BASLA:
        _test_siparislerini_sil()
    plan = _siparis_planla(senaryo, datetime.now(UTC))
    with SessionLocal() as db:
        mevcut = db.scalar(select(func.count()).select_from(Order).where(_test_filtre())) or 0
        if mevcut + len(plan) > MAX_TEST_ORDERS:
            raise HTTPException(status_code=429, detail="Çok fazla test siparişi var; önce 'Test siparişlerini sil'.")
        for durum, tutar, olusma, odeme in plan:
            db.add(Order(code=new_order_code(), buyer_name=TEST_NAME, buyer_email=f"{senaryo}{TEST_DOMAIN}",
                         total_amount=Decimal(tutar), status=durum, created_at=olusma, paid_at=odeme))
        db.commit()
    _log.info("alarm_test_orders_created", extra={"scenario": senaryo, "count": len(plan), **TEST})
    return len(plan)


KeyHeader = Annotated[str | None, Header(alias="X-Test-Key")]
KeyQuery = Annotated[str | None, Query(alias="anahtar")]
NO_CACHE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"}
ARAMA = {"kritik": "📞 arar", "uyari": "aramaz", "bilgi": "aramaz", "temizle": ""}


def _kart(ad: str, s: Senaryo, k: str, ek: str = "") -> str:
    etiket = " · ".join(x for x in (ARAMA[s.onem], f"{s.bekleme} içinde" if s.tur != "temizle" else "", ek) if x)
    return (f'<a class="b {s.onem}" href="/test/alarm/{ad}?anahtar={k}"><b>{html.escape(s.alarm)}</b>'
            f"<span>{html.escape(etiket)}</span><span>{html.escape(s.aciklama)}</span></a>")


def _menu(anahtar: str) -> HTMLResponse:
    """Telefon için tıklanabilir senaryo listesi."""
    k = quote(anahtar, safe="")
    log = "".join(_kart(ad, s, k) for ad, s in SENARYOLAR.items() if s.tur == "log")
    sip = "".join(_kart(ad, s, k) for ad, s in SENARYOLAR.items() if s.tur == "siparis")
    n = _test_siparis_sayisi()
    sayi = "bilinmiyor" if n is None else f"{n} test siparişi var"
    temiz = _kart("temizle", SENARYOLAR["temizle"], k, sayi)
    return _sayfa(
        "<h1>Alarm testi</h1><p>Bir senaryoya dokunun. Kırmızılar kritik: telefonla aranırsınız.</p>"
        f"<h2>Hata ve log alarmları</h2>{log}"
        "<h2>Satış ve ödeme alarmları</h2><p class='n'>Bunlar işaretli test siparişleri oluşturur; satış "
        "panolarında da görünür. İşiniz bitince en alttan silin.</p>"
        f"{sip}<h2>Temizlik</h2>{temiz}"
    )


def _sayfa(icerik: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        '<!doctype html><html lang="tr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Alarm testi</title><style>'
        "body{font-family:system-ui,sans-serif;margin:16px;background:#f6f6f6;color:#111}"
        "h1{font-size:20px}h2{font-size:15px;margin:22px 0 4px;color:#444}.n{font-size:13px;color:#555;margin:0}"
        ".b{display:block;padding:14px;margin:10px 0;border-radius:12px;background:#fff;"
        "text-decoration:none;color:inherit;border-left:6px solid #f59e0b}.b.kritik{border-left-color:#dc2626}"
        ".b.bilgi{border-left-color:#3b82f6}.b.temizle{border-left-color:#6b7280}"
        ".b span{display:block;font-size:13px;color:#555;margin-top:4px}"
        f"</style></head><body>{icerik}</body></html>",
        status_code=status_code,
        headers=NO_CACHE,
    )


@router.get("")
def senaryolar(x_test_key: KeyHeader = None, anahtar: KeyQuery = None):
    """Hangi senaryoların olduğunu listeler. ?anahtar ile açılırsa telefon menüsü gösterir."""
    _kontrol(x_test_key or anahtar)
    if anahtar and not x_test_key:
        return _menu(anahtar)
    return JSONResponse(
        {"senaryolar": {ad: {"alarm": s.alarm, "onem": s.onem, "tur": s.tur, "bekleme": s.bekleme,
                             "aciklama": s.aciklama} for ad, s in SENARYOLAR.items()},
         "test_siparisi": _test_siparis_sayisi()},
        headers=NO_CACHE,
    )


@router.get("/{senaryo}")
def tetikle(
    senaryo: str,
    x_test_key: KeyHeader = None,
    anahtar: KeyQuery = None,
    adet: Annotated[int | None, Query(ge=1, le=200)] = None,
):
    """Seçilen senaryoyu çalıştırır: log satırları üretir, test siparişi oluşturur ya da test siparişlerini siler."""
    _kontrol(x_test_key or anahtar)
    s = SENARYOLAR.get(senaryo)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Böyle bir senaryo yok. Seçenekler: {', '.join(SENARYOLAR)}")

    if s.tur == "temizle":
        n = _test_siparislerini_sil()
        sonuc, baslik = f"{n} test siparişi silindi. Satış alarmları birkaç dakika içinde normale döner.", "🧹 Temizlendi"
    elif s.tur == "siparis":
        n = _uret_siparis(senaryo)
        sonuc, baslik = f"{n} test siparişi oluşturuldu.", f"✅ {s.alarm}"
    else:
        n = adet or s.varsayilan_adet
        _uret_log(senaryo, n)
        sonuc, baslik = f"{n} log satırı üretildi.", f"✅ {s.alarm}"

    govde = {"senaryo": senaryo, "tur": s.tur, "adet": n, "beklenen_alarm": s.alarm, "onem": s.onem,
             "not": f"{sonuc} Alarm {s.bekleme} içinde tetiklenir. {s.aciklama}"}
    # 5xx senaryosunda bu istek de gerçekten 500 döner (o da sayılır)
    durum = 500 if senaryo == "5xx" else 200
    if anahtar and not x_test_key:  # telefondan açıldı: okunur sayfa
        if s.tur == "temizle":
            arama = ""
        elif s.onem == "kritik":
            arama = f"<p><b>Kritik alarm: telefonunuz {s.bekleme} içinde çalacak.</b></p>"
        else:
            arama = f"<p><b>Alarm {s.bekleme} içinde tetiklenir; bu seviyede arama yapılmaz.</b></p>"
        hatirlat = ("<p>İşiniz bitince menünün en altındaki <b>Test siparişlerini sil</b> düğmesine dokunun.</p>"
                    if s.tur == "siparis" else "")
        return _sayfa(
            f"<h1>{html.escape(baslik)}</h1><p>{html.escape(sonuc)}</p>{arama}"
            f"<p>{html.escape(s.aciklama)}</p>{hatirlat}"
            f'<a class="b" href="/test/alarm?anahtar={quote(anahtar, safe="")}"><b>← Menüye dön</b></a>',
            status_code=durum,
        )
    return JSONResponse(govde, status_code=durum, headers=NO_CACHE)
