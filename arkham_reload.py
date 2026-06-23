# -*- coding: utf-8 -*-
"""Reload local project modules in dependency order (for Jupyter kernels)."""

from __future__ import annotations

import importlib
from types import ModuleType


def reload_arkham_modules() -> tuple[ModuleType, ModuleType, ModuleType]:
    """Reload arkham_deck_options → arkham_canonical → arkham_popularity."""
    import arkham_deck_options

    importlib.reload(arkham_deck_options)

    import arkham_canonical

    importlib.reload(arkham_canonical)

    import arkham_popularity

    importlib.reload(arkham_popularity)
    return arkham_canonical, arkham_deck_options, arkham_popularity
