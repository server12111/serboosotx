from aiogram import Router

from . import balance, catalog, order, orders_list, profile, start, subscription_gate
from .admin import build_admin_router


def setup_routers() -> tuple[Router, Router]:
    user_router = Router(name="user")
    user_router.include_router(subscription_gate.router)
    user_router.include_router(start.router)
    user_router.include_router(catalog.router)
    user_router.include_router(order.router)
    user_router.include_router(orders_list.router)
    user_router.include_router(balance.router)
    user_router.include_router(profile.router)

    admin_router = build_admin_router()

    return user_router, admin_router
