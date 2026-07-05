from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from SourceMind.backend import config
from SourceMind.backend.routers.library import router as library_router


@asynccontextmanager
async def _lifespan(application: FastAPI):  # noqa: ARG001
    from SourceMind.backend.db import base
    from SourceMind.backend.pipeline import service

    base.init_db()
    service.reconcile_interrupted_jobs()
    yield


app = FastAPI(title="SourceMind API", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(library_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
