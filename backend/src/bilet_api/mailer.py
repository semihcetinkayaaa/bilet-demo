"""Sipariş onay e-postası.

SMTP ayarları (SMTP_HOST, SMTP_FROM, ...) yoksa e-posta gönderilmez,
sadece loglanır; sipariş akışı yine de çalışır.
"""

import logging
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bilet_api.config import settings
from bilet_api.db import SessionLocal
from bilet_api.models import Event, Order, OrderItem, TicketType

log = logging.getLogger("bilet_api.mailer")
TZ = ZoneInfo("Europe/Istanbul")


def _tl(amount) -> str:
    return f"{amount:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _build(order: Order) -> EmailMessage:
    event = order.items[0].ticket_type.event
    when = event.starts_at.astimezone(TZ).strftime("%d.%m.%Y %H:%M")
    lines = "\n".join(
        f"  - {i.quantity} x {i.ticket_type.name} ({_tl(i.unit_price)})" for i in order.items
    )
    msg = EmailMessage()
    msg["Subject"] = f"Biletin hazır: {event.title} ({order.code})"
    msg["From"] = settings.smtp_from
    msg["To"] = order.buyer_email
    msg.set_content(
        f"""Merhaba {order.buyer_name},

{settings.brand_name} üzerinden aldığın biletler onaylandı.

Etkinlik : {event.title}
Tarih    : {when}
Mekan    : {event.venue.name}, {event.venue.city}

Biletler:
{lines}

Toplam   : {_tl(order.total_amount)}
Sipariş kodu: {order.code}

Siparişini görüntüle: {settings.site_url.rstrip('/')}/siparis/{order.code}

Bu bir demo sitesidir; ödeme gerçek değildir.
İyi eğlenceler!
{settings.brand_name}
"""
    )
    return msg


def send_order_confirmation(order_id: int) -> None:
    """Arka planda çalışır; hata olursa siparişi etkilemez, sadece loglar."""
    with SessionLocal() as session:
        order = session.scalar(
            select(Order)
            .where(Order.id == order_id)
            .options(
                selectinload(Order.items)
                .selectinload(OrderItem.ticket_type)
                .selectinload(TicketType.event)
                .selectinload(Event.venue)
            )
        )
        if order is None or order.email_sent_at is not None:
            return

        if not settings.email_enabled:
            log.info("SMTP ayarlı değil; %s için e-posta atlanıyor", order.code)
            return

        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                if settings.smtp_starttls:
                    smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(_build(order))
        except Exception:
            log.exception("%s için e-posta gönderilemedi", order.code)
            return

        order.email_sent_at = datetime.now(UTC)
        session.commit()
        log.info("%s için onay e-postası gönderildi", order.code)
