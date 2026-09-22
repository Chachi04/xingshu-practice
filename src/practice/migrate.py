"""Upgrading card files written in older formats.

Kept apart from :mod:`practice.deck` so the loader only ever has to understand
the current schema: anything older is rewritten into it here first.
"""

from __future__ import annotations

import secrets


def migrate(raw: object) -> dict:
    """Bring a parsed card file up to the current schema.

    Recognises the original, unversioned layout -- a list of
    ``{"HSK Level": n, "Sets": [{"Set": m, "Terms": [...]}]}`` -- and flattens
    it, giving each term a fresh id and renaming ``saved`` to ``starred``.
    Anything already carrying a ``version`` is returned untouched for the
    caller to validate.

    Raises:
        ValueError: If ``raw`` is neither the old layout nor a versioned file.
    """
    if isinstance(raw, dict) and "version" in raw:
        return raw
    if not isinstance(raw, list):
        raise ValueError("card file is neither a versioned object nor the old list layout")

    cards: list[dict] = []
    used: set[str] = set()
    for level in raw:
        for group in level.get("Sets", []):
            for term in group.get("Terms", []):
                card_id = secrets.token_hex(4)
                while card_id in used:
                    card_id = secrets.token_hex(4)
                used.add(card_id)
                cards.append(
                    {
                        "id": card_id,
                        "hanzi": term["hanzi"],
                        "pinyin": term["pinyin"],
                        "hsk": level["HSK Level"],
                        "set": group["Set"],
                        "starred": bool(term.get("saved", False)),
                    }
                )
    return {"version": 1, "cards": cards}
