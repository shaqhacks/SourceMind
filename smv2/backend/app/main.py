from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import api_version, cors_origins, worker_enabled
from app.db.init import init_db
from app.jobs.worker import reconcile_interrupted_jobs, worker_loop
from app.routers import health, jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(init_db)
    await asyncio.to_thread(reconcile_interrupted_jobs)

    worker_task: asyncio.Task | None = None
    if worker_enabled():
        worker_task = asyncio.create_task(worker_loop())

    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
            except Exception:
                # The loop guards its own ticks; anything surfacing here means
                # the task died earlier — record it, don't fail shutdown.
                logging.getLogger(__name__).exception("worker task died with unhandled error")


def create_app() -> FastAPI:
    app = FastAPI(title="SourceMind v2 API", version=api_version(), lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(jobs.router)
    return app


app = create_app()
