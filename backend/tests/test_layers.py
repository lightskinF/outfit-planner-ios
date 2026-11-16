import numpy as np
import pytest
from PIL import Image, ImageDraw

from conftest import H, POSE, W, add_noise, draw_person, on_background
from tryon_backend.layers import BodyPose, compose, extract_layer, zone_rows

pose = BodyPose.from_dict(POSE)


def paint(image, box, colour):
    out = image.copy()
    ImageDraw.Draw(out).rectangle([box[0] * W, box[1] * H, box[2] * W, box[3] * H], fill=colour)
    return out


def alpha(layer):
    return np.asarray(layer.image.getchannel("A"))


def test_layer_is_exactly_the_changed_region(person):
    box = (0.33, 0.19, 0.67, 0.50)
    tried = paint(person, box, (20, 40, 150))
    layer = extract_layer(person, tried, "top", pose)

    a = alpha(layer)
    inside = a[int(0.22 * H):int(0.47 * H), int(0.36 * W):int(0.64 * W)]
    assert inside.min() == 255, "the middle of the garment must be fully opaque"
    outside = a.copy()
    outside[int(0.17 * H):int(0.52 * H), int(0.31 * W):int(0.69 * W)] = 0
    assert outside.max() == 0, "nothing outside the garment may be in the layer"
    assert 0.9 * 0.34 * 0.31 < layer.coverage < 1.05 * 0.34 * 0.31


def test_no_change_gives_an_empty_layer(person):
    layer = extract_layer(person, person.copy(), "top", pose)
    assert layer.is_empty and alpha(layer).max() == 0


def test_model_noise_alone_is_not_a_layer(person):
    layer = extract_layer(person, add_noise(person, 3.0), "top", pose)
    assert layer.is_empty


def test_noisy_output_still_gives_a_clean_layer(person):
    tried = add_noise(paint(person, (0.33, 0.19, 0.67, 0.50), (20, 40, 150)), 3.0)
    layer = extract_layer(person, tried, "top", pose)
    a = alpha(layer)
    assert a[int(0.3 * H), int(0.5 * W)] == 255
    assert a[int(0.8 * H):, :].max() == 0 and a[:int(0.12 * H), :].max() == 0


def test_face_is_never_part_of_a_layer(person):
    """A model that also repaints the face must not change the avatar's face."""
    tried = paint(person, (0.33, 0.19, 0.67, 0.50), (20, 40, 150))
    tried = paint(tried, (0.43, 0.04, 0.57, 0.14), (90, 200, 90))      # "new" face
    layer = extract_layer(person, tried, "top", pose)
    assert alpha(layer)[:int(pose.chin_y * H), :].max() == 0
    composed = compose(person, [layer.image]).convert("RGB")
    assert composed.getpixel((W // 2, int(0.09 * H))) == person.getpixel((W // 2, int(0.09 * H)))


def test_bottoms_cannot_touch_the_chest(person):
    tried = paint(person, (0.35, 0.48, 0.65, 0.95), (15, 15, 20))
    tried = paint(tried, (0.40, 0.25, 0.60, 0.35), (15, 15, 20))        # stray change on the chest
    layer = extract_layer(person, tried, "bottom", pose)
    assert alpha(layer)[:int(pose.waist_y * H), :].max() == 0
    assert alpha(layer)[int(0.8 * H), int(0.42 * W)] == 255


def test_revealed_skin_belongs_to_the_layer():
    """Shorts over an avatar in long trousers: the bare legs must come with the layer."""
    cutout = draw_person()
    base = on_background(cutout)
    long_trousers = paint(base, (0.36, 0.50, 0.48, 0.95), (40, 40, 45))
    long_trousers = paint(long_trousers, (0.52, 0.50, 0.64, 0.95), (40, 40, 45))
    layer = extract_layer(long_trousers, base, "bottom", pose)     # "try on" the shorts again
    composed = compose(long_trousers, [layer.image]).convert("RGB")
    assert composed.getpixel((int(0.42 * W), int(0.85 * H))) == base.getpixel((int(0.42 * W), int(0.85 * H)))


def test_same_colour_top_is_solid(person_cutout):
    """Grey sweater over a grey T-shirt: only its outline differs, yet trousers must not show through."""
    base = on_background(person_cutout)
    shirt = base.getpixel((W // 2, int(0.3 * H)))
    tried = base.copy()
    d = ImageDraw.Draw(tried)
    d.rectangle([0.25 * W, 0.19 * H, 0.33 * W, 0.56 * H], fill=shirt)          # long sleeves
    d.rectangle([0.67 * W, 0.19 * H, 0.75 * W, 0.56 * H], fill=shirt)
    d.rectangle([0.33 * W, 0.50 * H, 0.67 * W, 0.56 * H], fill=shirt)          # longer hem
    d.rectangle([0.44 * W, 0.17 * H, 0.56 * W, 0.19 * H], fill=shirt)          # collar

    top = extract_layer(person_cutout, tried, "top", pose)
    a = alpha(top)
    assert a[int(0.35 * H), int(0.5 * W)] == 255, "the unchanged chest must be filled in"
    assert a[int(0.40 * H), int(0.36 * W)] == 255, "the sides of the torso too"

    trousers = base.copy()
    ImageDraw.Draw(trousers).rectangle([0.34 * W, 0.42 * H, 0.66 * W, 0.95 * H], fill=(10, 10, 12))
    bottom = extract_layer(person_cutout, trousers, "bottom", pose)
    composed = compose(base, [bottom.image, top.image]).convert("RGB")
    torso = np.asarray(composed)[int(0.24 * H):int(0.54 * H), int(0.36 * W):int(0.64 * W)]
    assert (torso.sum(axis=-1) < 120).mean() == 0, "no trouser pixel may show through the sweater"


def test_outerwear_lets_the_top_show_through(person):
    """An open jacket only changes its two panels; the middle stays transparent."""
    tried = paint(person, (0.30, 0.19, 0.43, 0.56), (60, 40, 30))
    tried = paint(tried, (0.57, 0.19, 0.70, 0.56), (60, 40, 30))
    layer = extract_layer(person, tried, "outerwear", pose)
    a = alpha(layer)
    assert a[int(0.35 * H), int(0.36 * W)] == 255
    assert a[int(0.35 * H), int(0.50 * W)] == 0


def test_layers_stack_in_order(person):
    top = extract_layer(person, paint(person, (0.33, 0.19, 0.67, 0.55), (200, 30, 30)), "top", pose)
    bottom = extract_layer(person, paint(person, (0.35, 0.45, 0.65, 0.95), (30, 30, 200)), "bottom", pose)
    composed = compose(person, [bottom.image, top.image]).convert("RGB")
    assert composed.getpixel((W // 2, int(0.52 * H))) == (200, 30, 30)       # top over bottom
    assert composed.getpixel((int(0.42 * W), int(0.80 * H))) == (30, 30, 200)
    assert composed.getpixel((5, 5)) == person.getpixel((5, 5))


def test_result_at_another_size_is_brought_back(person):
    tried = paint(person, (0.33, 0.19, 0.67, 0.50), (20, 40, 150)).resize((W * 3 // 4, H * 3 // 4), Image.LANCZOS)
    layer = extract_layer(person, tried, "top", pose)
    assert layer.image.size == person.size and layer.coverage > 0.08


def test_pose_validation():
    with pytest.raises(ValueError, match="missing joint"):
        BodyPose.from_dict({"nose": (0.5, 0.1)})
    upside_down = {k: (x, 1 - y) for k, (x, y) in POSE.items()}
    with pytest.raises(ValueError, match="upright"):
        BodyPose.from_dict(upside_down)
    with pytest.raises(ValueError, match="outside"):
        BodyPose.from_dict({**POSE, "nose": (0.5, 1.4)})


def test_zones_cover_the_right_part_of_the_body():
    assert zone_rows("top", pose)[0] > pose.nose_y
    assert zone_rows("bottom", pose)[0] > pose.shoulder_y
    assert zone_rows("shoes", pose)[0] > pose.knee_y
    assert zone_rows("accessories", pose) == (0.0, 1.0)
