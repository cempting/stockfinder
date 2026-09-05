"""Compact bitmap charts for tabular security overviews."""

import base64
from io import BytesIO

import pandas as pd
from PIL import Image, ImageDraw

BACKGROUND = "#151e22"
PRICE_COLOR = "#49c28a"
SMA_COLOR = "#f4c95d"


def price_sma_thumbnail(history: pd.DataFrame) -> str:
    """Render six months of closing price and its 50-day average as a data URL."""
    close = history["Close"].dropna()
    sma50 = close.rolling(50).mean()
    close = close.tail(126)
    sma50 = sma50.reindex(close.index)

    width, height = 260, 74
    padding_x, padding_y = 5, 6
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    values = pd.concat([close, sma50]).dropna()
    if len(close) < 2 or values.empty:
        return _data_url(image)

    minimum = float(values.min())
    maximum = float(values.max())
    span = maximum - minimum or 1.0

    def points(series: pd.Series) -> list[tuple[float, float]]:
        valid = series.dropna()
        positions = close.index.get_indexer(valid.index)
        return [
            (
                padding_x
                + position * (width - 2 * padding_x) / max(1, len(close) - 1),
                height
                - padding_y
                - (float(value) - minimum) * (height - 2 * padding_y) / span,
            )
            for position, value in zip(positions, valid, strict=True)
        ]

    price_points = points(close)
    average_points = points(sma50)
    if len(price_points) > 1:
        draw.line(price_points, fill=PRICE_COLOR, width=2)
    if len(average_points) > 1:
        draw.line(average_points, fill=SMA_COLOR, width=2)
    return _data_url(image)


def _data_url(image: Image.Image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"