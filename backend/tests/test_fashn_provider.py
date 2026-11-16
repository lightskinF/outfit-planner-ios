import asyncio
import base64
import io
import json

import httpx
import pytest
from PIL import Image

from conftest import draw_person, garment_image, on_background
from tryon_backend.providers import base
from tryon_backend.providers.fashn_api import FashnAPIProvider


def data_uri(image):
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


class FakeFashn:
    """Plays FASHN's /v1/run and /v1/status as documented."""

    def __init__(self, statuses, run_response=None, run_status=200):
        self.statuses = list(statuses)
        self.run_response = run_response or {"id": "pred-1", "error": None}
        self.run_status = run_status
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/v1/run":
            return httpx.Response(self.run_status, json=self.run_response)
        assert request.url.path == "/v1/status/pred-1"
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return httpx.Response(200, json=status)


def provider(fake, **kwargs):
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake), base_url="https://api.fashn.ai",
                               headers={"Authorization": "Bearer key"})
    return FashnAPIProvider("key", client=client, poll_interval=0.0, **kwargs)


PERSON = on_background(draw_person())
RESULT = PERSON.copy()
RESULT.paste((20, 40, 150), (180, 160, 330, 380))


def run(coro):
    return asyncio.run(coro)


def test_clothing_goes_to_v16_and_the_result_is_decoded():
    fake = FakeFashn([{"id": "pred-1", "status": "in_queue", "error": None},
                      {"id": "pred-1", "status": "processing", "error": None},
                      {"id": "pred-1", "status": "completed", "output": [data_uri(RESULT)], "error": None}])
    image = run(provider(fake).try_on(PERSON, garment_image(), "outerwear", "flat-lay", seed=7))
    assert image.size == PERSON.size and image.getpixel((250, 250)) == (20, 40, 150)

    body = json.loads(fake.requests[0].content)
    assert fake.requests[0].headers["authorization"] == "Bearer key"
    assert body["model_name"] == "tryon-v1.6"
    inputs = body["inputs"]
    assert inputs["category"] == "tops" and inputs["garment_photo_type"] == "flat-lay"
    assert inputs["seed"] == 7 and inputs["return_base64"] is True and inputs["output_format"] == "png"
    assert inputs["model_image"].startswith("data:image/png;base64,")
    assert inputs["garment_image"].startswith("data:image/jpeg;base64,")
    assert len(fake.requests) == 4          # run + three polls


@pytest.mark.parametrize("category,expected", [("top", "tops"), ("bottom", "bottoms"), ("dress", "one-pieces")])
def test_category_names(category, expected):
    fake = FakeFashn([{"status": "completed", "output": [data_uri(RESULT)], "error": None}])
    run(provider(fake).try_on(PERSON, garment_image(), category))
    assert json.loads(fake.requests[0].content)["inputs"]["category"] == expected


def test_shoes_go_to_tryon_max():
    fake = FakeFashn([{"status": "completed", "output": [data_uri(RESULT)], "error": None}])
    run(provider(fake).try_on(PERSON, garment_image(), "shoes"))
    body = json.loads(fake.requests[0].content)
    assert body["model_name"] == "tryon-max"
    assert "product_image" in body["inputs"] and "garment_image" not in body["inputs"]
    assert body["inputs"]["generation_mode"] == "fast" and body["inputs"]["resolution"] == "1k"


def test_shoes_can_be_switched_off():
    p = provider(FakeFashn([]), use_max_for_accessories=False)
    assert not p.supports("shoes") and p.supports("top")
    with pytest.raises(base.UnsupportedCategory):
        run(p.try_on(PERSON, garment_image(), "shoes"))


@pytest.mark.parametrize("name,kind", [
    ("PoseError", base.PoseNotDetected),
    ("ContentModerationError", base.ContentBlocked),
    ("ImageLoadError", base.BadInputImage),
    ("UnavailableError", base.ProviderUnavailable),
    ("PipelineError", base.TryOnError),
])
def test_runtime_errors_are_translated(name, kind):
    fake = FakeFashn([{"id": "pred-1", "status": "failed", "error": {"name": name, "message": "details"}}])
    with pytest.raises(kind) as caught:
        run(provider(fake).try_on(PERSON, garment_image(), "top"))
    assert type(caught.value) is kind and caught.value.message == "details"


@pytest.mark.parametrize("status,error", [(401, "UnauthorizedAccess"), (429, "OutOfCredits"), (429, "RateLimitExceeded")])
def test_api_errors_do_not_leak_as_user_errors(status, error):
    fake = FakeFashn([], run_response={"error": error, "message": "nope"}, run_status=status)
    with pytest.raises(base.ProviderUnavailable):
        run(provider(fake).try_on(PERSON, garment_image(), "top"))


def test_timeout():
    fake = FakeFashn([{"id": "pred-1", "status": "processing", "error": None}])
    with pytest.raises(base.ProviderTimeout):
        run(provider(fake, timeout=0.05).try_on(PERSON, garment_image(), "top"))


def test_network_failure():
    def boom(request):
        raise httpx.ConnectError("down")
    with pytest.raises(base.ProviderUnavailable):
        run(provider(boom).try_on(PERSON, garment_image(), "top"))


def test_transparent_garment_is_flattened_onto_white():
    fake = FakeFashn([{"status": "completed", "output": [data_uri(RESULT)], "error": None}])
    run(provider(fake).try_on(PERSON, garment_image((10, 10, 10)), "top"))
    sent = json.loads(fake.requests[0].content)["inputs"]["garment_image"]
    image = Image.open(io.BytesIO(base64.b64decode(sent.split(",", 1)[1]))).convert("RGB")
    assert min(image.getpixel((2, 2))) > 245       # the transparent corner became white, not black
