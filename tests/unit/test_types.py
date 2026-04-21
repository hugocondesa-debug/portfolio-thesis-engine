"""Tests for shared.types aliases."""

from portfolio_thesis_engine.shared import types


def test_scalar_aliases_resolve_to_expected_underlying_types() -> None:
    assert types.Ticker.__value__ is str
    assert types.ISODate.__value__ is str
    assert types.UnixTimestamp.__value__ is int


def test_json_aliases_accept_expected_values() -> None:
    value: types.JsonDict = {
        "name": "AAPL",
        "price": 175.3,
        "count": 7,
        "is_active": True,
        "tags": ["tech", "large-cap"],
        "nested": {"sector": "IT", "score": None},
    }
    assert value["name"] == "AAPL"
    assert isinstance(value["tags"], list)

    items: types.JsonList = [1, "two", None, {"k": "v"}]
    assert len(items) == 4


def test_aliases_usable_as_annotations() -> None:
    ticker: types.Ticker = "AAPL"
    iso: types.ISODate = "2026-04-21"
    ts: types.UnixTimestamp = 1_700_000_000
    assert ticker == "AAPL"
    assert iso == "2026-04-21"
    assert ts == 1_700_000_000
