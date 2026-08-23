from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AdminAction


class AdminActionRepository:
    @staticmethod
    async def log(
        session: AsyncSession,
        admin_tg_id: int,
        action: str,
        target_user_id: int | None = None,
        payload: dict | None = None,
    ) -> None:
        session.add(
            AdminAction(
                admin_tg_id=admin_tg_id,
                action=action,
                target_user_id=target_user_id,
                payload=payload,
            )
        )
        await session.commit()
