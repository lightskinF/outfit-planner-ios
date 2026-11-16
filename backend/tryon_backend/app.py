"""HTTP API of the try-on server.

    POST /v1/devices   register an installation of the app, get a token
    POST /v1/layers    avatar + one garment -> the garment as a layer
    POST /v1/renders   avatar + a whole outfit -> one finished image
    GET  /v1/limits    how many generations this device has left
    GET  /healthz

Uploaded photos are processed in memory and never written to disk or logged.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from . import access
from .layers import BodyPose
from .pipeline import (MIN_COVERAGE, jpeg_base64, make_layer, open_image, parse_colour,
                       png_base64, prepare_avatar, prepare_garment, render_outfit)
from .providers import CATEGORIES, TryOnError, TryOnProvider, make_provider
from .providers.base import BadInputImage, UnsupportedCategory
from .settings import Settings

log = logging.getLogger("tryon")

DEFAULT_BACKGROUND = "#F5E8E4"
PHOTO_TYPES = ("auto", "flat-lay", "model")


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        self.status, self.code, self.message, self.headers = status, code, message, headers


def create_app(settings: Settings | None = None, provider: TryOnProvider | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.check()
    if settings.provider == "mock" and not settings.secret:
        settings.secret = "development-only-secret-not-for-production"
        settings.app_key = settings.app_key or "development-app-key"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await app.state.provider.aclose()

    app = FastAPI(title="Outfit planner try-on", version="1.0.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.provider = provider or make_provider(settings)
    app.state.limiter = access.Limiter(settings.per_device_hourly, settings.per_device_daily,
                                       settings.global_daily)

    # --- errors -----------------------------------------------------------

    def error(status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
        return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)

    @app.exception_handler(APIError)
    async def _api_error(_: Request, exc: APIError):
        return error(exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(TryOnError)
    async def _tryon_error(_: Request, exc: TryOnError):
        log.warning("try-on failed: %s (%s)", exc.code, exc.message)
        return error(exc.status, exc.code, exc.message)

    @app.exception_handler(access.LimitExceeded)
    async def _limit(_: Request, exc: access.LimitExceeded):
        return error(429, "limit_reached", f"generation limit reached ({exc.scope})",
                     {"Retry-After": str(exc.retry_after)})

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException):
        return error(exc.status_code, "request_error", str(exc.detail))

    # --- access -----------------------------------------------------------

    def device(authorization: str = Header(default="")) -> str:
        scheme, _, token = authorization.partition(" ")
        device_id = access.verify(token.strip(), settings.secret) if scheme.lower() == "bearer" else None
        if not device_id:
            raise APIError(401, "unauthorized", "missing or invalid token")
        return device_id

    async def read(upload: UploadFile, what: str) -> bytes:
        data = await upload.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            raise APIError(413, "too_large", f"the {what} image is too large")
        if not data:
            raise BadInputImage(f"the {what} image is empty")
        return data

    def parse_pose(text: str | None) -> BodyPose | None:
        if not text:
            return None
        try:
            return BodyPose.from_dict(json.loads(text))
        except (ValueError, TypeError, KeyError) as exc:
            raise APIError(422, "bad_pose", f"pose is not valid: {exc}") from exc

    def check_category(category: str) -> str:
        if category not in CATEGORIES:
            raise APIError(422, "bad_category", f"category must be one of: {', '.join(CATEGORIES)}")
        if not app.state.provider.supports(category):
            raise UnsupportedCategory(f"{category} cannot be tried on yet")
        return category

    # --- routes -----------------------------------------------------------

    @app.get("/healthz")
    async def healthz():
        provider = app.state.provider
        return {"status": "ok", "provider": provider.name,
                "categories": [c for c in CATEGORIES if provider.supports(c)]}

    @app.post("/v1/devices")
    async def register(x_app_key: str = Header(default="")):
        if not x_app_key or not access.hmac.compare_digest(x_app_key, settings.app_key):
            raise APIError(401, "unauthorized", "missing or invalid app key")
        return {"token": access.sign(access.new_device_id(), settings.secret)}

    @app.get("/v1/limits")
    async def limits(device_id: str = Depends(device)):
        return {"remaining": app.state.limiter.remaining(device_id)}

    @app.post("/v1/layers")
    async def layers(avatar: UploadFile = File(...), garment: UploadFile = File(...),
                     category: str = Form(...), pose: str | None = Form(default=None),
                     background: str = Form(default=DEFAULT_BACKGROUND),
                     garment_photo_type: str = Form(default="auto"),
                     device_id: str = Depends(device)):
        category = check_category(category)
        if garment_photo_type not in PHOTO_TYPES:
            raise APIError(422, "bad_photo_type", f"garment_photo_type must be one of: {', '.join(PHOTO_TYPES)}")
        limiter: access.Limiter = app.state.limiter
        limiter.check(device_id)

        avatar_image = open_image(await read(avatar, "avatar"), "avatar", settings.max_avatar_side)
        garment_image = prepare_garment(open_image(await read(garment, "garment"), "garment"))
        prepared = prepare_avatar(avatar_image, parse_colour(background), parse_pose(pose))

        layer, seconds = await make_layer(app.state.provider, prepared, garment_image, category,
                                          garment_photo_type)
        limiter.record(device_id)
        if layer.coverage < MIN_COVERAGE:
            raise APIError(422, "nothing_changed",
                           "the try-on did not change the avatar; try another photo of the garment")
        width, height = layer.image.size
        log.info("layer category=%s coverage=%.3f seconds=%.1f", category, layer.coverage, seconds)
        return {
            "layer": png_base64(layer.image),
            "width": width, "height": height,
            "bbox": list(layer.bbox),
            "coverage": round(layer.coverage, 4),
            "provider": app.state.provider.name,
            "seconds": round(seconds, 2),
            "remaining": limiter.remaining(device_id),
        }

    @app.post("/v1/renders")
    async def renders(avatar: UploadFile = File(...), garments: list[UploadFile] = File(...),
                      categories: str = Form(...), pose: str | None = Form(default=None),
                      background: str = Form(default=DEFAULT_BACKGROUND),
                      device_id: str = Depends(device)):
        try:
            names = json.loads(categories)
            if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                raise ValueError
        except ValueError as exc:
            raise APIError(422, "bad_category", 'categories must be a JSON list, e.g. ["top","bottom"]') from exc
        if len(names) != len(garments):
            raise APIError(422, "bad_category", "categories and garments must have the same length")
        if not 1 <= len(names) <= settings.max_render_garments:
            raise APIError(422, "too_many_garments",
                           f"an outfit can have 1 to {settings.max_render_garments} garments")
        names = [check_category(n) for n in names]
        limiter: access.Limiter = app.state.limiter
        limiter.check(device_id, cost=len(names))

        avatar_image = open_image(await read(avatar, "avatar"), "avatar", settings.max_avatar_side)
        prepared = prepare_avatar(avatar_image, parse_colour(background), parse_pose(pose))
        items = [(name, prepare_garment(open_image(await read(upload, "garment"), "garment")))
                 for name, upload in zip(names, garments)]

        image, used = await render_outfit(app.state.provider, prepared, items)
        limiter.record(device_id, cost=used)
        width, height = image.size
        log.info("render garments=%d generations=%d", len(items), used)
        return {
            "image": jpeg_base64(image), "format": "jpeg",
            "width": width, "height": height,
            "generations": used,
            "provider": app.state.provider.name,
            "remaining": limiter.remaining(device_id),
        }

    return app


def app_from_env() -> FastAPI:
    """Entry point for `uvicorn tryon_backend.app:app_from_env --factory`."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()
