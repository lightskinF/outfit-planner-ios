import io
import pathlib
import sys

import numpy as np
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

W, H = 512, 768
BACKGROUND = (245, 232, 228)

# A front-facing standing figure, as fractions of the image.
POSE = {
    "nose": (0.50, 0.10),
    "left_shoulder": (0.34, 0.21), "right_shoulder": (0.66, 0.21),
    "left_hip": (0.41, 0.52), "right_hip": (0.59, 0.52),
    "left_knee": (0.41, 0.72), "right_knee": (0.59, 0.72),
    "left_ankle": (0.41, 0.92), "right_ankle": (0.59, 0.92),
}


def draw_person(shirt=(120, 120, 124), shorts=(214, 204, 188), size=(W, H)) -> Image.Image:
    """A crude person as an RGBA cut-out: head, T-shirt, shorts, bare legs."""
    w, h = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    skin = (205, 160, 130, 255)
    d.ellipse((0.43 * w, 0.04 * h, 0.57 * w, 0.17 * h), fill=skin)                      # head
    d.rectangle((0.47 * w, 0.16 * h, 0.53 * w, 0.20 * h), fill=skin)                    # neck
    d.rectangle((0.26 * w, 0.20 * h, 0.33 * w, 0.56 * h), fill=skin)                    # arms
    d.rectangle((0.67 * w, 0.20 * h, 0.74 * w, 0.56 * h), fill=skin)
    d.rectangle((0.36 * w, 0.50 * h, 0.48 * w, 0.95 * h), fill=skin)                    # legs
    d.rectangle((0.52 * w, 0.50 * h, 0.64 * w, 0.95 * h), fill=skin)
    d.rectangle((0.33 * w, 0.19 * h, 0.67 * w, 0.50 * h), fill=shirt + (255,))          # T-shirt
    d.rectangle((0.26 * w, 0.19 * h, 0.33 * w, 0.30 * h), fill=shirt + (255,))          # sleeves
    d.rectangle((0.67 * w, 0.19 * h, 0.74 * w, 0.30 * h), fill=shirt + (255,))
    d.rectangle((0.35 * w, 0.48 * h, 0.65 * w, 0.62 * h), fill=shorts + (255,))         # shorts
    return image


def on_background(cutout: Image.Image, colour=BACKGROUND) -> Image.Image:
    canvas = Image.new("RGB", cutout.size, colour)
    canvas.paste(cutout, mask=cutout.getchannel("A"))
    return canvas


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def garment_image(colour=(30, 60, 160)) -> Image.Image:
    image = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    ImageDraw.Draw(image).rounded_rectangle((60, 40, 340, 360), radius=30, fill=colour + (255,))
    return image


def add_noise(image: Image.Image, amount: float = 2.0, seed: int = 1) -> Image.Image:
    rng = np.random.default_rng(seed)
    array = np.asarray(image.convert("RGB")).astype(np.float32)
    array += rng.normal(0, amount, array.shape)
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))


@pytest.fixture
def person_cutout():
    return draw_person()


@pytest.fixture
def person(person_cutout):
    return on_background(person_cutout)
