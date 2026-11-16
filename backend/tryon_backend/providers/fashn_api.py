"""FASHN's hosted API (https://docs.fashn.ai).

Clothing goes to `tryon-v1.6` (tops, bottoms, one-pieces; 1 credit per image).
Shoes and accessories go to `tryon-max`, which accepts any wearable item.

Images travel as base64 data URIs and results come back as base64 too
(`return_base64`), so nothing is left on a CDN for days.
"""
from __future__ import annotations

import asyncio
import base64
import io
import time

import httpx
from PIL import Image

from .base import (BadInputImage, ContentBlocked, PoseNotDetected, ProviderTimeout,
                   ProviderUnavailable, TryOnError, UnsupportedCategory)

_V16_CATEGORY = {"top": "tops", "outerwear": "tops", "bottom": "bottoms", "dress": "one-pieces"}
_MAX_CATEGORIES = {"shoes", "accessories"}

# FASHN error names -> our errors (https://docs.fashn.ai, "Error Handling").
_ERRORS = {
    "PoseError": PoseNotDetected,
    "ContentModerationError": ContentBlocked,
    "ImageLoadError": BadInputImage,
    "InputValidationError": BadInputImage,
    "ThirdPartyError": ProviderUnavailable,
    "UnavailableError": ProviderUnavailable,
}


class FashnAPIProvider:
    name = "fashn"

    def __init__(self, api_key: str, *, base_url: str = "https://api.fashn.ai",
                 mode: str = "balanced", timeout: float = 120.0, poll_interval: float = 1.0,
                 use_max_for_accessories: bool = True, client: httpx.AsyncClient | None = None):
        if not api_key:
            raise ValueError("FASHN_API_KEY is not set")
        self.mode = mode
        self.model = "tryon-v1.6"
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.use_max = use_max_for_accessories
        self._client = client or httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(30.0),
            headers={"Authorization": f"Bearer {api_key}"})

    def supports(self, category: str) -> bool:
        return category in _V16_CATEGORY or (self.use_max and category in _MAX_CATEGORIES)

    async def try_on(self, person: Image.Image, garment: Image.Image, category: str,
                     garment_photo_type: str = "auto", seed: int = 42) -> Image.Image:
        if not self.supports(category):
            raise UnsupportedCategory(f"{category} cannot be tried on with this provider")

        person_uri = _data_uri(person.convert("RGB"), "PNG")
        garment_uri = _data_uri(_flatten(garment), "JPEG")
        if category in _V16_CATEGORY:
            body = {"model_name": "tryon-v1.6", "inputs": {
                "model_image": person_uri,
                "garment_image": garment_uri,
                "category": _V16_CATEGORY[category],
                "garment_photo_type": garment_photo_type,
                "mode": self.mode,
                "seed": seed,
                "num_samples": 1,
                "output_format": "png",
                "return_base64": True,
            }}
        else:
            body = {"model_name": "tryon-max", "inputs": {
                "model_image": person_uri,
                "product_image": garment_uri,
                "resolution": "1k",
                "generation_mode": "fast",
                "seed": seed,
                "num_images": 1,
                "output_format": "png",
                "return_base64": True,
            }}

        prediction_id = await self._run(body)
        output = await self._wait(prediction_id)
        return await self._load(output)

    async def _run(self, body: dict) -> str:
        try:
            response = await self._client.post("/v1/run", json=body)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"could not reach the try-on service: {exc}") from exc
        data = _json(response)
        if response.status_code >= 400 or data.get("error"):
            raise _to_error(data, response.status_code)
        if not data.get("id"):
            raise ProviderUnavailable("the try-on service did not return a prediction id")
        return data["id"]

    async def _wait(self, prediction_id: str) -> str:
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                response = await self._client.get(f"/v1/status/{prediction_id}")
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(f"could not reach the try-on service: {exc}") from exc
            data = _json(response)
            if response.status_code >= 400:
                raise _to_error(data, response.status_code)
            status = data.get("status")
            if status == "completed":
                output = data.get("output") or []
                if not output:
                    raise ProviderUnavailable("the try-on finished without an image")
                return output[0]
            if status == "failed":
                raise _to_error(data, 200)
            if time.monotonic() >= deadline:
                raise ProviderTimeout("the try-on took too long")
            await asyncio.sleep(self.poll_interval)

    async def _load(self, output: str) -> Image.Image:
        try:
            if output.startswith("data:"):
                raw = base64.b64decode(output.split(",", 1)[1])
            else:  # a CDN URL, if base64 was not honoured
                response = await self._client.get(output)
                response.raise_for_status()
                raw = response.content
            image = Image.open(io.BytesIO(raw))
            image.load()
            return image.convert("RGB")
        except TryOnError:
            raise
        except Exception as exc:  # noqa: BLE001 - anything here means an unusable result
            raise ProviderUnavailable(f"the try-on result could not be read: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()


def _flatten(image: Image.Image) -> Image.Image:
    """Garment cut-outs are transparent; the model wants a plain background."""
    if image.mode != "RGBA":
        return image.convert("RGB")
    canvas = Image.new("RGB", image.size, (255, 255, 255))
    canvas.paste(image, mask=image.getchannel("A"))
    return canvas


def _data_uri(image: Image.Image, fmt: str) -> str:
    buffer = io.BytesIO()
    if fmt == "JPEG":
        image.save(buffer, "JPEG", quality=92)
        mime = "image/jpeg"
    else:
        image.save(buffer, "PNG", compress_level=3)
        mime = "image/png"
    return f"data:{mime};base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def _json(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        return {"error": "InvalidResponse", "message": response.text[:200]}
    return data if isinstance(data, dict) else {"error": "InvalidResponse", "message": str(data)[:200]}


def _to_error(data: dict, status_code: int) -> TryOnError:
    error = data.get("error")
    if isinstance(error, dict):          # status endpoint: {"name", "message"}
        name, message = error.get("name", ""), error.get("message", "")
    else:                                # run endpoint: {"error", "message"}
        name, message = str(error or ""), str(data.get("message", ""))
    kind = _ERRORS.get(name)
    if kind:
        return kind(message or name)
    if status_code in (401, 403):
        return ProviderUnavailable("the try-on service rejected the server's API key")
    if status_code == 429 or name in ("RateLimitExceeded", "ConcurrencyLimitExceeded", "OutOfCredits"):
        return ProviderUnavailable(message or "the try-on service is over its limit")
    return TryOnError(message or name or f"try-on failed (HTTP {status_code})")
