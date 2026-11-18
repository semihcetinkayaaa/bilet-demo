"""Örnek veri yükleyici: semihcetinkaya.tech bilet satış demosu.

Tüm mekan, sanatçı, takım, film ve kişi adları uydurmadır.
Alıcı e-postaları @example.com alan adındadır (bu alan adı test için ayrılmıştır,
gerçek kimseye e-posta gitmez).

Kullanım (backend klasöründe, SSH tüneli açıkken):
    uv run python -m bilet_api.seed --reset       # bilet_dev'i temizleyip doldurur
    uv run python -m bilet_api.seed --no-orders   # sadece mekan/etkinlik/bilet tipi

Güvenlik: --reset yalnızca adı "_dev" ile biten veritabanlarında çalışır.
Sahte siparişler de varsayılan olarak sadece _dev'e yazılır; gerçek veritabanına
yazmak için ayrıca --demo-orders-in-prod verilmelidir:
    python -m bilet_api.seed --demo-orders-in-prod
"""

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from bilet_api.codes import new_order_code
from bilet_api.db import SessionLocal, engine
from bilet_api.models import (
    Event,
    EventCategory,
    Order,
    OrderItem,
    OrderStatus,
    TicketType,
    Venue,
)

TZ = ZoneInfo("Europe/Istanbul")
C = EventCategory

# --------------------------------------------------------------------------- mekanlar

VENUES = {
    "arena": ("Kuzey Yıldızı Arena", "İstanbul", "Ayazağa Yolu No:12, Sarıyer", 18000),
    "liman": ("Mavi Liman Konser Salonu", "İzmir", "Kordon Boyu No:45, Alsancak", 2500),
    "bozkir": ("Bozkır Stadyumu", "Ankara", "Eskişehir Yolu 9. km, Çankaya", 32000),
    "yesilvadi": ("Yeşilvadi Stadyumu", "Bursa", "Uludağ Bulvarı No:3, Nilüfer", 22000),
    "kadife": ("Kadife Sinemaları Moda", "İstanbul", "Moda Caddesi No:88, Kadıköy", 180),
    "kadife_ank": ("Kadife Sinemaları Kızılay", "Ankara", "Meşrutiyet Caddesi No:21", 220),
    "isikli": ("Işıklı Sahne", "Ankara", "Tunalı Hilmi Caddesi No:56", 450),
    "degirmen": ("Eski Değirmen Tiyatrosu", "İzmir", "Değirmen Sokak No:7, Bornova", 300),
}

# Kategori başına bilet tipleri: (ad, fiyat TL, kapasitenin yüzde kaçı)
TICKETS = {
    C.CONCERT: [("Ayakta", 750, 0.55), ("Tribün", 1100, 0.35), ("VIP", 2500, 0.05)],
    C.MATCH: [
        ("Kale Arkası", 400, 0.40),
        ("Maraton", 900, 0.30),
        ("Kapalı Tribün", 1500, 0.15),
        ("Öğrenci", 250, 0.10),
    ],
    C.CINEMA: [("Tam", 220, 0.75), ("Öğrenci", 160, 0.25)],
    C.THEATER: [("Tam", 450, 0.60), ("Öğrenci", 300, 0.25), ("Loca", 700, 0.10)],
}


@dataclass
class EventSpec:
    category: EventCategory
    title: str
    venue: str
    days_from_now: int
    hour: int
    minute: int
    description: str


EVENTS = [
    # Konserler
    EventSpec(C.CONCERT, "Gece Martıları: Kış Turnesi", "arena", 12, 21, 0,
              "Gece Martıları yeni albümleri 'Sis Feneri' ile sahnede."),
    EventSpec(C.CONCERT, "Deniz Aksoylu Akustik", "liman", 19, 20, 30,
              "Deniz Aksoylu en sevilen şarkılarını akustik düzenlemelerle seslendiriyor."),
    EventSpec(C.CONCERT, "Elektrik Kuşları Festival Gecesi", "arena", 33, 22, 0,
              "Elektronik müziğin yükselen ismi Elektrik Kuşları ve konuk DJ'ler."),
    EventSpec(C.CONCERT, "Bahar Orkestrası: Film Müzikleri", "liman", 45, 20, 0,
              "60 kişilik orkestra eşliğinde unutulmaz film müzikleri."),
    # Maçlar
    EventSpec(C.MATCH, "Bozkır Kartalları - Liman Yıldızları", "bozkir", 9, 19, 0,
              "Süper Lig 14. hafta karşılaşması."),
    EventSpec(C.MATCH, "Yeşilvadi SK - Kuzey Rüzgarı FK", "yesilvadi", 16, 20, 0,
              "Süper Lig 15. hafta karşılaşması."),
    EventSpec(C.MATCH, "Bozkır Kartalları - Yeşilvadi SK", "bozkir", 30, 17, 0,
              "Kupa çeyrek final rövanşı."),
    # Sinema (her seans ayrı etkinlik)
    EventSpec(C.CINEMA, "Sessiz Kıyı", "kadife", 2, 19, 15,
              "Bir deniz feneri bekçisinin sırlarla dolu son kışı. Dram, 118 dk."),
    EventSpec(C.CINEMA, "Sessiz Kıyı", "kadife", 2, 21, 45,
              "Bir deniz feneri bekçisinin sırlarla dolu son kışı. Dram, 118 dk."),
    EventSpec(C.CINEMA, "Son Tren Zamanı", "kadife_ank", 3, 20, 0,
              "Kaçırılan bir trenin dört yabancıyı birbirine bağladığı bir gece. Gerilim, 104 dk."),
    EventSpec(C.CINEMA, "Kayıp Harita", "kadife", 5, 14, 0,
              "İki kardeşin büyükbabalarının haritasının peşine düştüğü macera. Aile, 96 dk."),
    EventSpec(C.CINEMA, "Kayıp Harita", "kadife_ank", 5, 16, 30,
              "İki kardeşin büyükbabalarının haritasının peşine düştüğü macera. Aile, 96 dk."),
    # Tiyatro
    EventSpec(C.THEATER, "Rüzgârın Kızı", "isikli", 7, 20, 30,
              "Bir Ege köyünde geçen, kuşaklar boyu süren bir aile hikâyesi. 2 perde."),
    EventSpec(C.THEATER, "Aynalar Odası", "degirmen", 14, 20, 0,
              "Kendi yansımasıyla konuşmaya başlayan bir adamın kara komedisi. Tek perde."),
    EventSpec(C.THEATER, "Bir Kahve Kırk Yıl", "isikli", 21, 19, 0,
              "Aynı kahvehanede kırk yıl boyunca buluşan iki dostun komedisi. 2 perde."),
]

FIRST_NAMES = [
    "Ayşe", "Mehmet", "Zeynep", "Mustafa", "Elif", "Ahmet", "Selin", "Emre", "Deniz",
    "Burak", "Ece", "Can", "Derya", "Kerem", "İrem", "Onur", "Melis", "Tolga", "Gizem", "Arda",
]
LAST_NAMES = [
    "Kaya", "Demir", "Yıldız", "Aydın", "Öztürk", "Arslan", "Doğan", "Kılıç", "Çelik",
    "Şahin", "Koç", "Kurt", "Özdemir", "Aksoy", "Polat", "Erdem", "Güneş", "Tekin",
]

_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def _email(first: str, last: str, n: int) -> str:
    return f"{first}.{last}{n}".translate(_ASCII).lower() + "@example.com"


# --------------------------------------------------------------------------- yardımcılar


def _db_name() -> str:
    return engine.url.database or ""


def _require_dev(what: str) -> None:
    if not _db_name().endswith("_dev"):
        sys.exit(
            f"HATA: {what} sadece geliştirme veritabanında yapılabilir. "
            f"Şu anki veritabanı: '{_db_name()}'"
        )


def reset(session: Session) -> None:
    _require_dev("--reset")
    session.execute(
        text(
            "TRUNCATE order_items, orders, ticket_types, events, venues "
            "RESTART IDENTITY CASCADE"
        )
    )
    session.commit()
    print(f"'{_db_name()}' temizlendi.")


def seed_catalog(session: Session) -> list[Event]:
    venues = {
        key: Venue(name=n, city=c, address=a, capacity=cap)
        for key, (n, c, a, cap) in VENUES.items()
    }
    session.add_all(venues.values())

    today = datetime.now(TZ).date()
    events: list[Event] = []
    for spec in EVENTS:
        venue = venues[spec.venue]
        starts = datetime.combine(
            today + timedelta(days=spec.days_from_now), time(spec.hour, spec.minute), TZ
        )
        event = Event(
            category=spec.category,
            title=spec.title,
            description=spec.description,
            starts_at=starts,
            venue=venue,
        )
        for name, price, share in TICKETS[spec.category]:
            event.ticket_types.append(
                TicketType(
                    name=name,
                    price=Decimal(price),
                    quota=max(1, int(venue.capacity * share)),
                    sold=0,
                )
            )
        events.append(event)
    session.add_all(events)
    session.commit()
    print(f"{len(venues)} mekan, {len(events)} etkinlik eklendi.")
    return events


def seed_orders(
    session: Session,
    events: list[Event],
    count: int,
    rng: random.Random,
    allow_prod: bool = False,
) -> None:
    """Son 30 güne yayılmış sahte siparişler; Grafana'da veri görmek için.

    Sahte alıcıların e-postaları @example.com ile biter; gerçek siparişlerden
    ayırmak için Grafana'da: WHERE buyer_email NOT LIKE '%@example.com'
    """
    if not allow_prod:
        _require_dev("Sahte sipariş eklemek (gerçek veritabanı için --demo-orders-in-prod)")
    now = datetime.now(UTC)
    ticket_types = [tt for e in events for tt in e.ticket_types]
    # Pahalı bilet tipleri daha az satılsın
    weights = [1 / float(tt.price) for tt in ticket_types]
    used_codes: set[str] = set()
    status_counts: dict[OrderStatus, int] = {}

    for _ in range(count):
        # Siparişler son günlere doğru yoğunlaşsın (satışlar etkinliğe yaklaştıkça artar)
        created = now - timedelta(days=30 * rng.random() ** 1.6, minutes=rng.randint(0, 1439))
        status = rng.choices(
            [OrderStatus.PAID, OrderStatus.FAILED, OrderStatus.CANCELLED], [0.86, 0.10, 0.04]
        )[0]

        tt = rng.choices(ticket_types, weights)[0]
        qty = rng.choices([1, 2, 3, 4], [0.35, 0.40, 0.15, 0.10])[0]
        if status is OrderStatus.PAID and tt.sold + qty > tt.quota:
            continue  # kontenjan doldu, bu siparişi atla

        code = new_order_code()
        while code in used_codes:
            code = new_order_code()
        used_codes.add(code)

        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        order = Order(
            code=code,
            buyer_name=f"{first} {last}",
            buyer_email=_email(first, last, rng.randint(1, 99)),
            total_amount=tt.price * qty,
            status=status,
            created_at=created,
            paid_at=created + timedelta(seconds=rng.randint(20, 240))
            if status is OrderStatus.PAID
            else None,
        )
        order.items.append(OrderItem(ticket_type=tt, quantity=qty, unit_price=tt.price))
        if status is OrderStatus.PAID:
            tt.sold += qty
        session.add(order)
        status_counts[status] = status_counts.get(status, 0) + 1

    session.commit()
    summary = ", ".join(f"{s.value}: {n}" for s, n in sorted(status_counts.items()))
    print(f"{sum(status_counts.values())} sahte sipariş eklendi ({summary}).")


# --------------------------------------------------------------------------- giriş


def main() -> None:
    parser = argparse.ArgumentParser(description="semihcetinkaya.tech örnek verileri")
    parser.add_argument("--reset", action="store_true", help="önce tüm tabloları temizle (sadece _dev)")
    parser.add_argument("--no-orders", action="store_true", help="sahte sipariş ekleme")
    parser.add_argument("--orders", type=int, default=400, help="sahte sipariş sayısı (varsayılan 400)")
    parser.add_argument("--random-seed", type=int, default=42, help="aynı veriyi tekrar üretmek için")
    parser.add_argument(
        "--demo-orders-in-prod",
        action="store_true",
        help="sahte siparişleri _dev olmayan veritabanına da yaz (e-postaları @example.com)",
    )
    args = parser.parse_args()

    print(f"Veritabanı: {_db_name()}")
    with SessionLocal() as session:
        if args.reset:
            reset(session)
        elif session.scalar(select(func.count()).select_from(Venue)):
            sys.exit("Veritabanında zaten veri var. Baştan doldurmak için --reset kullanın.")

        events = seed_catalog(session)
        if not args.no_orders:
            seed_orders(
                session,
                events,
                args.orders,
                random.Random(args.random_seed),
                allow_prod=args.demo_orders_in_prod,
            )
    print("Tamam.")


if __name__ == "__main__":
    main()
