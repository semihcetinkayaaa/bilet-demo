"""Sipariş ve dummy ödeme uç noktaları.

Akış:
  1. POST /orders              -> sipariş "pending" olarak açılır (kontenjan henüz düşmez)
  2. POST /orders/{code}/pay   -> dummy ödeme; başarılıysa kontenjan atomik olarak düşer,
                                  sipariş "paid" olur ve onay e-postası kuyruğa alınır
  3. GET  /orders/{code}       -> sipariş özeti

Kontenjan ödeme anında, tek bir UPDATE ile ve "sold + adet <= quota" koşuluyla düşürülür;
aynı anda gelen iki ödeme son bileti birlikte alamaz. Veritabanındaki CHECK kısıtı da
ikinci bir güvence.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from bilet_api.codes import new_order_code
from bilet_api.db import get_session
from bilet_api.events import to_summary
from bilet_api.mailer import send_order_confirmation
from bilet_api.models import Event, Order, OrderItem, OrderStatus, TicketType
from bilet_api.schemas import (
    MAX_TICKETS_PER_ORDER,
    OrderCreate,
    OrderItemOut,
    OrderOut,
    PaymentIn,
)

router = APIRouter(prefix="/orders", tags=["siparişler"])
# Sipariş olayları; kişisel veri (isim, e-posta, kart) loglanmaz.
log = logging.getLogger("bilet_api.orders")
SessionDep = Annotated[Session, Depends(get_session)]

# Dummy ödeme kuralı: bu numarayla biten kartlar reddedilir (test için).
DECLINED_CARD_SUFFIX = "0002"


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[0]}***@{domain}" if local else email


def _load(session: Session, code: str, *, for_update: bool = False) -> Order:
    stmt = (
        select(Order)
        .where(Order.code == code)
        .options(
            selectinload(Order.items)
            .selectinload(OrderItem.ticket_type)
            .selectinload(TicketType.event)
            .options(selectinload(Event.venue), selectinload(Event.ticket_types))
        )
    )
    if for_update:
        stmt = stmt.with_for_update(of=Order)
    order = session.scalar(stmt)
    if order is None:
        raise HTTPException(404, "Sipariş bulunamadı")
    return order


def _to_out(order: Order) -> OrderOut:
    event = order.items[0].ticket_type.event
    return OrderOut(
        code=order.code,
        status=order.status,
        buyer_name=order.buyer_name,
        buyer_email_masked=_mask_email(order.buyer_email),
        total_amount=order.total_amount,
        created_at=order.created_at,
        paid_at=order.paid_at,
        event=to_summary(event),
        items=[
            OrderItemOut(
                ticket_type_name=i.ticket_type.name,
                quantity=i.quantity,
                unit_price=i.unit_price,
                line_total=i.unit_price * i.quantity,
            )
            for i in order.items
        ],
    )


def _unique_code(session: Session) -> str:
    for _ in range(10):
        code = new_order_code()
        if session.scalar(select(Order.id).where(Order.code == code)) is None:
            return code
    raise HTTPException(500, "Sipariş kodu üretilemedi, lütfen tekrar deneyin")


@router.post("", response_model=OrderOut, status_code=201)
def create_order(body: OrderCreate, session: SessionDep) -> OrderOut:
    ids = [i.ticket_type_id for i in body.items]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Aynı bilet tipi birden fazla kez seçilmiş")
    if sum(i.quantity for i in body.items) > MAX_TICKETS_PER_ORDER:
        raise HTTPException(422, f"Bir siparişte en fazla {MAX_TICKETS_PER_ORDER} bilet alınabilir")

    ticket_types = {
        tt.id: tt
        for tt in session.scalars(
            select(TicketType)
            .where(TicketType.id.in_(ids))
            .options(selectinload(TicketType.event))
        )
    }
    if len(ticket_types) != len(ids):
        raise HTTPException(404, "Bilet tipi bulunamadı")

    events = {tt.event_id for tt in ticket_types.values()}
    if len(events) != 1:
        raise HTTPException(422, "Bir siparişte sadece tek bir etkinlik için bilet alınabilir")
    event = next(iter(ticket_types.values())).event
    if not event.is_published or event.starts_at < datetime.now(UTC):
        raise HTTPException(409, "Bu etkinliğin satışı sona erdi")

    for item in body.items:
        tt = ticket_types[item.ticket_type_id]
        if tt.quota - tt.sold < item.quantity:
            raise HTTPException(409, f"'{tt.name}' için yeterli bilet kalmadı")

    order = Order(
        code=_unique_code(session),
        buyer_name=body.buyer_name,
        buyer_email=str(body.buyer_email).lower(),
        total_amount=sum(ticket_types[i.ticket_type_id].price * i.quantity for i in body.items),
        status=OrderStatus.PENDING,
    )
    for item in body.items:
        tt = ticket_types[item.ticket_type_id]
        order.items.append(OrderItem(ticket_type=tt, quantity=item.quantity, unit_price=tt.price))
    session.add(order)
    session.commit()
    log.info(
        "order_created",
        extra={
            "order_code": order.code,
            "event_id": event.id,
            "category": event.category.value,
            "tickets": sum(i.quantity for i in body.items),
            "amount": float(order.total_amount),
        },
    )
    return _to_out(_load(session, order.code))


def _order_log_fields(order: Order) -> dict:
    event = order.items[0].ticket_type.event
    return {
        "order_code": order.code,
        "event_id": event.id,
        "category": event.category.value,
        "tickets": sum(i.quantity for i in order.items),
        "amount": float(order.total_amount),
    }


@router.get("/{code}", response_model=OrderOut)
def get_order(code: str, session: SessionDep) -> OrderOut:
    return _to_out(_load(session, code.upper()))


@router.post("/{code}/pay", response_model=OrderOut)
def pay_order(
    code: str, body: PaymentIn, session: SessionDep, background: BackgroundTasks
) -> OrderOut:
    # Siparişi kilitle: aynı sipariş iki kez ödenemesin.
    order = _load(session, code.upper(), for_update=True)
    if order.status is OrderStatus.PAID:
        return _to_out(order)  # tekrar gönderilen istek: sonucu aynen döndür
    if order.status is not OrderStatus.PENDING:
        raise HTTPException(409, "Bu sipariş artık ödenemez")

    event = order.items[0].ticket_type.event
    fields = _order_log_fields(order)
    if event.starts_at < datetime.now(UTC):
        order.status = OrderStatus.CANCELLED
        session.commit()
        log.warning("payment_event_started", extra=fields)
        raise HTTPException(409, "Etkinliğin satışı sona erdi")

    digits = body.card_number.replace(" ", "")
    if digits.endswith(DECLINED_CARD_SUFFIX):
        order.status = OrderStatus.FAILED
        session.commit()
        log.warning("payment_declined", extra=fields)
        raise HTTPException(402, "Ödeme reddedildi (demo test kartı)")

    # Kontenjanı atomik olarak düşür; biri bile yetmezse hepsini geri al.
    for item in order.items:
        result = session.execute(
            update(TicketType)
            .where(
                TicketType.id == item.ticket_type_id,
                TicketType.sold + item.quantity <= TicketType.quota,
            )
            .values(sold=TicketType.sold + item.quantity)
        )
        if result.rowcount != 1:
            sold_out_name = item.ticket_type.name
            session.rollback()
            failed = _load(session, code.upper(), for_update=True)
            failed.status = OrderStatus.FAILED
            session.commit()
            log.warning("payment_sold_out", extra={**fields, "ticket_type": sold_out_name})
            raise HTTPException(409, f"'{sold_out_name}' biletleri tükendi")

    order.status = OrderStatus.PAID
    order.paid_at = datetime.now(UTC)
    session.commit()
    log.info("payment_succeeded", extra=fields)
    background.add_task(send_order_confirmation, order.id)

    session.expire_all()
    return _to_out(_load(session, order.code))
