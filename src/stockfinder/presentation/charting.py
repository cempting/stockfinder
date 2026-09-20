"""Shared Plotly helpers for price and trading-volume charts."""

from collections.abc import Mapping

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def price_volume_subplots(
    *,
    row_heights: tuple[float, float] = (0.74, 0.26),
    vertical_spacing: float = 0.05,
) -> go.Figure:
    """Create aligned price and volume rows with a shared date axis."""
    return make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=vertical_spacing,
        row_heights=list(row_heights),
    )


def add_volume_bars(
    figure: go.Figure,
    history: pd.DataFrame,
    *,
    row: int = 2,
    name: str = "Volume",
    showlegend: bool = True,
) -> None:
    """Add raw volume bars when the supplied history contains volume data."""
    if history.empty or "Volume" not in history:
        return
    volume = history["Volume"].dropna()
    if volume.empty:
        return
    aligned = history.loc[volume.index]
    if "Open" in aligned and "Close" in aligned:
        rising = aligned["Close"] >= aligned["Open"]
    elif "Close" in aligned:
        rising = aligned["Close"].diff().fillna(0) >= 0
    else:
        rising = pd.Series(True, index=aligned.index)
    colors = rising.map({True: "#0b6e4f", False: "#d95d39"}).tolist()
    figure.add_trace(
        go.Bar(
            x=volume.index,
            y=volume,
            marker_color=colors,
            name=name,
            showlegend=showlegend,
        ),
        row=row,
        col=1,
    )
    figure.update_yaxes(title_text="Volume", row=row, col=1)


def add_relative_volume_lines(
    figure: go.Figure,
    histories: Mapping[str, pd.DataFrame],
    *,
    row: int = 2,
    window: int = 20,
) -> None:
    """Add comparable volume ratios for a multi-instrument price chart."""
    for symbol, history in histories.items():
        if history.empty or "Volume" not in history:
            continue
        volume = history["Volume"].dropna().copy()
        if isinstance(volume.index, pd.DatetimeIndex):
            volume.index = volume.index.tz_localize(None).normalize()
        baseline = volume.rolling(window, min_periods=1).mean()
        ratio = volume.div(baseline.where(baseline > 0))
        figure.add_trace(
            go.Scatter(
                x=ratio.index,
                y=ratio,
                name=f"{symbol} volume",
                mode="lines",
                line={"width": 1.5},
            ),
            row=row,
            col=1,
        )
    figure.add_hline(
        y=1,
        line_dash="dot",
        line_color="#7d8990",
        row=row,
        col=1,
    )
    figure.update_yaxes(title_text="Vol / 20D", row=row, col=1)
