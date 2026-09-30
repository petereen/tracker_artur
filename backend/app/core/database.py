from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core import tenancy

engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    # A tenant bound by an auth dependency lives until the request ends; do
    # not let it outlive the request when several requests share one task
    # (in-process test clients).
    bound = tenancy.current_tenant_id()
    try:
        async with AsyncSessionLocal() as session:
            yield session
    finally:
        tenancy.set_current_tenant(bound)
