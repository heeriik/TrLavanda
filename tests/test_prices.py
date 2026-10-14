from datetime import date

import polars as pl
import pytest

from trlavanda.data.prices import add_raw_close, add_total_return, merge, needs_full_refetch


def frame(rows):
    return pl.DataFrame(
        rows,
        schema={
            "date": pl.Date,
            "ticker": pl.Utf8,
            "close": pl.Float64,
            "volume": pl.Float64,
            "dividends": pl.Float64,
            "splits": pl.Float64,
        },
        orient="row",
    )


def test_add_raw_close_undoes_later_splits():
    # Split 10:1 el día 2: el día 1 cotizaba realmente a 10x el close ajustado.
    prices = frame(
        [
            (date(2024, 6, 7), "NVDA", 120.0, 0.0, 0.0, 0.0),
            (date(2024, 6, 10), "NVDA", 121.0, 0.0, 0.0, 10.0),
            (date(2024, 6, 11), "NVDA", 122.0, 0.0, 0.0, 0.0),
        ]
    )
    assert add_raw_close(prices)["raw_close"].to_list() == pytest.approx([1200.0, 121.0, 122.0])


def test_total_return_reinvests_dividends_and_never_rewrites_the_past():
    p = frame(
        [
            (date(2024, 1, 1), "X", 100.0, 0.0, 0.0, 0.0),
            (date(2024, 1, 2), "X", 99.0, 0.0, 1.0, 0.0),  # paga 1 $ y el precio cae 1 $
        ]
    )
    adj = add_total_return(p)["adj_close"].to_list()
    assert adj == pytest.approx([100.0, 100.0])  # para el accionista no ha cambiado nada

    # Añadir un día nuevo no cambia los valores anteriores.
    longer = pl.concat([p, frame([(date(2024, 1, 3), "X", 110.0, 0.0, 0.5, 0.0)])])
    assert add_total_return(longer)["adj_close"].to_list()[:2] == pytest.approx(adj)


def test_needs_full_refetch_on_split_or_mismatch():
    old = frame(
        [
            (date(2024, 1, 2), "A", 10.0, 0, 0, 0),
            (date(2024, 1, 2), "B", 20.0, 0, 0, 0),
            (date(2024, 1, 2), "C", 30.0, 0, 0, 0),
        ]
    )
    new = frame(
        [
            (date(2024, 1, 2), "A", 10.0, 0, 0, 0),  # igual
            (date(2024, 1, 2), "B", 10.0, 0, 0, 0),  # Yahoo ha reescrito el pasado
            (date(2024, 1, 3), "C", 15.0, 0, 0, 2.0),  # split nuevo
        ]
    )
    assert needs_full_refetch(old, new) == {"B", "C"}


def test_merge_replaces_overlap_and_appends():
    old = frame([(date(2024, 1, 2), "A", 10.0, 0, 0, 0), (date(2024, 1, 3), "A", 11.0, 0, 0, 0)])
    new = frame([(date(2024, 1, 3), "A", 11.5, 0, 0, 0), (date(2024, 1, 4), "A", 12.0, 0, 0, 0)])
    assert merge(old, new)["close"].to_list() == [10.0, 11.5, 12.0]
