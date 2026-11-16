"""A stand-in provider for development and tests. It does not try anything on.

It paints a block in the garment's colour where the garment would go, so the
whole pipeline (upload, layer extraction, caching, stacking in the app) can be
exercised without a GPU or an API key. Never use it in production.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from .base import CATEGORIES

# left, top, right, bottom as fractions of the image
_BOXES = {
    "top": (0.22, 0.20, 0.78, 0.52),
    "outerwear": (0.18, 0.19, 0.82, 0.56),
    "dress": (0.24, 0.20, 0.76, 0.80),
    "bottom": (0.30, 0.50, 0.70, 0.92),
    "shoes": (0.30, 0.93, 0.70, 0.99),
    "accessories": (0.40, 0.02, 0.60, 0.07),
}


class MockProvider:
    name = "mock"
    model = "mock"

    def supports(self, category: str) -> bool:
        return category in CATEGORIES

    async def try_on(self, person: Image.Image, garment: Image.Image, category: str,
                     garment_photo_type: str = "auto", seed: int = 42) -> Image.Image:
        colour = _dominant_colour(garment)
        out = person.convert("RGB").copy()
        w, h = out.size
        l, t, r, b = _BOXES[category]
        ImageDraw.Draw(out).rounded_rectangle(
            (int(l * w), int(t * h), int(r * w), int(b * h)), radius=int(0.03 * w), fill=colour)
        return out

    async def aclose(self) -> None:
        return None


def _dominant_colour(garment: Image.Image) -> tuple[int, int, int]:
    small = garment.convert("RGBA").resize((48, 48))
    px = np.asarray(small).reshape(-1, 4)
    opaque = px[px[:, 3] > 127][:, :3]
    if len(opaque) == 0:
        opaque = px[:, :3]
    r, g, b = np.median(opaque, axis=0)
    return int(r), int(g), int(b)
