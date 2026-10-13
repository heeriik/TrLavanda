from datetime import date

import polars as pl

from trlavanda.data.universe import month_ends, normalize_ticker, reconstruct_membership


def test_normalize_ticker():
    assert normalize_ticker(" brk.b ") == "BRK-B"
    assert normalize_ticker(None) is None


def test_reconstruct_membership_undoes_changes_backwards():
    # Hoy el índice es {A, B, C}. El 2020-06-15 entró C y salió X.
    changes = pl.DataFrame(
        {"date": [date(2020, 6, 15)], "added": ["C"], "removed": ["X"]},
        schema={"date": pl.Date, "added": pl.Utf8, "removed": pl.Utf8},
    )
    dates = [date(2020, 5, 31), date(2020, 6, 15), date(2020, 6, 30)]
    m = reconstruct_membership({"A", "B", "C"}, changes, dates)

    def at(d):
        return set(m.filter(pl.col("date") == d)["ticker"])

    assert at(date(2020, 5, 31)) == {"A", "B", "X"}  # antes del cambio
    assert at(date(2020, 6, 15)) == {"A", "B", "C"}  # el día del cambio ya cuenta
    assert at(date(2020, 6, 30)) == {"A", "B", "C"}


def test_reconstruct_membership_handles_add_only_change():
    changes = pl.DataFrame(
        {"date": [date(2021, 1, 10)], "added": ["D"], "removed": [None]},
        schema={"date": pl.Date, "added": pl.Utf8, "removed": pl.Utf8},
    )
    m = reconstruct_membership({"A", "D"}, changes, [date(2020, 12, 31)])
    assert set(m["ticker"]) == {"A"}


def test_month_ends():
    ends = month_ends("2024-01-01", date(2024, 3, 15))
    assert ends == [date(2024, 1, 31), date(2024, 2, 29)]
