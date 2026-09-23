from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.core.config import settings
from app.core.logging import configure_logging
from app.api.routes.chat import router as chat_router
from app.api.routes.chat_stream import router as chat_stream_router
from app.api.routes.files import router as files_router
from app.api.routes.health import router as health_router
from app.api.routes.history import router as history_router
from app.api.routes.models import router as models_router
from app.api.routes.workspaces import router as workspaces_router


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(title="AI Chat Backend", version="0.1.0")
    chart_dir = Path(settings.storage_dir).resolve() / "analysis_charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/analysis-charts", StaticFiles(directory=chart_dir), name="analysis-charts")

    origins = [o.strip() for o in (settings.cors_origins or "").split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(chat_stream_router)
    app.include_router(files_router)
    app.include_router(history_router)
    app.include_router(models_router)
    app.include_router(workspaces_router)

    return app


app = create_app()
