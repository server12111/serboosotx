from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RequiredChannel


class RequiredChannelRepository:
    @staticmethod
    async def add(
        session: AsyncSession, chat_id: int, username: str, title: str, added_by: int
    ) -> RequiredChannel:
        channel = RequiredChannel(chat_id=chat_id, username=username, title=title, added_by=added_by)
        session.add(channel)
        await session.commit()
        return channel

    @staticmethod
    async def list_active(session: AsyncSession) -> list[RequiredChannel]:
        result = await session.execute(
            select(RequiredChannel).where(RequiredChannel.is_active.is_(True))
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_all(session: AsyncSession) -> list[RequiredChannel]:
        result = await session.execute(select(RequiredChannel).order_by(RequiredChannel.created_at))
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(session: AsyncSession, channel_id: int) -> RequiredChannel | None:
        return await session.get(RequiredChannel, channel_id)

    @staticmethod
    async def deactivate(session: AsyncSession, channel_id: int) -> None:
        await session.execute(
            update(RequiredChannel).where(RequiredChannel.id == channel_id).values(is_active=False)
        )
        await session.commit()
