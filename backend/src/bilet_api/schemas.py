"""API'nin dışarıya verdiği ve aldığı veri biçimleri."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from bilet_api.models import EventCategory, OrderStatus

MAX_TICKETS_PER_ORDER = 10


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- etkinlik


class VenueOut(_Out):
    id: int
    name: str
    city: str
    address: str | None


class TicketTypeOut(_Out):
    id: int
    name: str
    price: Decimal
    remaining: int


class EventSummary(_Out):
    id: int
    category: EventCategory
    title: str
    starts_at: datetime
    image_url: str | None
    venue: VenueOut
    min_price: Decimal | None
    remaining: int


class EventDetail(EventSummary):
    description: str | None
    ticket_types: list[TicketTypeOut]


# --------------------------------------------------------------------------- sipariş

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]


class OrderItemIn(BaseModel):
    ticket_type_id: int
    quantity: int = Field(ge=1, le=MAX_TICKETS_PER_ORDER)


class OrderCreate(BaseModel):
    buyer_name: Name
    buyer_email: EmailStr
    items: list[OrderItemIn] = Field(min_length=1, max_length=10)


class PaymentIn(BaseModel):
    """Dummy ödeme. Kart bilgisi hiçbir yerde saklanmaz ya da loglanmaz."""

    card_holder: Name
    card_number: Annotated[str, StringConstraints(pattern=r"^[0-9 ]{12,23}$")]
    expiry: Annotated[str, StringConstraints(pattern=r"^(0[1-9]|1[0-2])/[0-9]{2}$")]
    cvc: Annotated[str, StringConstraints(pattern=r"^[0-9]{3,4}$")]


class OrderItemOut(BaseModel):
    ticket_type_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class OrderOut(BaseModel):
    code: str
    status: OrderStatus
    buyer_name: str
    buyer_email_masked: str
    total_amount: Decimal
    created_at: datetime
    paid_at: datetime | None
    event: EventSummary
    items: list[OrderItemOut]
