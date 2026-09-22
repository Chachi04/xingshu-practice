"""The interactive flashcard app.

Two screens: :class:`SetScreen` lists every set and starts one, and
:class:`CardScreen` runs through a list of cards, pinyin first, flipping to
the sentence drawn in xingshu. Neither screen knows how images are drawn;
they are handed a widget class chosen by :mod:`practice.graphics` before the
app starts.
"""

from __future__ import annotations

import random
import unicodedata

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from practice.deck import Card, Deck
from search import Library

SLOT_WIDTHS = (6, 8, 10, 12, 16, 20)
"""Selectable image widths in cells, smallest first; ``+``/``-`` step through."""

DEFAULT_SLOT = 2
"""Index into :data:`SLOT_WIDTHS` used at startup."""

GAP = 1
"""Columns between neighbouring characters."""


def _is_punctuation(char: str) -> bool:
    return unicodedata.category(char).startswith("P")


class HanziGrid(Widget):
    """A sentence drawn one xingshu image per character, wrapping to width.

    Characters without a rendering -- punctuation, digits, anything the books
    do not index -- keep their slot and are shown as plain text, so the
    sentence still reads left to right.
    """

    DEFAULT_CSS = """
    HanziGrid {
        layout: grid;
        height: auto;
        grid-gutter: 1 1;
        width: auto;
    }
    HanziGrid > .slot {
        height: auto;
    }
    HanziGrid > .miss {
        content-align: center middle;
        color: $text-muted;
        text-style: bold;
    }
    """

    slot_width: reactive[int] = reactive(SLOT_WIDTHS[DEFAULT_SLOT])

    def __init__(self, library: Library, image_cls: type, **kwargs) -> None:
        super().__init__(**kwargs)
        self.library = library
        self.image_cls = image_cls

    def show(self, text: str) -> None:
        """Replace the grid with the renderings of ``text``."""
        self.release()
        self.remove_children()

        slots: list[Widget] = []
        for char in unicodedata.normalize("NFC", text):
            if char.isspace():
                continue
            renderings = [] if _is_punctuation(char) else self.library.resolve(char)
            if renderings:
                slots.append(self.image_cls(renderings[0].path, classes="slot"))
            else:
                slots.append(Static(char, classes="slot miss"))

        self.mount_all(slots)
        self._apply_width()
        # On a flip the parent was hidden until now and has no width yet;
        # measure again once it has been laid out.
        self.call_after_refresh(self._apply_width)

    def release(self) -> None:
        """Free every image this grid sent to the terminal.

        textual-image deletes the image data when an ``Image`` widget is given
        a new image, but not when it is unmounted. Without this, every card
        flipped would leave its images resident in Kitty for the rest of the
        session.
        """
        for child in self.children:
            if not isinstance(child, Static):
                child.image = None

    def on_unmount(self) -> None:
        self.release()

    def watch_slot_width(self) -> None:
        self._apply_width()

    def _apply_width(self) -> None:
        """Fit as many slots per row as the parent allows, and no more.

        Sized from the parent rather than from the grid itself: the grid is
        exactly as wide as its columns, so that a short sentence sits centred
        instead of hugging the left edge. Its owner calls this again on resize.
        """
        width = self.slot_width
        # PNGs are square and a cell is about twice as tall as it is wide.
        height = max(1, width // 2)
        available = self.parent.content_size.width if self.parent else self.size.width
        columns = max(1, (available + GAP) // (width + GAP))
        columns = max(1, min(columns, len(self.children)))

        self.styles.grid_size_columns = columns
        self.styles.grid_columns = str(width)
        self.styles.width = total = columns * width + (columns - 1) * GAP
        self.styles.margin = (0, 0, 0, max(0, (available - total) // 2))
        for child in self.children:
            child.styles.width = width
            if isinstance(child, Static):
                child.styles.height = height


class SetScreen(Screen):
    """Pick a set to practise."""

    BINDINGS = [
        Binding("r", "toggle_shuffle", "Shuffle"),
        Binding("q", "app.quit", "Quit"),
    ]

    STARRED = "starred"

    def compose(self) -> ComposeResult:
        yield Header()
        yield OptionList(id="sets")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_sets()
        self._update_title()

    def on_screen_resume(self) -> None:
        # Stars may have changed while practising.
        self.refresh_sets()

    def refresh_sets(self) -> None:
        deck: Deck = self.app.deck
        options = self.query_one("#sets", OptionList)
        highlighted = options.highlighted
        options.clear_options()

        starred = deck.select(starred=True)
        options.add_option(
            Option(f"★  All starred  ({len(starred)} cards)", id=self.STARRED)
        )
        for (hsk, number), cards in deck.sets().items():
            stars = sum(card.starred for card in cards)
            label = f"HSK {hsk} · Set {number:<3} ({len(cards)} cards"
            label += f", {stars}★)" if stars else ")"
            options.add_option(Option(label, id=f"{hsk}-{number}"))

        options.highlighted = highlighted if highlighted is not None else 1
        options.focus()

    def action_toggle_shuffle(self) -> None:
        self.app.shuffle = not self.app.shuffle
        self._update_title()

    def _update_title(self) -> None:
        self.title = "Xingshu practice"
        self.sub_title = "shuffled" if self.app.shuffle else "in order"

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        deck: Deck = self.app.deck
        key = event.option.id
        if key == self.STARRED:
            cards, title = deck.select(starred=True), "All starred"
        else:
            hsk, number = (int(part) for part in key.split("-"))
            cards, title = deck.select(hsk=hsk, set=number), f"HSK {hsk} · Set {number}"

        if not cards:
            self.notify("No cards here.", severity="warning")
            return
        self.app.push_screen(CardScreen(cards, title, shuffle=self.app.shuffle))


class CardScreen(Screen):
    """Run through cards: pinyin on the front, xingshu on the back."""

    BINDINGS = [
        Binding("space,enter", "flip", "Flip"),
        Binding("right,l,n", "next", "Next"),
        Binding("left,h,p", "previous", "Prev"),
        Binding("s", "star", "Star"),
        Binding("plus,equals_sign", "zoom(1)", "Bigger"),
        Binding("minus", "zoom(-1)", "Smaller"),
        Binding("escape,q", "leave", "Back"),
    ]

    DEFAULT_CSS = """
    CardScreen #card {
        height: 1fr;
        padding: 1 2;
    }
    CardScreen #pinyin {
        text-style: bold;
        text-align: center;
        width: 100%;
        padding: 1 0;
    }
    CardScreen #back {
        height: auto;
        align-horizontal: center;
    }
    CardScreen #hanzi {
        text-align: center;
        width: 100%;
        padding: 1 0;
        color: $text-muted;
    }
    CardScreen #status {
        height: 1;
        padding: 0 2;
        background: $boost;
    }
    """

    index: reactive[int] = reactive(0)
    flipped: reactive[bool] = reactive(False)

    def __init__(self, cards: list[Card], title: str, *, shuffle: bool = False) -> None:
        super().__init__()
        self.cards = list(cards)
        if shuffle:
            random.shuffle(self.cards)
        self.set_title = title
        self.slot = DEFAULT_SLOT

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="card"):
            yield Static(id="pinyin")
            with Vertical(id="back"):
                if self.app.library is not None and self.app.image_cls is not None:
                    yield HanziGrid(self.app.library, self.app.image_cls, id="grid")
                yield Static(id="hanzi")
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = self.set_title
        self._render_card()

    @property
    def card(self) -> Card:
        return self.cards[self.index]

    def _grid(self) -> HanziGrid | None:
        grids = self.query("#grid")
        return grids.first(HanziGrid) if grids else None

    def _render_card(self) -> None:
        card = self.card
        self.query_one("#pinyin", Static).update(card.pinyin)
        self.query_one("#back").display = self.flipped

        grid = self._grid()
        hanzi = self.query_one("#hanzi", Static)
        if self.flipped:
            if grid is not None:
                grid.show(card.hanzi)
            hanzi.update(card.hanzi)
        else:
            if grid is not None:
                grid.release()
                grid.remove_children()
            hanzi.update("")

        star = "★" if card.starred else "☆"
        side = "back" if self.flipped else "front"
        self.query_one("#status", Static).update(
            f"{self.index + 1} / {len(self.cards)}   {star}   {side}   id {card.id}"
        )

    def watch_index(self) -> None:
        if self.is_mounted:
            self._render_card()

    def watch_flipped(self) -> None:
        if self.is_mounted:
            self._render_card()

    def on_resize(self) -> None:
        if (grid := self._grid()) is not None:
            grid.call_after_refresh(grid._apply_width)

    def action_flip(self) -> None:
        self.flipped = not self.flipped

    def action_next(self) -> None:
        if self.index + 1 < len(self.cards):
            self.flipped = False
            self.index += 1
        else:
            self.notify("Last card. Esc to go back.")

    def action_previous(self) -> None:
        if self.index > 0:
            self.flipped = False
            self.index -= 1

    def action_star(self) -> None:
        card = self.card
        card.starred = not card.starred
        try:
            self.app.deck.save()
        except OSError as exc:
            card.starred = not card.starred
            self.notify(f"Could not save: {exc}", severity="error")
        self._render_card()

    def action_zoom(self, step: int) -> None:
        self.slot = min(max(self.slot + step, 0), len(SLOT_WIDTHS) - 1)
        if (grid := self._grid()) is not None:
            grid.slot_width = SLOT_WIDTHS[self.slot]

    def action_leave(self) -> None:
        if len(self.app.screen_stack) > 2:
            self.app.pop_screen()
        else:
            self.app.exit()


class PracticeApp(App):
    """Flashcards of pinyin sentences with their xingshu on the back.

    Args:
        deck: The loaded cards; starring saves back through it.
        library: Character image lookup, or ``None`` to show hanzi as text.
        image_cls: textual-image widget class, or ``None`` for text only.
        start: Cards to go straight into, skipping set selection.
        title: Title for ``start``.
        shuffle: Initial shuffle setting.
        notice: Shown once on startup, e.g. why images are unavailable.
    """

    TITLE = "Xingshu practice"

    def __init__(
        self,
        deck: Deck,
        library: Library | None,
        image_cls: type | None,
        *,
        start: list[Card] | None = None,
        title: str = "",
        shuffle: bool = False,
        notice: str | None = None,
    ) -> None:
        super().__init__()
        self.deck = deck
        self.library = library
        self.image_cls = image_cls
        self.start = start
        self.start_title = title
        self.shuffle = shuffle
        self.notice = notice

    def on_mount(self) -> None:
        if self.start is not None:
            self.push_screen(CardScreen(self.start, self.start_title, shuffle=self.shuffle))
        else:
            self.push_screen(SetScreen())
        if self.notice:
            self.notify(self.notice, severity="warning", timeout=8)
