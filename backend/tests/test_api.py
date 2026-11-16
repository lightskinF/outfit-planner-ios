import base64
import io
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import POSE, draw_person, garment_image, on_background, png_bytes
from tryon_backend.app import create_app
from tryon_backend.providers.base import PoseNotDetected
from tryon_backend.providers.mock import MockProvider
from tryon_backend.settings import Settings

AVATAR = png_bytes(draw_person())
GARMENT = png_bytes(garment_image((30, 60, 160)))


def make(provider=None, **overrides):
    settings = Settings(provider="mock", app_key="app-key-for-tests-0001", secret="x" * 32)
    for key, value in overrides.items():
        setattr(settings, key, value)
    return TestClient(create_app(settings, provider or MockProvider()))


def token(client):
    response = client.post("/v1/devices", headers={"X-App-Key": "app-key-for-tests-0001"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


def layer_request(client, headers, **form):
    data = {"category": "top", "pose": json.dumps(POSE), **form}
    return client.post("/v1/layers", headers=headers, data=data,
                       files={"avatar": ("a.png", AVATAR, "image/png"), "garment": ("g.png", GARMENT, "image/png")})


def test_health_reports_provider_and_categories():
    body = make().get("/healthz").json()
    assert body["status"] == "ok" and body["provider"] == "mock" and "top" in body["categories"]


def test_registration_needs_the_app_key():
    client = make()
    assert client.post("/v1/devices").status_code == 401
    assert client.post("/v1/devices", headers={"X-App-Key": "wrong"}).status_code == 401


def test_layers_need_a_token():
    client = make()
    assert layer_request(client, {}).status_code == 401
    assert layer_request(client, {"Authorization": "Bearer made.up"}).status_code == 401


def test_layer_roundtrip():
    client = make()
    response = layer_request(client, token(client))
    assert response.status_code == 200, response.text
    body = response.json()
    layer = Image.open(io.BytesIO(base64.b64decode(body["layer"])))
    assert layer.mode == "RGBA" and layer.size == (body["width"], body["height"]) == (512, 768)
    alpha = np.asarray(layer.getchannel("A"))
    assert alpha[int(0.35 * 768), 256] == 255            # the mock paints the chest
    assert alpha[int(0.09 * 768), 256] == 0              # never the face
    assert tuple(layer.getpixel((256, int(0.35 * 768)))[:3]) == (30, 60, 160)
    l, t, r, b = body["bbox"]
    assert 0 <= l < r <= 512 and 0 <= t < b <= 768
    assert body["remaining"]["hour"] == 39


def test_layer_is_drawn_on_the_requested_background():
    """Where a garment uncovers background, the layer carries the app's canvas colour."""
    class Sleeveless(MockProvider):
        async def try_on(self, person, garment, category, garment_photo_type="auto", seed=42):
            out = person.copy()                           # the left arm disappears
            out.paste(person.getpixel((2, 2)), (int(0.25 * 512), int(0.20 * 768), int(0.34 * 512), int(0.57 * 768)))
            return out

    client = make(Sleeveless())
    body = layer_request(client, token(client), background="#102030").json()
    layer = Image.open(io.BytesIO(base64.b64decode(body["layer"])))
    assert layer.getpixel((int(0.295 * 512), int(0.40 * 768))) == (16, 32, 48, 255)


def test_avatar_must_be_two_by_three():
    client = make()
    square = png_bytes(on_background(draw_person(size=(512, 512))))
    response = client.post("/v1/layers", headers=token(client), data={"category": "top"},
                           files={"avatar": ("a.png", square, "image/png"), "garment": ("g.png", GARMENT, "image/png")})
    assert response.status_code == 422 and response.json()["error"]["code"] == "bad_image"


@pytest.mark.parametrize("form,code", [
    ({"category": "hat"}, "bad_category"),
    ({"pose": "{not json"}, "bad_pose"),
    ({"pose": json.dumps({"nose": [0.5, 0.1]})}, "bad_pose"),
    ({"background": "pink"}, "bad_image"),
    ({"garment_photo_type": "selfie"}, "bad_photo_type"),
])
def test_bad_form_fields(form, code):
    client = make()
    response = layer_request(client, token(client), **form)
    assert response.status_code == 422 and response.json()["error"]["code"] == code


def test_unreadable_upload():
    client = make()
    response = client.post("/v1/layers", headers=token(client), data={"category": "top"},
                           files={"avatar": ("a.png", b"not an image", "image/png"), "garment": ("g.png", GARMENT, "image/png")})
    assert response.status_code == 422 and response.json()["error"]["code"] == "bad_image"


def test_upload_size_limit():
    client = make(max_upload_bytes=1000)
    response = layer_request(client, token(client))
    assert response.status_code == 413


def test_provider_errors_reach_the_app_with_their_code():
    class NoPose(MockProvider):
        async def try_on(self, *args, **kwargs):
            raise PoseNotDetected("no body pose was detected")
    client = make(NoPose())
    headers = token(client)
    response = layer_request(client, headers)
    assert response.status_code == 422 and response.json()["error"]["code"] == "pose_not_detected"
    # a failed generation is not counted against the device
    assert client.get("/v1/limits", headers=headers).json()["remaining"]["hour"] == 40


def test_unchanged_avatar_is_an_error_not_an_empty_layer():
    class Lazy(MockProvider):
        async def try_on(self, person, *args, **kwargs):
            return person.copy()
    client = make(Lazy())
    response = layer_request(client, token(client))
    assert response.status_code == 422 and response.json()["error"]["code"] == "nothing_changed"


def test_unsupported_category():
    class TopsOnly(MockProvider):
        def supports(self, category): return category == "top"
    client = make(TopsOnly())
    response = layer_request(client, token(client), category="shoes")
    assert response.status_code == 422 and response.json()["error"]["code"] == "category_not_supported"


def test_rate_limit():
    client = make(per_device_hourly=2)
    headers = token(client)
    assert layer_request(client, headers).status_code == 200
    assert layer_request(client, headers).status_code == 200
    response = layer_request(client, headers)
    assert response.status_code == 429 and response.json()["error"]["code"] == "limit_reached"
    assert int(response.headers["Retry-After"]) > 0
    assert layer_request(client, token(client)).status_code == 200      # another device still works


def test_render_dresses_the_avatar_in_order():
    client = make()
    headers = token(client)
    files = [("avatar", ("a.png", AVATAR, "image/png")),
             ("garments", ("top.png", png_bytes(garment_image((200, 30, 30))), "image/png")),
             ("garments", ("bottom.png", png_bytes(garment_image((30, 30, 200))), "image/png"))]
    response = client.post("/v1/renders", headers=headers, files=files,
                           data={"categories": json.dumps(["top", "bottom"]), "pose": json.dumps(POSE)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["generations"] == 2 and body["remaining"]["hour"] == 38
    image = Image.open(io.BytesIO(base64.b64decode(body["image"]))).convert("RGB")
    assert image.size == (512, 768)
    r, g, b = image.getpixel((256, int(0.35 * 768)))
    assert r > 150 and b < 90                               # top on the chest
    r, g, b = image.getpixel((int(0.42 * 512), int(0.80 * 768)))
    assert b > 150 and r < 90                               # bottom on the legs
    # where both overlap, the top (generated last) wins
    r, g, b = image.getpixel((256, int(0.51 * 768)))
    assert r > 150 and b < 90


def test_render_validates_its_lists():
    client = make()
    headers = token(client)
    files = [("avatar", ("a.png", AVATAR, "image/png")), ("garments", ("g.png", GARMENT, "image/png"))]
    for categories in ('["top","bottom"]', '"top"', "[]"):
        response = client.post("/v1/renders", headers=headers, files=files, data={"categories": categories})
        assert response.status_code == 422, categories
