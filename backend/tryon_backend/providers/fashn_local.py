"""FASHN VTON v1.5 running on your own GPU (Apache-2.0).

Install it next to this server:

    git clone https://github.com/fashn-AI/fashn-vton-1.5 && cd fashn-vton-1.5
    pip install -e . && python scripts/download_weights.py --weights-dir ./weights

No image leaves your machine. It supports tops, bottoms and one-pieces; shoes
and accessories are not supported by this model.
"""
from __future__ import annotations

import asyncio

from PIL import Image

from .base import ProviderUnavailable, UnsupportedCategory

_CATEGORY = {"top": "tops", "outerwear": "tops", "bottom": "bottoms", "dress": "one-pieces"}


class FashnLocalProvider:
    name = "local"
    model = "fashn-vton-1.5"

    def __init__(self, weights_dir: str, *, num_timesteps: int = 30, guidance_scale: float = 1.5):
        self.weights_dir = weights_dir
        self.num_timesteps = num_timesteps
        self.guidance_scale = guidance_scale
        self._pipeline = None
        self._lock = asyncio.Lock()   # one GPU, one generation at a time

    def supports(self, category: str) -> bool:
        return category in _CATEGORY

    def _load(self):
        if self._pipeline is None:
            try:
                from fashn_vton import TryOnPipeline
            except ImportError as exc:
                raise ProviderUnavailable(
                    "fashn_vton is not installed: see tryon_backend/providers/fashn_local.py") from exc
            self._pipeline = TryOnPipeline(weights_dir=self.weights_dir)
        return self._pipeline

    def _run(self, person: Image.Image, garment: Image.Image, category: str,
             garment_photo_type: str, seed: int) -> Image.Image:
        pipeline = self._load()
        result = pipeline(
            person_image=person.convert("RGB"),
            garment_image=_flatten(garment),
            category=_CATEGORY[category],
            garment_photo_type="model" if garment_photo_type == "model" else "flat-lay",
            num_samples=1,
            num_timesteps=self.num_timesteps,
            guidance_scale=self.guidance_scale,
            seed=seed,
        )
        return result.images[0].convert("RGB")

    async def try_on(self, person: Image.Image, garment: Image.Image, category: str,
                     garment_photo_type: str = "auto", seed: int = 42) -> Image.Image:
        if not self.supports(category):
            raise UnsupportedCategory(f"{category} cannot be tried on with this model")
        async with self._lock:
            return await asyncio.to_thread(self._run, person, garment, category, garment_photo_type, seed)

    async def aclose(self) -> None:
        self._pipeline = None


def _flatten(image: Image.Image) -> Image.Image:
    if image.mode != "RGBA":
        return image.convert("RGB")
    canvas = Image.new("RGB", image.size, (255, 255, 255))
    canvas.paste(image, mask=image.getchannel("A"))
    return canvas
