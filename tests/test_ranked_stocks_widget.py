import pandas as pd

from stockfinder.presentation.navigation import AnalysisContext
from stockfinder.widgets.ranked_stocks import _context_candidates


def test_context_candidates_tolerates_empty_legacy_snapshot_schema() -> None:
    context = AnalysisContext({"analysis_context_region": "Europe"})

    result = _context_candidates(pd.DataFrame(), context)

    assert result.empty