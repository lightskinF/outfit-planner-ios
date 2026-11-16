"""What every try-on provider has to do, and the errors it may raise."""
from __future__ import annotations

from typing import Protocol

from PIL import Image

# Categories the app knows. Providers support a subset.
CATEGORIES = ("top", "bottom", "outerwear", "dress", "shoes", "accessories")


class TryOnError(Exception):
    """A try-on failed for a reason the person using the app can act on."""

    code = "tryon_failed"
    status = 502

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class UnsupportedCategory(TryOnError):
    code = "category_not_supported"
    status = 422


class PoseNotDetected(TryOnError):
    code = "pose_not_detected"
    status = 422


class ContentBlocked(TryOnError):
    code = "content_blocked"
    status = 422


class BadInputImage(TryOnError):
    code = "bad_image"
    status = 422


class ProviderUnavailable(TryOnError):
    code = "provider_unavailable"
    status = 503


class ProviderTimeout(TryOnError):
    code = "provider_timeout"
    status = 504


class TryOnProvider(Protocol):
    name: str

    def supports(self, category: str) -> bool: ...

    async def try_on(self, person: Image.Image, garment: Image.Image, category: str,
                     garment_photo_type: str = "auto", seed: int = 42) -> Image.Image:
        """Return `person` wearing `garment`. Same framing as `person`."""
        ...

    async def aclose(self) -> None: ...
