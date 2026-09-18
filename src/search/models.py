"""Value types shared across the package.

Nothing here touches the filesystem or reads configuration; these are plain
descriptions of a grid position and of a resolved lookup result.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from search.index import Sheet


@dataclass(frozen=True, slots=True, order=True)
class Cell:
    """A position in one book's character grid, 1-based.

    A cell records *where* a character was printed, not what its image file is
    called. Turning a cell into a filename is the owning :class:`Sheet`'s job,
    because the naming convention is per-book configuration rather than a fact
    about the character.
    """

    page: int
    row: int
    col: int

    def __str__(self) -> str:
        """Compact human-readable position, e.g. ``p01 r16 c12``."""
        return f"Page: {self.page}, Row: {self.row}, Col: {self.col}"


@dataclass(frozen=True, slots=True)
class Rendering:
    """One book's version of one character, resolved to something openable.

    A character may have several renderings -- one per book that contains it --
    in which case :meth:`Library.resolve` returns them in preference order.
    """

    char: str
    sheet: Sheet
    cell: Cell

    @property
    def path(self) -> Path:
        """Absolute path to this rendering's PNG.

        The file is not guaranteed to exist; :meth:`Library.check` is what
        verifies that every indexed cell has an image behind it.
        """
        return self.sheet.path(self.cell)

    def __str__(self) -> str:
        """The bare path, so CLI output pipes into an image viewer unchanged."""
        return str(self.path)
