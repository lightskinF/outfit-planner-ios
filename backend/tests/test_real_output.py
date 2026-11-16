"""Layer extraction on a real try-on result.

`fashn_tryon_top.webp` was produced by FASHN VTON 1.5 (the public demo) from
`avatar_576x864.webp` and a phone photo of a garment. It checks the two facts
the layer approach rests on, with a real model instead of synthetic images:
the model leaves everything outside the garment as it was, and stacking the
extracted layer on the avatar gives back the model's image.
"""
import json
import pathlib

import numpy as np
from PIL import Image

from tryon_backend.layers import BodyPose, compose, difference_map, extract_layer

HERE = pathlib.Path(__file__).parent / "real"
pose = BodyPose.from_dict(json.loads((HERE / "avatar_joints.json").read_text()))
avatar = Image.open(HERE / "avatar_576x864.webp").convert("RGB")
tried = Image.open(HERE / "fashn_tryon_top.webp").convert("RGB")


def test_model_leaves_head_legs_and_background_alone():
    d = difference_map(np.asarray(avatar), np.asarray(tried))
    h = d.shape[0]
    assert d[: int(0.13 * h)].mean() < 2.0          # head
    assert d[int(0.70 * h):].mean() < 2.0           # legs and feet
    assert d[:, :100].mean() < 2.0 and d[:, -100:].mean() < 2.0


def test_stacked_layer_reproduces_the_model_output():
    layer = extract_layer(avatar, tried, "top", pose)
    assert 0.07 < layer.coverage < 0.16
    assert layer.bbox[1] > pose.chin_y * avatar.height - 2       # nothing above the collar
    stacked = np.asarray(compose(avatar, [layer.image]).convert("RGB")).astype(int)
    assert np.abs(stacked - np.asarray(tried).astype(int)).mean() < 2.5
    face = (slice(30, 110), slice(240, 340))
    assert np.array_equal(stacked[face], np.asarray(avatar).astype(int)[face])
