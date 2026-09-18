"""Resolution of the two kinds of path this package needs.

Packaged data -- the per-book indexes under ``sheets/``, plus ``sheets.toml``
and ``overrides.json`` -- ships inside the wheel and is addressed through
:mod:`importlib.resources`.

The character images do not ship: there are roughly 7000 of them. Their
location is resolved at runtime from an explicit argument, the environment, a
user config file, or a development checkout, in that order.
"""

from __future__ import annotations

import os
import tomllib
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

PKG: Traversable = resources.files("search")
"""The installed ``search`` package directory, for reading packaged data."""

ENV_VAR = "XINGSHU_IMAGES"
"""Environment variable naming the directory that holds the image folders."""


class ImagesNotFound(RuntimeError):
    """The character image directory could not be located.

    Carries a message naming the candidates that were tried and how to point
    at the images explicitly.
    """


def package_file(*parts: str) -> Traversable:
    """Address a data file that ships inside the package.

    Returns a :class:`Traversable` rather than a :class:`Path`: in a zipped
    install there is no real file on disk, so callers should use
    ``.read_text()`` instead of :func:`open`.

    Args:
        *parts: Path components relative to the package root, e.g.
            ``("sheets", "3500-chars.json")``.
    """
    return PKG.joinpath(*parts)


def packaged_sheet_names() -> list[str]:
    """Names of the sheet indexes that ship with this package, sorted.

    Derived from the ``.json`` files under ``sheets/``. This is not how sheets
    are discovered -- ``sheets.toml`` is the registry, since an index alone
    does not say where its images live or how its cells are named. It exists so
    :meth:`Library.load` can cross-check the two and refuse an index with no
    table, or a table with no index, instead of failing later on a missing key.
    """
    return sorted(
        entry.name.removesuffix(".json")
        for entry in package_file("sheets").iterdir()
        if entry.name.endswith(".json")
    )


def images_root(override: Path | None = None) -> Path:
    """Locate the directory holding the per-book image directories.

    The directory returned is the one that *contains* ``3500-chars/`` and
    ``3000-chars/``; in a source checkout that is ``public/``.

    Resolution order, first hit wins:

    1. ``override``, as passed to ``--images-root``
    2. the ``XINGSHU_IMAGES`` environment variable
    3. ``images_root`` in the user config file, if one exists
    4. a development checkout, found by walking up from this file for a
       directory containing both ``pyproject.toml`` and ``public/``

    An explicitly named directory that does not exist is an error rather than a
    reason to keep looking: someone who passed ``--images-root`` or set
    ``XINGSHU_IMAGES`` wants that directory, and silently falling back to a
    development checkout would hide the typo. The config file and the checkout
    are softer -- they are guesses, so a miss just moves to the next candidate.

    Args:
        override: An explicit directory that wins over every other source.

    Returns:
        An absolute, user-expanded path. Its existence is checked; whether it
        actually holds the expected image folders is left to
        :meth:`Library.check`.

    Raises:
        ImagesNotFound: If no candidate produced an existing directory. An
            installed copy of the package has no images beside it, so this is
            the expected outcome there rather than a bug.
    """
    if override is not None:
        return _require_dir(override, "--images-root")

    if env := os.environ.get(ENV_VAR):
        return _require_dir(env, f"${ENV_VAR}")

    tried = [f"${ENV_VAR} (unset)"]

    config = user_config_path()
    if (configured := _configured_images_root(config)) is not None:
        candidate = Path(configured).expanduser()
        if candidate.is_dir():
            return candidate.resolve()
        tried.append(f"{config} (images_root = {configured!r}: not a directory)")
    else:
        tried.append(f"{config} (no images_root)")

    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "public").is_dir():
            return (parent / "public").resolve()
    tried.append("development checkout (no pyproject.toml beside a public/)")

    raise ImagesNotFound(
        "could not locate the character images; tried "
        + "; ".join(tried)
        + f". Pass --images-root, or set {ENV_VAR}, or put "
        + f'images_root = "/path/to/images" in {config}'
    )


def _require_dir(value: Path | str, source: str) -> Path:
    """Resolve an explicitly named directory, or say who named it.

    Raises:
        ImagesNotFound: If ``value`` is not an existing directory.
    """
    path = Path(value).expanduser()
    if not path.is_dir():
        raise ImagesNotFound(f"{source} is not a directory: {path}")
    return path.resolve()


def _configured_images_root(config: Path) -> str | None:
    """Read ``images_root`` out of the user config file, if readable.

    A missing, unreadable or malformed config file is treated as "nothing
    configured" rather than an error: it is one optional hint among several,
    and failing the whole lookup over a stray character in a file the user may
    have forgotten about would be unhelpful.
    """
    try:
        data = tomllib.loads(config.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    value = data.get("images_root")
    return value if isinstance(value, str) else None


def user_config_path() -> Path:
    """Path to the optional user config file, whether or not it exists.

    Honours ``XDG_CONFIG_HOME``, falling back to ``~/.config``.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "xingshu" / "config.toml"
