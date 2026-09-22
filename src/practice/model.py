from dataclasses import dataclass


@dataclass
class Practice:
    cards: list[dict]
    hsk: int
    set: int

    def run(self) -> int: ...
