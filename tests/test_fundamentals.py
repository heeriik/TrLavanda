from datetime import date

import polars as pl
import pytest

from trlavanda.factors.fundamentals import first_filed, quarterly_from_ytd, ttm

SCHEMA = {
    "cik": pl.Int64,
    "concept": pl.Utf8,
    "start": pl.Date,
    "end": pl.Date,
    "accn": pl.Utf8,
    "filed": pl.Date,
    "value": pl.Float64,
    "form": pl.Utf8,
    "unit": pl.Utf8,
}


def facts(rows):
    return pl.DataFrame(rows, schema=SCHEMA, orient="row").lazy()


def test_first_filed_ignores_later_restatements():
    f = facts(
        [
            (
                1,
                "NetIncomeLoss",
                date(2023, 1, 1),
                date(2023, 3, 31),
                "a",
                date(2023, 5, 1),
                10.0,
                "10-Q",
                "USD",
            ),
            (
                1,
                "NetIncomeLoss",
                date(2023, 1, 1),
                date(2023, 3, 31),
                "b",
                date(2024, 5, 1),
                12.0,
                "10-Q",
                "USD",
            ),
        ]
    )
    out = first_filed(f).collect()
    assert out["value"].to_list() == [10.0]


def test_quarterly_from_ytd_derives_q2_q3_q4_from_cumulative():
    # Flujo de caja: el 10-Q solo da acumulados 3, 6, 9 meses y el 10-K 12 meses.
    s = date(2023, 1, 1)
    rows = [
        (1, "OCF", s, date(2023, 3, 31), date(2023, 5, 1), 10.0),
        (1, "OCF", s, date(2023, 6, 30), date(2023, 8, 1), 25.0),
        (1, "OCF", s, date(2023, 9, 30), date(2023, 11, 1), 45.0),
        (1, "OCF", s, date(2023, 12, 31), date(2024, 2, 15), 70.0),
    ]
    lf = pl.DataFrame(
        rows,
        schema={
            "cik": pl.Int64,
            "concept": pl.Utf8,
            "start": pl.Date,
            "end": pl.Date,
            "filed": pl.Date,
            "value": pl.Float64,
        },
        orient="row",
    ).lazy()
    q = quarterly_from_ytd(lf).collect().sort("end")
    assert q["value"].to_list() == [10.0, 15.0, 20.0, 25.0]
    # El Q4 solo se conoce cuando sale el 10-K.
    assert q["filed"].to_list()[-1] == date(2024, 2, 15)

    t = ttm(q.lazy()).collect()
    assert t["ttm"].to_list() == pytest.approx([70.0])
    assert t["available"].to_list() == [date(2024, 2, 15)]
