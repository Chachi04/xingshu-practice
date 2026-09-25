import json
from pathlib import Path

import pytest

from practice.cli import main
from practice.deck import Card, Deck, cards_path
from practice.migrate import migrate

OLD = [
    {
        "HSK Level": 1,
        "Sets": [
            {
                "Set": 1,
                "Terms": [
                    {"hanzi": "我很好。", "pinyin": "wǒ hěn hǎo 。", "saved": False},
                    {"hanzi": "请坐。", "pinyin": "qǐng zuò 。", "saved": True},
                ],
            },
            {"Set": 2, "Terms": [{"hanzi": "你好", "pinyin": "nǐ hǎo", "saved": False}]},
        ],
    },
    {"HSK Level": 2, "Sets": [{"Set": 1, "Terms": [{"hanzi": "游泳", "pinyin": "yóu yǒng", "saved": False}]}]},
]


@pytest.fixture
def card_file(tmp_path: Path) -> Path:
    path = tmp_path / "cards.json"
    path.write_text(json.dumps(OLD, ensure_ascii=False), "utf-8")
    return path


def test_migrate_keeps_every_term(card_file: Path) -> None:
    deck = Deck.load(card_file)
    assert [(c.hanzi, c.hsk, c.set, c.starred) for c in deck.cards] == [
        ("我很好。", 1, 1, False),
        ("请坐。", 1, 1, True),
        ("你好", 1, 2, False),
        ("游泳", 2, 1, False),
    ]
    assert len({c.id for c in deck.cards}) == 4


def test_migrate_leaves_versioned_files_alone() -> None:
    data = {"version": 1, "cards": []}
    assert migrate(data) is data


def test_save_round_trip_writes_version(card_file: Path) -> None:
    deck = Deck.load(card_file)
    deck.save()
    raw = json.loads(card_file.read_text("utf-8"))
    assert raw["version"] == 1
    assert Deck.load(card_file).cards == deck.cards
    assert list(card_file.parent.iterdir()) == [card_file]  # no temp file left


def test_rejects_newer_version(tmp_path: Path) -> None:
    path = tmp_path / "cards.json"
    path.write_text('{"version": 99, "cards": []}')
    with pytest.raises(ValueError, match="unsupported version"):
        Deck.load(path)


def test_rejects_duplicate_ids(tmp_path: Path) -> None:
    card = {"id": "aa", "hanzi": "你", "pinyin": "nǐ", "hsk": 1, "set": 1}
    path = tmp_path / "cards.json"
    path.write_text(json.dumps({"version": 1, "cards": [card, card]}))
    with pytest.raises(ValueError, match="duplicate"):
        Deck.load(path)


def test_sets_and_select(card_file: Path) -> None:
    deck = Deck.load(card_file)
    assert list(deck.sets()) == [(1, 1), (1, 2), (2, 1)]
    assert [c.hanzi for c in deck.select(hsk=1, set=1)] == ["我很好。", "请坐。"]
    assert [c.hanzi for c in deck.select(starred=True)] == ["请坐。"]
    assert [c.hanzi for c in deck.select(set=1)] == ["我很好。", "请坐。", "游泳"]


def test_add_edit_remove() -> None:
    deck = Deck([])
    card = deck.add("你好", "nǐ hǎo", 1, 3)
    assert deck.get(card.id) is card

    deck.edit(card.id, pinyin="nǐhǎo", set=4, starred=True, hanzi=None)
    assert (card.hanzi, card.pinyin, card.set, card.starred) == ("你好", "nǐhǎo", 4, True)

    with pytest.raises(ValueError):
        deck.edit(card.id, id="x")

    assert deck.remove(card.id) is card
    assert deck.cards == []


def test_get_by_prefix() -> None:
    deck = Deck(
        [
            Card("一", "yī", 1, 1, id="abc123"),
            Card("二", "èr", 1, 1, id="abd456"),
        ]
    )
    assert deck.get("abc").hanzi == "一"
    with pytest.raises(KeyError, match="ambiguous"):
        deck.get("ab")
    with pytest.raises(KeyError, match="no card"):
        deck.get("zz")


def test_default_path_is_seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XINGSHU_CARDS", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    path = cards_path()
    assert path == tmp_path / "xingshu" / "cards.json"
    assert Deck.load(path).cards


def test_cli_list_add_edit_rm(card_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cards = ["--cards", str(card_file)]

    assert main([*cards, "add", "谢谢", "--hsk", "1", "--set", "2", "--pinyin", "xiè xie"]) == 0
    card_id = capsys.readouterr().out.split()[0]

    assert main([*cards, "edit", card_id, "--star"]) == 0
    assert main([*cards, "list", "--starred"]) == 0
    out = capsys.readouterr().out
    assert "谢谢" in out and "请坐。" in out

    assert main([*cards, "rm", card_id, "nope"]) == 1
    assert "no card" in capsys.readouterr().err
    assert all(c.id != card_id for c in Deck.load(card_file).cards)


def test_cli_add_suggests_pinyin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "new.json"
    assert main(["--cards", str(path), "add", "我很好", "--hsk", "1", "--set", "1"]) == 0
    assert "wǒ hěn hǎo" in capsys.readouterr().out
    assert Deck.load(path).cards[0].pinyin == "wǒ hěn hǎo"


def test_cli_edit_hanzi_regenerates_pinyin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cards = ["--cards", str(tmp_path / "new.json")]
    assert main([*cards, "add", "我很好", "--hsk", "1", "--set", "1", "--pinyin", "wǒ hěn hǎo"]) == 0
    card_id = capsys.readouterr().out.split()[0]

    def pinyin() -> str:
        return Deck.load(tmp_path / "new.json").get(card_id).pinyin

    assert main([*cards, "edit", card_id, "--hsk", "2"]) == 0
    assert pinyin() == "wǒ hěn hǎo"
    assert main([*cards, "edit", card_id, "--hanzi", "你好"]) == 0
    assert pinyin() == "nǐ hǎo"
    assert "generated" in capsys.readouterr().err
    assert main([*cards, "edit", card_id, "--hanzi", "请坐", "--pinyin", "qǐng zuò"]) == 0
    assert pinyin() == "qǐng zuò"


def test_cli_run_options_survive_subcommand() -> None:
    from practice.cli import build_parser

    args = build_parser().parse_args(["--images", "kitty", "run", "--hsk", "1"])
    assert args.images == "kitty"
    args = build_parser().parse_args(["run", "--images", "text"])
    assert args.images == "text"


@pytest.mark.parametrize(
    ("help_argv", "flag_argv"),
    [(["help"], ["--help"]), (["help", "add"], ["add", "--help"])],
)
def test_cli_help_command_matches_flag(
    help_argv: list[str], flag_argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as via_command:
        main(help_argv)
    command_out = capsys.readouterr().out
    with pytest.raises(SystemExit) as via_flag:
        main(flag_argv)
    assert via_command.value.code == via_flag.value.code == 0
    assert command_out == capsys.readouterr().out


def test_cli_help_rejects_unknown_topic(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["help", "nope"])
    assert exc.value.code == 2


def test_learnt_survives_round_trip(tmp_path: Path) -> None:
    card = {"id": "aa", "hanzi": "你", "pinyin": "nǐ", "hsk": 1, "set": 1, "learnt": True}
    path = tmp_path / "cards.json"
    path.write_text(json.dumps({"version": 1, "cards": [card]}))
    deck = Deck.load(path)
    assert deck.cards[0].learnt
    deck.save()
    assert json.loads(path.read_text("utf-8"))["cards"][0]["learnt"] is True


def test_cli_learn_and_list_json(card_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cards = ["--cards", str(card_file)]
    deck = Deck.load(card_file)
    deck.save()  # the fixture is pre-versioned; ids only stick once saved
    card_id = deck.cards[0].id

    assert main([*cards, "edit", card_id, "--learn"]) == 0
    capsys.readouterr()
    assert main([*cards, "list", "--learnt", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [(c["id"], c["learnt"]) for c in listed] == [(card_id, True)]

    assert main([*cards, "edit", card_id, "--unlearn"]) == 0
    capsys.readouterr()
    assert main([*cards, "list", "--learnt", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
