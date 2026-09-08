"""Application-level analysis assembled from data and scoring services."""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from stockfinder.data import (
    INDUSTRY_ETFS,
    METAL_PROXIES,
    METALS_BENCHMARK,
    SECTOR_ETFS,
    SECURITY_UNIVERSE,
    DataResult,
    fundamental_metrics,
    get_history,
    get_profile,
    risk_metrics,
)
from stockfinder.models import MarketRegime, PositionPlan, SecurityAnalysis, SwingSetup
from stockfinder.scoring import score_fundamentals, score_risk, score_technicals
from stockfinder.thumbnails import price_sma_thumbnail


@dataclass(frozen=True)
class AnalysisResult:
    """A security analysis and all evidence needed by the UI."""

    analysis: SecurityAnalysis
    history: DataResult
    profile: DataResult
    latest_price: float
    daily_change: float
    atr: float
    swing_low: float


def _average_true_range(history: pd.DataFrame, periods: int = 14) -> float:
    previous_close = history["Close"].shift(1)
    true_range = pd.concat(
        [
            history["High"] - history["Low"],
            (history["High"] - previous_close).abs(),
            (history["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return float(true_range.rolling(periods).mean().iloc[-1])


def _recent_swing_low(history: pd.DataFrame, periods: int = 20) -> float:
    return float(history["Low"].tail(periods).min())


def analyze_security(symbol: str) -> AnalysisResult:
    """Build independent quality, risk, and technical scores for a symbol."""
    normalized_symbol = symbol.strip().upper()
    history_result = get_history(normalized_symbol, "2y")
    profile_result = get_profile(normalized_symbol)
    history = history_result.data
    profile = profile_result.data
    quality = score_fundamentals(fundamental_metrics(profile))
    risk = score_risk(risk_metrics(history, profile))
    technical = score_technicals(history)
    close = history["Close"]
    daily_change = float(close.pct_change().iloc[-1] * 100) if len(close) > 1 else 0.0
    atr = _average_true_range(history)
    swing_low = _recent_swing_low(history)
    analysis = SecurityAnalysis(normalized_symbol, quality, risk, technical)
    return AnalysisResult(
        analysis,
        history_result,
        profile_result,
        float(close.iloc[-1]),
        daily_change,
        atr,
        swing_low,
    )


def build_market_risk_profiles(
    histories: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Profile price risk for already downloaded histories without provider calls."""
    rows = []
    for symbol, history in histories.items():
        required = {"High", "Low", "Close"}
        if history.empty or not required.issubset(history.columns):
            continue
        frame = history.dropna(subset=list(required))
        if len(frame) < 20:
            continue
        close = frame["Close"]
        returns = close.pct_change().dropna()
        volatility = float(returns.std() * np.sqrt(252) * 100)
        drawdown = close / close.cummax() - 1
        atr = _average_true_range(frame)
        latest = float(close.iloc[-1])
        metrics = risk_metrics(frame, {})
        risk = score_risk(metrics)
        rows.append(
            {
                "Symbol": symbol,
                "Last price": latest,
                "Day %": float(close.pct_change().iloc[-1] * 100),
                "Volatility %": round(volatility, 1),
                "Max drawdown %": round(float(drawdown.min() * 100), 1),
                "ATR14": atr,
                "ATR %": round(atr / latest * 100, 1),
                "Swing low": _recent_swing_low(frame),
                "Market risk": risk.value,
                "Risk label": risk.label,
                "Risk data %": risk.completeness,
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Symbol").reset_index(drop=True)


def sector_rotation() -> pd.DataFrame:
    """Rank sector proxies across multiple end-of-day horizons."""
    rows = []
    benchmark = get_history("SPY").data["Close"]
    for sector, symbol in SECTOR_ETFS.items():
        result = get_history(symbol)
        history = result.data
        close = history["Close"]
        returns = {
            "1M %": _period_return(close, 21),
            "3M %": _period_return(close, 63),
            "6M %": _period_return(close, 126),
        }
        relative = returns["3M %"] - _period_return(benchmark, 63)
        volume_ratio = float(
            history["Volume"].tail(10).mean() / history["Volume"].tail(50).mean()
        )
        liquidity = liquidity_rotation_6m(history)
        score = np.mean(
            [
                _normalize(returns["1M %"], -10, 15),
                _normalize(returns["3M %"], -20, 30),
                _normalize(returns["6M %"], -30, 50),
                _normalize(relative, -15, 20),
                _normalize(volume_ratio, 0.7, 1.5),
                liquidity["score"],
            ]
        )
        rows.append(
            {
                "Price · SMA50": price_sma_thumbnail(history),
                "Sector": sector,
                "ETF": symbol,
                **returns,
                "Relative 3M %": relative,
                "Volume ratio": volume_ratio,
                "6M liquidity score": liquidity["score"],
                "6M liquidity trend %": liquidity["trend"],
                "6M flow balance %": liquidity["flow_balance"],
                "Rotation score": round(float(score), 1),
                "Source": result.source,
            }
        )
    return pd.DataFrame(rows).sort_values("Rotation score", ascending=False)


def liquidity_rotation_6m(history: pd.DataFrame) -> dict[str, float]:
    """Measure six-month dollar-volume growth and accumulation balance."""
    if len(history[["Close", "Volume"]].dropna()) < 42:
        return {"score": 0.0, "trend": 0.0, "flow_balance": 0.0}
    return liquidity_rotation(history, 126)


def liquidity_rotation(history: pd.DataFrame, sessions: int) -> dict[str, float]:
    """Measure dollar-volume growth and accumulation over a session window."""
    window = history[["Close", "Volume"]].dropna().tail(sessions)
    minimum_sessions = min(sessions, 10)
    if len(window) < minimum_sessions:
        return {"score": 0.0, "trend": 0.0, "flow_balance": 0.0}

    dollar_volume = window["Close"] * window["Volume"]
    segment = max(5, min(21, len(window) // 3))
    baseline = float(dollar_volume.head(segment).mean())
    recent = float(dollar_volume.tail(segment).mean())
    trend = (recent / baseline - 1) * 100 if baseline > 0 else 0.0

    direction = window["Close"].pct_change()
    up_flow = float(dollar_volume[direction > 0].sum())
    down_flow = float(dollar_volume[direction < 0].sum())
    directional_total = up_flow + down_flow
    flow_balance = (
        (up_flow - down_flow) / directional_total * 100
        if directional_total > 0
        else 0.0
    )
    score = np.mean(
        [
            _normalize(trend, -30, 50),
            _normalize(flow_balance, -20, 20),
        ]
    )
    return {
        "score": round(float(score), 1),
        "trend": round(trend, 1),
        "flow_balance": round(flow_balance, 1),
    }


def industry_rotation(sector: str) -> pd.DataFrame:
    """Rank a sector's industries using equal-weight member evidence."""
    members = SECURITY_UNIVERSE[SECURITY_UNIVERSE["Sector"] == sector]
    if members.empty:
        return pd.DataFrame()

    sector_symbol = SECTOR_ETFS.get(sector, "SPY")
    sector_close = get_history(sector_symbol).data["Close"]
    rows = []
    for industry, industry_members in members.groupby("Industry", sort=False):
        industry = str(industry)
        proxy_symbol = INDUSTRY_ETFS.get(industry, sector_symbol)
        proxy_result = get_history(proxy_symbol)
        histories = {
            symbol: get_history(symbol).data
            for symbol in industry_members["Symbol"].tolist()
        }
        history = _aggregate_industry_history(histories)
        close = history["Close"]
        returns = {
            "1M %": _period_return(close, 21),
            "3M %": _period_return(close, 63),
            "6M %": _period_return(close, 126),
        }
        relative = returns["3M %"] - _period_return(sector_close, 63)
        breadth = (
            np.mean(
                [
                    float(member_history["Close"].iloc[-1])
                    > float(member_history["Close"].rolling(50).mean().iloc[-1])
                    for member_history in histories.values()
                ]
            )
            * 100
        )
        liquidity = liquidity_rotation_6m(history)
        score = np.mean(
            [
                _normalize(returns["1M %"], -10, 15),
                _normalize(returns["3M %"], -20, 30),
                _normalize(returns["6M %"], -30, 50),
                _normalize(relative, -15, 20),
                breadth,
                liquidity["score"],
            ]
        )
        rows.append(
            {
                "Price · SMA50": price_sma_thumbnail(proxy_result.data),
                "Industry": industry,
                "ETF": proxy_symbol,
                "ETF data": (
                    "Demonstration" if proxy_result.is_fallback else proxy_result.source
                ),
                "Members": len(industry_members),
                **returns,
                "Relative 3M %": relative,
                "Breadth above SMA50 %": round(float(breadth), 1),
                "6M liquidity score": liquidity["score"],
                "Industry score": round(float(score), 1),
            }
        )
    return pd.DataFrame(rows).sort_values("Industry score", ascending=False)


def _aggregate_industry_history(
    histories: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Build an equal-weight price index with aggregate member dollar volume."""
    normalized_closes = []
    dollar_volumes = []
    for history in histories.values():
        history = history[["Close", "Volume"]].dropna().tail(260)
        close = history["Close"]
        normalized_closes.append((close / close.iloc[0] * 100).rename("Close"))
        dollar_volumes.append((close * history["Volume"]).rename("Dollar volume"))

    close_index = pd.concat(normalized_closes, axis=1).mean(axis=1).dropna()
    dollar_volume = (
        pd.concat(dollar_volumes, axis=1).sum(axis=1).reindex(close_index.index)
    )
    synthetic_volume = dollar_volume / close_index
    return pd.DataFrame({"Close": close_index, "Volume": synthetic_volume})


def rank_sector_stocks(sector: str, industry: str | None = None) -> pd.DataFrame:
    """Rank representative securities in a sector and optional industry."""
    members = SECURITY_UNIVERSE[SECURITY_UNIVERSE["Sector"] == sector]
    if industry:
        members = members[members["Industry"] == industry]
    rows = []
    for member in members.itertuples(index=False):
        symbol = str(member.Symbol)
        result = analyze_security(symbol)
        rows.append(
            {
                "Price · SMA50": price_sma_thumbnail(result.history.data),
                "Symbol": symbol,
                "Company": member.Name,
                "Industry": member.Industry,
                "Price": result.latest_price,
                "Day %": result.daily_change,
                "Quality": result.analysis.quality.value,
                "Risk": result.analysis.risk.value,
                "Technical": result.analysis.technical.value,
                "Data %": min(
                    result.analysis.quality.completeness,
                    result.analysis.risk.completeness,
                    result.analysis.technical.completeness,
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["Quality", "Technical", "Risk"], ascending=[False, False, True]
    )


def universe_group_scores(universe: pd.DataFrame, group_column: str) -> pd.DataFrame:
    """Score current participation for sectors or industries in a universe."""
    rows = []
    for group, members in universe.groupby(group_column):
        changes = members["Day %"].dropna()
        average_change = float(changes.mean()) if not changes.empty else 0.0
        breadth = float((changes > 0).mean() * 100) if not changes.empty else 0.0
        score = np.mean(
            [
                _normalize(average_change, -3, 3),
                breadth,
            ]
        )
        rows.append(
            {
                group_column: group,
                "Members": len(members),
                "Day %": round(average_change, 2),
                "Advancing %": round(breadth, 1),
                "Market cap": float(members["Market cap"].fillna(0).sum()),
                "Participation score": round(float(score), 1),
            }
        )
    return pd.DataFrame(rows).sort_values("Participation score", ascending=False)


def mansfield_relative_strength(
    stock_close: pd.Series, industry_close: pd.Series
) -> float | None:
    """Return weekly Mansfield RS versus a 52-week relative-ratio average."""
    aligned = pd.concat(
        [stock_close.rename("stock"), industry_close.rename("industry")], axis=1
    ).dropna()
    if isinstance(aligned.index, pd.DatetimeIndex):
        aligned = aligned.resample("W-FRI").last().dropna()
    relative_ratio = aligned["stock"] / aligned["industry"]
    baseline = relative_ratio.rolling(52).mean()
    if len(relative_ratio) < 52 or pd.isna(baseline.iloc[-1]):
        return None
    return round(float((relative_ratio.iloc[-1] / baseline.iloc[-1] - 1) * 100), 2)


def rank_stocks_by_mansfield(
    histories: dict[str, pd.DataFrame], names: dict[str, str] | None = None
) -> pd.DataFrame:
    """Rank stocks against an equal-weight index of their own industry."""
    usable = {
        symbol: history
        for symbol, history in histories.items()
        if not history.empty and len(history["Close"].dropna()) >= 50
    }
    if not usable:
        return pd.DataFrame()
    industry_history = _aggregate_industry_history(usable)
    rows = []
    for symbol, history in usable.items():
        close = history["Close"].dropna()
        technical = score_technicals(history)
        rows.append(
            {
                "Price · SMA50": price_sma_thumbnail(history),
                "Symbol": symbol,
                "Company": (names or {}).get(symbol, symbol),
                "Price": float(close.iloc[-1]),
                "Mansfield RS": mansfield_relative_strength(
                    close, industry_history["Close"]
                ),
                "Technical": technical.value,
                "Data %": technical.completeness,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["Mansfield RS", "Technical"], ascending=False, na_position="last"
    )


def early_rotation_evidence(
    histories: dict[str, pd.DataFrame], benchmark_close: pd.Series
) -> dict[str, float | str]:
    """Detect early accumulation independently of established price momentum."""
    usable = {
        symbol: history.dropna(subset=["Close", "Volume"])
        for symbol, history in histories.items()
        if {"Close", "Volume"}.issubset(history.columns)
        and len(history.dropna(subset=["Close", "Volume"])) >= 50
    }
    if not usable:
        return {
            "Early rotation score": 0.0,
            "Early rotation signal": "Unavailable",
            "Breadth acceleration": 0.0,
            "RS inflection": 0.0,
            "Positive dollar volume": 0.0,
            "Close pressure": 0.0,
        }

    current_breadth = []
    prior_breadth = []
    dollar_volume_scores = []
    close_pressure_scores = []
    for history in usable.values():
        close = history["Close"]
        volume = history["Volume"]
        sma20 = close.rolling(20).mean()
        current_breadth.append(bool(close.iloc[-1] > sma20.iloc[-1]))
        prior_breadth.append(bool(close.iloc[-11] > sma20.iloc[-11]))

        recent_dollar_volume = float((close * volume).tail(5).mean())
        baseline_dollar_volume = float((close * volume).iloc[-45:-5].mean())
        volume_change = (
            (recent_dollar_volume / baseline_dollar_volume - 1) * 100
            if baseline_dollar_volume > 0
            else 0.0
        )
        five_day_return = _period_return(close, 5)
        signed_volume_change = (
            volume_change if five_day_return > 0 else -abs(volume_change)
        )
        dollar_volume_scores.append(_normalize(signed_volume_change, -30, 100))

        if {"High", "Low"}.issubset(history.columns):
            recent = history.tail(10)
            day_range = (recent["High"] - recent["Low"]).replace(0, np.nan)
            close_location = (
                ((recent["Close"] - recent["Low"]) / day_range)
                .clip(0, 1)
                .dropna()
            )
            weights = (recent["Close"] * recent["Volume"]).reindex(
                close_location.index
            )
            close_pressure_scores.append(
                float(np.average(close_location, weights=weights) * 100)
                if not close_location.empty and float(weights.sum()) > 0
                else 50.0
            )
        else:
            recent_close = close.tail(20)
            price_range = float(recent_close.max() - recent_close.min())
            close_pressure_scores.append(
                (float(close.iloc[-1] - recent_close.min()) / price_range * 100)
                if price_range > 0
                else 50.0
            )

    breadth_change = (
        float(np.mean(current_breadth) - np.mean(prior_breadth)) * 100
    )
    breadth_score = _normalize(breadth_change, -20, 30)

    industry_close = _aggregate_industry_history(usable)["Close"]
    aligned = pd.concat(
        [industry_close.rename("industry"), benchmark_close.rename("benchmark")],
        axis=1,
    ).dropna()
    if len(aligned) >= 31:
        relative = aligned["industry"] / aligned["benchmark"]
        recent_relative_return = _period_return(relative, 10)
        prior_relative_return = float(
            (relative.iloc[-11] / relative.iloc[-31] - 1) * 100
        )
        relative_inflection = recent_relative_return - prior_relative_return
        relative_score = _normalize(relative_inflection, -5, 8)
    else:
        relative_score = 50.0

    components = {
        "Breadth acceleration": breadth_score,
        "RS inflection": relative_score,
        "Positive dollar volume": float(np.mean(dollar_volume_scores)),
        "Close pressure": float(np.mean(close_pressure_scores)),
    }
    score = float(np.mean(list(components.values())))
    confirmations = sum(value >= 60 for value in components.values())
    if score >= 65 and confirmations >= 3:
        signal = "Emerging"
    elif score >= 55 and confirmations >= 2:
        signal = "Building"
    elif score < 35 and confirmations == 0:
        signal = "Fading"
    else:
        signal = "Neutral"
    return {
        "Early rotation score": round(score, 1),
        "Early rotation signal": signal,
        **{name: round(value, 1) for name, value in components.items()},
    }


def broad_rotation_scan(
    universe: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate all stocks across weekly through six-month liquidity horizons."""
    windows = {"1W": 5, "1M": 21, "3M": 63, "6M": 126}
    industry_rows = []
    market_histories = {
        symbol: history
        for symbol, history in histories.items()
        if len(history) >= 170 and {"Close", "Volume"}.issubset(history.columns)
    }
    benchmark_close = (
        _aggregate_industry_history(market_histories)["Close"]
        if market_histories
        else pd.Series(dtype=float)
    )
    group_columns = [
        column for column in ("Region", "Sector", "Industry") if column in universe
    ]
    for _, members in universe.groupby(group_columns):
        member_histories = {
            symbol: histories[symbol]
            for symbol in members["Symbol"]
            if symbol in histories and len(histories[symbol]) >= 170
        }
        if not member_histories:
            continue
        aggregate = _aggregate_industry_history(member_histories)
        close = aggregate["Close"]
        sma150 = close.rolling(150).mean()
        returns = {
            label: _period_return(close, min(sessions, len(close) - 1))
            for label, sessions in windows.items()
        }
        liquidity = {
            label: liquidity_rotation(aggregate, sessions)
            for label, sessions in windows.items()
        }
        liquidity_composite = float(
            np.mean([metrics["score"] for metrics in liquidity.values()])
        )
        flow_composite = float(
            np.mean([metrics["flow_balance"] for metrics in liquidity.values()])
        )
        momentum_change = float(
            np.mean(
                [
                    _normalize(returns["1W"], -5, 8),
                    _normalize(returns["1M"], -10, 15),
                ]
            )
            - np.mean(
                [
                    _normalize(returns["3M"], -20, 30),
                    _normalize(returns["6M"], -30, 50),
                ]
            )
        )
        liquidity_change = float(
            np.mean([liquidity[label]["score"] for label in ("1W", "1M")])
            - np.mean([liquidity[label]["score"] for label in ("3M", "6M")])
        )
        recent_flow = float(
            np.mean([liquidity[label]["flow_balance"] for label in ("1W", "1M")])
        )
        rotation_state = classify_rotation_state(
            momentum_change, liquidity_change, recent_flow
        )
        confirmations = sum(metrics["score"] >= 50 for metrics in liquidity.values())
        breadth = (
            np.mean(
                [
                    _is_above_rising_sma150(history)
                    for history in member_histories.values()
                ]
            )
            * 100
        )
        uptrend = bool(
            close.iloc[-1] > sma150.iloc[-1]
            and sma150.iloc[-1] > sma150.iloc[-20]
            and returns["3M"] > 0
            and returns["6M"] > 0
        )
        score = np.mean(
            [
                np.mean(
                    [
                        _normalize(returns["1W"], -5, 8),
                        _normalize(returns["1M"], -10, 15),
                        _normalize(returns["3M"], -20, 30),
                        _normalize(returns["6M"], -30, 50),
                    ]
                ),
                liquidity_composite,
                breadth,
            ]
        )
        early_rotation = early_rotation_evidence(
            member_histories, benchmark_close
        )
        representative = members.iloc[0]
        sector = str(representative["Sector"])
        industry = str(representative["Industry"])
        region = str(representative.get("Region", "United States"))
        industry_rows.append(
            {
            "Region": region,
                "Sector": sector,
                "Industry": industry,
                "Members": len(member_histories),
                **{
                    f"Return {label} %": round(value, 1)
                    for label, value in returns.items()
                },
                **{
                    f"Liquidity {label}": metrics["score"]
                    for label, metrics in liquidity.items()
                },
                **{
                    f"Flow {label} %": metrics["flow_balance"]
                    for label, metrics in liquidity.items()
                },
                "Liquidity composite": round(liquidity_composite, 1),
                "Flow composite %": round(flow_composite, 1),
                "Momentum change": round(momentum_change, 1),
                "Liquidity change": round(liquidity_change, 1),
                "Recent flow %": round(recent_flow, 1),
                "Rotation state": rotation_state,
                "Liquidity confirmations": confirmations,
                "Above rising SMA150 %": round(float(breadth), 1),
                "Rotation score": round(float(score), 1),
                "Winning": uptrend and confirmations >= 3 and breadth >= 50,
                **early_rotation,
            }
        )
    industries = pd.DataFrame(industry_rows)
    if industries.empty:
        return pd.DataFrame(), industries
    industries = industries.sort_values("Rotation score", ascending=False)
    sectors = (
        industries.groupby(["Region", "Sector"], as_index=False)
        .agg(
            Industries=("Industry", "count"),
            Winners=("Winning", "sum"),
            **{
                "Liquidity composite": ("Liquidity composite", "mean"),
                "Flow composite %": ("Flow composite %", "mean"),
                "Rotation score": ("Rotation score", "mean"),
            },
        )
        .sort_values("Rotation score", ascending=False)
    )
    return sectors, industries


def classify_rotation_state(
    momentum_change: float, liquidity_change: float, recent_flow: float
) -> str:
    """Classify whether short-horizon price and liquidity evidence is rotating."""
    if momentum_change > 0 and liquidity_change > 0 and recent_flow > 0:
        return "Gaining"
    if momentum_change < 0 and liquidity_change < 0 and recent_flow < 0:
        return "Losing"
    return "Mixed"


def breakout_candidates(
    universe: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    winning_industries: set[str | tuple[str, str, str]],
) -> pd.DataFrame:
    """Describe filterable stocks in selected industries with technical evidence."""
    rows = []
    names = universe.set_index("Symbol")
    for symbol, history in histories.items():
        if symbol not in names.index:
            continue
        member = names.loc[symbol]
        region = str(member.get("Region", "United States"))
        group = (region, str(member["Sector"]), str(member["Industry"]))
        selected = (
            group in winning_industries or member["Industry"] in winning_industries
        )
        if not selected or len(history) < 170:
            continue
        setup = analyze_long_swing_setup(history)
        close = history["Close"].dropna()
        distance_to_sma50 = setup.metrics["Distance to SMA50 %"]
        crossed_sma50_recently = bool(setup.metrics["Crossed SMA50 recently"])
        volume_trend_ratio = setup.metrics["Volume trend ratio"]
        returns = close.pct_change().dropna()
        volatility = float(returns.std() * np.sqrt(252) * 100)
        drawdown = close / close.cummax() - 1
        consolidation = all(
            setup.checks.get(name, False)
            for name in (
                "Base range no more than 15%",
                "Base volume controlled",
            )
        )
        rows.append(
            {
                "Price · SMA50": price_sma_thumbnail(history),
                "Symbol": symbol,
                "Company": member["Name"],
                "Region": region,
                "Country": member.get("Country", "Unknown"),
                "Exchange": member.get("Exchange", "Unknown"),
                "Currency": member.get("Currency", "Unknown"),
                "Sector": member["Sector"],
                "Industry": member["Industry"],
                "Price": float(close.iloc[-1]),
                "Setup state": setup.state,
                "Price above SMA50": setup.checks.get("Price above SMA50", False),
                "Near SMA50": abs(distance_to_sma50) <= 5.0,
                "Crossed SMA50 recently": crossed_sma50_recently,
                "Distance to SMA50 %": round(distance_to_sma50, 1),
                "SMA50 rising": setup.checks.get("SMA50 rising", False),
                "SMA50 slope 20D %": round(
                    setup.metrics["SMA50 slope 20D %"], 1
                ),
                "Price above SMA150": setup.checks.get("Price above SMA150", False),
                "Volume Evidence": setup.checks.get(
                    "Breakout volume at least 1.5x", False
                ),
                "Consolidation base": consolidation,
                "Heartbeat base": bool(
                    consolidation
                    and setup.metrics["Base length sessions"] >= 7
                    and setup.metrics["Heartbeat turns"] >= 2
                ),
                "Pivot": setup.pivot,
                "Base sessions": int(setup.metrics["Base length sessions"]),
                "Heartbeat turns": int(setup.metrics["Heartbeat turns"]),
                "Base range %": round(setup.metrics["Base range %"], 1),
                "From pivot %": round(-setup.metrics["Distance to pivot %"], 1),
                "Breakout volume": round(setup.metrics["Breakout volume ratio"], 2),
                "Volume increasing": volume_trend_ratio >= 1.10,
                "Volume trend ratio": round(volume_trend_ratio, 2),
                "Volatility %": round(volatility, 1),
                "Max drawdown %": round(float(drawdown.min() * 100), 1),
                "Setup score": setup.score,
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Setup score", ascending=False)


def analyze_long_swing_setup(history: pd.DataFrame) -> SwingSetup:
    """Evaluate trend, consolidation, and confirmed breakout evidence."""
    required = {"High", "Low", "Close", "Volume"}
    if len(history) < 170 or not required.issubset(history.columns):
        return SwingSetup("Insufficient data", 0.0, {}, {}, 0.0, 0.0, 0.0, 0.0)

    frame = history.dropna(subset=list(required)).copy()
    close = frame["Close"]
    sma50 = close.rolling(50).mean()
    sma150 = close.rolling(150).mean()
    volume50 = frame["Volume"].rolling(50).mean()
    atr = _average_true_range(frame)

    base_length, base = _select_consolidation_base(frame)
    base_high = float(base["High"].max())
    base_low = float(base["Low"].min())
    latest = frame.iloc[-1]
    latest_close = float(latest["Close"])
    base_range = (base_high - base_low) / max(0.01, float(base["Close"].iloc[-1]))
    distance_to_pivot = base_high / latest_close - 1
    base_start = len(frame) - base_length - 1
    impulse_start = max(0, base_start - 40)
    prior_advance = float(close.iloc[base_start] / close.iloc[impulse_start] - 1)
    prior_volume = float(
        frame["Volume"].iloc[impulse_start:base_start].median()
    )
    base_volume = float(base["Volume"].median())
    base_volume_ratio = base_volume / prior_volume if prior_volume > 0 else float("inf")
    directions = np.sign(base["Close"].diff().dropna())
    directions = directions[directions != 0]
    heartbeat_turns = int((directions != directions.shift(1)).sum() - 1)
    heartbeat_turns = max(0, heartbeat_turns)
    average_volume = float(volume50.iloc[-1])
    breakout_volume = (
        float(latest["Volume"]) / average_volume if average_volume > 0 else 0.0
    )
    recent_volume = float(frame["Volume"].tail(10).mean())
    baseline_volume = float(frame["Volume"].iloc[-50:-10].mean())
    volume_trend_ratio = (
        recent_volume / baseline_volume if baseline_volume > 0 else 0.0
    )
    distance_to_sma50 = float((latest_close / sma50.iloc[-1] - 1) * 100)
    crossed_sma50_recently = bool(
        latest_close >= sma50.iloc[-1] and close.iloc[-6] < sma50.iloc[-6]
    )
    day_range = max(0.01, float(latest["High"] - latest["Low"]))
    close_location = float((latest_close - latest["Low"]) / day_range)
    breakout = latest_close > base_high

    sma150_slope = float((sma150.iloc[-1] / sma150.iloc[-20] - 1) * 100)
    emerging_trend = bool(
        sma150_slope >= -1.0
        and sma50.iloc[-1] > sma150.iloc[-1]
        and sma50.iloc[-1] > sma50.iloc[-20]
    )
    checks = {
        "Price above SMA50": latest_close > sma50.iloc[-1],
        "Price above SMA150": latest_close > sma150.iloc[-1],
        "SMA50 rising": sma50.iloc[-1] > sma50.iloc[-20],
        "SMA150 rising or flattening after crossover": (
            sma150.iloc[-1] > sma150.iloc[-20] or emerging_trend
        ),
        "Prior advance at least 10%": prior_advance >= 0.10,
        "Base range no more than 15%": base_range <= 0.15,
        "Within 5% below pivot": 0 <= distance_to_pivot <= 0.05,
        "Base volume controlled": base_volume_ratio <= 1.10,
        "Breakout above pivot": breakout,
        "Breakout volume at least 1.5x": breakout_volume >= 1.5,
        "Breakout close in upper quartile": close_location >= 0.75,
    }
    trend_pass = all(
        checks[name]
        for name in (
            "Price above SMA50",
            "Price above SMA150",
            "SMA50 rising",
            "SMA150 rising or flattening after crossover",
        )
    )
    base_pass = all(
        checks[name]
        for name in (
            "Prior advance at least 10%",
            "Base range no more than 15%",
            "Base volume controlled",
        )
    )
    ready_pass = base_pass and checks["Within 5% below pivot"]
    breakout_pass = all(
        checks[name]
        for name in (
            "Breakout above pivot",
            "Breakout volume at least 1.5x",
            "Breakout close in upper quartile",
        )
    )
    if trend_pass and base_pass and breakout_pass:
        state = "Breakout confirmed"
    elif trend_pass and base_pass and breakout and not breakout_pass:
        state = "Price breakout · volume unconfirmed"
    elif trend_pass and ready_pass and not breakout:
        state = "Ready near pivot"
    elif not trend_pass:
        state = "Reject: trend"
    else:
        state = "Developing"

    relevant_checks = list(checks.values())
    score = round(100 * sum(relevant_checks) / len(relevant_checks), 1)
    entry = base_high + max(0.01, 0.25 * atr)
    atr_stop = entry - 2 * atr
    structural_stop = base_low - 0.25 * atr
    metrics = {
        "Close": latest_close,
        "SMA50": float(sma50.iloc[-1]),
        "SMA150": float(sma150.iloc[-1]),
        "Distance to SMA50 %": distance_to_sma50,
        "Crossed SMA50 recently": float(crossed_sma50_recently),
        "SMA50 slope 20D %": float((sma50.iloc[-1] / sma50.iloc[-20] - 1) * 100),
        "SMA150 slope 20D %": float((sma150.iloc[-1] / sma150.iloc[-20] - 1) * 100),
        "Base length sessions": float(base_length),
        "Heartbeat turns": float(heartbeat_turns),
        "Base range %": base_range * 100,
        "Distance to pivot %": distance_to_pivot * 100,
        "Prior advance %": prior_advance * 100,
        "Base volume ratio": base_volume_ratio,
        "Breakout volume ratio": breakout_volume,
        "Volume trend ratio": volume_trend_ratio,
        "Breakout close location %": close_location * 100,
        "ATR14": atr,
    }
    return SwingSetup(
        state,
        score,
        checks,
        metrics,
        base_high,
        entry,
        atr_stop,
        structural_stop,
    )


def _select_consolidation_base(frame: pd.DataFrame) -> tuple[int, pd.DataFrame]:
    """Choose the longest recent 5-20 session base no wider than 15%."""
    selected_length = 20
    selected = frame.iloc[-21:-1]
    for length in (20, 15, 10, 7, 5):
        candidate = frame.iloc[-length - 1 : -1]
        width = float(candidate["High"].max() - candidate["Low"].min()) / max(
            0.01, float(candidate["Close"].iloc[-1])
        )
        if width <= 0.15:
            return length, candidate
    return selected_length, selected


def calculate_position_plan(
    account_value: float,
    risk_percent: float,
    entry_price: float,
    stop_price: float,
) -> PositionPlan:
    """Size shares from planned loss, capped by available account capital."""
    if account_value <= 0 or risk_percent <= 0 or entry_price <= 0:
        raise ValueError("Account value, risk percent, and entry must be positive")
    if stop_price < 0 or stop_price >= entry_price:
        raise ValueError("Stop price must be non-negative and below entry price")
    risk_budget = account_value * risk_percent / 100
    risk_per_share = entry_price - stop_price
    risk_limited = int(risk_budget // risk_per_share)
    capital_limited = int(account_value // entry_price)
    shares = min(risk_limited, capital_limited)
    return PositionPlan(
        shares=shares,
        risk_budget=risk_budget,
        risk_per_share=risk_per_share,
        planned_loss=shares * risk_per_share,
        position_value=shares * entry_price,
        risk_limited_shares=risk_limited,
        capital_limited_shares=capital_limited,
    )


def calculate_reward_risk(
    entry_price: float, stop_price: float, target_price: float
) -> float:
    """Return the planned reward/risk multiple for a valid long trade."""
    if stop_price >= entry_price:
        raise ValueError("Stop price must be below entry price")
    if target_price <= entry_price:
        raise ValueError("Target price must be above entry price")
    return (target_price - entry_price) / (entry_price - stop_price)


def classify_market_regime(histories: dict[str, pd.DataFrame]) -> MarketRegime:
    """Classify risk appetite from equity, breadth, credit, and volatility proxies."""
    required = {"SPY", "IWM", "HYG", "IEF", "^VIX"}
    if not required.issubset(histories):
        return MarketRegime("Unavailable", 0, {})
    closes = {
        symbol: history["Close"].dropna() for symbol, history in histories.items()
    }
    spy = closes["SPY"]
    vix = closes["^VIX"]
    checks = {
        "SPY above rising SMA150": _is_above_rising_sma150(histories["SPY"]),
        "Small caps outperforming SPY over 3M": (
            _period_return(closes["IWM"], 63) > _period_return(spy, 63)
        ),
        "High yield outperforming Treasuries over 3M": (
            _period_return(closes["HYG"], 63) > _period_return(closes["IEF"], 63)
        ),
        "VIX below SMA50": bool(vix.iloc[-1] < vix.rolling(50).mean().iloc[-1]),
    }
    score = sum(checks.values())
    label = "Risk-on" if score >= 3 else "Mixed" if score == 2 else "Risk-off"
    return MarketRegime(label, score, checks)


def _is_above_rising_sma150(history: pd.DataFrame) -> bool:
    close = history["Close"].dropna()
    if len(close) < 170:
        return False
    sma150 = close.rolling(150).mean()
    return bool(close.iloc[-1] > sma150.iloc[-1] > sma150.iloc[-20])


def normalized_performance(symbols: list[str], period: str = "6mo") -> pd.DataFrame:
    """Return aligned growth-of-100 series for comparison charts."""
    series = {}
    for symbol in symbols:
        close = get_history(symbol, period).data["Close"].copy()
        if isinstance(close.index, pd.DatetimeIndex):
            close.index = close.index.tz_localize(None).normalize()
        series[symbol] = close / close.iloc[0] * 100
    return pd.DataFrame(series).dropna(how="all")


def analyze_metals(
    histories: Mapping[str, pd.DataFrame],
    proxies: Mapping[str, tuple[str, str]] = METAL_PROXIES,
    benchmark_symbol: str = METALS_BENCHMARK,
) -> pd.DataFrame:
    """Rank investable metal proxies using price, flow, and risk evidence."""
    benchmark = histories.get(benchmark_symbol)
    benchmark_close = (
        benchmark["Close"].dropna()
        if isinstance(benchmark, pd.DataFrame) and "Close" in benchmark
        else pd.Series(dtype=float)
    )
    rows = []
    for symbol, (metal, category) in proxies.items():
        history = histories.get(symbol)
        if not isinstance(history, pd.DataFrame) or not {"Close", "Volume"}.issubset(
            history.columns
        ):
            continue
        frame = history.dropna(subset=["Close", "Volume"])
        if len(frame) < 50:
            continue
        close = frame["Close"]
        volume = frame["Volume"]
        returns = {
            "1M %": _optional_period_return(close, 21),
            "3M %": _optional_period_return(close, 63),
            "6M %": _optional_period_return(close, 126),
        }
        benchmark_return = _optional_period_return(benchmark_close, 63)
        relative = (
            returns["3M %"] - benchmark_return
            if returns["3M %"] is not None and benchmark_return is not None
            else None
        )
        sma50 = close.rolling(50).mean()
        trend_components = [
            100.0 if close.iloc[-1] > sma50.iloc[-1] else 20.0,
            100.0 if len(close) >= 60 and sma50.iloc[-1] > sma50.iloc[-10] else 25.0,
        ]
        momentum_components = [
            _normalize(value, low, high)
            for value, low, high in (
                (returns["1M %"], -10, 15),
                (returns["3M %"], -20, 30),
                (returns["6M %"], -30, 50),
            )
            if value is not None
        ]
        volume_baseline = float(volume.tail(50).mean())
        volume_ratio = (
            float(volume.tail(10).mean() / volume_baseline)
            if volume_baseline > 0
            else None
        )
        liquidity = liquidity_rotation_6m(frame)
        participation_components = [liquidity["score"]]
        if volume_ratio is not None:
            participation_components.append(_normalize(volume_ratio, 0.7, 1.5))
        daily_returns = close.pct_change().dropna()
        volatility = float(daily_returns.std() * np.sqrt(252) * 100)
        drawdown = float((close / close.cummax() - 1).min() * -100)
        pillars = {
            "Momentum": _mean_or_none(momentum_components),
            "Trend": _mean_or_none(trend_components),
            "Relative strength": (
                _normalize(relative, -15, 20) if relative is not None else None
            ),
            "Participation": _mean_or_none(participation_components),
            "Risk resilience": np.mean(
                [
                    100.0 - _normalize(volatility, 15, 60),
                    100.0 - _normalize(drawdown, 10, 50),
                ]
            ),
        }
        available_pillars = [
            float(value) for value in pillars.values() if value is not None
        ]
        score = float(np.mean(available_pillars)) if available_pillars else 0.0
        rows.append(
            {
                "Metal": metal,
                "Symbol": symbol,
                "Category": category,
                "Price": float(close.iloc[-1]),
                "Day %": (
                    float(close.pct_change().iloc[-1] * 100)
                    if len(close) > 1
                    else 0.0
                ),
                **returns,
                "Relative 3M %": relative,
                "Volume ratio": volume_ratio,
                "Volatility %": volatility,
                "Max drawdown %": drawdown,
                **pillars,
                "Metal score": round(score, 1),
                "Signal": _metal_score_label(score),
                "Data completeness %": round(
                    len(available_pillars) / len(pillars) * 100, 1
                ),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Metal score", ascending=False).reset_index(
        drop=True
    )


def _optional_period_return(close: pd.Series, sessions: int) -> float | None:
    if len(close) <= sessions:
        return None
    return _period_return(close, sessions)


def _mean_or_none(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def _metal_score_label(score: float) -> str:
    if score >= 80:
        return "Strong"
    if score >= 65:
        return "Positive"
    if score >= 45:
        return "Neutral"
    return "Weak"


def _period_return(close: pd.Series, sessions: int) -> float:
    if len(close) <= sessions:
        return 0.0
    return float((close.iloc[-1] / close.iloc[-sessions - 1] - 1) * 100)


def _normalize(value: float, low: float, high: float) -> float:
    return max(0.0, min(100.0, 100 * (value - low) / (high - low)))
