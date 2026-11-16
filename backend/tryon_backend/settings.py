"""Configuration, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass
class Settings:
    # Which try-on model does the work: mock | fashn | local
    provider: str = field(default_factory=lambda: os.environ.get("TRYON_PROVIDER", "mock"))
    fashn_api_key: str = field(default_factory=lambda: os.environ.get("FASHN_API_KEY", ""))
    fashn_mode: str = field(default_factory=lambda: os.environ.get("FASHN_MODE", "balanced"))
    weights_dir: str = field(default_factory=lambda: os.environ.get("TRYON_WEIGHTS_DIR", "./weights"))
    provider_timeout: float = field(default_factory=lambda: float(os.environ.get("TRYON_PROVIDER_TIMEOUT", "120")))

    # Access. The app key ships inside the app and only allows registering a
    # device; the secret signs the per-device tokens and never leaves the server.
    app_key: str = field(default_factory=lambda: os.environ.get("TRYON_APP_KEY", ""))
    secret: str = field(default_factory=lambda: os.environ.get("TRYON_SECRET", ""))

    # Spending limits. One "generation" is one call to the try-on model.
    per_device_hourly: int = field(default_factory=lambda: _int("TRYON_PER_DEVICE_HOURLY", 40))
    per_device_daily: int = field(default_factory=lambda: _int("TRYON_PER_DEVICE_DAILY", 120))
    global_daily: int = field(default_factory=lambda: _int("TRYON_GLOBAL_DAILY", 2000))

    # Uploads.
    max_upload_bytes: int = field(default_factory=lambda: _int("TRYON_MAX_UPLOAD_BYTES", 12 * 1024 * 1024))
    max_avatar_side: int = field(default_factory=lambda: _int("TRYON_MAX_AVATAR_SIDE", 2304))
    max_render_garments: int = field(default_factory=lambda: _int("TRYON_MAX_RENDER_GARMENTS", 4))

    def check(self) -> None:
        if self.provider != "mock":
            if len(self.secret) < 24:
                raise RuntimeError("TRYON_SECRET must be set to a random string of 24+ characters")
            if len(self.app_key) < 16:
                raise RuntimeError("TRYON_APP_KEY must be set to a random string of 16+ characters")
        if self.provider == "fashn" and not self.fashn_api_key:
            raise RuntimeError("FASHN_API_KEY is required when TRYON_PROVIDER=fashn")
