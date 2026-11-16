"""The layer approach checked on the images that ship with the app.

The prototype contains images of the same avatar wearing one garment at a time
and wearing whole outfits, all generated directly. Stacking the single-garment
layers must give the same outfit as the directly generated one.
"""
import pathlib

import cv2
import numpy as np
import pytest
from PIL import Image

from tryon_backend.layers import BodyPose, compose, extract_layer

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "demo-assets"
pytestmark = pytest.mark.skipif(not (ASSETS / "Grey Shirt AI.imageset").exists(), reason="demo assets not present")

W, H = 640, 1668
JOINTS = {"nose": (322, 165), "left_shoulder": (150, 350), "right_shoulder": (500, 350),
          "left_hip": (230, 880), "right_hip": (415, 880), "left_knee": (225, 1200),
          "right_knee": (420, 1200), "left_ankle": (215, 1530), "right_ankle": (435, 1530)}
pose = BodyPose.from_dict({k: (x / W, y / H) for k, (x, y) in JOINTS.items()})


def load(name):
    image = Image.open(ASSETS / f"{name}.imageset" / f"{name}.png").convert("RGB")
    return image.crop((0, 0, 1280, 3336)).resize((W, H), Image.LANCZOS)


@pytest.fixture(scope="module")
def studio():
    shoes, sweater = load("Puma Shoes AI"), load("Grey Shirt AI")
    base = shoes.copy()                                    # T-shirt and shorts...
    base.paste(sweater.crop((0, int(H * 0.86), W, H)), (0, int(H * 0.86)))   # ...barefoot
    cv2.setRNGSeed(0)
    marks = np.full((H, W), cv2.GC_PR_BGD, np.uint8)
    marks[:, :30] = marks[:, -30:] = cv2.GC_BGD
    marks[40:1640, 60:590] = cv2.GC_PR_FGD
    for x, y in JOINTS.values():
        cv2.circle(marks, (x, y), 22, cv2.GC_FGD, -1)
    cv2.rectangle(marks, (200, 330), (450, 1000), cv2.GC_FGD, -1)
    cv2.grabCut(cv2.cvtColor(np.asarray(base), cv2.COLOR_RGB2BGR), marks, None,
                np.zeros((1, 65)), np.zeros((1, 65)), 4, cv2.GC_INIT_WITH_MASK)
    silhouette = (marks == cv2.GC_FGD) | (marks == cv2.GC_PR_FGD)
    layer = lambda name, category: extract_layer(base, load(name), category, pose, silhouette=silhouette)
    return {"base": base,
            "grey": layer("Grey Shirt AI", "top"), "navy": layer("Dark Blue Shirt AI", "top"),
            "black": layer("Black Jeans AI", "bottom"), "blue": layer("Blue Jeans AI", "bottom"),
            "sneakers": layer("Puma Shoes AI", "shoes"), "boots": layer("Black Boots AI", "shoes")}


def region(image, box):
    l, t, r, b = box
    return np.asarray(image.convert("RGB"))[t:b, l:r].astype(np.float32)


def test_layers_have_plausible_size_and_place(studio):
    for name, low, high in (("grey", .18, .30), ("navy", .18, .30), ("black", .15, .27),
                            ("blue", .15, .27), ("sneakers", .015, .05), ("boots", .02, .06)):
        assert low < studio[name].coverage < high, name
    assert studio["grey"].bbox[1] > pose.chin_y * H - 5          # tops stay below the face
    assert studio["black"].bbox[1] > pose.waist_y * H - 5        # trousers below the waist
    assert studio["sneakers"].bbox[1] > pose.knee_y * H


def test_trousers_do_not_show_through_a_same_colour_top(studio):
    """Grey sweater over the avatar's grey T-shirt, with black jeans underneath."""
    look = compose(studio["base"], [studio["black"].image, studio["grey"].image])
    chest = region(look, (250, 420, 440, 800))    # between the arms, down to just above the hem
    assert (chest.mean(axis=-1) < 70).mean() < 0.002


@pytest.mark.parametrize("top,bottom,shoes,direct", [
    ("grey", "black", "sneakers", "Grey Shirt_Black Jeans_Puma Shoes AI"),
    ("navy", "blue", "boots", "Dark Blue Shirt_Blue Jeans_Black Boots AI"),
    ("navy", "black", "sneakers", "Dark Blue Shirt_Black Jeans_Puma Shoes AI"),
    ("grey", "blue", "sneakers", "Grey Shirt_Blue Jeans_Puma Shoes AI"),
])
def test_stacked_layers_match_the_directly_generated_outfit(studio, top, bottom, shoes, direct):
    look = compose(studio["base"], [studio[shoes].image, studio[bottom].image, studio[top].image])
    wanted = load(direct)
    # Average colour of each garment area must agree (the two images are separate generations,
    # so they are compared by area, not pixel by pixel).
    for name, box in (("chest", (220, 420, 430, 700)), ("thighs", (190, 960, 450, 1150)),
                      ("shins", (190, 1250, 450, 1450)), ("face", (250, 80, 400, 250))):
        got, want = region(look, box).mean(axis=(0, 1)), region(wanted, box).mean(axis=(0, 1))
        assert np.abs(got - want).max() < 18, f"{name}: {got.round()} vs {want.round()}"
    # and the face is the avatar's own, untouched
    assert np.array_equal(region(look, (250, 80, 400, 230)), region(studio["base"], (250, 80, 400, 230)))
