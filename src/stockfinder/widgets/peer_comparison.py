"""Regional industry peer and configured benchmark comparison widget."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from stockfinder.analysis import normalized_performance_from_histories
from stockfinder.infrastructure.config import configured_proxy
from stockfinder.presentation.charting import (
    add_relative_volume_lines,
    price_volume_subplots,
)
from stockfinder.presentation.dashboard import WidgetSpec
from stockfinder.presentation.dashboard_runtime import DashboardServices
from stockfinder.presentation.navigation import AnalysisContext


def select_peer_symbols(
    universe: pd.DataFrame,
    symbol: str,
    *,
    limit: int = 5,
) -> tuple[list[str], dict[str, str]]:
    """Select leading same-region, same-industry peers for one instrument."""
    if universe.empty or "Symbol" not in universe:
        return [], {}
    selected = universe[universe["Symbol"].astype(str) == symbol]
    if selected.empty:
        return [], {}
    row = selected.iloc[0]
    attributes = {
        "region": str(row.get("Region", "")),
        "sector": str(row.get("Sector", "")),
        "industry": str(row.get("Industry", "")),
    }
    peers = universe[
        (universe["Region"].astype(str) == attributes["region"])
        & (universe["Industry"].astype(str) == attributes["industry"])
        & (universe["Symbol"].astype(str) != symbol)
    ].copy()
    if "Market cap" in peers:
        peers = peers.sort_values("Market cap", ascending=False, na_position="last")
    return peers["Symbol"].astype(str).head(limit).tolist(), attributes


def render_peer_comparison(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    symbol = (
        context.get("instrument") if spec.follow_context else None
    ) or str(spec.settings.get("default_symbol", "SPY"))
    universe_result, _, _, _, warning = services.load_scan(services.load_mode)
    if warning:
        st.caption(warning)
    peers, attributes = select_peer_symbols(universe_result.data, symbol)
    if not attributes:
        st.info(f"{symbol} is outside the latest classified stock universe.")
        return

    benchmark, benchmark_role = configured_proxy(
        services.get_analysis_config(),
        attributes["region"],
        attributes["sector"],
        attributes["industry"],
    )
    symbols = list(dict.fromkeys([symbol, *peers, benchmark]))
    results = {item: services.get_history(item, "6mo") for item in symbols}
    performance = normalized_performance_from_histories(
        {item: result.data for item, result in results.items()}
    )
    if symbol not in performance:
        st.info(f"No comparable price history is available for {symbol}.")
        return

    figure = _peer_comparison_figure(performance, results, symbol, benchmark)
    st.plotly_chart(figure, width="stretch", key=f"{spec.widget_id}_comparison")

    returns = performance.ffill().iloc[-1] - 100
    selected_return = float(returns[symbol])
    benchmark_return = float(returns[benchmark]) if benchmark in returns else None
    selected_metric, benchmark_metric, relative_metric = st.columns(3)
    selected_metric.metric(f"{symbol} · 6M", f"{selected_return:+.1f}%")
    benchmark_metric.metric(
        f"{benchmark} · 6M",
        f"{benchmark_return:+.1f}%" if benchmark_return is not None else "Unavailable",
    )
    relative_metric.metric(
        "Relative to benchmark",
        (
            f"{selected_return - benchmark_return:+.1f}%"
            if benchmark_return is not None
            else "Unavailable"
        ),
    )
    summary = pd.DataFrame(
        {
            "Symbol": returns.index,
            "Role": [
                "Selected"
                if item == symbol
                else benchmark_role.title()
                if item == benchmark
                else "Regional industry peer"
                for item in returns.index
            ],
            "6M return %": returns.values.round(1),
        }
    ).sort_values("6M return %", ascending=False)
    st.dataframe(summary, hide_index=True, width="stretch")
    sources = sorted({result.source for result in results.values()})
    st.caption(
        f"{attributes['region']} · {attributes['industry']} · "
        f"{len(peers)} peers · benchmark {benchmark} ({benchmark_role}) · "
        f"sources: {', '.join(sources)}"
    )


def _peer_comparison_figure(
    performance: pd.DataFrame,
    results: dict[str, object],
    symbol: str,
    benchmark: str,
) -> go.Figure:
    """Plot relative prices with comparable volume participation beneath."""
    figure = price_volume_subplots(row_heights=(0.7, 0.3))
    for item in performance:
        role = (
            "Selected"
            if item == symbol
            else "Benchmark"
            if item == benchmark
            else "Peer"
        )
        figure.add_scatter(
            x=performance.index,
            y=performance[item],
            name=f"{item} · {role}",
            line={
                "width": 3 if item == symbol else 2,
                "dash": "dot" if item == benchmark else "solid",
            },
            row=1,
            col=1,
        )
    add_relative_volume_lines(
        figure,
        {item: result.data for item, result in results.items()},
    )
    figure.update_layout(
        height=510,
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        hovermode="x unified",
        legend={"orientation": "h"},
    )
    figure.update_yaxes(title_text="Growth of 100", row=1, col=1)
    return figure