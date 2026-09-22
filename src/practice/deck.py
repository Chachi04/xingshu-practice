"""The card collection: loading, saving and editing it.

Cards are stored as one flat list rather than nested by level and set. Sets
are derived by grouping on ``(hsk, set)``, so moving a card to another set is a
one-field edit and adding or removing one never has to find the right branch
of a tree first. Every card carries a stable ``id`` that the command line
addresses it by; positions shift as cards come and go, ids do not.

The file shipped inside the package is only a seed. The working copy lives in
the user's data directory, because an installed package directory is not
somewhere a program should be writing to.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import unicodedata
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path

from practice.migrate import migrate

VERSION = 1
"""Schema version written to, and required of, every card file."""

ENV_VAR = "XINGSHU_CARDS"
"""Environment variable naming the card file to use."""

SetKey = tuple[int, int]
"""A set's address: ``(hsk level, set number)``."""


def new_id() -> str:
    """A fresh card id: eight hex digits, short enough to type."""
    return secrets.token_hex(4)


@dataclass(slots=True)
class Card:
    """One flashcard: pinyin on the front, hanzi on the back.

    Attributes:
        id: Stable identifier, unique within a deck.
        hanzi: The sentence in characters; what the xingshu images are of.
        pinyin: The sentence in tone-marked pinyin; what is shown first.
        hsk: HSK level the card belongs to.
        set: Set number within that level.
        starred: Marked by the user for extra practice.
    """

    hanzi: str
    pinyin: str
    hsk: int
    set: int
    starred: bool = False
    id: str = field(default_factory=new_id)

    @property
    def key(self) -> SetKey:
        """The set this card belongs to."""
        return (self.hsk, self.set)

    @classmethod
    def from_dict(cls, raw: dict) -> Card:
        """Build a card from one entry of the ``cards`` list.

        Raises:
            ValueError: If a required field is missing or has the wrong type.
        """
        try:
            card = cls(
                id=str(raw["id"]),
                hanzi=unicodedata.normalize("NFC", str(raw["hanzi"])),
                pinyin=str(raw["pinyin"]),
                hsk=int(raw["hsk"]),
                set=int(raw["set"]),
                starred=bool(raw.get("starred", False)),
            )
        except KeyError as exc:
            raise ValueError(f"card {raw!r}: missing field {exc.args[0]!r}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"card {raw!r}: {exc}") from exc
        return card

    def to_dict(self) -> dict:
        """The card as it is written to disk, id first for readability."""
        data = asdict(self)
        return {"id": data.pop("id"), **data}


class Deck:
    """Every card, plus the file they were read from.

    Mutating methods change memory only; call :meth:`save` to persist. The
    command line saves once per invocation and the practice screen saves on
    every star toggle.
    """

    def __init__(self, cards: list[Card], path: Path | None = None) -> None:
        self.cards = cards
        self.path = path

    @classmethod
    def load(cls, path: Path) -> Deck:
        """Read a card file, upgrading the pre-versioned nested format.

        A file in the old ``[{"HSK Level": …, "Sets": […]}]`` shape is
        converted in memory and written back as version 1 on the next save.

        Raises:
            ValueError: If the file is not valid JSON, is from a newer
                version, or holds a malformed card or a duplicate id.
        """
        try:
            raw = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: not valid JSON: {exc}") from exc

        raw = migrate(raw)
        if raw.get("version") != VERSION:
            raise ValueError(
                f"{path}: unsupported version {raw.get('version')!r}; "
                f"this program reads version {VERSION}"
            )

        cards = [Card.from_dict(entry) for entry in raw.get("cards", [])]
        seen: set[str] = set()
        for card in cards:
            if card.id in seen:
                raise ValueError(f"{path}: duplicate card id {card.id!r}")
            seen.add(card.id)
        return cls(cards, path)

    def save(self, path: Path | None = None) -> None:
        """Write the deck atomically.

        Writes a sibling temporary file and renames it over the target, so an
        interrupted save leaves the previous version intact rather than half a
        file.

        Args:
            path: Where to write; defaults to the file the deck was loaded from.
        """
        target = path or self.path
        if target is None:
            raise ValueError("deck has no path to save to")

        data = {"version": VERSION, "cards": [card.to_dict() for card in self.cards]}
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"

        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self.path = target

    def sets(self) -> dict[SetKey, list[Card]]:
        """Cards grouped by set, sets sorted, cards in file order."""
        grouped: dict[SetKey, list[Card]] = {}
        for card in self.cards:
            grouped.setdefault(card.key, []).append(card)
        return dict(sorted(grouped.items()))

    def select(
        self,
        hsk: int | None = None,
        set: int | None = None,
        starred: bool = False,
    ) -> list[Card]:
        """Cards matching every given filter, in file order.

        Args:
            hsk: Only this level.
            set: Only this set number (within ``hsk`` if that is given too).
            starred: Only starred cards.
        """
        return [
            card
            for card in self.cards
            if (hsk is None or card.hsk == hsk)
            and (set is None or card.set == set)
            and (not starred or card.starred)
        ]

    def get(self, ref: str) -> Card:
        """Find a card by id or unambiguous id prefix, the way git does.

        Raises:
            KeyError: If nothing matches, or the prefix matches several cards.
        """
        if exact := [card for card in self.cards if card.id == ref]:
            return exact[0]
        matches = [card for card in self.cards if card.id.startswith(ref)]
        if not matches:
            raise KeyError(f"no card with id {ref!r}")
        if len(matches) > 1:
            raise KeyError(
                f"id {ref!r} is ambiguous: "
                + ", ".join(card.id for card in matches)
            )
        return matches[0]

    def add(self, hanzi: str, pinyin: str, hsk: int, set: int) -> Card:
        """Append a new card to the end of its set and return it."""
        ids = {card.id for card in self.cards}
        card_id = new_id()
        while card_id in ids:
            card_id = new_id()

        card = Card(
            id=card_id,
            hanzi=unicodedata.normalize("NFC", hanzi),
            pinyin=pinyin,
            hsk=hsk,
            set=set,
        )
        self.cards.append(card)
        return card

    def remove(self, ref: str) -> Card:
        """Remove the card ``ref`` names and return it.

        Raises:
            KeyError: As :meth:`get`.
        """
        card = self.get(ref)
        self.cards.remove(card)
        return card

    def edit(self, ref: str, **changes: object) -> Card:
        """Change fields of one card in place and return it.

        Args:
            ref: Id or id prefix, as :meth:`get`.
            **changes: Any of ``hanzi``, ``pinyin``, ``hsk``, ``set``,
                ``starred``; ``None`` values are ignored so callers can pass
                unset options straight through.

        Raises:
            KeyError: As :meth:`get`.
            ValueError: If a field name is not editable.
        """
        editable = {"hanzi", "pinyin", "hsk", "set", "starred"}
        if unknown := sorted(set(changes) - editable):
            raise ValueError(f"cannot edit field(s) {', '.join(unknown)}")

        card = self.get(ref)
        for name, value in changes.items():
            if value is None:
                continue
            if name == "hanzi":
                value = unicodedata.normalize("NFC", str(value))
            setattr(card, name, value)
        return card


def data_path() -> Path:
    """Default location of the working card file, whether or not it exists.

    Honours ``XDG_DATA_HOME``, falling back to ``~/.local/share``.
    """
    base = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
    return Path(base).expanduser() / "xingshu" / "cards.json"


def cards_path(override: Path | None = None) -> Path:
    """Locate the card file to use, seeding the default one on first run.

    Resolution order, first hit wins:

    1. ``override``, as passed to ``--cards``
    2. the ``XINGSHU_CARDS`` environment variable
    3. :func:`data_path`, copied from the packaged ``cards.json`` if absent

    An explicitly named file is used as given and never seeded: pointing
    ``--cards`` at a new path is how an empty deck is started.
    """
    if override is not None:
        return override.expanduser()
    if env := os.environ.get(ENV_VAR):
        return Path(env).expanduser()

    path = data_path()
    if not path.exists():
        seed = resources.files("practice").joinpath("cards.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(seed.read_text("utf-8"), "utf-8")
    return path


def open_deck(override: Path | None = None) -> Deck:
    """Resolve the card file and load it; a missing explicit file is empty."""
    path = cards_path(override)
    if not path.exists():
        return Deck([], path)
    return Deck.load(path)
