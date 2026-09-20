import pandas as pd

from stockfinder.widgets.peer_comparison import select_peer_symbols


def test_select_peer_symbols_stays_within_region_and_industry() -> None:
    universe = pd.DataFrame(
        {
            "Symbol": ["TARGET", "LARGE", "SMALL", "OTHER", "FOREIGN"],
            "Region": ["Europe", "Europe", "Europe", "Europe", "Asia"],
            "Sector": ["Technology"] * 5,
            "Industry": ["Software", "Software", "Software", "Hardware", "Software"],
            "Market cap": [50, 100, 20, 200, 300],
        }
    )

    peers, attributes = select_peer_symbols(universe, "TARGET", limit=2)

    assert peers == ["LARGE", "SMALL"]
    assert attributes == {
        "region": "Europe",
        "sector": "Technology",
        "industry": "Software",
    }