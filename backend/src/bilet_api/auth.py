"""Üyelik: kayıt, giriş, çıkış ve oturum doğrulama.

Oturum modeli:
  - Girişte rastgele bir anahtar üretilir (secrets.token_urlsafe). Frontend bunu httpOnly
    çerezde saklar ve backend'e "Authorization: Bearer <anahtar>" başlığıyla gönderir.
  - Veritabanında anahtarın kendisi değil SHA-256 özeti tutulur; veritabanı sızsa bile
    oturumlar ele geçirilemez. Çıkışta kayıt silinir, oturum gerçekten geçersiz olur.

Kaba kuvvet koruması: art arda 5 hatalı şifreden sonra hesap 15 dakika kilitlenir.
"""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field, StringConstraints
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bilet_api.db import get_session
from bilet_api.models import User, UserSession

router = APIRouter(prefix="/auth", tags=["üyelik"])
log = logging.getLogger("bilet_api.auth")
SessionDep = Annotated[Session, Depends(get_session)]

SESSION_DAYS = 30
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15

_hasher = PasswordHasher()
# Olmayan kullanıcıda da aynı sürede cevap vermek için (e-posta varlığını süreden anlamasınlar)
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


# --------------------------------------------------------------------------- şemalar

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
Password = Annotated[str, Field(min_length=8, max_length=128)]


class RegisterIn(BaseModel):
    name: Name
    email: EmailStr
    password: Password


class LoginIn(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    email_verified: bool
    created_at: datetime


class AuthOut(BaseModel):
    token: str
    expires_at: datetime
    user: UserOut


def to_user_out(user: User) -> UserOut:
    return UserOut(id=user.id, name=user.name, email=user.email,
                   email_verified=user.email_verified_at is not None, created_at=user.created_at)


# --------------------------------------------------------------------------- oturum yardımcıları


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_session(session: Session, user: User) -> AuthOut:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=SESSION_DAYS)
    session.add(UserSession(token_hash=_hash_token(token), user=user, expires_at=expires))
    # Fırsat buldukça süresi dolmuş oturumları temizle
    session.execute(delete(UserSession).where(UserSession.expires_at < datetime.now(UTC)))
    session.commit()
    session.refresh(user)
    return AuthOut(token=token, expires_at=expires, user=to_user_out(user))


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        return token if 20 <= len(token) <= 100 else None
    return None


def get_optional_user(
    session: SessionDep, authorization: Annotated[str | None, Header()] = None
) -> User | None:
    """Geçerli bir oturum varsa kullanıcıyı, yoksa None döndürür (misafir)."""
    token = _bearer(authorization)
    if not token:
        return None
    return session.scalar(
        select(User)
        .join(UserSession)
        .where(UserSession.token_hash == _hash_token(token), UserSession.expires_at > datetime.now(UTC))
    )


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def get_current_user(user: OptionalUser) -> User:
    if user is None:
        raise HTTPException(401, "Oturum açmanız gerekiyor")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# --------------------------------------------------------------------------- uç noktalar


@router.post("/register", response_model=AuthOut, status_code=201)
def register(body: RegisterIn, session: SessionDep) -> AuthOut:
    email = str(body.email).lower()
    if session.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "Bu e-posta adresiyle zaten bir hesap var. Giriş yapmayı deneyin.")
    user = User(email=email, name=body.name, password_hash=_hasher.hash(body.password),
                last_login_at=datetime.now(UTC))
    session.add(user)
    try:
        session.flush()
    except IntegrityError:  # aynı anda iki kayıt isteği
        session.rollback()
        raise HTTPException(409, "Bu e-posta adresiyle zaten bir hesap var. Giriş yapmayı deneyin.") from None
    log.info("user_registered", extra={"user_id": user.id})
    return _new_session(session, user)


@router.post("/login", response_model=AuthOut)
def login(body: LoginIn, session: SessionDep) -> AuthOut:
    email = str(body.email).lower()
    user = session.scalar(select(User).where(User.email == email).with_for_update())
    now = datetime.now(UTC)

    if user is None:
        try:
            _hasher.verify(_DUMMY_HASH, body.password)
        except VerifyMismatchError:
            pass
        log.warning("login_failed", extra={"reason": "unknown_email"})
        raise HTTPException(401, "E-posta adresi ya da şifre hatalı")

    if user.locked_until and user.locked_until > now:
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        log.warning("login_locked", extra={"user_id": user.id})
        raise HTTPException(429, f"Çok fazla hatalı deneme. Lütfen {minutes} dakika sonra tekrar deneyin.")

    try:
        _hasher.verify(user.password_hash, body.password)
    except (VerifyMismatchError, InvalidHashError):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_logins = 0
            log.warning("login_locked_now", extra={"user_id": user.id})
        else:
            log.warning("login_failed", extra={"user_id": user.id, "reason": "wrong_password"})
        session.commit()
        raise HTTPException(401, "E-posta adresi ya da şifre hatalı")

    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = _hasher.hash(body.password)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    log.info("login_succeeded", extra={"user_id": user.id})
    return _new_session(session, user)


@router.post("/logout", status_code=204)
def logout(session: SessionDep, authorization: Annotated[str | None, Header()] = None) -> Response:
    token = _bearer(authorization)
    if token:
        session.execute(delete(UserSession).where(UserSession.token_hash == _hash_token(token)))
        session.commit()
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return to_user_out(user)
