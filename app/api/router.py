from fastapi import APIRouter

from app.api.v1 import (
    auth,
    notifications,
    books,
    devices,
    docker,
    brand,
    logos,
    messages,
    music,
    navlinks,
    recycle,
    seeds,
    settings,
    sources,
    sse,
    stats,
    transfer,
    users,
    video,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(books.router)
api_router.include_router(devices.router)
api_router.include_router(users.router)
api_router.include_router(sources.router)
api_router.include_router(logos.router)
api_router.include_router(brand.router)
api_router.include_router(notifications.router)
api_router.include_router(messages.router)
api_router.include_router(transfer.router)
api_router.include_router(navlinks.router)
api_router.include_router(music.router)
api_router.include_router(video.router)
api_router.include_router(stats.router)
api_router.include_router(docker.router)
api_router.include_router(settings.router)
api_router.include_router(recycle.router)
api_router.include_router(seeds.router)
api_router.include_router(sse.router)
