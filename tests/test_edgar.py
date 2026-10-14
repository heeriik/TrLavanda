from datetime import date

from trlavanda.data.edgar import facts_to_frame

PAYLOAD = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "NetIncomeLoss": {
                "units": {
                    "USD": [
                        {
                            "start": "2023-10-01",
                            "end": "2024-09-28",
                            "val": 93736000000,
                            "accn": "0000320193-24-000123",
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2024-11-01",
                            "frame": "CY2024",
                        }
                    ]
                }
            },
            "SomethingWeIgnore": {"units": {"USD": [{"end": "2024-09-28", "val": 1}]}},
        },
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {
                    "shares": [{"end": "2024-10-18", "val": 15115823000, "filed": "2024-11-01"}]
                }
            }
        },
    },
}


def test_facts_to_frame_keeps_only_wanted_concepts_and_parses_dates():
    df = facts_to_frame(PAYLOAD)
    assert set(df["concept"]) == {"NetIncomeLoss", "EntityCommonStockSharesOutstanding"}
    row = df.filter(df["concept"] == "NetIncomeLoss").row(0, named=True)
    assert row["filed"] == date(2024, 11, 1)  # fecha de publicación: clave contra look-ahead
    assert row["end"] == date(2024, 9, 28)
    assert row["value"] == 93736000000.0


def test_instant_facts_have_no_start():
    df = facts_to_frame(PAYLOAD)
    shares = df.filter(df["concept"] == "EntityCommonStockSharesOutstanding").row(0, named=True)
    assert shares["start"] is None


def test_parse_form_index_keeps_10k_10q():
    from trlavanda.data.edgar import parse_form_index

    text = "\n".join(
        [
            "Form Type   Company Name      CIK         Date Filed  File Name",
            "-" * 60,
            "10-Q             APOGEE ENTERPRISES, INC.          6845        2026-10-06  edgar/data/6845/x.txt",  # noqa: E501
            "8-K              APPLE INC                         320193      2026-10-07  edgar/data/320193/y.txt",  # noqa: E501
            "10-K/A           SOME CO  INC                      1234        2026-10-08  edgar/data/1234/z.txt",  # noqa: E501
        ]
    )
    df = parse_form_index(text)
    assert df["cik"].to_list() == [6845, 1234]
    assert df["form"].to_list() == ["10-Q", "10-K/A"]
