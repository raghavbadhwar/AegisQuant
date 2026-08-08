"""Thin control-plane API; M0 intentionally exposes no execution path."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict


class HealthStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["ok"] = "ok"
    milestone: Literal["M0_SECURITY_KERNEL"] = "M0_SECURITY_KERNEL"
    live_trading_enabled: Literal[False] = False
    broker_adapter_present: Literal[False] = False
    unrestricted_web_enabled: Literal[False] = False


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # External clients are initialized here only after their milestones pass.
    yield


app = FastAPI(
    title="AegisQuant Control API",
    version="0.1.0",
    lifespan=lifespan,
    description="M0 fixture-only control plane; no broker or execution endpoints.",
)


@app.get("/health/live", response_model=HealthStatus)
async def live() -> HealthStatus:
    return HealthStatus()


@app.get("/health/ready", response_model=HealthStatus)
async def ready() -> HealthStatus:
    return HealthStatus()
