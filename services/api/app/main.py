from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, engagement, reports, signals

app = FastAPI(
    title="LocalSignal API",
    description="API for local change intelligence reports and feedback.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(signals.router)
app.include_router(reports.router)
app.include_router(admin.router)
app.include_router(engagement.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.options("/{path:path}")
def options_handler(path: str) -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)
