import base64
from io import BytesIO

import pandas as pd
from PIL import Image, ImageColor

from stockfinder.thumbnails import (
    PRICE_COLOR,
    SMA_COLOR,
    VOLUME_DOWN_COLOR,
    VOLUME_UP_COLOR,
    price_sma_thumbnail,
)


def test_price_thumbnail_contains_price_and_sma_lines() -> None:
    history = pd.DataFrame(
        {
            "Close": [
                100 + index * 0.4 + (-1 if index % 2 else 1)
                for index in range(126)
            ],
            "Volume": [1_000 + index * 10 for index in range(126)],
        }
    )

    data_url = price_sma_thumbnail(history)
    image = Image.open(BytesIO(base64.b64decode(data_url.split(",", 1)[1])))
    colors = set(image.get_flattened_data())

    assert image.size == (260, 112)
    assert ImageColor.getrgb(PRICE_COLOR) in colors
    assert ImageColor.getrgb(SMA_COLOR) in colors
    assert ImageColor.getrgb(VOLUME_UP_COLOR) in colors
    assert ImageColor.getrgb(VOLUME_DOWN_COLOR) in colors