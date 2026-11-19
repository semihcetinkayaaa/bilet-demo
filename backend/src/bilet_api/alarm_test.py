"""Alarm deneme uçları: Grafana alarmlarını (ve n8n → telefon aramasını) bilerek tetiklemek için.

Gerçek bir arıza yaratmaz; alarmların baktığı log satırlarının AYNISINI üretir. Her satırda
"test": true alanı vardır, Loki'de ayırt edilebilir (| json | test="true").

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
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from bilet_api.config import settings

router = APIRouter(prefix="/test/alarm", tags=["alarm testi"], include_in_schema=False)

_http = logging.getLogger("bilet_api.http")
_auth = logging.getLogger("bilet_api.auth")
_mail = logging.getLogger("bilet_api.mailer")
_db = logging.getLogger("bilet_api.db")
TEST = {"test": True}


@dataclass(frozen=True)
class Senaryo:
    alarm: str
    onem: str
    varsayilan_adet: int
    aciklama: str


SENARYOLAR: dict[str, Senaryo] = {
    "5xx": Senaryo("Backend 5xx hataları", "kritik", 10,
                   "1 dakikada 5'ten fazla 500 hatası. Kritik: telefonla aranırsınız."),
    "veritabani": Senaryo("Veritabanı bağlantı hatası", "kritik", 1,
                          "Veritabanına bağlanılamadı log satırı. Kritik: telefonla aranırsınız."),
    "kaba-kuvvet": Senaryo("Olası kaba kuvvet saldırısı", "kritik", 40,
                           "1 dakikada 15'ten fazla başarısız giriş. Kritik: telefonla aranırsınız."),
    "hesap-kilidi": Senaryo("Çok sayıda hesap kilitlendi", "uyari", 5,
                            "5 dakikada 3'ten fazla hesap kilidi. Uyarı: arama yapılmaz."),
    "eposta": Senaryo("Onay e-postası gönderilemedi", "uyari", 1,
                      "E-posta gönderilemedi log satırı. Uyarı: arama yapılmaz."),
    "yavas": Senaryo("API yavaşladı", "uyari", 100,
                     "Yanıt süresi 3 sn olan istekler. Alarm 10 dk sürmesini bekler: "
                     "12 dk boyunca 2-3 dakikada bir çağırın. Uyarı: arama yapılmaz."),
}


def _kontrol(anahtar: str | None) -> None:
    beklenen = settings.alarm_test_key
    if len(beklenen) < 32:
        raise HTTPException(status_code=404, detail="Not Found")
    if not anahtar or not secrets.compare_digest(anahtar.encode(), beklenen.encode()):
        raise HTTPException(status_code=401, detail="X-Test-Key başlığı eksik ya da yanlış")


def _uret(senaryo: str, adet: int) -> None:
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


KeyHeader = Annotated[str | None, Header(alias="X-Test-Key")]
KeyQuery = Annotated[str | None, Query(alias="anahtar")]
NO_CACHE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"}


def _menu(anahtar: str) -> HTMLResponse:
    """Telefon için tıklanabilir senaryo listesi."""
    k = quote(anahtar, safe="")
    satirlar = "".join(
        f'<a class="b {s.onem}" href="/test/alarm/{ad}?anahtar={k}">'
        f'<b>{html.escape(s.alarm)}</b><span>{"📞 arar" if s.onem == "kritik" else "aramaz"} · '
        f'{html.escape(s.aciklama)}</span></a>'
        for ad, s in SENARYOLAR.items()
    )
    return _sayfa("<h1>Alarm testi</h1><p>Bir senaryoya dokunun; alarm yaklaşık 30 saniyede tetiklenir, 1 dakikada kapanır.</p>" + satirlar)


def _sayfa(icerik: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        '<!doctype html><html lang="tr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Alarm testi</title><style>'
        "body{font-family:system-ui,sans-serif;margin:16px;background:#f6f6f6;color:#111}"
        "h1{font-size:20px}.b{display:block;padding:14px;margin:10px 0;border-radius:12px;background:#fff;"
        "text-decoration:none;color:inherit;border-left:6px solid #f59e0b}.b.kritik{border-left-color:#dc2626}"
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
        {ad: {"alarm": s.alarm, "onem": s.onem, "varsayilan_adet": s.varsayilan_adet, "aciklama": s.aciklama}
         for ad, s in SENARYOLAR.items()},
        headers=NO_CACHE,
    )


@router.get("/{senaryo}")
def tetikle(
    senaryo: str,
    x_test_key: KeyHeader = None,
    anahtar: KeyQuery = None,
    adet: Annotated[int | None, Query(ge=1, le=200)] = None,
):
    """Seçilen alarmın baktığı log satırlarını üretir. Alarm 1 dakika içinde değerlendirilir."""
    _kontrol(x_test_key or anahtar)
    s = SENARYOLAR.get(senaryo)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Böyle bir senaryo yok. Seçenekler: {', '.join(SENARYOLAR)}")
    n = adet or s.varsayilan_adet
    _uret(senaryo, n)
    govde = {"senaryo": senaryo, "uretilen_satir": n, "beklenen_alarm": s.alarm, "onem": s.onem,
             "not": "Grafana alarmı yaklaşık 30 saniye içinde tetiklenir. " + s.aciklama}
    # 5xx senaryosunda bu istek de gerçekten 500 döner (o da sayılır)
    durum = 500 if senaryo == "5xx" else 200
    if anahtar and not x_test_key:  # telefondan açıldı: okunur sayfa
        arama = "Kritik alarm: telefonunuz birazdan çalacak." if s.onem == "kritik" else "Uyarı seviyesi: arama yapılmaz."
        return _sayfa(
            f'<h1>✅ {html.escape(s.alarm)}</h1><p>{n} log satırı üretildi. Grafana alarmı yaklaşık 30 saniye içinde '
            f"tetiklenir.</p><p><b>{arama}</b></p><p>{html.escape(s.aciklama)}</p>"
            f'<a class="b" href="/test/alarm?anahtar={quote(anahtar, safe="")}"><b>← Menüye dön</b></a>',
            status_code=durum,
        )
    return JSONResponse(govde, status_code=durum, headers=NO_CACHE)
