"""Alarm deneme uçları: Grafana alarmlarını (ve n8n → telefon aramasını) bilerek tetiklemek için.

Gerçek bir arıza yaratmaz; alarmların baktığı log satırlarının AYNISINI üretir. Her satırda
"test": true alanı vardır, Loki'de ayırt edilebilir (| json | test="true").

Güvenlik:
- ALARM_TEST_KEY ortam değişkeni boşsa (ya da 32 karakterden kısaysa) uçlar hiç yokmuş gibi 404 döner.
- Her istekte X-Test-Key başlığı gerekir. Anahtar adreste (URL) taşınmaz, böylece loglara düşmez.

Örnek (PowerShell):
    $h = @{ "X-Test-Key" = $env:ALARM_TEST_KEY }
    Invoke-RestMethod https://api.../test/alarm -Headers $h                 # senaryo listesi
    Invoke-RestMethod https://api.../test/alarm/5xx?adet=10 -Headers $h     # 10 adet 500 hatası
"""

import logging
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

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
                   "5 dakikada 5'ten fazla 500 hatası. Kritik: telefonla aranırsınız."),
    "veritabani": Senaryo("Veritabanı bağlantı hatası", "kritik", 1,
                          "Veritabanına bağlanılamadı log satırı. Kritik: telefonla aranırsınız."),
    "kaba-kuvvet": Senaryo("Olası kaba kuvvet saldırısı", "kritik", 40,
                           "5 dakikada 30'dan fazla başarısız giriş. Kritik: telefonla aranırsınız."),
    "hesap-kilidi": Senaryo("Çok sayıda hesap kilitlendi", "uyari", 5,
                            "15 dakikada 3'ten fazla hesap kilidi. Uyarı: arama yapılmaz."),
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


@router.get("")
def senaryolar(x_test_key: KeyHeader = None) -> JSONResponse:
    """Hangi senaryoların olduğunu listeler."""
    _kontrol(x_test_key)
    return JSONResponse(
        {ad: {"alarm": s.alarm, "onem": s.onem, "varsayilan_adet": s.varsayilan_adet, "aciklama": s.aciklama}
         for ad, s in SENARYOLAR.items()},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{senaryo}")
def tetikle(
    senaryo: str,
    x_test_key: KeyHeader = None,
    adet: Annotated[int | None, Query(ge=1, le=200)] = None,
) -> JSONResponse:
    """Seçilen alarmın baktığı log satırlarını üretir. Alarm 1 dakika içinde değerlendirilir."""
    _kontrol(x_test_key)
    s = SENARYOLAR.get(senaryo)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Böyle bir senaryo yok. Seçenekler: {', '.join(SENARYOLAR)}")
    n = adet or s.varsayilan_adet
    _uret(senaryo, n)
    govde = {"senaryo": senaryo, "uretilen_satir": n, "beklenen_alarm": s.alarm, "onem": s.onem,
             "not": "Grafana alarmı yaklaşık 1-2 dakika içinde tetiklenir. " + s.aciklama}
    # 5xx senaryosunda bu istek de gerçekten 500 döner (o da sayılır)
    return JSONResponse(govde, status_code=500 if senaryo == "5xx" else 200, headers={"Cache-Control": "no-store"})
