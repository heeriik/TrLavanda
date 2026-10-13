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
