import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from SourceMind.backend.routers.library import router as library_router


@asynccontextmanager
async def _lifespan(application: FastAPI):  # noqa: ARG001
    from SourceMind.backend.db import base

    base.init_db()
    yield


def _cors_origins() -> list[str]:
    defaults = ["http://localhost:3000", "http://127.0.0.1:3000"]
    configured = [
        origin.strip()
        for origin in os.getenv("SOURCEMIND_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    return [*defaults, *[origin for origin in configured if origin not in defaults]]


app = FastAPI(title="SourceMind API", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(library_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
