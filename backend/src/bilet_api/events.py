"""Etkinlik uç noktaları (sadece okuma)."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from bilet_api.db import get_session
from bilet_api.models import Event, EventCategory, TicketType, Venue
from bilet_api.schemas import EventDetail, EventSummary, TicketTypeOut, VenueOut

router = APIRouter(prefix="/events", tags=["etkinlikler"])
SessionDep = Annotated[Session, Depends(get_session)]


def _remaining(tt: TicketType) -> int:
    return max(0, tt.quota - tt.sold)


def to_summary(event: Event) -> EventSummary:
    available = [tt for tt in event.ticket_types if _remaining(tt) > 0]
    return EventSummary(
        id=event.id,
        category=event.category,
        title=event.title,
        starts_at=event.starts_at,
        image_url=event.image_url,
        venue=VenueOut.model_validate(event.venue),
        min_price=min((tt.price for tt in available), default=None),
        remaining=sum(_remaining(tt) for tt in event.ticket_types),
    )


def to_detail(event: Event) -> EventDetail:
    return EventDetail(
        **to_summary(event).model_dump(),
        description=event.description,
        ticket_types=[
            TicketTypeOut(id=tt.id, name=tt.name, price=tt.price, remaining=_remaining(tt))
            for tt in sorted(event.ticket_types, key=lambda t: t.price)
        ],
    )


def _upcoming():
    return (
        select(Event)
        .where(Event.is_published, Event.starts_at >= datetime.now(UTC))
        .options(selectinload(Event.venue), selectinload(Event.ticket_types))
    )


@router.get("", response_model=list[EventSummary])
def list_events(
    session: SessionDep,
    category: EventCategory | None = None,
    city: Annotated[str | None, Query(max_length=100)] = None,
) -> list[EventSummary]:
    """Yaklaşan, yayındaki etkinlikler; tarihe göre sıralı."""
    stmt = _upcoming().order_by(Event.starts_at)
    if category:
        stmt = stmt.where(Event.category == category)
    if city:
        stmt = stmt.join(Event.venue).where(Venue.city == city)
    return [to_summary(e) for e in session.scalars(stmt)]


@router.get("/cities", response_model=list[str])
def list_cities(session: SessionDep) -> list[str]:
    """Yaklaşan etkinliği olan şehirler (filtre menüsü için)."""
    stmt = (
        select(Venue.city)
        .join(Venue.events)
        .where(Event.is_published, Event.starts_at >= datetime.now(UTC))
        .distinct()
        .order_by(Venue.city)
    )
    return list(session.scalars(stmt))


@router.get("/{event_id}", response_model=EventDetail)
def get_event(event_id: int, session: SessionDep) -> EventDetail:
    event = session.scalar(_upcoming().where(Event.id == event_id))
    if event is None:
        raise HTTPException(404, "Etkinlik bulunamadı ya da satışı sona erdi")
    return to_detail(event)
