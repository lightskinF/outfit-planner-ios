"""From uploaded images to a garment layer.

The avatar arrives as a cut-out (a person on a transparent background). It is
placed on a flat background colour, which becomes the "studio" every image
lives in: the model sees a plain backdrop, changed pixels are easy to find,
and stacking layers on the phone is plain source-over drawing.
"""
from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps

from .layers import BodyPose, Layer, compose, extract_layer
from .providers.base import BadInputImage, TryOnProvider

ASPECT = 2 / 3            # width / height the try-on models work at
ASPECT_TOLERANCE = 0.02
MIN_COVERAGE = 0.004      # below this the model changed nothing worth keeping

# Garments go on from the inside out.
RENDER_ORDER = {"shoes": 0, "bottom": 1, "dress": 2, "top": 3, "outerwear": 4, "accessories": 5}


@dataclass
class Avatar:
    image: Image.Image                # RGB on the flat background
    silhouette: np.ndarray | None     # where the person is, if known
    pose: BodyPose | None


def parse_colour(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise BadInputImage("background must be a colour like #F5E8E4")
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise BadInputImage("background must be a colour like #F5E8E4") from exc


def open_image(data: bytes, what: str, max_side: int | None = None) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001 - any failure means "not an image we can use"
        raise BadInputImage(f"the {what} image could not be read") from exc
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
    if min(image.size) < 256:
        raise BadInputImage(f"the {what} image is too small (at least 256 px per side)")
    if max_side and max(image.size) > max_side:
        raise BadInputImage(f"the {what} image is too large (at most {max_side} px per side)")
    return image


def prepare_avatar(image: Image.Image, background: tuple[int, int, int], pose: BodyPose | None) -> Avatar:
    w, h = image.size
    if abs(w / h - ASPECT) > ASPECT_TOLERANCE:
        raise BadInputImage("the avatar must be a 2:3 portrait image (for example 1024x1536)")
    silhouette = None
    if image.mode == "RGBA":
        alpha = np.asarray(image.getchannel("A"))
        if alpha.min() < 250:
            silhouette = alpha > 127
        canvas = Image.new("RGB", image.size, background)
        canvas.paste(image, mask=image.getchannel("A"))
        image = canvas
    return Avatar(image.convert("RGB"), silhouette, pose)


def prepare_garment(image: Image.Image, max_side: int = 1536) -> Image.Image:
    if max(image.size) > max_side:
        image = image.copy()
        image.thumbnail((max_side, max_side), Image.LANCZOS)
    return image


async def make_layer(provider: TryOnProvider, avatar: Avatar, garment: Image.Image, category: str,
                     garment_photo_type: str = "auto", seed: int = 42) -> tuple[Layer, float]:
    """One generation: dress the avatar in one garment and cut the layer out."""
    started = time.monotonic()
    tried = await provider.try_on(avatar.image, garment, category, garment_photo_type, seed)
    layer = extract_layer(avatar.image, tried, category, avatar.pose, silhouette=avatar.silhouette)
    return layer, time.monotonic() - started


async def render_outfit(provider: TryOnProvider, avatar: Avatar,
                        garments: list[tuple[str, Image.Image]], seed: int = 42) -> tuple[Image.Image, int]:
    """Dress the avatar one garment after the other, each on top of the last.

    Unlike stacked layers, every garment is generated knowing what is already
    worn, so hems, waistbands and cuffs meet the way the model thinks they
    should. Each step still keeps only the pixels it changed inside its own
    part of the body, so the face and background stay the original ones.
    Returns the image and how many generations it used.
    """
    current = avatar.image
    used = 0
    for category, garment in sorted(garments, key=lambda g: RENDER_ORDER.get(g[0], 9)):
        tried = await provider.try_on(current, garment, category, "auto", seed)
        used += 1
        layer = extract_layer(current, tried, category, avatar.pose, silhouette=avatar.silhouette)
        if not layer.is_empty:
            current = compose(current, [layer.image]).convert("RGB")
    return current, used


def png_base64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, "PNG", compress_level=6)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def jpeg_base64(image: Image.Image, quality: int = 92) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("ascii")
