"""Garment layers: what a try-on changed, cut out so it can be re-used.

A try-on model returns the whole avatar wearing one garment. The app does not
want the whole image: it wants only the pixels the model changed, as a
transparent layer aligned with the avatar. Layers of different garments can
then be stacked on the phone, in any combination, without another generation.

"What the model changed" is the right definition of a layer: it contains the
garment and any skin the garment newly reveals (bare legs under shorts, arms
under a T-shirt), and nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class LayerParams:
    # Difference thresholds in CIE Lab units (roughly: 2 = just noticeable).
    strong: float = 14.0      # a pixel this different certainly changed
    weak: float = 6.0         # ...and pulls in neighbours at least this different
    # All sizes are fractions of the image width, so they scale with resolution.
    denoise: float = 0.0030   # removes thin outlines caused by sub-pixel shifts
    close: float = 0.0060     # bridges small gaps inside a garment
    min_area: float = 0.0015  # (of the image area) drops specks
    max_hole: float = 0.0040  # (of the image area) fills holes up to this size
    shrink: float = 0.0040    # pulls the edge back in, undoing the blur's spread
    feather: float = 0.0015   # soft edge


@dataclass(frozen=True)
class Layer:
    image: Image.Image                 # RGBA, same size as the avatar
    bbox: tuple[int, int, int, int]    # left, top, right, bottom of the opaque area
    coverage: float                    # fraction of the image the layer covers

    @property
    def is_empty(self) -> bool:
        return self.coverage <= 0.0


def _odd(n: float) -> int:
    k = max(1, int(round(n)))
    return k if k % 2 == 1 else k + 1


def _median_1d(values: np.ndarray, window: int) -> np.ndarray:
    """Running median that ignores NaN (NaN where the whole window is NaN)."""
    half = window // 2
    padded = np.pad(values.astype(np.float64), half, constant_values=np.nan)
    windows = np.lib.stride_tricks.sliding_window_view(padded, window)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            return np.nanmedian(windows, axis=1)


def _ellipse(size: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


def difference_map(base: np.ndarray, tryon: np.ndarray) -> np.ndarray:
    """Per-pixel colour distance between two RGB uint8 images, in Lab units."""
    a = cv2.cvtColor(base, cv2.COLOR_RGB2LAB).astype(np.float32)
    b = cv2.cvtColor(tryon, cv2.COLOR_RGB2LAB).astype(np.float32)
    # OpenCV stores 8-bit L as 0..255; bring it back to 0..100.
    a[..., 0] *= 100.0 / 255.0
    b[..., 0] *= 100.0 / 255.0
    return np.sqrt(((a - b) ** 2).sum(axis=-1))


# --- Body pose -------------------------------------------------------------
#
# The app already detects the body pose when the avatar photo is taken (Apple
# Vision, on the phone) and sends the joints along. They are used for two
# things only: limiting a garment to the part of the body it can cover, and
# keeping tops solid over the torso.

REQUIRED_JOINTS = (
    "nose", "left_shoulder", "right_shoulder", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
)

# Garments that are one solid piece over the torso. Outerwear is deliberately
# not here: an open jacket must let the top underneath show through.
SOLID_CATEGORIES = {"top", "dress"}


@dataclass(frozen=True)
class BodyPose:
    """Joint positions as fractions of the image (x right, y down, 0..1)."""
    joints: dict[str, tuple[float, float]]

    @classmethod
    def from_dict(cls, data: dict) -> "BodyPose":
        joints: dict[str, tuple[float, float]] = {}
        for name in REQUIRED_JOINTS:
            if name not in data:
                raise ValueError(f"missing joint: {name}")
            x, y = data[name]
            x, y = float(x), float(y)
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError(f"joint {name} is outside the image")
            joints[name] = (x, y)
        pose = cls(joints)
        if not (pose.nose_y < pose.shoulder_y < pose.hip_y < pose.knee_y < pose.ankle_y):
            raise ValueError("joints are not in head-to-feet order: the avatar must be upright")
        return pose

    def _y(self, *names: str) -> float:
        return sum(self.joints[n][1] for n in names) / len(names)

    @property
    def nose_y(self) -> float: return self._y("nose")
    @property
    def shoulder_y(self) -> float: return self._y("left_shoulder", "right_shoulder")
    @property
    def hip_y(self) -> float: return self._y("left_hip", "right_hip")
    @property
    def knee_y(self) -> float: return self._y("left_knee", "right_knee")
    @property
    def ankle_y(self) -> float: return self._y("left_ankle", "right_ankle")

    @property
    def chin_y(self) -> float:
        # A stand-up collar reaches the jaw; nothing we dress reaches the mouth.
        return self.nose_y + 0.40 * (self.shoulder_y - self.nose_y)

    @property
    def waist_y(self) -> float:
        # High-waisted trousers stop around the navel.
        return self.shoulder_y + 0.60 * (self.hip_y - self.shoulder_y)

    @property
    def shin_y(self) -> float:
        return self.knee_y + 0.50 * (self.ankle_y - self.knee_y)

    @property
    def torso_x(self) -> tuple[float, float]:
        """Columns that are certainly torso (between the hip joints, a bit wider)."""
        xs = sorted((self.joints["left_hip"][0], self.joints["right_hip"][0]))
        pad = 0.20 * (xs[1] - xs[0])
        return xs[0] - pad, xs[1] + pad


def zone_rows(category: str, pose: BodyPose) -> tuple[float, float]:
    """Vertical span (fractions of the height) a garment category may change."""
    if category == "top":
        return pose.chin_y, pose.knee_y
    if category == "outerwear":
        return pose.chin_y, pose.ankle_y
    if category == "dress":
        return pose.chin_y, 1.0
    if category == "bottom":
        return pose.waist_y, 1.0
    if category == "shoes":
        return pose.shin_y, 1.0
    return 0.0, 1.0


def zone_mask(category: str, pose: BodyPose, size: tuple[int, int]) -> np.ndarray:
    w, h = size
    y0, y1 = zone_rows(category, pose)
    mask = np.zeros((h, w), dtype=bool)
    mask[int(round(y0 * h)):int(round(y1 * h)), :] = True
    return mask


def fill_torso(mask: np.ndarray, category: str, pose: BodyPose,
               silhouette: np.ndarray | None = None) -> np.ndarray:
    """Make a top solid from the shoulders to its hem.

    Where a new garment has the colour of what the avatar was already wearing
    (a grey sweater over a grey T-shirt) the difference is too small to detect
    and the layer gets holes. Trousers would then show through the sweater.
    A top has no holes, so:

    * every torso column is filled from the first changed pixel (the collar)
      down to the hem;
    * with a `silhouette` (the avatar cut-out), everything on the body between
      the shoulders and the hem is filled too, which covers the sides of the
      torso and the arms.
    """
    h, w = mask.shape
    x0, x1 = pose.torso_x
    c0, c1 = max(0, int(round(x0 * w))), min(w, int(round(x1 * w)))
    y0, y1 = zone_rows(category, pose)
    r0, r1 = int(round(y0 * h)), int(round(y1 * h))
    if c1 <= c0 or r1 <= r0:
        return mask

    sub = mask[r0:r1, c0:c1]
    has = sub.any(axis=0)
    if has.mean() < 0.5:        # not a garment that covers the torso
        return mask
    first = np.where(has, sub.argmax(axis=0), r1 - r0)
    last = np.where(has, sub.shape[0] - 1 - sub[::-1].argmax(axis=0), -1)

    # The hem is roughly level. Columns where it was not detected take the
    # median of their neighbours; the fill never goes below a detected hem, so
    # it closes holes without adding what is under the garment.
    last_f = _median_1d(np.where(has, last, np.nan), _odd(w * 0.10))
    last_f = np.where(has, np.maximum(last, np.minimum(last_f, last + w * 0.01)), last_f)
    last_f = np.where(np.isnan(last_f), -1, last_f)
    first_f = cv2.erode(first.astype(np.float32).reshape(1, -1), np.ones((1, _odd(w * 0.02)), np.uint8)).ravel()

    out = mask.copy()
    rows = np.arange(sub.shape[0])[:, None]
    out[r0:r1, c0:c1] |= (rows >= first_f[None, :]) & (rows <= last_f[None, :])

    if silhouette is not None:
        # Beside the torso: the body, from the shoulders down to the hem level
        # found at the nearest edge of the torso.
        shoulders = int(round(pose.shoulder_y * h))
        body = silhouette | mask
        edge = max(3, (c1 - c0) // 10)
        for cols, hem_rel in ((slice(0, c0), np.nanmedian(last_f[:edge])),
                              (slice(c1, w), np.nanmedian(last_f[-edge:]))):
            hem = r0 + int(round(float(hem_rel)))
            if hem > shoulders:
                out[shoulders:hem + 1, cols] |= body[shoulders:hem + 1, cols]
    return out


def change_mask(base: np.ndarray, tryon: np.ndarray, params: LayerParams = LayerParams(),
                zone: np.ndarray | None = None) -> np.ndarray:
    """Boolean mask of the pixels the try-on changed.

    `zone`, if given, is a boolean mask the result is limited to (for example
    "below the waist" for trousers). It protects against models that also touch
    pixels they should have left alone, such as the face.
    """
    h, w = base.shape[:2]
    diff = difference_map(base, tryon)
    diff = cv2.GaussianBlur(diff, (0, 0), sigmaX=max(0.8, w * 0.0012))

    weak = diff > params.weak
    strong = diff > params.strong
    if zone is not None:
        weak &= zone
        strong &= zone

    # Hysteresis: keep weak regions only if they contain a strong pixel.
    n, labels = cv2.connectedComponents(weak.astype(np.uint8), connectivity=8)
    if n <= 1:
        return np.zeros((h, w), dtype=bool)
    keep = np.zeros(n, dtype=bool)
    keep[np.unique(labels[strong])] = True
    keep[0] = False
    mask = keep[labels].astype(np.uint8)

    # Opening removes one-pixel outlines; closing bridges gaps in the garment.
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _ellipse(_odd(w * params.denoise)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _ellipse(_odd(w * params.close)))

    # Drop specks.
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    min_area = params.min_area * h * w
    keep = np.zeros(n, dtype=bool)
    for i in range(1, n):
        keep[i] = stats[i, cv2.CC_STAT_AREA] >= min_area
    mask = keep[labels].astype(np.uint8)

    # Fill small holes: a patch of the garment that happened to match the base
    # colour. Large holes are left alone (the gap between two legs is real).
    inv = (1 - mask).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    max_hole = params.max_hole * h * w
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        touches_border = x == 0 or y == 0 or x + bw == w or y + bh == h
        if not touches_border and area <= max_hole:
            mask[labels == i] = 1

    if zone is not None:
        mask &= zone.astype(np.uint8)
    return mask.astype(bool)


def extract_layer(base: Image.Image, tryon: Image.Image, category: str | None = None,
                  pose: BodyPose | None = None, params: LayerParams = LayerParams(),
                  zone: np.ndarray | None = None,
                  silhouette: np.ndarray | None = None) -> Layer:
    """Cut the changed pixels of `tryon` out as an RGBA layer aligned with `base`.

    With a `category` and a `pose` the layer is limited to the part of the body
    that category covers (the face is never part of a layer, so the avatar's
    face always stays the original photo) and tops are made solid.
    """
    # An avatar sent as a cut-out (RGBA) carries its own silhouette.
    if silhouette is None and base.mode == "RGBA":
        alpha = np.asarray(base.getchannel("A"))
        if alpha.min() < 250:
            silhouette = alpha > 127
    base_rgb = np.asarray(base.convert("RGB"))
    if tryon.size != base.size:
        tryon = tryon.resize(base.size, Image.LANCZOS)
    tryon_rgb = np.asarray(tryon.convert("RGB"))
    h, w = base_rgb.shape[:2]

    if zone is None and category and pose:
        zone = zone_mask(category, pose, (w, h))
    mask = change_mask(base_rgb, tryon_rgb, params, zone)
    if mask.any() and pose and category in SOLID_CATEGORIES:
        mask = fill_torso(mask, category, pose, silhouette)
    if mask.any():
        mask = cv2.erode(mask.astype(np.uint8), _ellipse(_odd(w * params.shrink))).astype(bool)
    if not mask.any():
        empty = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        return Layer(empty, (0, 0, 0, 0), 0.0)

    # Feather inwards so the soft edge never shows base pixels as a halo.
    sigma = max(0.6, w * params.feather)
    core = cv2.erode(mask.astype(np.uint8), _ellipse(_odd(sigma * 2)))
    alpha = cv2.GaussianBlur(core.astype(np.float32), (0, 0), sigmaX=sigma)
    alpha = np.clip(alpha, 0.0, 1.0) * mask  # never extend past the hard mask
    alpha8 = (alpha * 255.0 + 0.5).astype(np.uint8)

    rgba = np.dstack([tryon_rgb, alpha8])
    ys, xs = np.nonzero(alpha8)
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    return Layer(Image.fromarray(rgba, "RGBA"), bbox, float(mask.mean()))


def compose(base: Image.Image, layers: list[Image.Image]) -> Image.Image:
    """Stack layers on the avatar, first layer at the bottom.

    This is exactly what the app does on the phone (source-over drawing); it
    lives here too so the server and the tests share one definition.
    """
    out = base.convert("RGBA")
    for layer in layers:
        if layer.size != out.size:
            layer = layer.resize(out.size, Image.LANCZOS)
        out = Image.alpha_composite(out, layer.convert("RGBA"))
    return out
