from aiogram import Router

from . import broadcast, catalog_admin, channels, legal, markup, panel, stats, support, tools, users_admin


def build_admin_router() -> Router:
    router = Router(name="admin")
    router.include_router(panel.router)
    router.include_router(stats.router)
    router.include_router(broadcast.router)
    router.include_router(markup.router)
    router.include_router(users_admin.router)
    router.include_router(catalog_admin.router)
    router.include_router(support.router)
    router.include_router(channels.router)
    router.include_router(legal.router)
    router.include_router(tools.router)
    return router
