"""Owner accounts and the sessions of the panel.

A password is stored as an scrypt hash with its own salt and parameters. A session is a
random token of which only the SHA-256 is stored, so reading the table gives nobody a
session. Signing in and resolving a session happen before a tenant is known and go through
two database functions that return one row for one exact key.
"""

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.db.models import OwnerSession

SESSION_LIFETIME = timedelta(hours=12)

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _KEY_BYTES = 2**14, 8, 1, 32
_FIND_OWNER = text(
    "select user_id, tenant_id, name, password_hash from find_owner_by_email(:email)"
)
_RESOLVE_SESSION = text("select user_id, tenant_id from resolve_owner_session(:token_hash, :now)")
# Checked when the e-mail is unknown, so that the answer takes as long as a wrong password.
_NOBODY = "scrypt$16384$8$1$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


@dataclass(frozen=True)
class Owner:
    user_id: UUID
    tenant_id: UUID


@dataclass(frozen=True)
class SignedIn:
    owner: Owner
    name: str
    token: str
    expires_at: datetime


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_KEY_BYTES
    )
    parts = (_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _text(salt), _text(key))
    return "scrypt$" + "$".join(str(part) for part in parts)


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        key = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(base64.b64decode(expected)),
        )
    except ValueError:
        return False
    return scheme == "scrypt" and hmac.compare_digest(key, base64.b64decode(expected))


async def find_owner(session: AsyncSession, email: str, password: str) -> tuple[Owner, str] | None:
    """The owner with that e-mail, if the password is theirs. Works before a tenant is set."""
    row = (await session.execute(_FIND_OWNER, {"email": email})).one_or_none()
    if row is None:
        verify_password(password, _NOBODY)
        return None
    if not verify_password(password, row.password_hash):
        return None
    return Owner(row.user_id, row.tenant_id), row.name


async def open_session(session: AsyncSession, owner: Owner, name: str, now: datetime) -> SignedIn:
    """Creates a session. The session of the caller has to be scoped to the owner's tenant."""
    token = secrets.token_urlsafe(32)
    expires_at = now + SESSION_LIFETIME
    session.add(
        OwnerSession(
            tenant_id=owner.tenant_id,
            user_id=owner.user_id,
            token_hash=_hash(token),
            created_at=now,
            expires_at=expires_at,
        )
    )
    return SignedIn(owner=owner, name=name, token=token, expires_at=expires_at)


async def resolve_session(session: AsyncSession, token: str, now: datetime) -> Owner | None:
    """Who a session token belongs to, if it has not expired. Works before a tenant is set."""
    row = (
        await session.execute(_RESOLVE_SESSION, {"token_hash": _hash(token), "now": now})
    ).one_or_none()
    return None if row is None else Owner(row.user_id, row.tenant_id)


async def close_session(session: AsyncSession, token: str) -> None:
    await session.execute(delete(OwnerSession).where(OwnerSession.token_hash == _hash(token)))


def _text(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
