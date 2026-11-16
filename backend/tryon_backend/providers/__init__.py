from .base import CATEGORIES, TryOnError, TryOnProvider, UnsupportedCategory

__all__ = ["CATEGORIES", "TryOnError", "TryOnProvider", "UnsupportedCategory", "make_provider"]


def make_provider(settings) -> TryOnProvider:
    """Build the provider named in the settings."""
    kind = settings.provider
    if kind == "mock":
        from .mock import MockProvider
        return MockProvider()
    if kind == "fashn":
        from .fashn_api import FashnAPIProvider
        return FashnAPIProvider(settings.fashn_api_key, mode=settings.fashn_mode,
                                timeout=settings.provider_timeout)
    if kind == "local":
        from .fashn_local import FashnLocalProvider
        return FashnLocalProvider(settings.weights_dir)
    raise ValueError(f"unknown TRYON_PROVIDER: {kind!r} (use mock, fashn or local)")
