"""Choosing how xingshu images are drawn, including inside tmux.

Drawing is delegated to :mod:`textual_image`. With the Terminal Graphics
Protocol it places images through Unicode placeholders (U+10EEEE), which are
ordinary text to tmux: they scroll, clip and clear with the pane like anything
else, and only the image data itself travels through tmux passthrough. That is
what makes the Python side simpler than ``lua/xingshu/backend.lua``, which has
to position images absolutely and correct for pane offsets.

What textual-image cannot do on its own inside tmux is *choose* that
protocol. It asks the terminal, and the reply to a graphics query does not make
it back through tmux to the pane that asked. Worse, tmux answers the device
attributes query itself and may claim Sixel, which Kitty cannot display.
So inside tmux the decision is made here instead, from what tmux can be asked
directly -- the same inference ``backend.supported()`` makes in the Lua plugin.
"""

from __future__ import annotations

import os
import subprocess
from typing import Literal

Mode = Literal["auto", "kitty", "sixel", "halfcell", "text"]
"""How to draw images; ``text`` draws none and shows the hanzi only."""

MODES: tuple[Mode, ...] = ("auto", "kitty", "sixel", "halfcell", "text")


def in_tmux() -> bool:
    """Whether this process runs inside a tmux pane."""
    return bool(os.environ.get("TMUX"))


def _tmux_query(fmt: str) -> str | None:
    """Evaluate a ``tmux display-message`` format string, or ``None``."""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", fmt],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def tmux_kitty() -> tuple[bool, str | None]:
    """Whether tmux will forward Kitty graphics, and if not, why not.

    Checks that passthrough is enabled and that the attached client is Kitty.
    ``allow-passthrough`` may be ``on`` or ``all``; either works here.

    Returns:
        ``(True, None)`` if images can be shown, else ``(False, reason)``.
    """
    passthrough = _tmux_query("#{?#{==:#{allow-passthrough},off},off,on}")
    if passthrough is None:
        return False, "in tmux, but the tmux command is not runnable"
    if passthrough == "off":
        return False, "tmux needs: set -g allow-passthrough on"

    term = _tmux_query("#{client_termname}") or ""
    if "kitty" not in term.lower():
        return False, f"tmux is attached to {term!r}, which is not Kitty"
    return True, None


def image_class(mode: Mode = "auto") -> tuple[type | None, str | None]:
    """The textual-image widget class to draw with.

    Importing :mod:`textual_image.widget` probes the terminal, which only
    works before Textual takes over stdin, so this must be called before
    :meth:`App.run`.

    Args:
        mode: ``auto`` picks the best the terminal supports, preferring Kitty
            inside tmux when tmux can forward it; the others force a renderer.

    Returns:
        ``(cls, note)``: the widget class, or ``None`` for text only, and a
        human-readable note explaining a downgrade, if there was one.
    """
    if mode == "text":
        return None, None

    from textual_image import widget

    forced = {
        "kitty": widget.TGPImage,
        "sixel": widget.SixelImage,
        "halfcell": widget.HalfcellImage,
    }
    if mode in forced:
        return forced[mode], None

    if in_tmux():
        ok, reason = tmux_kitty()
        if ok:
            return widget.TGPImage, None
        return widget.HalfcellImage, f"{reason}; using low-resolution images"

    return widget.Image, None
