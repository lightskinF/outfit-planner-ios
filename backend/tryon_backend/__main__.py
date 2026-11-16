"""Try the pipeline on your own photos, without the app.

    python -m tryon_backend --avatar me.png --garment shirt.jpg --category top --out out/

Writes the model's raw result, the extracted layer and the avatar wearing it.
Uses the provider configured in the environment (TRYON_PROVIDER, FASHN_API_KEY...).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib

from PIL import Image

from .layers import BodyPose, compose, extract_layer
from .pipeline import open_image, parse_colour, prepare_avatar, prepare_garment
from .providers import CATEGORIES, make_provider
from .settings import Settings


def _fit_two_by_three(image: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    """Pad a photo to 2:3 so any full-body picture can be tried from the command line."""
    w, h = image.size
    target_w, target_h = (w, round(w * 3 / 2)) if w * 3 >= h * 2 else (round(h * 2 / 3), h)
    if (target_w, target_h) == (w, h):
        return image
    canvas = Image.new("RGBA" if image.mode == "RGBA" else "RGB", (target_w, target_h),
                       (0, 0, 0, 0) if image.mode == "RGBA" else background)
    canvas.paste(image, ((target_w - w) // 2, (target_h - h) // 2))
    return canvas


async def _run(args: argparse.Namespace) -> None:
    settings = Settings()
    provider = make_provider(settings)
    background = parse_colour(args.background)
    pose = BodyPose.from_dict(json.loads(pathlib.Path(args.pose).read_text())) if args.pose else None

    avatar_image = _fit_two_by_three(open_image(pathlib.Path(args.avatar).read_bytes(), "avatar"), background)
    if max(avatar_image.size) > 1536:
        avatar_image = avatar_image.resize((1024, 1536), Image.LANCZOS)
    avatar = prepare_avatar(avatar_image, background, pose)

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    avatar.image.save(out / "avatar.png")
    layers = []
    try:
        for index, (path, category) in enumerate(zip(args.garment, args.category)):
            garment = prepare_garment(open_image(pathlib.Path(path).read_bytes(), "garment"))
            print(f"{category}: asking {provider.name}...")
            tried = await provider.try_on(avatar.image, garment, category)
            tried.save(out / f"{index}_{category}_model_output.png")
            layer = extract_layer(avatar.image, tried, category, avatar.pose, silhouette=avatar.silhouette)
            layer.image.save(out / f"{index}_{category}_layer.png")
            print(f"{category}: layer covers {layer.coverage:.1%} of the image")
            layers.append((category, layer.image))
    finally:
        await provider.aclose()

    order = {"shoes": 0, "bottom": 1, "dress": 2, "top": 3, "outerwear": 4, "accessories": 5}
    stacked = compose(avatar.image, [image for _, image in sorted(layers, key=lambda l: order[l[0]])])
    stacked.convert("RGB").save(out / "outfit.png")
    print(f"written to {out}/ (outfit.png is the avatar wearing everything)")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m tryon_backend", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--avatar", required=True, help="full-body photo (a cut-out PNG works best)")
    parser.add_argument("--garment", required=True, action="append", help="photo of a garment; repeat for more")
    parser.add_argument("--category", required=True, action="append", choices=CATEGORIES,
                        help="category of each garment, in the same order")
    parser.add_argument("--pose", help="JSON file with body joints (optional)")
    parser.add_argument("--background", default="#F5E8E4")
    parser.add_argument("--out", default="tryon-out")
    args = parser.parse_args()
    if len(args.garment) != len(args.category):
        parser.error("give one --category per --garment")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
