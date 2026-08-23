from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User


class UserRepository:
    @staticmethod
    async def get_by_tg_id(session: AsyncSession, tg_id: int) -> User | None:
        result = await session.execute(select(User).where(User.tg_id == tg_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
        return await session.get(User, user_id)

    @staticmethod
    async def get_or_create(
        session: AsyncSession,
        tg_id: int,
        username: str | None,
        full_name: str | None,
        referrer_id: int | None = None,
    ) -> User:
        """Idempotent upsert-on-conflict — safe against a race where two updates
        (e.g. two quick messages) both try to create the same user concurrently.
        referrer_id is only ever applied on the INSERT path (it's deliberately absent
        from on_conflict_do_update's SET) — an existing user's referrer can never be
        overwritten by a later /start with a different referral link."""
        stmt = (
            pg_insert(User)
            .values(tg_id=tg_id, username=username, full_name=full_name, referrer_id=referrer_id)
            .on_conflict_do_update(
                index_elements=[User.tg_id],
                set_={"username": username, "full_name": full_name},
            )
            .returning(User)
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.scalar_one()

    @staticmethod
    async def count_referrals(session: AsyncSession, referrer_id: int) -> int:
        result = await session.execute(
            select(func.count()).select_from(User).where(User.referrer_id == referrer_id)
        )
        return result.scalar_one()

    @staticmethod
    async def touch_last_seen(session: AsyncSession, user_id: int) -> None:
        await session.execute(
            update(User).where(User.id == user_id).values(last_seen_at=func.now())
        )
        await session.commit()

    @staticmethod
    async def try_debit(session: AsyncSession, user_id: int, amount: Decimal) -> Decimal | None:
        """Atomic conditional debit. Returns the new balance on success, None if
        insufficient funds. Does NOT commit — caller controls the transaction so
        this can be combined with other writes (e.g. order + ledger insert)."""
        stmt = (
            update(User)
            .where(User.id == user_id, User.balance >= amount)
            .values(balance=User.balance - amount)
            .returning(User.balance)
        )
        result = await session.execute(stmt)
        row = result.first()
        return row[0] if row else None

    @staticmethod
    async def credit(session: AsyncSession, user_id: int, amount: Decimal) -> Decimal:
        """Atomic credit. Does NOT commit — caller controls the transaction."""
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(balance=User.balance + amount)
            .returning(User.balance)
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    @staticmethod
    async def set_ban(session: AsyncSession, user_id: int, banned: bool) -> None:
        await session.execute(update(User).where(User.id == user_id).values(is_banned=banned))
        await session.commit()

    @staticmethod
    async def list_paginated(session: AsyncSession, offset: int, limit: int) -> list[User]:
        result = await session.execute(
            select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count(session: AsyncSession) -> int:
        result = await session.execute(select(func.count()).select_from(User))
        return result.scalar_one()

    @staticmethod
    async def search(session: AsyncSession, query: str) -> list[User]:
        like = f"%{query}%"
        condition = User.username.ilike(like) | User.full_name.ilike(like)
        if query.isdigit():
            condition = condition | (User.tg_id == int(query))
        result = await session.execute(select(User).where(condition).limit(20))
        return list(result.scalars().all())
