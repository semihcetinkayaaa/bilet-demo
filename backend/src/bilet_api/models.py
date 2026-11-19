"""Veritabanı tabloları.

Tablo ve sütun adları İngilizce; Grafana sorgularında da bu adlar kullanılır.
Tutarlar Numeric(10, 2) ile tutulur (kuruş hassasiyeti, yuvarlama hatası yok).
Zamanlar saat dilimiyle (timestamptz) saklanır.
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bilet_api.db import Base


class EventCategory(enum.StrEnum):
    CONCERT = "concert"  # konser
    MATCH = "match"  # maç
    CINEMA = "cinema"  # sinema
    THEATER = "theater"  # tiyatro


class OrderStatus(enum.StrEnum):
    PENDING = "pending"  # ödeme bekleniyor
    PAID = "paid"  # dummy ödeme başarılı
    FAILED = "failed"  # dummy ödeme başarısız
    CANCELLED = "cancelled"  # iptal


def _str_enum(enum_cls: type[enum.StrEnum], name: str) -> Enum:
    # PostgreSQL'e özel ENUM tipi yerine VARCHAR + CHECK kullanır:
    # Grafana'da düz metin olarak okunur, yeni değer eklemek de kolaydır.
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,  # izin verilmeyen değer yazılamaz
        values_callable=lambda e: [m.value for m in e],
        length=20,
    )


class Venue(Base):
    """Mekan: stadyum, konser salonu, sinema, tiyatro."""

    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100), index=True)
    address: Mapped[str | None] = mapped_column(String(300))
    capacity: Mapped[int | None]

    events: Mapped[list["Event"]] = relationship(back_populates="venue")


class Event(Base):
    """Etkinlik: konser, maç, film seansı ya da tiyatro oyunu."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[EventCategory] = mapped_column(
        _str_enum(EventCategory, "event_category"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    image_url: Mapped[str | None] = mapped_column(String(500))
    is_published: Mapped[bool] = mapped_column(default=True, server_default="true")
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    venue: Mapped[Venue] = relationship(back_populates="events")
    ticket_types: Mapped[list["TicketType"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class TicketType(Base):
    """Bilet tipi: bir etkinliğin 'Tribün', 'VIP', 'Öğrenci' gibi kategorileri."""

    __tablename__ = "ticket_types"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint("quota >= 0", name="quota_non_negative"),
        # Satılan adet kontenjanı asla aşamaz (aynı anda gelen siparişlerde bile).
        CheckConstraint("sold >= 0 AND sold <= quota", name="sold_within_quota"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    quota: Mapped[int]
    sold: Mapped[int] = mapped_column(default=0, server_default="0")

    event: Mapped[Event] = relationship(back_populates="ticket_types")


class User(Base):
    """Üye. Üyelik isteğe bağlı: bilet almak için gerekmez."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Her zaman küçük harfle saklanır
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    # argon2 özeti; düz şifre hiçbir yerde saklanmaz
    password_hash: Mapped[str] = mapped_column(String(255))
    # E-posta doğrulanınca dolar (SMTP kurulunca); misafir siparişleri ancak bundan sonra bağlanır
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Kaba kuvvet koruması
    failed_logins: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    """Giriş oturumu. Tarayıcıdaki çerezde rastgele anahtar, burada sadece SHA-256 özeti durur."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class Order(Base):
    """Sipariş: alıcı ad ve e-posta ile tanımlanır; giriş yapılmışsa üyeye de bağlanır."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="total_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Müşteriye ve e-postaya gösterilen kod, ör. "BLT-7K3QX9"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    buyer_name: Mapped[str] = mapped_column(String(200))
    buyer_email: Mapped[str] = mapped_column(String(320), index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[OrderStatus] = mapped_column(
        _str_enum(OrderStatus, "order_status"), default=OrderStatus.PENDING, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Misafir siparişlerinde boş
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    """Sipariş kalemi: hangi bilet tipinden kaç adet, hangi fiyattan."""

    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    ticket_type_id: Mapped[int] = mapped_column(ForeignKey("ticket_types.id"), index=True)
    quantity: Mapped[int]
    # Satın alma anındaki fiyat; bilet tipinin fiyatı sonradan değişse de korunur.
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    order: Mapped[Order] = relationship(back_populates="items")
    ticket_type: Mapped[TicketType] = relationship()
