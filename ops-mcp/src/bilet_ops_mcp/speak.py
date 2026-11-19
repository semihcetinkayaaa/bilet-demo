"""Telefonda sesli okunacak Türkçe metin yardımcıları.

Araçlar JSON değil kısa cümleler döndürür; sesli agent bunları olduğu gibi okuyabilir.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Istanbul")
_DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
           "Eylül", "Ekim", "Kasım", "Aralık"]
CATEGORY = {"concert": "konser", "match": "maç", "cinema": "sinema", "theater": "tiyatro"}
STATUS = {"paid": "ödendi", "pending": "ödeme bekliyor", "failed": "ödeme reddedildi", "cancelled": "iptal edildi"}


def num(n: float | int) -> str:
    """12345 -> '12.345' (Türkçe binlik ayıracı)."""
    return f"{round(n):,}".replace(",", ".")


def tl(n: float | int) -> str:
    return f"{num(n)} lira"


def pct(ratio: float) -> str:
    return f"yüzde {round(ratio * 100)}"


def when(dt: datetime, with_date: bool = True) -> str:
    local = dt.astimezone(TZ)
    clock = local.strftime("%H:%M")
    if not with_date:
        return clock
    today = datetime.now(TZ).date()
    delta = (local.date() - today).days
    if delta == 0:
        day = "bugün"
    elif delta == 1:
        day = "yarın"
    elif 1 < delta < 7:
        day = _DAYS[local.weekday()]
    else:
        day = f"{local.day} {_MONTHS[local.month - 1]} {_DAYS[local.weekday()]}"
    return f"{day} {clock}"


def ago(dt: datetime) -> str:
    minutes = int((datetime.now(TZ) - dt.astimezone(TZ)).total_seconds() // 60)
    if minutes < 1:
        return "az önce"
    if minutes < 60:
        return f"{minutes} dakika önce"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} saat önce"
    return f"{hours // 24} gün önce"


def compare(current: float, baseline: float) -> str:
    """Normale göre değişimi söyler."""
    if baseline <= 0:
        return "karşılaştırma için geçmiş veri yok"
    ratio = current / baseline
    if 0.9 <= ratio <= 1.1:
        return "geçen haftanın aynı saatleriyle hemen hemen aynı"
    if ratio > 1:
        return f"geçen haftanın aynı saatlerine göre {pct(ratio - 1)} fazla"
    return f"geçen haftanın aynı saatlerine göre {pct(1 - ratio)} az"


def mask_name(name: str) -> str:
    """'Ayşe Kaya' -> 'A. K.' (kişisel veriyi telefonda okumamak için)."""
    return " ".join(f"{p[0]}." for p in name.split() if p) or "?"
