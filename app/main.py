"""Application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import ROOT, get_settings
from app import database
from app.database import init_db
from app.errors import AppError
from app.i18n import STRINGS
from app.routers import api, pages
from app.social import router as social_router
from app.seed import seed
from app.web import language_of, render, static_dir

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("saan")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if database.SessionLocal is None:
        raise RuntimeError("Database is not initialized")
    db = database.SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.secret_key == "dev-only-change-me":
        log.warning("Using the development session secret. Set SAAN_SECRET_KEY before sharing this server.")
    init_db(settings.resolved_database_url())
    settings.resolved_upload_dir()

    app = FastAPI(
        title="S.A.A.N.",
        summary="Smart Accessibility Assistance Network",
        description="OCR reading desk and volunteer proofreading API.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="saan_session",
        max_age=60 * 60 * 24 * 14,
        same_site="lax",
        https_only=settings.session_https_only,
    )
    app.include_router(pages.router)
    app.include_router(social_router)
    app.include_router(api.router)
    app.mount("/static", StaticFiles(directory=str(static_dir())), name="static")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(ROOT / "static" / "img" / "saan-mark.jpg")

    @app.exception_handler(AppError)
    async def on_app_error(request: Request, exc: AppError):
        wants_json = request.url.path.startswith("/api") or request.headers.get("x-saan-fetch") == "1"
        strings = STRINGS[language_of(request)]
        message = strings.get(exc.code, strings["server_error"])
        if wants_json:
            return JSONResponse({"error": exc.code, "message": message}, status_code=exc.status)
        if exc.status == 401 or exc.code == "login_required":
            from urllib.parse import quote

            from fastapi.responses import RedirectResponse

            return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)
        if exc.code == "account_suspended":
            request.session.clear()
        code = exc.code if exc.code in strings else "server_error"
        return render(
            request,
            "error.html",
            status=exc.status,
            title=strings.get(code, strings["server_error"]),
            code=code,
        )

    return app


app = create_app()
