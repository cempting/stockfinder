"""Compact bitmap charts for tabular security overviews."""

import base64
from io import BytesIO

import pandas as pd
from PIL import Image, ImageDraw

BACKGROUND = "#151e22"
PRICE_COLOR = "#49c28a"
SMA_COLOR = "#f4c95d"
VOLUME_UP_COLOR = "#28795b"
VOLUME_DOWN_COLOR = "#9b4d52"
DIVIDER_COLOR = "#344047"


def price_sma_thumbnail(history: pd.DataFrame) -> str:
    """Render the supplied price, SMA50, and volume range as a compact data URL."""
    close = history["Close"].dropna()
    sma50 = close.rolling(50).mean()
    sma50 = sma50.reindex(close.index)
    volume = history.get("Volume", pd.Series(dtype=float)).reindex(close.index)

    width, height = 260, 112
    padding_x, padding_y = 5, 6
    volume_height = 32
    divider_y = height - volume_height - padding_y
    price_bottom = divider_y - 4
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
                price_bottom
                - (float(value) - minimum) * (price_bottom - padding_y) / span,
            )
            for position, value in zip(positions, valid, strict=True)
        ]

    price_points = points(close)
    average_points = points(sma50)
    if len(price_points) > 1:
        draw.line(price_points, fill=PRICE_COLOR, width=2)
    if len(average_points) > 1:
        draw.line(average_points, fill=SMA_COLOR, width=2)
    draw.line((padding_x, divider_y, width - padding_x, divider_y), fill=DIVIDER_COLOR)

    valid_volume = volume.dropna()
    maximum_volume = float(valid_volume.max()) if not valid_volume.empty else 0.0
    if maximum_volume > 0:
        bar_width = max(1, (width - 2 * padding_x) // max(1, len(close)))
        previous_close = close.shift(1)
        for position, (index, value) in enumerate(volume.items()):
            if pd.isna(value):
                continue
            x = padding_x + position * (width - 2 * padding_x) / max(1, len(close))
            bar_height = float(value) / maximum_volume * (volume_height - 4)
            color = (
                VOLUME_DOWN_COLOR
                if float(close.loc[index]) < float(previous_close.loc[index])
                else VOLUME_UP_COLOR
            )
            draw.rectangle(
                (x, height - padding_y - bar_height, x + bar_width, height - padding_y),
                fill=color,
            )
    return _data_url(image)


def _data_url(image: Image.Image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"