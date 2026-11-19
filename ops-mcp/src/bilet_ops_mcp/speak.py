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


def period(hours: int) -> str:
    """1 -> 'son bir saatte', 6 -> 'son 6 saatte', 24 -> 'son bir günde', 168 -> 'son 7 günde'."""
    if hours == 1:
        return "son bir saatte"
    if hours == 24:
        return "son bir günde"
    if hours % 24 == 0:
        return f"son {hours // 24} günde"
    return f"son {hours} saatte"


def baseline_label(hours: int) -> str:
    """Karşılaştırmanın neye göre yapıldığı (bkz. server._baseline)."""
    if hours < 24:
        return "geçen haftanın aynı saatlerine"
    return "önceki güne" if hours == 24 else f"önceki {hours // 24} güne" if hours % 24 == 0 else "önceki eşit döneme"


def compare(current: float, baseline: float, against: str) -> str:
    """Normale göre değişimi söyler. against: 'geçen haftanın aynı saatlerine' gibi (yönelme hâli)."""
    if baseline <= 0:
        return "için karşılaştırılacak geçmiş veri yok"
    ratio = current / baseline
    if 0.9 <= ratio <= 1.1:
        return f"{against} göre hemen hemen aynı"
    if ratio > 1:
        return f"{against} göre {pct(ratio - 1)} fazla"
    return f"{against} göre {pct(1 - ratio)} az"


def spell_code(code: str) -> str:
    """'BLT-7K3QX9' -> 'BLT, 7 K 3 Q X 9' (telefonda karakter karakter okunsun)."""
    body = code.split("-", 1)[-1]
    return "BLT, " + " ".join(body)


def mask_name(name: str) -> str:
    """'Ayşe Kaya' -> 'A. K.' (kişisel veriyi telefonda okumamak için)."""
    return " ".join(f"{p[0]}." for p in name.split() if p) or "?"
