from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db(request: Request) -> AsyncGenerator[AsyncSession]:
    """Yield a request-scoped async database session."""

    async with request.app.state.db_session() as session:
        yield session
