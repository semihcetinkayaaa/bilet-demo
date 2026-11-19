"""Örnek veri yükleyici: semihcetinkaya.tech bilet satış demosu.

Tüm mekan, sanatçı, takım, film, oyun ve kişi adları uydurmadır.
Etkinlikler aynı --random-seed ile her seferinde aynı şekilde üretilir
(tarihler çalıştırıldığı güne göre önümüzdeki ~3 aya yayılır).
Alıcı e-postaları @example.com alan adındadır (bu alan adı test için ayrılmıştır,
gerçek kimseye e-posta gitmez).

Kullanım (backend klasöründe, SSH tüneli açıkken):
    uv run python -m bilet_api.seed --reset          # bilet_dev'i temizleyip doldurur
    uv run python -m bilet_api.seed --no-orders      # sadece mekan/etkinlik/bilet tipi

Güvenlik:
  * --reset, adı "_dev" ile bitmeyen bir veritabanında ancak veritabanı adı
    --confirm-db ile açıkça yazılırsa çalışır:
        python -m bilet_api.seed --reset --confirm-db bilet --demo-orders-in-prod
  * Sahte siparişler varsayılan olarak sadece _dev'e yazılır; gerçek veritabanı
    için --demo-orders-in-prod gerekir.
"""

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
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
HORIZON_DAYS = 90  # etkinlikler bugünden itibaren bu kadar güne yayılır

# Kategori başına üretilecek etkinlik sayısı (toplam 150)
EVENT_COUNTS = {C.CONCERT: 40, C.MATCH: 30, C.CINEMA: 50, C.THEATER: 30}

# --------------------------------------------------------------------------- mekanlar


@dataclass(frozen=True)
class VenueSpec:
    key: str
    name: str
    city: str
    address: str
    capacity: int
    category: EventCategory


VENUES = [
    # Konser
    VenueSpec("arena", "Kuzey Yıldızı Arena", "İstanbul", "Ayazağa Yolu No:12, Sarıyer", 18000, C.CONCERT),
    VenueSpec("bogaz", "Boğaz Kulüp Sahnesi", "İstanbul", "Kuruçeşme Caddesi No:5, Beşiktaş", 1200, C.CONCERT),
    VenueSpec("liman", "Mavi Liman Konser Salonu", "İzmir", "Kordon Boyu No:45, Alsancak", 2500, C.CONCERT),
    VenueSpec("kizilirmak", "Kızılırmak Açıkhava", "Ankara", "Gençlik Parkı İçi, Altındağ", 6000, C.CONCERT),
    VenueSpec("portakal", "Portakal Bahçesi Sahnesi", "Antalya", "Konyaaltı Sahil Yolu No:30", 4000, C.CONCERT),
    VenueSpec("kanal", "Kanal Kenarı Kulüp", "Eskişehir", "Porsuk Bulvarı No:14, Odunpazarı", 800, C.CONCERT),
    # Maç (stadyumlar)
    VenueSpec("marmara", "Marmara Rüzgarı Arena", "İstanbul", "Seyrantepe Yolu No:1, Sarıyer", 40000, C.MATCH),
    VenueSpec("bozkir", "Bozkır Stadyumu", "Ankara", "Eskişehir Yolu 9. km, Çankaya", 32000, C.MATCH),
    VenueSpec("dalga", "Dalga Kıyısı Stadyumu", "İzmir", "İnciraltı Caddesi No:2, Balçova", 28000, C.MATCH),
    VenueSpec("yesilvadi", "Yeşilvadi Stadyumu", "Bursa", "Uludağ Bulvarı No:3, Nilüfer", 22000, C.MATCH),
    VenueSpec("akdeniz", "Akdeniz Güneşi Stadyumu", "Antalya", "Lara Yolu No:40, Muratpaşa", 20000, C.MATCH),
    # Sinema
    VenueSpec("kadife_moda", "Kadife Sinemaları Moda", "İstanbul", "Moda Caddesi No:88, Kadıköy", 180, C.CINEMA),
    VenueSpec("kadife_kizilay", "Kadife Sinemaları Kızılay", "Ankara", "Meşrutiyet Caddesi No:21", 220, C.CINEMA),
    VenueSpec("kadife_alsancak", "Kadife Sinemaları Alsancak", "İzmir", "Kıbrıs Şehitleri Caddesi No:60", 160, C.CINEMA),
    VenueSpec("kadife_lara", "Kadife Sinemaları Lara", "Antalya", "Tekelioğlu Caddesi No:9", 200, C.CINEMA),
    VenueSpec("kadife_nilufer", "Kadife Sinemaları Nilüfer", "Bursa", "FSM Bulvarı No:120", 190, C.CINEMA),
    # Tiyatro
    VenueSpec("perdeacik", "Perdeaçık Tiyatrosu", "İstanbul", "İstiklal Caddesi No:140, Beyoğlu", 600, C.THEATER),
    VenueSpec("isikli", "Işıklı Sahne", "Ankara", "Tunalı Hilmi Caddesi No:56", 450, C.THEATER),
    VenueSpec("degirmen", "Eski Değirmen Tiyatrosu", "İzmir", "Değirmen Sokak No:7, Bornova", 300, C.THEATER),
    VenueSpec("porsuk", "Porsuk Sahnesi", "Eskişehir", "Adalar Mevkii No:3", 350, C.THEATER),
    VenueSpec("narcicegi", "Narçiçeği Sahnesi", "Antalya", "Kaleiçi Hesapçı Sokak No:11", 400, C.THEATER),
]

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

# Küçük mekanlarda fiyatlar daha düşük olsun (büyük arena ile kulüp aynı olmasın)
PRICE_FACTOR_BY_CAPACITY = [(1000, 0.6), (3000, 0.8), (10000, 1.0), (10**9, 1.2)]

# --------------------------------------------------------------------------- içerik

# (sanatçı, tür/açıklama). Konserler mekanların büyüklüğüne göre dağıtılır.
ARTISTS = [
    ("Gece Martıları", "yeni albümleri 'Sis Feneri' ile sahnede"),
    ("Deniz Aksoylu", "en sevilen şarkılarını akustik düzenlemelerle seslendiriyor"),
    ("Elektrik Kuşları", "elektronik müziğin yükselen ismi, konuk DJ'lerle"),
    ("Bahar Orkestrası", "60 kişilik orkestra eşliğinde unutulmaz film müzikleri"),
    ("Kırmızı Bisiklet", "indie rock grubundan enerjik bir gece"),
    ("Selin Toprak", "caz standartlarını kendi yorumuyla söylüyor"),
    ("Kuzey Işıkları Korosu", "Anadolu ezgilerinden çok sesli bir seçki"),
    ("Paslı Teneke", "garaj rock ve bol gitar"),
    ("Ayaz Ertan", "yeni teklisi 'Yarım Ay' ile turnede"),
    ("Mor Dalga", "synth-pop ve ışık şovu"),
    ("Taş Plak Kumpanyası", "eski İstanbul şarkıları, canlı orkestra"),
    ("Rüya Ekspresi", "psikedelik rock gecesi"),
    ("Lale Demirsoy", "piyano ve vokal, samimi bir akşam"),
    ("Dört Mevsim Dörtlüsü", "yaylı çalgılar dörtlüsünden klasik ve modern eserler"),
    ("Koyu Kahve", "lo-fi ve soul, hafif bir akşam"),
    ("Fırtına Kardeşler", "Karadeniz rock'ı, kemençe ve elektro gitar bir arada"),
    ("Neon Sokak", "80'ler esintili pop"),
    ("Umut Kaya Trio", "modern caz, doğaçlama ağırlıklı"),
    ("Sarı Tramvay", "Türkçe alternatif, yeni albüm lansmanı"),
    ("Yıldız Tozu", "akustik folk, hikâyeli şarkılar"),
]
CONCERT_SUFFIXES = ["Konseri", "Kış Turnesi", "Canlı", "Özel Gece", "Akustik", "Albüm Lansmanı"]

# (takım, iç saha stadyum anahtarı)
TEAMS = [
    ("Marmara Rüzgarı SK", "marmara"),
    ("Kuzey Rüzgarı FK", "marmara"),
    ("Bozkır Kartalları", "bozkir"),
    ("Başkent Yıldızları", "bozkir"),
    ("Liman Yıldızları", "dalga"),
    ("Ege Dalgası", "dalga"),
    ("Yeşilvadi SK", "yesilvadi"),
    ("Uludağ Kaplanları", "yesilvadi"),
    ("Akdeniz Güneşi", "akdeniz"),
    ("Portakal Spor", "akdeniz"),
]
MATCH_KINDS = ["Süper Lig {n}. hafta karşılaşması.", "Kupa son 16 turu karşılaşması.", "Kupa çeyrek final maçı."]

# (film, tür, süre dk, konu)
FILMS = [
    ("Sessiz Kıyı", "Dram", 118, "Bir deniz feneri bekçisinin sırlarla dolu son kışı."),
    ("Son Tren Zamanı", "Gerilim", 104, "Kaçırılan bir trenin dört yabancıyı birbirine bağladığı bir gece."),
    ("Kayıp Harita", "Aile", 96, "İki kardeşin büyükbabalarının haritasının peşine düştüğü macera."),
    ("Ay Işığında Bisiklet", "Romantik komedi", 101, "Bir yaz kasabasında yanlışlıkla başlayan bir aşk."),
    ("Demir Kubbe", "Bilim kurgu", 132, "Yeraltı şehrinde yaşayan son insanların yüzeye dönüş hikâyesi."),
    ("Kar Altında Bahçe", "Dram", 112, "Köyüne dönen bir öğretmenin ailesiyle hesaplaşması."),
    ("Gölge Avcısı", "Aksiyon", 124, "Emekli bir dedektifin son davası."),
    ("Tuzlu Rüzgar", "Belgesel", 88, "Ege'de son kalan ahşap tekne ustalarının portresi."),
    ("Sihirli Çorap", "Animasyon", 84, "Kaybolan çorapların gittiği gizli dünyanın keşfi."),
    ("Kırık Saat", "Gizem", 109, "Bir antikacıda bulunan saatin geçmişe açılan kapısı."),
    ("Yalnız Kurt Kafe", "Komedi", 95, "İflasın eşiğindeki bir kafeyi kurtarmaya çalışan üç arkadaş."),
    ("Uzak Yıldız", "Bilim kurgu", 141, "Sinyal gönderen bir yıldıza giden tek kişilik yolculuk."),
]
CINEMA_HOURS = [(11, 0), (13, 30), (16, 15), (19, 0), (21, 45)]

# (oyun, tür, açıklama)
PLAYS = [
    ("Rüzgârın Kızı", "Dram", "Bir Ege köyünde geçen, kuşaklar boyu süren bir aile hikâyesi. 2 perde."),
    ("Aynalar Odası", "Kara komedi", "Kendi yansımasıyla konuşmaya başlayan bir adamın hikâyesi. Tek perde."),
    ("Bir Kahve Kırk Yıl", "Komedi", "Aynı kahvehanede kırk yıl boyunca buluşan iki dostun komedisi. 2 perde."),
    ("Köprüdeki Kadın", "Dram", "Her sabah aynı köprüde bekleyen bir kadının sırrı. 2 perde."),
    ("Kapıcının Rüyası", "Komedi", "Apartman sakinlerinin rüyalarına karışan bir kapıcı. 2 perde."),
    ("Mektup", "Tek kişilik oyun", "Hiç gönderilmemiş bir mektubun hikâyesi. Tek perde."),
    ("Sahte Kral", "Müzikal", "Yanlışlıkla tahta oturan bir terzinin şarkılı macerası. 2 perde."),
    ("Kış Masalı Yeniden", "Uyarlama", "Klasik bir kış masalının modern yorumu. 2 perde."),
    ("Saat Tamircisi", "Çocuk oyunu", "Zamanı durduran bir tamircinin eğlenceli öyküsü. Tek perde."),
    ("Yarım Kalan Senfoni", "Dram", "Son eserini bitiremeyen bir bestecinin son haftası. 2 perde."),
    ("Bodrum Katı", "Gerilim", "Elektrikler kesilince bodrumda mahsur kalan altı komşu. Tek perde."),
    ("Ev Hali", "Komedi", "Aynı evi kiralayan iki yabancının hikâyesi. 2 perde."),
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


def reset(session: Session, confirm_db: str | None) -> None:
    if not _db_name().endswith("_dev") and confirm_db != _db_name():
        sys.exit(
            f"HATA: '{_db_name()}' geliştirme veritabanı değil. Tüm siparişler dahil her şeyi "
            f"silmek istediğinden eminsen --confirm-db {_db_name()} ekle."
        )
    session.execute(
        text(
            "TRUNCATE order_items, orders, ticket_types, events, venues, sessions, users "
            "RESTART IDENTITY CASCADE"
        )
    )
    session.commit()
    print(f"'{_db_name()}' temizlendi.")


@dataclass
class _Draft:
    category: EventCategory
    title: str
    description: str
    venue: VenueSpec
    day: date
    hour: int
    minute: int


class _Calendar:
    """Aynı mekanda aynı gün/saatte iki etkinlik çakışmasın."""

    def __init__(self) -> None:
        self.used: set[tuple] = set()

    def take(self, key: tuple) -> bool:
        if key in self.used:
            return False
        self.used.add(key)
        return True


def _day(rng: random.Random, today: date, weekend_bias: float = 0.5) -> date:
    for _ in range(20):
        d = today + timedelta(days=rng.randint(1, HORIZON_DAYS))
        if d.weekday() >= 4 or rng.random() > weekend_bias:
            return d
    return d


def _concerts(rng, today, cal) -> list[_Draft]:
    venues = [v for v in VENUES if v.category is C.CONCERT]
    out = []
    while len(out) < EVENT_COUNTS[C.CONCERT]:
        artist, blurb = rng.choice(ARTISTS)
        venue = rng.choice(venues)
        d = _day(rng, today)
        if not cal.take((venue.key, d)):
            continue
        title = f"{artist}: {rng.choice(CONCERT_SUFFIXES)}"
        out.append(_Draft(C.CONCERT, title, f"{artist} {blurb}.", venue, d, rng.choice([20, 21, 21, 22]), rng.choice([0, 0, 30])))
    return out


def _matches(rng, today, cal) -> list[_Draft]:
    stadiums = {v.key: v for v in VENUES if v.category is C.MATCH}
    out = []
    week = 10
    while len(out) < EVENT_COUNTS[C.MATCH]:
        home, away = rng.sample(TEAMS, 2)
        venue = stadiums[home[1]]
        d = _day(rng, today, weekend_bias=0.8)
        if not cal.take((venue.key, d)):
            continue
        kind = rng.choices(MATCH_KINDS, [0.8, 0.12, 0.08])[0]
        week += 1
        out.append(_Draft(C.MATCH, f"{home[0]} - {away[0]}", kind.format(n=week % 34 + 1), venue, d, rng.choice([16, 19, 20]), rng.choice([0, 0, 30, 45])))
    return out


def _cinema(rng, today, cal) -> list[_Draft]:
    cinemas = [v for v in VENUES if v.category is C.CINEMA]
    out = []
    while len(out) < EVENT_COUNTS[C.CINEMA]:
        film, genre, minutes, plot = rng.choice(FILMS)
        venue = rng.choice(cinemas)
        # Sinema seansları yakın günlerde yoğun
        d = today + timedelta(days=min(HORIZON_DAYS, int(rng.random() ** 2 * 30) + 1))
        h, m = rng.choice(CINEMA_HOURS)
        if not cal.take((venue.key, d, h)):
            continue
        out.append(_Draft(C.CINEMA, film, f"{plot} {genre}, {minutes} dk.", venue, d, h, m))
    return out


def _theater(rng, today, cal) -> list[_Draft]:
    stages = [v for v in VENUES if v.category is C.THEATER]
    out = []
    while len(out) < EVENT_COUNTS[C.THEATER]:
        play, genre, plot = rng.choice(PLAYS)
        venue = rng.choice(stages)
        d = _day(rng, today)
        if not cal.take((venue.key, d)):
            continue
        h, m = (14, 0) if genre == "Çocuk oyunu" else rng.choice([(19, 0), (20, 0), (20, 30)])
        out.append(_Draft(C.THEATER, play, f"{genre}. {plot}", venue, d, h, m))
    return out


def _price_factor(capacity: int) -> float:
    return next(f for limit, f in PRICE_FACTOR_BY_CAPACITY if capacity <= limit)


def seed_catalog(session: Session, rng: random.Random) -> list[Event]:
    venues = {
        v.key: Venue(name=v.name, city=v.city, address=v.address, capacity=v.capacity)
        for v in VENUES
    }
    session.add_all(venues.values())

    today = datetime.now(TZ).date()
    cal = _Calendar()
    drafts = (
        _concerts(rng, today, cal)
        + _matches(rng, today, cal)
        + _cinema(rng, today, cal)
        + _theater(rng, today, cal)
    )

    events: list[Event] = []
    for d in sorted(drafts, key=lambda x: (x.day, x.hour, x.minute)):
        event = Event(
            category=d.category,
            title=d.title,
            description=d.description,
            starts_at=datetime.combine(d.day, time(d.hour, d.minute), TZ),
            venue=venues[d.venue.key],
        )
        factor = _price_factor(d.venue.capacity)
        for name, price, share in TICKETS[d.category]:
            # Fiyatları 10 TL'ye yuvarla; etkinlikten etkinliğe küçük farklar olsun
            p = round(price * factor * rng.uniform(0.9, 1.15) / 10) * 10
            event.ticket_types.append(
                TicketType(
                    name=name,
                    price=Decimal(max(p, 50)),
                    quota=max(1, int(d.venue.capacity * share)),
                    sold=0,
                )
            )
        events.append(event)
    session.add_all(events)
    session.commit()
    by_cat = ", ".join(f"{c.value}: {sum(e.category is c for e in events)}" for c in EVENT_COUNTS)
    print(f"{len(venues)} mekan, {len(events)} etkinlik eklendi ({by_cat}).")
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
    parser.add_argument("--reset", action="store_true", help="önce tüm tabloları temizle")
    parser.add_argument("--confirm-db", help="_dev olmayan veritabanında --reset için veritabanı adı")
    parser.add_argument("--no-orders", action="store_true", help="sahte sipariş ekleme")
    parser.add_argument("--orders", type=int, default=2500, help="sahte sipariş sayısı (varsayılan 2500)")
    parser.add_argument("--random-seed", type=int, default=42, help="aynı veriyi tekrar üretmek için")
    parser.add_argument(
        "--demo-orders-in-prod",
        action="store_true",
        help="sahte siparişleri _dev olmayan veritabanına da yaz (e-postaları @example.com)",
    )
    args = parser.parse_args()

    print(f"Veritabanı: {_db_name()}")
    rng = random.Random(args.random_seed)
    with SessionLocal() as session:
        if args.reset:
            reset(session, args.confirm_db)
        elif session.scalar(select(func.count()).select_from(Venue)):
            sys.exit("Veritabanında zaten veri var. Baştan doldurmak için --reset kullanın.")

        events = seed_catalog(session, rng)
        if not args.no_orders:
            seed_orders(session, events, args.orders, rng, allow_prod=args.demo_orders_in_prod)
    print("Tamam.")


if __name__ == "__main__":
    main()
