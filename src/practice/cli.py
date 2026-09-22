"""Command-line entry point.

With no subcommand, opens the practice app on the set list. The other
subcommands manage the card file without starting the app, so they can be
scripted: ``list`` prints the ids that ``edit`` and ``rm`` take.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from practice.deck import ENV_VAR, Deck, open_deck
from practice.graphics import MODES
from search.paths import ENV_VAR as IMAGES_ENV_VAR

EXIT_OK = 0
"""Everything asked for was done."""

EXIT_INCOMPLETE = 1
"""The command ran, but some of what was asked for could not be done."""

EXIT_USAGE = 2
"""The command could not run: bad arguments, or the card file would not load."""


def build_parser() -> argparse.ArgumentParser:
    """Define the command-line interface.

    Kept separate from :func:`main` so the parser can be exercised in tests
    without running a command.
    """
    parser = argparse.ArgumentParser(
        prog="practice",
        description="Practice Chinese Xingshu with flashcards.",
        epilog=(
            "Cards show a sentence in pinyin; flipping one shows it written in "
            "xingshu. Run without a command to pick a set interactively."
        ),
    )
    parser.add_argument(
        "--cards",
        type=Path,
        metavar="FILE",
        help=f"card file to use (default: ${ENV_VAR}, else ~/.local/share/xingshu/cards.json)",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    run = commands.add_parser("run", help="practise straight away, skipping set selection")
    _add_filters(run)
    run.add_argument("-r", "--random", action="store_true", help="shuffle the cards")
    # Accepted before or after ``run``. The subcommand's copies default to
    # SUPPRESS, because argparse lets a subparser's defaults overwrite values
    # already parsed by the parent.
    for sub, root_default, mode_default in (
        (parser, None, "auto"),
        (run, argparse.SUPPRESS, argparse.SUPPRESS),
    ):
        sub.add_argument(
            "--images-root",
            type=Path,
            metavar="DIR",
            default=root_default,
            help=f"directory holding the image folders (default: ${IMAGES_ENV_VAR})",
        )
        sub.add_argument(
            "--images",
            choices=MODES,
            default=mode_default,
            help="how to draw characters (default: auto)",
        )

    listing = commands.add_parser("list", aliases=["ls"], help="print cards with their ids")
    _add_filters(listing)

    add = commands.add_parser("add", help="add a card")
    add.add_argument("hanzi", help="the sentence in characters")
    add.add_argument("--hsk", type=int, required=True, help="HSK level")
    add.add_argument("--set", type=int, required=True, help="set number within the level")
    add.add_argument("--pinyin", help="tone-marked pinyin (default: generated, check it)")

    remove = commands.add_parser("rm", help="remove cards")
    remove.add_argument("ids", nargs="+", metavar="ID", help="card id or unique prefix")

    edit = commands.add_parser("edit", help="change a card")
    edit.add_argument("id", metavar="ID", help="card id or unique prefix")
    edit.add_argument("--hanzi")
    edit.add_argument("--pinyin")
    edit.add_argument("--hsk", type=int)
    edit.add_argument("--set", type=int)
    star = edit.add_mutually_exclusive_group()
    star.add_argument("--star", dest="starred", action="store_const", const=True)
    star.add_argument("--unstar", dest="starred", action="store_const", const=False)

    help_cmd = commands.add_parser("help", help="show help for practice or one command")
    help_cmd.add_argument(
        "topic",
        nargs="?",
        metavar="COMMAND",
        choices=[name for name in commands.choices if name != "help"],
        help="command to describe; omit for the overview",
    )

    return parser


def _add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hsk", type=int, help="only this HSK level")
    parser.add_argument("--set", type=int, help="only this set number")
    parser.add_argument("--starred", action="store_true", help="only starred cards")


def suggest_pinyin(hanzi: str) -> str:
    """Tone-marked pinyin for ``hanzi``, one syllable per word.

    Generated pinyin gets polyphones and neutral tones wrong often enough
    (的, 得, 儿) that it is only a starting point; ``add`` prints it so it can
    be checked and fixed with ``edit``.
    """
    from pypinyin import Style, lazy_pinyin

    return " ".join(lazy_pinyin(hanzi, style=Style.TONE, neutral_tone_with_five=False))


def cmd_list(args: argparse.Namespace, deck: Deck) -> int:
    """Print matching cards, one per line: ``id  hsk-set  hanzi  pinyin``."""
    for card in deck.select(args.hsk, args.set, args.starred):
        star = "★" if card.starred else " "
        print(f"{card.id}  {card.hsk}-{card.set:<3} {star} {card.hanzi}  {card.pinyin}")
    return EXIT_OK


def cmd_add(args: argparse.Namespace, deck: Deck) -> int:
    """Append a card and print its id, generating pinyin if none was given."""
    pinyin = args.pinyin or suggest_pinyin(args.hanzi)
    card = deck.add(args.hanzi, pinyin, args.hsk, args.set)
    deck.save()
    print(f"{card.id}  {card.hsk}-{card.set}  {card.hanzi}  {card.pinyin}")
    if args.pinyin is None:
        print("practice: pinyin was generated; check it", file=sys.stderr)
    return EXIT_OK


def cmd_rm(args: argparse.Namespace, deck: Deck) -> int:
    """Remove each named card; unknown ids are reported but do not stop the rest."""
    status = EXIT_OK
    for ref in args.ids:
        try:
            card = deck.remove(ref)
        except KeyError as exc:
            print(f"practice: {exc.args[0]}", file=sys.stderr)
            status = EXIT_INCOMPLETE
            continue
        print(f"removed {card.id}  {card.hanzi}")
    deck.save()
    return status


def cmd_edit(args: argparse.Namespace, deck: Deck) -> int:
    """Change the given fields of one card and print the result."""
    card = deck.edit(
        args.id,
        hanzi=args.hanzi,
        pinyin=args.pinyin,
        hsk=args.hsk,
        set=args.set,
        starred=args.starred,
    )
    deck.save()
    star = "★" if card.starred else " "
    print(f"{card.id}  {card.hsk}-{card.set:<3} {star} {card.hanzi}  {card.pinyin}")
    return EXIT_OK


def cmd_practice(args: argparse.Namespace, deck: Deck) -> int:
    """Start the app, on the set list or, for ``run``, straight on the cards."""
    from practice.graphics import image_class
    from search import ImagesNotFound, Library

    start = None
    title = ""
    if args.command == "run":
        start = deck.select(args.hsk, args.set, args.starred)
        if not start:
            print("practice: no cards match", file=sys.stderr)
            return EXIT_INCOMPLETE
        parts = [f"HSK {args.hsk}" if args.hsk else "", f"Set {args.set}" if args.set else ""]
        title = " · ".join(p for p in parts if p) or "All cards"
        if args.starred:
            title += " ★"

    notes: list[str] = []
    try:
        library = Library.load(args.images_root)
    except (ImagesNotFound, ValueError) as exc:
        library = None
        notes.append(f"xingshu images unavailable: {exc}")

    # Must run before the app starts: it probes the terminal.
    image_cls, note = image_class(args.images)
    if note:
        notes.append(note)

    from practice.tui import PracticeApp

    PracticeApp(
        deck,
        library,
        image_cls,
        start=start,
        title=title,
        shuffle=getattr(args, "random", False),
        notice="\n".join(notes) or None,
    ).run()
    return EXIT_OK


COMMANDS = {
    "list": cmd_list,
    "ls": cmd_list,
    "add": cmd_add,
    "rm": cmd_rm,
    "edit": cmd_edit,
}


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, load the card file, dispatch to a command.

    Args:
        argv: Argument list for testing; defaults to ``sys.argv[1:]``.

    Returns:
        A process exit status. Problems that are the user's to fix -- a
        malformed card file, an unknown or ambiguous id -- are reported as a
        single line on stderr rather than a traceback.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "help":
        # Reuse ``--help`` itself rather than imitating it: same text, and it
        # exits the same way, before any card file is touched.
        parser.parse_args([args.topic, "--help"] if args.topic else ["--help"])

    try:
        deck = open_deck(args.cards)
    except (OSError, ValueError) as exc:
        print(f"practice: {exc}", file=sys.stderr)
        return EXIT_USAGE

    command = COMMANDS.get(args.command, cmd_practice)
    try:
        return command(args, deck)
    except (KeyError, ValueError) as exc:
        message = exc.args[0] if isinstance(exc, KeyError) else exc
        print(f"practice: {message}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
