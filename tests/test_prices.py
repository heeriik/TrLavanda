from datetime import date

import polars as pl
import pytest

from trlavanda.data.prices import add_raw_close


def test_add_raw_close_undoes_later_splits():
    # Split 10:1 el día 2: el día 1 cotizaba realmente a 10x el close ajustado.
    prices = pl.DataFrame(
        {
            "date": [date(2024, 6, 7), date(2024, 6, 10), date(2024, 6, 11)],
            "ticker": ["NVDA"] * 3,
            "close": [120.0, 121.0, 122.0],
            "splits": [0.0, 10.0, 0.0],
        }
    )
    raw = add_raw_close(prices)["raw_close"].to_list()
    assert raw == pytest.approx([1200.0, 121.0, 122.0])
