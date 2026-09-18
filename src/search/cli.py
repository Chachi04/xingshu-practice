"""Command-line entry point.

Resolves the images root once, builds a :class:`Library`, and prints. All
policy about *which* rendering wins lives in :mod:`search.index`; this module
only decides how results are formatted and what the exit code is.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from search.index import Library, Problem
from search.models import Rendering
from search.paths import ENV_VAR, ImagesNotFound

EXIT_OK = 0
"""Everything asked for was delivered."""

EXIT_INCOMPLETE = 1
"""The command ran, but found problems or could not resolve every character."""

EXIT_USAGE = 2
"""The command could not run: bad arguments, or the library would not load."""


def build_parser() -> argparse.ArgumentParser:
    """Define the command-line interface.

    Kept separate from :func:`main` so the parser can be exercised in tests
    without running a command.
    """
    parser = argparse.ArgumentParser(
        prog="search",
        description="Find the xingshu image for each character of some Chinese text.",
        epilog=(
            "Prints one absolute path per line, so output pipes straight into "
            "an image viewer:  search 你好 | xargs feh"
        ),
    )
    parser.add_argument(
        "text",
        nargs="?",
        help="characters to look up; whitespace and punctuation are ignored",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="validate every index against its grid and its images, then exit",
    )
    mode.add_argument(
        "--coverage",
        action="store_true",
        help="report how much of each book has been transcribed, then exit",
    )

    parser.add_argument(
        "--all",
        dest="show_all",
        action="store_true",
        help="print every book's version of each character, not just the best",
    )
    parser.add_argument(
        "--sheet",
        metavar="NAME",
        help="restrict the lookup to one book, ignoring overrides and order",
    )
    parser.add_argument(
        "--images-root",
        type=Path,
        metavar="DIR",
        help=f"directory holding the image folders (default: ${ENV_VAR})",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="annotate each path with its character, book and cell",
    )
    return parser


def _format(rendering: Rendering, *, verbose: bool) -> str:
    """One output line for one rendering.

    A bare path by default: anything else would have to be stripped back off
    before the output could be piped anywhere useful.
    """
    if not verbose:
        return str(rendering.path)
    return (
        f"{rendering.char}  {rendering.sheet.name}  {rendering.cell}  {rendering.path}"
    )


def _format_problem(problem: Problem) -> str:
    """One output line for one validation problem."""
    label = "error" if problem.fatal else "warning"
    where = f"{problem.sheet}: {problem.char}" if problem.char else problem.sheet
    return f"search: {label}: {where}: {problem.message}"


def cmd_search(args: argparse.Namespace, library: Library) -> int:
    """Print the best image path for each character of the query.

    With ``--all``, prints every rendering of every character instead, which is
    how you compare two books before deciding to write an override.

    Characters that resolved go to stdout, one path per line, so the output
    pipes into an image viewer. Characters that did not resolve are reported on
    stderr and make the command exit non-zero -- a partial result is still
    useful, but the caller needs to know it was partial.
    """
    missing: list[str] = []

    for char, renderings in library.lookup(args.text, args.sheet):
        if not renderings:
            missing.append(char)
            continue
        for rendering in renderings if args.show_all else renderings[:1]:
            print(_format(rendering, verbose=args.verbose))

    if missing:
        print(f"search: no rendering for {' '.join(missing)}", file=sys.stderr)
        return EXIT_INCOMPLETE
    return EXIT_OK


def cmd_check(args: argparse.Namespace, library: Library) -> int:
    """Validate the indexes against the grids and the images on disk.

    Prints one line per :class:`Problem`. Exits non-zero if any fatal problem
    was found; non-fatal ones are printed as warnings and do not fail the
    command on their own -- a suspicious transcription is worth surfacing on
    every run without breaking a script that depends on the exit code.
    """
    problems = library.check()

    for problem in problems:
        print(
            _format_problem(problem),
            file=sys.stderr if problem.fatal else sys.stdout,
        )

    errors = sum(1 for problem in problems if problem.fatal)
    warnings = len(problems) - errors
    indexed = sum(len(sheet.index) for sheet in library.sheets.values())
    summary = f"{indexed} indexed cells across {len(library.sheets)} sheets"

    if not problems:
        print(f"{summary}: no problems")
        return EXIT_OK

    print(
        f"{summary}: {errors} error(s), {warnings} warning(s)",
        file=sys.stderr if errors else sys.stdout,
    )
    return EXIT_INCOMPLETE if errors else EXIT_OK


def cmd_coverage(args: argparse.Namespace, library: Library) -> int:
    """Print transcription progress per sheet, e.g. ``960/3648 (26%)``."""
    coverage = library.coverage()
    width = max((len(name) for name in coverage), default=0)

    for name, (indexed, capacity) in coverage.items():
        percent = 100 * indexed / capacity if capacity else 0.0
        print(f"{name:<{width}}  {indexed:>5}/{capacity:<5}  ({percent:.0f}%)")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, load the library once, dispatch to a command.

    Args:
        argv: Argument list for testing; defaults to ``sys.argv[1:]``.

    Returns:
        A process exit status. Failures that are the user's to fix -- images
        not located, an unknown sheet name -- are reported as a single line on
        stderr rather than a traceback.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if not (args.check or args.coverage) and args.text is None:
        parser.error("give some text to look up, or pass --check or --coverage")

    try:
        library = Library.load(args.images_root)
    except (ImagesNotFound, ValueError) as exc:
        print(f"search: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.check:
        return cmd_check(args, library)
    if args.coverage:
        return cmd_coverage(args, library)

    try:
        return cmd_search(args, library)
    except ValueError as exc:  # an unknown --sheet, raised by Library.resolve
        print(f"search: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
