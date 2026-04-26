import logging
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import decode_token
from app.models.models import AdminUser

log = logging.getLogger(__name__)
bearer = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    token = credentials.credentials
    payload = decode_token(token)
    log.warning("AUTH token[:20]=%s payload=%s", token[:20], payload)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    sub = payload.get("sub")
    log.warning("AUTH sub=%s type=%s", sub, type(sub))
    result = await db.execute(select(AdminUser).where(AdminUser.id == int(sub)))
    user = result.scalar_one_or_none()
    log.warning("AUTH user=%s", user)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user
