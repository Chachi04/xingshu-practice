"""Loading the packaged indexes and answering lookups.

Three kinds of data come together here, deliberately kept in separate files:

``sheets/<name>.json``
    Facts. A mechanical transcription of one book's grid, character to cell.
``sheets.toml``
    Configuration. Where each book's images live, how its cells are named,
    how big its grid is, and the default order to prefer books in.
``overrides.json``
    Taste. The characters for which the default order is wrong.

A transcription can be machine-checked against its grid; an opinion about which
rendering looks better cannot. Keeping them apart is what makes
:meth:`Library.check` possible.
"""

from __future__ import annotations

import functools
import json
import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from search.models import Cell, Rendering
from search.paths import images_root as resolve_images_root
from search.paths import package_file, packaged_sheet_names

_FIELDS = ("page", "row", "col")
"""The placeholders a sheet's ``pattern`` must contain, exactly once each."""

_PLACEHOLDER = re.compile(r"\{(\w+)(?::[^}]*)?\}")


def _is_cjk_ideograph(char: str) -> bool:
    """Whether ``char`` is in the CJK Unified Ideographs block (U+4E00-U+9FFF).

    Deliberately narrow. Both books teach common simplified characters, which
    all live in this block, so anything outside it is worth a second look --
    typically a visually identical character borrowed from Bopomofo, Kangxi
    radicals or the compatibility blocks, which no lookup will ever match.
    """
    return "\u4e00" <= char <= "\u9fff"


def _describe(char: str) -> str:
    """Render a character with its code point, for a problem report."""
    return f"{char!r} (U+{ord(char):04X})" if len(char) == 1 else repr(char)


def _cell_from_match(match: re.Match[str]) -> Cell:
    """Build a cell from a match produced by :func:`_pattern_to_regex`."""
    return Cell(page=int(match["page"]), row=int(match["row"]), col=int(match["col"]))


@functools.cache
def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a sheet's ``pattern`` into a regex that reads it back.

    ``sheets.toml`` declares the naming convention once, as a
    :meth:`str.format` template such as
    ``page{page:02d}_row{row:02d}_col{col:02d}.png``. That template is used in
    both directions -- :meth:`Sheet.path` formats a cell into a filename,
    :meth:`Sheet.parse_cell` matches a filename back into a cell -- so the
    convention cannot drift between reading and writing.

    Literal text is escaped; each ``{field:...}`` placeholder becomes a named
    group matching one or more digits. Results are cached per pattern.

    Raises:
        ValueError: If the template does not contain each of ``page``, ``row``
            and ``col`` exactly once, or contains any other placeholder.
    """
    parts: list[str] = []
    seen: set[str] = set()
    pos = 0

    for match in _PLACEHOLDER.finditer(pattern):
        field = match[1]
        if field not in _FIELDS:
            raise ValueError(
                f"pattern {pattern!r}: unknown placeholder {{{field}}}; "
                f"expected one of {', '.join(_FIELDS)}"
            )
        if field in seen:
            raise ValueError(f"pattern {pattern!r}: {{{field}}} appears twice")
        seen.add(field)
        parts.append(re.escape(pattern[pos : match.start()]))
        parts.append(rf"(?P<{field}>\d+)")
        pos = match.end()

    if missing := [f for f in _FIELDS if f not in seen]:
        raise ValueError(
            f"pattern {pattern!r}: missing placeholder(s) "
            f"{', '.join('{' + f + '}' for f in missing)}"
        )

    parts.append(re.escape(pattern[pos:]))
    return re.compile("".join(parts))


@dataclass(frozen=True, slots=True)
class Problem:
    """One fault found by :meth:`Library.check`.

    Attributes:
        sheet: Name of the sheet the fault belongs to.
        char: The character at fault, or ``None`` for whole-sheet problems.
        message: What is wrong, phrased for a terminal.
        fatal: ``True`` for a broken index, ``False`` for something merely
            suspicious -- a character transcribed twice in one 1:1 grid is
            almost always a misread, but it is not structurally invalid.
    """

    sheet: str
    char: str | None
    message: str
    fatal: bool = True


@dataclass(frozen=True, slots=True)
class Sheet:
    """One source book: its grid, its images, and its transcription.

    Attributes:
        name: Key used in configuration and on the command line,
            e.g. ``"3500-chars"``.
        title: The book's own title, for display.
        dir: Image directory name, relative to the images root.
        pattern: :meth:`str.format` template turning a cell into a filename.
        pages, rows, cols: Grid dimensions, used to reject impossible cells.
        index: The transcription, character to cell.
        images_root: Injected at load time; see :func:`search.paths.images_root`.
        duplicates: Characters the raw JSON listed more than once. Recorded at
            parse time because ``index`` is a mapping -- by the time it exists
            the repeat has already been collapsed and is undetectable.
    """

    name: str
    title: str
    dir: str
    pattern: str
    pages: int
    rows: int
    cols: int
    index: dict[str, Cell]
    images_root: Path
    duplicates: tuple[str, ...] = ()

    @classmethod
    def load(cls, name: str, config: dict, images_root: Path) -> Sheet:
        """Build a sheet from its ``sheets.toml`` entry and packaged index.

        Args:
            name: The sheet's key, which is also its index filename stem.
            config: The ``[sheets.<name>]`` table from ``sheets.toml``.
            images_root: Directory containing this sheet's ``dir``.

        Parses every index value through the sheet's own ``pattern``, so a
        mismatch between configuration and transcription surfaces here rather
        than as a missing file much later.

        Raises:
            ValueError: If the ``sheets.toml`` entry is missing a key, or the
                index contains a cell name that does not match ``pattern``.
        """
        try:
            title = config["title"]
            directory = config["dir"]
            pattern = config["pattern"]
            pages = int(config["pages"])
            rows = int(config["rows"])
            cols = int(config["cols"])
        except KeyError as exc:
            raise ValueError(
                f"sheet {name!r}: missing key {exc.args[0]!r} in sheets.toml"
            ) from exc

        regex = _pattern_to_regex(pattern)
        repeated: list[str] = []

        def keep_last(pairs: list[tuple[str, str]]) -> dict[str, str]:
            """Collapse duplicate keys the way :func:`json.loads` would, noting them.

            A character listed twice is almost always a pair of misread
            lookalikes, but that is a judgement for :meth:`Library.check` to
            report rather than a reason to refuse the file here.
            """
            out: dict[str, str] = {}
            for key, value in pairs:
                key = unicodedata.normalize("NFC", key)
                if key in out:
                    repeated.append(key)
                out[key] = value
            return out

        raw: dict[str, str] = json.loads(
            package_file("sheets", f"{name}.json").read_text("utf-8"),
            object_pairs_hook=keep_last,
        )

        index: dict[str, Cell] = {}
        for char, filename in raw.items():
            match = regex.fullmatch(filename)
            if match is None:
                raise ValueError(
                    f"sheet {name!r}: {char!r} -> {filename!r} does not match "
                    f"pattern {pattern!r}"
                )
            index[char] = _cell_from_match(match)

        return cls(
            name=name,
            title=title,
            dir=directory,
            pattern=pattern,
            pages=pages,
            rows=rows,
            cols=cols,
            index=index,
            images_root=images_root,
            duplicates=tuple(dict.fromkeys(repeated)),
        )

    def get(self, char: str) -> Cell | None:
        """The cell holding ``char`` in this book, or ``None`` if not indexed.

        ``None`` covers both "this book does not contain the character" and
        "that page has not been transcribed yet"; the two are indistinguishable
        from the index alone and callers treat them the same way.
        """
        return self.index.get(unicodedata.normalize("NFC", char))

    def path(self, cell: Cell) -> Path:
        """Absolute path to a cell's image, via this sheet's naming pattern.

        The only place a cell becomes a filename. Inverse of
        :meth:`parse_cell`; both go through ``pattern``, so re-splitting the
        PDFs under a different convention means editing that one line of
        ``sheets.toml`` rather than the index.
        """
        return (
            self.images_root
            / self.dir
            / self.pattern.format(page=cell.page, row=cell.row, col=cell.col)
        )

    def parse_cell(self, filename: str) -> Cell:
        """Parse an index value such as ``page01_row16_col12.png`` into a cell.

        Index values are stored as filenames because that is what is
        convenient to type and to grep while transcribing. They are parsed
        once, at load time, so no other code does string surgery on a filename.

        The convention comes from this sheet's ``pattern``, not from a rule
        baked into the loader -- a book split under a different scheme parses
        correctly as long as its ``sheets.toml`` entry says so.

        Raises:
            ValueError: If the name does not match this sheet's pattern.
        """
        match = _pattern_to_regex(self.pattern).fullmatch(filename)
        if match is None:
            raise ValueError(
                f"sheet {self.name!r}: {filename!r} does not match pattern "
                f"{self.pattern!r}"
            )
        return _cell_from_match(match)

    def holds(self, cell: Cell) -> bool:
        """Whether ``cell`` falls inside this book's declared grid."""
        return (
            1 <= cell.page <= self.pages
            and 1 <= cell.row <= self.rows
            and 1 <= cell.col <= self.cols
        )

    def capacity(self) -> int:
        """Total number of cells in the book: pages x rows x cols."""
        return self.pages * self.rows * self.cols

    def coverage(self) -> tuple[int, int]:
        """Transcription progress as ``(indexed, capacity)``."""
        return len(self.index), self.capacity()


@dataclass(frozen=True, slots=True)
class Library:
    """Every book, plus the policy for choosing between them.

    Attributes:
        sheets: Loaded sheets by name.
        default_order: Sheet names, most preferred first, from ``sheets.toml``.
        overrides: Characters mapped to the sheet that should win for them.
    """

    sheets: dict[str, Sheet]
    default_order: list[str]
    overrides: dict[str, str]

    @classmethod
    def load(cls, images_root: Path | None = None) -> Library:
        """Read ``sheets.toml``, every packaged index, and ``overrides.json``.

        Called once per process. Every subsequent lookup is served from memory.

        Args:
            images_root: Where the image directories live. Always passed
                through :func:`search.paths.images_root`, so an explicitly
                named directory is validated rather than trusted -- otherwise
                ``--images-root /typo`` would yield paths that cannot exist.

        ``default_order`` is optional. When absent it is the order the sheets
        are declared in; when present it may name a subset, in which case the
        omitted sheets are still loaded and reachable through ``--sheet`` but
        are never chosen on their own.

        ``overrides.json`` is optional and an absent file means no overrides --
        it holds preferences, and having none is a normal state.

        Raises:
            ImagesNotFound: If the images could not be located.
            ValueError: If ``sheets.toml`` and ``sheets/`` disagree about which
                books exist, or if ``default_order`` or ``overrides.json``
                names a sheet that was not declared.
        """
        root = resolve_images_root(images_root)

        config = tomllib.loads(package_file("sheets.toml").read_text("utf-8"))
        tables: dict[str, dict] = config.get("sheets", {})
        if not tables:
            raise ValueError("sheets.toml declares no [sheets.*] tables")

        packaged = set(packaged_sheet_names())
        if orphans := sorted(packaged - set(tables)):
            raise ValueError(
                "sheets/ holds "
                + ", ".join(f"{o}.json" for o in orphans)
                + " with no matching [sheets.*] table in sheets.toml"
            )
        if undeclared := sorted(set(tables) - packaged):
            raise ValueError(
                "sheets.toml declares "
                + ", ".join(undeclared)
                + " but sheets/ has no matching .json"
            )

        sheets = {name: Sheet.load(name, table, root) for name, table in tables.items()}

        order: list[str] = config.get("default_order", list(tables))
        if unknown := [name for name in order if name not in sheets]:
            raise ValueError(
                "sheets.toml: default_order names undeclared sheet(s) "
                + ", ".join(unknown)
            )

        overrides: dict[str, str] = {}
        source = package_file("overrides.json")
        if source.is_file():
            for char, sheet_name in json.loads(source.read_text("utf-8")).items():
                if sheet_name not in sheets:
                    raise ValueError(
                        f"overrides.json: {char} names undeclared sheet {sheet_name!r}"
                    )
                overrides[unicodedata.normalize("NFC", char)] = sheet_name

        return cls(sheets=sheets, default_order=order, overrides=overrides)

    def resolve(self, char: str, sheet: str | None = None) -> list[Rendering]:
        """Every available rendering of one character, best first.

        Preference order is ``overrides[char]`` if present, then
        ``default_order``; sheets that do not hold the character are skipped.
        An override naming a sheet that lacks the character is therefore a
        no-op rather than an error, which keeps ``overrides.json`` usable while
        a book is still being transcribed.

        Args:
            char: A single character. Normalised to NFC before lookup.
            sheet: Restrict the result to this one sheet, ignoring both the
                overrides and the default order.

        Returns:
            Possibly empty: an unindexed character is a normal outcome here,
            not an exception.

        Raises:
            ValueError: If ``sheet`` names a book that was not declared.
        """
        char = unicodedata.normalize("NFC", char)

        if sheet is not None:
            if sheet not in self.sheets:
                raise ValueError(
                    f"unknown sheet {sheet!r}; declared sheets are "
                    + ", ".join(sorted(self.sheets))
                )
            order = [sheet]
        elif (preferred := self.overrides.get(char)) is not None:
            order = [preferred, *self.default_order]
        else:
            order = list(self.default_order)

        return [
            Rendering(char=char, sheet=self.sheets[name], cell=cell)
            for name in dict.fromkeys(order)
            if (cell := self.sheets[name].get(char)) is not None
        ]

    def lookup(
        self, text: str, sheet: str | None = None
    ) -> list[tuple[str, list[Rendering]]]:
        """Resolve every character of ``text``, preserving input order.

        One entry per character, so the caller can see exactly which ones came
        back empty rather than being told only that something was missing.

        Args:
            text: Arbitrary input. Whitespace and punctuation are dropped;
                remaining characters are resolved whether or not they are Han.
            sheet: Passed through to :meth:`resolve`.

        Raises:
            ValueError: If ``sheet`` names a book that was not declared.
        """
        return [
            (char, self.resolve(char, sheet))
            for char in unicodedata.normalize("NFC", text)
            if not char.isspace() and not unicodedata.category(char).startswith("P")
        ]

    def check(self) -> list[Problem]:
        """Validate every sheet against its grid and its images.

        The only code that needs the indexes and the image directory at the
        same time. Checks, per sheet:

        - every cell lies within the declared ``pages x rows x cols``
        - every cell resolves to a file that exists
        - no two characters claim the same cell
        - no character appears twice (non-fatal: in a 1:1 grid this is
          almost always a pair of misread lookalikes)
        - every key is a single CJK unified ideograph

        Returns:
            Problems in report order, fatal ones first. Empty means clean.
        """
        problems: list[Problem] = []

        for name, sheet in self.sheets.items():
            directory = sheet.images_root / sheet.dir
            if not directory.is_dir():
                problems.append(
                    Problem(
                        sheet=name,
                        char=None,
                        message=f"image directory not found: {directory}",
                    )
                )

            claimed: dict[Cell, list[str]] = {}
            for char, cell in sheet.index.items():
                claimed.setdefault(cell, []).append(char)

                if not sheet.holds(cell):
                    problems.append(
                        Problem(
                            sheet=name,
                            char=char,
                            message=(
                                f"{cell} is outside the declared grid "
                                f"({sheet.pages} x {sheet.rows} x {sheet.cols})"
                            ),
                        )
                    )
                elif directory.is_dir() and not sheet.path(cell).is_file():
                    problems.append(
                        Problem(
                            sheet=name,
                            char=char,
                            message=f"no image at {sheet.path(cell).name}",
                        )
                    )

                if len(char) != 1 or not _is_cjk_ideograph(char):
                    problems.append(
                        Problem(
                            sheet=name,
                            char=char,
                            message=(
                                f"{_describe(char)} is not a single CJK unified "
                                "ideograph; likely a lookalike from another block"
                            ),
                            fatal=False,
                        )
                    )

            for cell, chars in claimed.items():
                if len(chars) > 1:
                    problems.append(
                        Problem(
                            sheet=name,
                            char=chars[0],
                            message=f"{cell} is claimed by {' and '.join(chars)}",
                        )
                    )

            for char in sheet.duplicates:
                problems.append(
                    Problem(
                        sheet=name,
                        char=char,
                        message=(
                            "listed more than once; in a one-to-one grid this is "
                            "almost always a misread lookalike"
                        ),
                        fatal=False,
                    )
                )

        problems.sort(key=lambda p: (not p.fatal, p.sheet, p.char or ""))
        return problems

    def coverage(self) -> dict[str, tuple[int, int]]:
        """Per-sheet transcription progress, keyed by sheet name."""
        return {name: sheet.coverage() for name, sheet in self.sheets.items()}
