from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import api_version, cors_origins, worker_enabled
from app.db.init import init_db
from app.jobs.worker import reconcile_interrupted_jobs, worker_loop
from app.llm.limiter import LLMBusyError
from app.routers import (
    assets,
    cards,
    chat,
    courses,
    export,
    health,
    ingest,
    jobs,
    lessons,
    llm_usage,
    review,
    sections,
    tests,
)
from app.services import jobs_service
from app.services.backup_service import should_run_backup
from app.services.sample_service import seed_sample_course_if_first_run


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(init_db)
    await asyncio.to_thread(reconcile_interrupted_jobs)
    await seed_sample_course_if_first_run()

    if await asyncio.to_thread(should_run_backup):
        await asyncio.to_thread(jobs_service.create_job, "backup", None)

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
    app.include_router(courses.router)
    app.include_router(assets.router)
    app.include_router(ingest.router)
    app.include_router(sections.router)
    app.include_router(sections.section_router)
    app.include_router(export.router)
    app.include_router(lessons.router)
    app.include_router(llm_usage.router)
    app.include_router(cards.router)
    app.include_router(review.router)
    app.include_router(tests.router)
    app.include_router(chat.router)

    @app.exception_handler(LLMBusyError)
    async def llm_busy_handler(request: Request, exc: LLMBusyError) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    return app


app = create_app()
