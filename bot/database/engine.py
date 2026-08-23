import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import config

if config.DATABASE_URL.startswith("sqlite"):
    db_path = config.DATABASE_URL.split("///")[-1]
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """WAL lets readers proceed while a writer holds the lock (instead of blocking
    everyone), busy_timeout makes a writer that arrives mid-lock wait and retry rather
    than immediately raising "database is locked", and foreign_keys=ON matches
    Postgres's default enforcement (SQLite ignores FKs unless told otherwise)."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=10000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
