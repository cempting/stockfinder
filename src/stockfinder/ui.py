"""Streamlit user interface for Stockfinder."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from stockfinder.analysis import (
    AnalysisResult,
    analyze_long_swing_setup,
    analyze_metals,
    analyze_security,
    breakout_candidates,
    broad_rotation_scan,
    build_market_risk_profiles,
    calculate_position_plan,
    calculate_reward_risk,
    classify_market_regime,
    industry_rotation,
    normalized_performance,
    rank_sector_stocks,
    rank_stocks_by_mansfield,
    sector_rotation,
    universe_group_scores,
)
from stockfinder.data import (
    INDUSTRY_ETFS,
    METAL_PROXIES,
    METALS_BENCHMARK,
    SECTOR_ETFS,
    SECURITY_UNIVERSE,
    DataResult,
    clear_market_data_caches,
    fundamental_metrics,
    fundamental_pillar_metrics,
    get_batch_histories,
    get_global_universe,
    get_history,
    get_market_universe,
    get_nasdaq_universe,
    get_news,
    get_profile,
)
from stockfinder.models import Score
from stockfinder.scoring import score_fundamentals
from stockfinder.storage import Repository, ScanSnapshot, ScanSnapshotStore

ROOT = Path(__file__).resolve().parents[2]
MARKET_SCAN_VERSION = "2026-09-global-listings-v10"
ROTATION_MODEL_VERSION = "legacy-sector"
INDUSTRY_MODEL_VERSION = "legacy-industry"
STOCK_RANKING_MODEL_VERSION = "legacy-stock"


@st.cache_resource
def repository() -> Repository:
    return Repository(ROOT / "data" / "stockfinder.db")


@st.cache_resource
def scan_snapshot_store() -> ScanSnapshotStore:
    return ScanSnapshotStore(ROOT / "data" / "latest_scan")


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def cached_analysis(symbol: str) -> AnalysisResult:
    return analyze_security(symbol)


@st.cache_data(ttl=60 * 60 * 3, show_spinner=False)
def cached_news(symbol: str) -> DataResult:
    return get_news(symbol)


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def cached_candidate_fundamentals(symbols: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
        result = get_profile(symbol)
        if result.is_fallback:
            rows.append({"Symbol": symbol, "Fundamental data": "Unavailable"})
            continue
        metrics = fundamental_metrics(result.data)
        score = score_fundamentals(metrics)
        rows.append(
            {
                "Symbol": symbol,
                "Growth": metrics.get("Growth"),
                "Quality": score.value,
                "Financial strength": metrics.get("Stability"),
                "Valuation": metrics.get("Valuation"),
                "Fundamental data": f"{score.completeness:.0f}%",
            }
        )
    return pd.DataFrame(rows).reindex(
        columns=[
            "Symbol",
            "Growth",
            "Quality",
            "Financial strength",
            "Valuation",
            "Fundamental data",
        ]
    )


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def cached_broad_universe(day_key: str, refresh_token: int) -> DataResult:
    del refresh_token
    return get_global_universe(date.fromisoformat(day_key))


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def cached_history_chunk(
    symbols: tuple[str, ...], period: str, refresh_token: int
) -> DataResult:
    del refresh_token
    return get_batch_histories(symbols, period)


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def cached_nasdaq_universe(day_key: str) -> DataResult:
    return get_nasdaq_universe(date.fromisoformat(day_key))


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def cached_market_universe(name: str, day_key: str) -> DataResult:
    return get_market_universe(name, date.fromisoformat(day_key))


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def cached_mansfield_ranking(
    symbols: tuple[str, ...], names: tuple[tuple[str, str], ...]
) -> tuple[pd.DataFrame, str | None]:
    histories = get_batch_histories(symbols)
    return rank_stocks_by_mansfield(histories.data, dict(names)), histories.warning


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def cached_sector_rotation(model_version: str) -> pd.DataFrame:
    del model_version
    return sector_rotation()


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def cached_industry_rotation(sector: str, model_version: str) -> pd.DataFrame:
    del model_version
    return industry_rotation(sector)


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def cached_sector_stocks(
    sector: str, industry: str, model_version: str
) -> pd.DataFrame:
    del model_version
    return rank_sector_stocks(sector, industry)


def main() -> None:
    st.set_page_config(
        page_title="Stockfinder",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="auto",
    )
    _theme()
    page, risk_profile, load_mode = _sidebar()

    if page == "Market pulse":
        _market_page(load_mode)
    elif page == "Rotation leaders":
        _sector_page(load_mode)
    elif page == "Metals":
        _metals_page()
    elif page == "Stocks":
        _stocks_page(risk_profile, load_mode)
    elif page == "Portfolio":
        _portfolio_page()
    else:
        _methodology_page(risk_profile, load_mode)


def _sidebar() -> tuple[str, str, str]:
    with st.sidebar:
        st.markdown('<div class="brand">STOCKFINDER</div>', unsafe_allow_html=True)
        st.caption("Evidence-led market research")
        pending_page = st.session_state.pop("pending_workspace_page", None)
        if pending_page:
            st.session_state["workspace_page"] = pending_page
        pages = [
            "Market pulse",
            "Rotation leaders",
            "Metals",
            "Stocks",
            "Portfolio",
            "Methodology",
        ]
        if st.session_state.get("workspace_page") not in pages:
            st.session_state["workspace_page"] = "Market pulse"
        page = st.radio(
            "Workspace",
            pages,
            key="workspace_page",
        )
        st.divider()
        risk_profile = st.segmented_control(
            "Risk profile",
            ["Conservative", "Balanced", "Aggressive"],
            default="Balanced",
        )
        with st.expander("Data controls"):
            extended = st.toggle(
                "Extended loading",
                help=(
                    "Load two years in smaller batches. This is slower but gives "
                    "more history and isolates provider failures more narrowly."
                ),
            )
            if st.button("Refresh now", width="stretch"):
                _force_market_refresh()
                st.rerun()
            st.caption(
                "Standard: 1 year / 200-symbol batches\n\n"
                "Extended: 2 years / 100-symbol batches"
            )
        st.caption("Daily data · refreshed after market close")
    return page, risk_profile or "Balanced", "extended" if extended else "standard"


def _metals_page() -> None:
    _heading(
        "Metals",
        "Physical-metal proxies ranked by momentum, trend, participation, and risk",
    )
    symbols = (*METAL_PROXIES, METALS_BENCHMARK)
    refresh_token = st.session_state.get("market_refresh_token", 0)
    with st.spinner("Loading one year of metals market history..."):
        result = cached_history_chunk(symbols, "1y", refresh_token)
    if result.warning:
        st.warning(result.warning)
    ranked = analyze_metals(result.data)
    st.caption(
        f"Source: {result.source} · retrieved "
        f"{result.retrieved_at.strftime('%Y-%m-%d %H:%M UTC')} · "
        "exchange-traded proxies, USD"
    )
    if ranked.empty:
        st.error("No metal proxy has enough usable history for analysis.")
        return

    leader = ranked.iloc[0]
    strongest_month = ranked.sort_values("1M %", ascending=False).iloc[0]
    positive_trends = int((ranked["Trend"] >= 65).sum())
    complete = len(ranked)
    leader_column, month_column, breadth_column, coverage_column = st.columns(4)
    leader_column.metric(
        "Composite leader",
        str(leader["Metal"]),
        f"{leader['Metal score']:.0f}/100 · {leader['Signal']}",
    )
    month_column.metric(
        "Strongest 1M",
        str(strongest_month["Metal"]),
        f"{strongest_month['1M %']:+.1f}%",
    )
    breadth_column.metric("Positive trends", f"{positive_trends} of {complete}")
    coverage_column.metric(
        "Proxy coverage", f"{complete} of {len(METAL_PROXIES)}"
    )

    pulse_tab, detail_tab, method_tab = st.tabs(
        ["Metals pulse", "Metal detail", "Methodology"]
    )
    with pulse_tab:
        st.plotly_chart(
            _metals_performance_chart(result.data, ranked), width="stretch"
        )
        st.dataframe(
            ranked,
            hide_index=True,
            width="stretch",
            column_config={
                "Price": st.column_config.NumberColumn(format="$%.2f"),
                "Day %": st.column_config.NumberColumn(format="%+.2f%%"),
                "1M %": st.column_config.NumberColumn(format="%+.1f%%"),
                "3M %": st.column_config.NumberColumn(format="%+.1f%%"),
                "6M %": st.column_config.NumberColumn(format="%+.1f%%"),
                "Relative 3M %": st.column_config.NumberColumn(format="%+.1f%%"),
                "Volume ratio": st.column_config.NumberColumn(format="%.2fx"),
                "Volatility %": st.column_config.NumberColumn(format="%.1f%%"),
                "Max drawdown %": st.column_config.NumberColumn(format="%.1f%%"),
                **{
                    column: st.column_config.ProgressColumn(
                        min_value=0, max_value=100
                    )
                    for column in (
                        "Momentum",
                        "Trend",
                        "Relative strength",
                        "Participation",
                        "Risk resilience",
                        "Metal score",
                        "Data completeness %",
                    )
                },
            },
        )

    with detail_tab:
        selected_metal = st.selectbox("Metal", ranked["Metal"].tolist())
        selected = ranked[ranked["Metal"] == selected_metal].iloc[0]
        symbol = str(selected["Symbol"])
        score_column, price_column, relative_column, risk_column = st.columns(4)
        score_column.metric(
            "Metal score",
            f"{selected['Metal score']:.0f}/100",
            str(selected["Signal"]),
        )
        price_column.metric(
            "Proxy price",
            f"${selected['Price']:,.2f}",
            f"{selected['Day %']:+.2f}% today",
        )
        relative_column.metric(
            "Vs broad commodities · 3M",
            f"{selected['Relative 3M %']:+.1f}%",
        )
        risk_column.metric(
            "Risk resilience",
            f"{selected['Risk resilience']:.0f}/100",
            f"{selected['Volatility %']:.1f}% volatility",
        )
        st.write(_metal_summary(selected))
        st.plotly_chart(
            _metal_price_chart(result.data[symbol], selected_metal), width="stretch"
        )
        evidence = pd.DataFrame(
            [
                (pillar, selected[pillar], _score_context(selected[pillar]))
                for pillar in (
                    "Momentum",
                    "Trend",
                    "Relative strength",
                    "Participation",
                    "Risk resilience",
                )
            ],
            columns=["Pillar", "Score", "Threshold context"],
        )
        st.dataframe(
            evidence,
            hide_index=True,
            width="stretch",
            column_config={
                "Score": st.column_config.ProgressColumn(min_value=0, max_value=100)
            },
        )

    with method_tab:
        st.markdown("### How the metal score works")
        st.write(
            "Momentum combines 1-, 3-, and 6-month returns. Trend checks price "
            "against its 50-day average and whether that average is rising. "
            "Relative strength compares the 3-month return with DBC, a broad "
            "commodity benchmark. Participation combines recent volume with "
            "six-month dollar-volume accumulation. Risk resilience rewards lower "
            "annualized volatility and shallower drawdowns."
        )
        st.write(
            "Available pillars are equally weighted. Missing pillars reduce data "
            "completeness instead of receiving a neutral score. The instruments "
            "are exchange-traded proxies, so returns can differ from spot metal "
            "prices because of fees, structure, liquidity, and tracking effects."
        )
        st.caption(
            "Scores summarize observed market evidence; they are not forecasts or "
            "investment recommendations."
        )


def _metals_performance_chart(
    histories: dict[str, pd.DataFrame], ranked: pd.DataFrame
) -> go.Figure:
    series = {}
    names = ranked.set_index("Symbol")["Metal"].to_dict()
    for symbol, metal in names.items():
        history = histories.get(symbol)
        if history is None or history.empty:
            continue
        close = history["Close"].dropna().tail(126)
        if not close.empty:
            series[str(metal)] = close / close.iloc[0] * 100
    performance = pd.DataFrame(series)
    figure = px.line(
        performance,
        labels={"value": "Growth of 100", "index": "Date", "variable": "Metal"},
        title="Six-month relative performance",
    )
    figure.update_layout(height=430, hovermode="x unified", legend_title_text="")
    return figure


def _metal_price_chart(history: pd.DataFrame, metal: object) -> go.Figure:
    close = history["Close"].dropna()
    sma50 = close.rolling(50).mean()
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=close.index, y=close, name=str(metal)))
    figure.add_trace(go.Scatter(x=sma50.index, y=sma50, name="SMA50"))
    figure.update_layout(
        title=f"{metal} proxy price and 50-day trend",
        height=440,
        hovermode="x unified",
        yaxis_title="USD",
    )
    return figure


def _metal_summary(metal: pd.Series) -> str:
    trend = "constructive" if metal["Trend"] >= 65 else "not yet constructive"
    if pd.isna(metal["Relative 3M %"]):
        relative = (
            "not comparable with broad commodities because benchmark data is missing"
        )
    else:
        relative = (
            "outperforming broad commodities"
            if metal["Relative 3M %"] >= 0
            else "underperforming broad commodities"
        )
    participation = (
        "supportive" if metal["Participation"] >= 65 else "mixed or weak"
    )
    return (
        f"{metal['Metal']} has a {str(metal['Signal']).lower()} composite signal. "
        f"Its price trend is {trend}, it is {relative} over three months, and "
        f"volume participation is {participation}."
    )


def _stocks_page(risk_profile: str, load_mode: str) -> None:
    pending_view = st.session_state.pop("pending_stocks_workspace_view", None)
    if pending_view:
        st.session_state["stocks_workspace_view"] = pending_view
    view = st.segmented_control(
        "Stocks workspace",
        ["Discover", "Research", "Watchlist"],
        default="Discover",
        key="stocks_workspace_view",
    )
    if view == "Research":
        _research_page(risk_profile)
    elif view == "Watchlist":
        _watchlist_page()
    else:
        _stocks_discovery_page(load_mode)


def _stocks_discovery_page(load_mode: str) -> None:
    _journey_progress(3)
    _heading(
        "Stocks",
        "Filter the global market, rank setup evidence, and open full research",
    )
    universe, _, _, candidates, history_warning = _load_scan(load_mode)
    _scan_freshness_notice()
    _scan_coverage_warning(history_warning)
    if candidates.empty:
        st.info("No stocks with sufficient cached history are available.")
        return
    stocks = _stock_discovery_frame(
        universe.data, candidates, _cached_risk_profiles()
    )

    total_column, region_column, sector_column, setup_column = st.columns(4)
    total_column.metric("Filterable stocks", f"{len(stocks):,}")
    region_column.metric("Regions", f"{stocks['Region'].nunique():,}")
    sector_column.metric("Sectors", f"{stocks['Sector'].nunique():,}")
    setup_column.metric(
        "Positive setups", f"{int((stocks['Setup score'] >= 65).sum()):,}"
    )
    st.caption(
        f"{len(universe.data):,} listings in the current market universe. "
        "Filterable rows require at least 170 sessions of usable price history."
    )

    search = st.text_input(
        "Search symbol or company", placeholder="AAPL or Apple", key="stocks_search"
    )
    with st.expander("Market and classification filters", expanded=True):
        region_column, sector_column, industry_column, exchange_column = st.columns(4)
        regions = region_column.multiselect(
            "Regions", sorted(stocks["Region"].dropna().unique())
        )
        sectors = sector_column.multiselect(
            "Sectors", sorted(stocks["Sector"].dropna().unique())
        )
        industries = industry_column.multiselect(
            "Industries", sorted(stocks["Industry"].dropna().unique())
        )
        exchanges = exchange_column.multiselect(
            "Exchanges", sorted(stocks["Exchange"].dropna().unique())
        )
    with st.expander("Price, setup, and risk filters", expanded=True):
        states = st.multiselect(
            "Setup states", sorted(stocks["Setup state"].dropna().unique())
        )
        price_min_column, price_max_column, cap_column = st.columns(3)
        minimum_price = price_min_column.number_input(
            "Minimum price", min_value=0.0, value=0.0, step=5.0
        )
        maximum_price = price_max_column.number_input(
            "Maximum price", min_value=0.0, value=10000.0, step=25.0
        )
        cap_label = cap_column.selectbox(
            "Minimum market cap",
            ["Any", "$300M", "$2B", "$10B", "$50B"],
        )
        minimum_market_cap = {
            "Any": 0.0,
            "$300M": 300e6,
            "$2B": 2e9,
            "$10B": 10e9,
            "$50B": 50e9,
        }[cap_label]
        setup_score_column, risk_column, volatility_column = st.columns(3)
        minimum_setup = setup_score_column.slider(
            "Minimum setup score", 0, 100, 50, 5
        )
        maximum_risk = risk_column.slider("Maximum market risk", 0, 100, 80, 5)
        maximum_volatility = volatility_column.slider(
            "Maximum annualized volatility %", 10, 200, 100, 5
        )
        sma50_column, sma150_column = st.columns(2)
        require_sma50 = sma50_column.toggle("Require price above SMA50")
        require_sma150 = sma150_column.toggle("Require price above SMA150")

    filtered = _filter_market_stocks(
        stocks,
        search=search,
        regions=tuple(regions),
        sectors=tuple(sectors),
        industries=tuple(industries),
        exchanges=tuple(exchanges),
        setup_states=tuple(states),
        minimum_price=minimum_price,
        maximum_price=maximum_price,
        minimum_market_cap=minimum_market_cap,
        minimum_setup=minimum_setup,
        maximum_risk=maximum_risk,
        maximum_volatility=maximum_volatility,
        require_sma50=require_sma50,
        require_sma150=require_sma150,
    )
    sort_label = st.selectbox(
        "Rank by",
        ["Setup score", "Market cap", "Day performance", "Lowest risk"],
    )
    sort_column, ascending = {
        "Setup score": ("Setup score", False),
        "Market cap": ("Market cap", False),
        "Day performance": ("Day %", False),
        "Lowest risk": ("Market risk", True),
    }[sort_label]
    filtered = filtered.sort_values(
        sort_column, ascending=ascending, na_position="last"
    )
    st.caption(f"Showing {len(filtered):,} of {len(stocks):,} filterable stocks")
    if filtered.empty:
        st.info("No stocks match the current filters.")
        return

    enrich = st.toggle(
        "Add fundamental scores to the top 50 matches",
        help=(
            "Fetches free company-profile data only for the current shortlist. "
            "Results are cached for six hours."
        ),
    )
    display = filtered.head(250).copy()
    if enrich:
        symbols = tuple(display["Symbol"].head(50))
        with st.spinner(f"Loading fundamentals for {len(symbols)} stocks..."):
            fundamentals = cached_candidate_fundamentals(symbols)
        display = display.merge(fundamentals, on="Symbol", how="left")

    selection = st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        height=650,
        row_height=72,
        key="global_stock_discovery",
        on_select="rerun",
        selection_mode="single-row",
        column_config=_stock_discovery_columns(),
    )
    if len(filtered) > len(display):
        st.caption("The table is capped at the top 250 ranked matches.")
    selected_rows = _selected_rows(selection)
    if selected_rows:
        selected = display.iloc[selected_rows[0]]
        st.session_state["research_symbol"] = str(selected["Symbol"])
        st.session_state["research_listing"] = {
            key: selected.get(key)
            for key in ("Symbol", "Region", "Country", "Exchange", "Currency")
        }
        st.session_state["pending_stocks_workspace_view"] = "Research"
        st.rerun()


def _stock_discovery_frame(
    universe: pd.DataFrame,
    candidates: pd.DataFrame,
    risk_profiles: pd.DataFrame,
) -> pd.DataFrame:
    market_columns = ["Symbol", "Market cap", "Volume", "Day %"]
    frame = candidates.merge(
        universe[market_columns].drop_duplicates("Symbol"), on="Symbol", how="left"
    )
    if not risk_profiles.empty:
        frame = frame.merge(
            risk_profiles[["Symbol", "Market risk", "Risk label", "ATR %"]],
            on="Symbol",
            how="left",
        )
    else:
        frame["Market risk"] = pd.NA
        frame["Risk label"] = "Unavailable"
        frame["ATR %"] = pd.NA
    return frame


def _stock_discovery_columns() -> dict[str, object]:
    progress = {
        column: st.column_config.ProgressColumn(min_value=0, max_value=100)
        for column in (
            "Setup score",
            "Market risk",
            "Quality",
            "Growth",
            "Financial strength",
            "Valuation",
        )
    }
    return {
        "Price · SMA50": st.column_config.ImageColumn(width=240),
        "Price": st.column_config.NumberColumn(format="%.2f"),
        "Day %": st.column_config.NumberColumn(format="%+.2f%%"),
        "Market cap": st.column_config.NumberColumn(format="$%.0f"),
        "Volume": st.column_config.NumberColumn(format="%.0f"),
        "Volatility %": st.column_config.NumberColumn(format="%.1f%%"),
        "Max drawdown %": st.column_config.NumberColumn(format="%.1f%%"),
        "ATR %": st.column_config.NumberColumn(format="%.1f%%"),
        "From pivot %": st.column_config.NumberColumn(format="%+.1f%%"),
        "Breakout volume": st.column_config.NumberColumn(format="%.2fx"),
        **progress,
    }


def _force_market_refresh() -> None:
    st.session_state["market_refresh_token"] = (
        st.session_state.get("market_refresh_token", 0) + 1
    )
    for key in list(st.session_state):
        if isinstance(key, str) and key.startswith("broad_scan_result_"):
            del st.session_state[key]
    st.session_state.pop("scan_risk_profiles", None)
    st.session_state["force_market_refresh"] = True
    clear_market_data_caches()


def _market_universe_analysis_page(name: str) -> None:
    _heading(
        f"{name} analysis",
        "Universe → sector → industry → Mansfield-ranked stocks",
    )
    with st.spinner(f"Refreshing {name} membership and classifications..."):
        result = cached_market_universe(name, date.today().isoformat())
    universe = result.data
    if result.warning:
        st.warning(result.warning)
    st.caption(
        f"Source: {result.source} · retrieved "
        f"{result.retrieved_at.strftime('%Y-%m-%d %H:%M UTC')}"
    )

    total, sector_count, industry_count = st.columns(3)
    total.metric("Stocks", f"{len(universe):,}")
    sector_count.metric("Sectors", f"{universe['Sector'].nunique():,}")
    industry_count.metric("Industries", f"{universe['Industry'].nunique():,}")

    sector_scores = universe_group_scores(universe, "Sector")
    st.subheader("Sector participation")
    st.dataframe(
        sector_scores,
        hide_index=True,
        width="stretch",
        column_config=_participation_columns(),
    )
    sectors = sector_scores["Sector"].tolist()
    sector = st.selectbox("Open sector", sectors, key=f"universe_sector_{name}")

    sector_members = universe[universe["Sector"] == sector]
    industry_scores = universe_group_scores(sector_members, "Industry")
    st.subheader(f"{sector} industries")
    st.dataframe(
        industry_scores,
        hide_index=True,
        width="stretch",
        column_config=_participation_columns(),
    )
    industries = industry_scores["Industry"].tolist()
    industry = st.selectbox(
        "Open industry",
        industries,
        key=f"universe_industry_{name}_{sector}",
    )

    members = sector_members[sector_members["Industry"] == industry]
    symbols = tuple(members["Symbol"].tolist())
    names = tuple(zip(members["Symbol"], members["Name"], strict=True))
    with st.spinner(
        f"Calculating weekly Mansfield RS for {len(symbols):,} {industry} stocks..."
    ):
        stocks, history_warning = cached_mansfield_ranking(symbols, names)
    st.subheader(f"{industry} stocks")
    st.caption(
        "Mansfield RS compares each stock with an equal-weight index of this "
        "industry and its trailing 52-week relative-ratio average."
    )
    if history_warning:
        st.warning(history_warning)
    if stocks.empty:
        st.info("No members have enough usable history for Mansfield ranking.")
        return
    selection = st.dataframe(
        stocks,
        hide_index=True,
        width="stretch",
        row_height=82,
        key=f"universe_stocks_{name}_{sector}_{industry}",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Price · SMA50": st.column_config.ImageColumn(
                width=260,
                help="Two-year price history (green) and SMA50 (amber).",
            ),
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "Mansfield RS": st.column_config.NumberColumn(format="%.2f"),
            "Technical": st.column_config.ProgressColumn(min_value=0, max_value=100),
        },
    )
    selected_rows = _selected_rows(selection)
    selected_symbol = (
        str(stocks.iloc[selected_rows[0]]["Symbol"]) if selected_rows else None
    )
    selection_id = (name, sector, industry, selected_symbol)
    if not selected_symbol:
        st.session_state.pop("processed_universe_candidate", None)
    elif st.session_state.get("processed_universe_candidate") != selection_id:
        st.session_state["processed_universe_candidate"] = selection_id
        st.session_state["research_symbol"] = selected_symbol
        st.session_state["pending_stocks_workspace_view"] = "Research"
        st.session_state["pending_workspace_page"] = "Stocks"
        st.rerun()


def _participation_columns():
    return {
        "Day %": st.column_config.NumberColumn(format="%.2f%%"),
        "Advancing %": st.column_config.NumberColumn(format="%.1f%%"),
        "Market cap": st.column_config.NumberColumn(format="$%.0f"),
        "Participation score": st.column_config.ProgressColumn(
            min_value=0, max_value=100
        ),
    }


def _rotation_change_columns():
    return {
        "Momentum change": st.column_config.NumberColumn(
            format="%+.1f",
            help="Short-horizon normalized momentum minus the 3M/6M baseline.",
        ),
        "Liquidity change": st.column_config.NumberColumn(
            format="%+.1f",
            help="Average 1W/1M liquidity score minus the 3M/6M average.",
        ),
        "Recent flow %": st.column_config.NumberColumn(
            format="%+.1f%%",
            help="Average 1W/1M up-day versus down-day dollar-volume balance.",
        ),
        "Above rising SMA150 %": st.column_config.NumberColumn(format="%.1f%%"),
    }


def _nasdaq_universe_page() -> None:
    _heading(
        "NASDAQ universe",
        "Daily public listing approximation · no liquidity exclusions",
    )
    with st.spinner("Refreshing the public NASDAQ stock universe..."):
        result = cached_nasdaq_universe(date.today().isoformat())
    universe = result.data
    if result.is_fallback:
        st.error(result.warning or "NASDAQ universe unavailable.")
    st.caption(
        f"Source: {result.source} · retrieved "
        f"{result.retrieved_at.strftime('%Y-%m-%d %H:%M UTC')}"
    )

    total, sectors, industries = st.columns(3)
    total.metric("Listed stocks", f"{len(universe):,}")
    sectors.metric("Mapped sectors", f"{universe['Sector'].nunique():,}")
    industries.metric("Provider industries", f"{universe['Industry'].nunique():,}")

    search_column, sector_column, industry_column = st.columns([2, 1, 1])
    search = search_column.text_input(
        "Search symbol or company",
        placeholder="AAPL or Apple",
    ).strip()
    sector_options = ["All sectors", *sorted(universe["Sector"].dropna().unique())]
    sector = sector_column.selectbox("Sector", sector_options)
    sector_frame = (
        universe if sector == "All sectors" else universe[universe["Sector"] == sector]
    )
    industry_options = [
        "All industries",
        *sorted(sector_frame["Industry"].dropna().unique()),
    ]
    industry = industry_column.selectbox("Industry", industry_options)

    filtered = sector_frame
    if industry != "All industries":
        filtered = filtered[filtered["Industry"] == industry]
    if search:
        search_mask = filtered["Symbol"].str.contains(
            search, case=False, regex=False
        ) | filtered["Name"].str.contains(search, case=False, regex=False)
        filtered = filtered[search_mask]

    st.caption(f"Showing {len(filtered):,} of {len(universe):,} stocks")
    display_columns = [
        "Symbol",
        "Name",
        "Sector",
        "Industry",
        "Last price",
        "Market cap",
        "Volume",
        "Country",
        "IPO year",
    ]
    selection = st.dataframe(
        filtered[display_columns],
        hide_index=True,
        width="stretch",
        height=620,
        key=f"nasdaq_universe_{sector}_{industry}_{search}",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Last price": st.column_config.NumberColumn(format="$%.2f"),
            "Market cap": st.column_config.NumberColumn(format="$%.0f"),
            "Volume": st.column_config.NumberColumn(format="%.0f"),
        },
    )
    selected_rows = _selected_rows(selection)
    selected_symbol = (
        str(filtered.iloc[selected_rows[0]]["Symbol"]) if selected_rows else None
    )
    selection_id = (sector, industry, search, selected_symbol)
    if not selected_symbol:
        st.session_state.pop("processed_nasdaq_symbol", None)
    elif st.session_state.get("processed_nasdaq_symbol") != selection_id:
        st.session_state["processed_nasdaq_symbol"] = selection_id
        st.session_state["research_symbol"] = selected_symbol
        st.session_state["pending_stocks_workspace_view"] = "Research"
        st.session_state["pending_workspace_page"] = "Stocks"
        st.rerun()


def _legacy_market_page(horizon: str) -> None:
    _heading("Market pulse", f"US regime overview · {horizon} profile")
    symbols = ["SPY", "QQQ", "IWM", "^VIX", "TLT", "GLD"]
    columns = st.columns(6)
    fallback_symbols = []
    for column, symbol in zip(columns, symbols, strict=True):
        result = get_history(symbol, "6mo")
        close = result.data["Close"]
        change = (close.iloc[-1] / close.iloc[-2] - 1) * 100
        column.metric(symbol, f"{close.iloc[-1]:,.2f}", f"{change:+.2f}%")
        if result.is_fallback:
            fallback_symbols.append(symbol)
    if fallback_symbols:
        st.warning("Demonstration data is active for: " + ", ".join(fallback_symbols))

    performance = normalized_performance(symbols[:3])
    figure = px.line(
        performance,
        labels={"value": "Growth of 100", "index": "Date", "variable": "Index"},
        color_discrete_sequence=["#0b6e4f", "#d95d39", "#2364aa"],
    )
    figure.update_layout(height=390, legend_title_text="", hovermode="x unified")
    st.plotly_chart(figure, width="stretch")

    rotation = cached_sector_rotation(ROTATION_MODEL_VERSION)
    leaders = rotation.head(3)
    laggards = rotation.tail(3).sort_values("Rotation score")
    left, right = st.columns(2)
    with left:
        st.subheader("Capital rotation leaders")
        leader_selection = st.dataframe(
            leaders[
                [
                    "Sector",
                    "1M %",
                    "3M %",
                    "6M liquidity score",
                    "Rotation score",
                ]
            ],
            hide_index=True,
            width="stretch",
            key="market_leaders",
            on_select="rerun",
            selection_mode="single-row",
        )
    with right:
        st.subheader("Areas under pressure")
        laggard_selection = st.dataframe(
            laggards[
                [
                    "Sector",
                    "1M %",
                    "3M %",
                    "6M liquidity score",
                    "Rotation score",
                ]
            ],
            hide_index=True,
            width="stretch",
            key="market_laggards",
            on_select="rerun",
            selection_mode="single-row",
        )
    selected_sector = _selected_sector(
        (leader_selection, leaders),
        (laggard_selection, laggards),
    )
    if not selected_sector:
        st.session_state.pop("processed_market_sector", None)
    elif st.session_state.get("processed_market_sector") != selected_sector:
        st.session_state["processed_market_sector"] = selected_sector
        st.session_state["selected_sector"] = selected_sector
        st.session_state["pending_workspace_page"] = "Sector rotation"
        st.rerun()


def _selected_sector(*tables: tuple[object, pd.DataFrame]) -> str | None:
    """Return the sector represented by the first selected table row."""
    for event, frame in tables:
        rows = _selected_rows(event)
        if rows:
            return str(frame.iloc[rows[0]]["Sector"])
    return None


def _legacy_sector_page() -> None:
    _heading(
        "Sector rotation",
        "Follow relative strength, six-month liquidity, and volume",
    )
    with st.spinner("Evaluating sector proxies..."):
        rotation = cached_sector_rotation(ROTATION_MODEL_VERSION)
    chart = px.bar(
        rotation.sort_values("Rotation score"),
        x="Rotation score",
        y="Sector",
        orientation="h",
        color="Rotation score",
        color_continuous_scale=["#d95d39", "#f4c95d", "#0b6e4f"],
        range_color=[0, 100],
    )
    chart.update_layout(height=470, coloraxis_showscale=False)
    st.plotly_chart(chart, width="stretch")
    st.dataframe(
        rotation,
        hide_index=True,
        width="stretch",
        height=520,
        row_height=82,
        column_config={
            "Price · SMA50": st.column_config.ImageColumn(
                width=260,
                help=("Six-month sector ETF price (green) and 50-day average (amber)."),
            ),
            "Rotation score": st.column_config.ProgressColumn(
                min_value=0, max_value=100
            ),
            "1M %": st.column_config.NumberColumn(format="%.1f%%"),
            "3M %": st.column_config.NumberColumn(format="%.1f%%"),
            "6M %": st.column_config.NumberColumn(format="%.1f%%"),
            "6M liquidity score": st.column_config.ProgressColumn(
                min_value=0,
                max_value=100,
                help=(
                    "Composite of six-month dollar-volume growth and the balance "
                    "between up-day and down-day dollar volume."
                ),
            ),
            "6M liquidity trend %": st.column_config.NumberColumn(format="%.1f%%"),
            "6M flow balance %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

    sectors = rotation["Sector"].tolist()
    selected_sector = st.session_state.pop("selected_sector", None)
    selected_index = sectors.index(selected_sector) if selected_sector in sectors else 0
    sector = str(
        st.selectbox("Open sector", sectors, index=selected_index) or sectors[0]
    )
    with st.spinner(f"Ranking {sector} industries..."):
        industries = cached_industry_rotation(sector, INDUSTRY_MODEL_VERSION)
    st.subheader(f"{sector} industry ranking")
    industry_selection = st.dataframe(
        industries,
        hide_index=True,
        width="stretch",
        row_height=82,
        key=f"sector_industries_{sector}",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Price · SMA50": st.column_config.ImageColumn(
                width=260,
                help=(
                    "Six-month representative industry ETF price (green) and "
                    "50-day average (amber)."
                ),
            ),
            "1M %": st.column_config.NumberColumn(format="%.1f%%"),
            "3M %": st.column_config.NumberColumn(format="%.1f%%"),
            "6M %": st.column_config.NumberColumn(format="%.1f%%"),
            "Relative 3M %": st.column_config.NumberColumn(format="%.1f%%"),
            "Breadth above SMA50 %": st.column_config.NumberColumn(format="%.0f%%"),
            "6M liquidity score": st.column_config.ProgressColumn(
                min_value=0, max_value=100
            ),
            "Industry score": st.column_config.ProgressColumn(
                min_value=0, max_value=100
            ),
        },
    )
    industry_rows = _selected_rows(industry_selection)
    active_industry_key = f"active_industry_{sector}"
    if industry_rows:
        industry = str(industries.iloc[industry_rows[0]]["Industry"])
        st.session_state[active_industry_key] = industry
    else:
        industry = str(
            st.session_state.get(
                active_industry_key, str(industries.iloc[0]["Industry"])
            )
        )

    with st.spinner(f"Evaluating representative {industry} securities..."):
        stocks = cached_sector_stocks(sector, industry, STOCK_RANKING_MODEL_VERSION)
    st.subheader(f"{industry} candidates")
    st.caption(
        "Representative development universe. Replace with licensed Russell 3000 "
        "membership before production use."
    )
    candidate_selection = st.dataframe(
        stocks,
        hide_index=True,
        width="stretch",
        row_height=82,
        key=f"sector_candidates_{sector}_{industry}",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "Day %": st.column_config.NumberColumn(format="%.2f%%"),
            "Price · SMA50": st.column_config.ImageColumn(
                width=260,
                help="Six-month closing price (green) and 50-day average (amber).",
            ),
            "Quality": st.column_config.ProgressColumn(min_value=0, max_value=100),
            "Risk": st.column_config.ProgressColumn(min_value=0, max_value=100),
            "Technical": st.column_config.ProgressColumn(min_value=0, max_value=100),
        },
    )
    selected_rows = _selected_rows(candidate_selection)
    selected_symbol = (
        str(stocks.iloc[selected_rows[0]]["Symbol"]) if selected_rows else None
    )
    selection_id = (sector, industry, selected_symbol) if selected_symbol else None
    if not selection_id:
        st.session_state.pop("processed_candidate", None)
    elif st.session_state.get("processed_candidate") != selection_id:
        st.session_state["processed_candidate"] = selection_id
        st.session_state["research_symbol"] = selected_symbol
        st.session_state["pending_stocks_workspace_view"] = "Research"
        st.session_state["pending_workspace_page"] = "Stocks"
        st.rerun()


def _load_scan(
    load_mode: str,
) -> tuple[DataResult, pd.DataFrame, pd.DataFrame, pd.DataFrame, str | None]:
    refresh_token = st.session_state.get("market_refresh_token", 0)
    result_key = (
        f"broad_scan_result_{date.today().isoformat()}_{load_mode}_"
        f"{MARKET_SCAN_VERSION}_{refresh_token}"
    )
    if result_key in st.session_state:
        return st.session_state[result_key]

    if not st.session_state.get("force_market_refresh", False):
        snapshot = scan_snapshot_store().load()
        if (
            snapshot is not None
            and snapshot.mode == load_mode
            and snapshot.model_version == MARKET_SCAN_VERSION
            and not snapshot.risk_profiles.empty
        ):
            universe_result = DataResult(
                snapshot.universe,
                snapshot.source,
                snapshot.completed_at,
                warning=snapshot.warning,
            )
            industries = _ensure_rotation_columns(snapshot.industries)
            result = (
                universe_result,
                snapshot.sectors,
                industries,
                snapshot.candidates,
                snapshot.warning,
            )
            st.session_state[result_key] = result
            st.session_state["scan_snapshot_meta"] = {
                "completed_at": snapshot.completed_at,
                "coverage": snapshot.coverage,
                "mode": snapshot.mode,
                "source": snapshot.source,
            }
            st.session_state["scan_risk_profiles"] = snapshot.risk_profiles
            return result

    period = "2y" if load_mode == "extended" else "1y"
    chunk_size = 100 if load_mode == "extended" else 200
    with st.status("Preparing broad market scan", expanded=True) as status:
        status.write("Refreshing US membership and curated international listings...")
        universe_result = cached_broad_universe(date.today().isoformat(), refresh_token)
        symbols = tuple(universe_result.data["Symbol"].tolist())
        status.write(f"Found {len(symbols):,} classified and curated listings.")
        progress = st.progress(0, text="Waiting for price batches")
        histories: dict[str, pd.DataFrame] = {}
        warnings = []
        chunks = [
            symbols[offset : offset + chunk_size]
            for offset in range(0, len(symbols), chunk_size)
        ]
        for index, chunk in enumerate(chunks, start=1):
            chunk_result = cached_history_chunk(chunk, period, refresh_token)
            histories.update(chunk_result.data)
            if chunk_result.warning:
                warnings.append(chunk_result.warning)
            completed = min(index * chunk_size, len(symbols))
            progress.progress(
                index / len(chunks),
                text=(
                    f"Price history: {completed:,}/{len(symbols):,} symbols · "
                    f"{len(histories):,} usable"
                ),
            )
        status.write("Aggregating sectors and industries across four horizons...")
        sectors, industries = broad_rotation_scan(universe_result.data, histories)
        industries = _ensure_rotation_columns(industries)
        status.write("Building adjustable stock evidence for gaining industries...")
        industry_groups = set(
            industries[["Region", "Sector", "Industry"]].itertuples(
                index=False, name=None
            )
        )
        candidates = breakout_candidates(
            universe_result.data, histories, industry_groups
        )
        status.write("Profiling cached price risk for every usable stock...")
        risk_profiles = build_market_risk_profiles(histories)
        coverage = len(histories) / max(1, len(symbols)) * 100
        provider_note = " · Some provider batches had gaps" if warnings else ""
        warning = (
            f"History coverage: {len(histories):,}/{len(symbols):,} "
            f"({coverage:.1f}%){provider_note}"
        )
        status.update(
            label=(
                f"Scan complete · {len(industries):,} industries · "
                f"{len(candidates):,} filterable stocks"
            ),
            state="complete",
            expanded=False,
        )
    completed_at = datetime.now(UTC)
    scan_snapshot_store().save(
        ScanSnapshot(
            universe=universe_result.data,
            sectors=sectors,
            industries=industries,
            candidates=candidates,
            completed_at=completed_at,
            source=universe_result.source,
            coverage=coverage,
            mode=load_mode,
            model_version=MARKET_SCAN_VERSION,
            warning=warning,
            risk_profiles=risk_profiles,
        )
    )
    st.session_state["scan_snapshot_meta"] = {
        "completed_at": completed_at,
        "coverage": coverage,
        "mode": load_mode,
        "source": universe_result.source,
    }
    st.session_state["force_market_refresh"] = False
    st.session_state["scan_risk_profiles"] = risk_profiles
    result = universe_result, sectors, industries, candidates, warning
    st.session_state[result_key] = result
    return result


def _ensure_rotation_columns(industries: pd.DataFrame) -> pd.DataFrame:
    """Add rotation deltas when an older hot-loaded analysis module omits them."""
    required = {
        "Momentum change",
        "Liquidity change",
        "Recent flow %",
        "Rotation state",
    }
    if industries.empty or required.issubset(industries.columns):
        return industries
    frame = industries.copy()

    def normalized(column: str, low: float, high: float) -> pd.Series:
        return (100 * (frame[column] - low) / (high - low)).clip(0, 100)

    frame["Momentum change"] = (
        (
            normalized("Return 1W %", -5, 8)
            + normalized("Return 1M %", -10, 15)
        )
        / 2
        - (
            normalized("Return 3M %", -20, 30)
            + normalized("Return 6M %", -30, 50)
        )
        / 2
    ).round(1)
    frame["Liquidity change"] = (
        (frame["Liquidity 1W"] + frame["Liquidity 1M"]) / 2
        - (frame["Liquidity 3M"] + frame["Liquidity 6M"]) / 2
    ).round(1)
    frame["Recent flow %"] = (
        (frame["Flow 1W %"] + frame["Flow 1M %"]) / 2
    ).round(1)
    frame["Rotation state"] = frame.apply(_rotation_state_from_row, axis=1)
    return frame


def _cached_risk_profiles() -> pd.DataFrame:
    profiles = st.session_state.get("scan_risk_profiles")
    if isinstance(profiles, pd.DataFrame):
        return profiles
    snapshot = scan_snapshot_store().load()
    if snapshot is None:
        return pd.DataFrame()
    st.session_state["scan_risk_profiles"] = snapshot.risk_profiles
    return snapshot.risk_profiles


def _enrich_with_cached_risk(frame: pd.DataFrame) -> pd.DataFrame:
    profiles = _cached_risk_profiles().rename(
        columns={
            "Symbol": "symbol",
            "Last price": "last_price",
            "Market risk": "market_risk",
            "Risk label": "risk_label",
            "ATR %": "atr_%",
        }
    )
    columns = ["symbol", "last_price", "market_risk", "risk_label", "atr_%"]
    if "symbol" not in profiles:
        profiles = pd.DataFrame(columns=columns)
    else:
        profiles = profiles.reindex(columns=columns)
    return frame.merge(profiles, on="symbol", how="left")


def _rotation_state_from_row(row: pd.Series) -> str:
    signals = (
        float(row["Momentum change"]),
        float(row["Liquidity change"]),
        float(row["Recent flow %"]),
    )
    if all(value > 0 for value in signals):
        return "Gaining"
    if all(value < 0 for value in signals):
        return "Losing"
    return "Mixed"


def _market_page(load_mode: str) -> None:
    _journey_progress(1)
    _heading("Market pulse", "Follow momentum as liquidity rotates between industries")
    st.caption(
        "Built for active rotation decisions rather than a passive buy-and-hold "
        "assumption. Gaining and losing states require price momentum, liquidity, "
        "and recent directional volume to agree."
    )
    symbols = ["SPY", "QQQ", "IWM", "^VIX", "TLT", "GLD"]
    columns = st.columns(6)
    market_histories = {}
    for column, symbol in zip(columns, symbols, strict=True):
        result = get_history(symbol, "1y")
        market_histories[symbol] = result.data
        close = result.data["Close"]
        change = (close.iloc[-1] / close.iloc[-2] - 1) * 100
        column.metric(symbol, f"{close.iloc[-1]:,.2f}", f"{change:+.2f}%")

    for symbol in ("HYG", "IEF", "UUP", "DBC"):
        market_histories[symbol] = get_history(symbol, "1y").data
    regime = classify_market_regime(market_histories)
    regime_column, equity_column, credit_column = st.columns(3)
    regime_column.metric("Market regime", regime.label, f"{regime.score}/4 checks")
    equity_check = regime.checks.get("SPY above rising SMA150", False)
    credit_check = regime.checks.get(
        "High yield outperforming Treasuries over 3M", False
    )
    equity_column.metric("Equity trend", "Supportive" if equity_check else "Defensive")
    credit_column.metric(
        "Credit appetite", "Supportive" if credit_check else "Defensive"
    )
    with st.expander("Market regime evidence"):
        st.dataframe(
            pd.DataFrame(
                [
                    (name, "Supportive" if passed else "Defensive")
                    for name, passed in regime.checks.items()
                ],
                columns=["Signal", "State"],
            ),
            hide_index=True,
            width="stretch",
        )

    st.subheader("Cross-asset direction")
    cross_asset_rows = []
    for symbol in ("SPY", "IWM", "HYG", "IEF", "TLT", "UUP", "GLD", "DBC"):
        close = market_histories[symbol]["Close"].dropna()
        cross_asset_rows.append(
            (
                symbol,
                (close.iloc[-1] / close.iloc[-22] - 1) * 100,
                (close.iloc[-1] / close.iloc[-64] - 1) * 100,
                "Above"
                if close.iloc[-1] > close.rolling(150).mean().iloc[-1]
                else "Below",
            )
        )
    st.dataframe(
        pd.DataFrame(
            cross_asset_rows,
            columns=["Proxy", "1M %", "3M %", "Versus SMA150"],
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "1M %": st.column_config.NumberColumn(format="%.1f%%"),
            "3M %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    st.caption(
        "Cross-asset direction and industry accumulation are price/volume proxies. "
        "They do not measure subscriptions, redemptions, or cash flows directly."
    )

    performance = normalized_performance(symbols[:3])
    figure = px.line(
        performance,
        labels={"value": "Growth of 100", "index": "Date", "variable": "Index"},
        color_discrete_sequence=["#49c28a", "#f4c95d", "#4f8edc"],
    )
    figure.update_layout(height=330, legend_title_text="", hovermode="x unified")
    st.plotly_chart(figure, width="stretch")

    universe, _, industries, _, history_warning = _load_scan(load_mode)
    risk_profiles = _cached_risk_profiles()
    _scan_freshness_notice()
    _scan_coverage_warning(history_warning)
    st.caption(
        f"{len(universe.data):,} US and curated international listings · "
        f"{len(risk_profiles):,} cached market-risk profiles · "
        "1W, 1M, 3M, and 6M liquidity always analyzed"
    )
    for labels in (("1W", "1M"), ("3M", "6M")):
        horizon_columns = st.columns(2)
        for column, label in zip(horizon_columns, labels, strict=True):
            column.metric(
                f"{label} market liquidity",
                f"{industries[f'Liquidity {label}'].mean():.0f} / 100",
                f"Flow {industries[f'Flow {label} %'].mean():+.1f}%",
            )
    losing = industries[industries["Rotation state"] == "Losing"].sort_values(
        ["Momentum change", "Liquidity change"]
    )
    established_winners = industries[industries["Winning"]].sort_values(
        "Rotation score", ascending=False
    )
    winning_count, losing_count, total_count = st.columns(3)
    winning_count.metric("Winning industries", f"{len(established_winners):,}")
    losing_count.metric("Losing industries", f"{len(losing):,}")
    total_count.metric("Regional industries", f"{len(industries):,}")
    st.subheader("Industry rotation now")
    gain_column, loss_column = st.columns(2)
    rotation_columns = [
        "Region",
        "Sector",
        "Industry",
        "Momentum change",
        "Liquidity change",
        "Recent flow %",
        "Above rising SMA150 %",
    ]
    with gain_column:
        st.markdown("**Winning industries**")
        st.dataframe(
            established_winners[rotation_columns].head(10),
            hide_index=True,
            width="stretch",
            column_config=_rotation_change_columns(),
        )
    with loss_column:
        st.markdown("**Losing momentum and liquidity**")
        st.dataframe(
            losing[rotation_columns].head(10),
            hide_index=True,
            width="stretch",
            column_config=_rotation_change_columns(),
        )
    st.caption(
        "Change values compare normalized 1W/1M evidence with 3M/6M evidence. "
        "Positive values indicate acceleration; negative values indicate decay. "
        "Directional volume is a price/volume proxy, not observed fund flow."
    )
    rotation_view = st.segmented_control(
        "Industry direction",
        ["Winning", "Losing"],
        default="Winning",
        key="market_industry_direction",
    )
    selected_frame = established_winners if rotation_view == "Winning" else losing
    if not selected_frame.empty:
        selected_position = st.selectbox(
            "Industry proxy chart",
            range(len(selected_frame)),
            format_func=lambda position: _industry_option_label(
                selected_frame.iloc[position]
            ),
            key=f"market_industry_proxy_{rotation_view}",
        )
        selected_industry = selected_frame.iloc[int(selected_position)]
        proxy, proxy_kind = _industry_proxy(selected_industry)
        proxy_result = get_history(proxy, "1y")
        if proxy_result.warning:
            st.warning(proxy_result.warning)
        st.plotly_chart(
            _industry_proxy_figure(
                proxy, proxy_result.data, market_histories["SPY"]
            ),
            width="stretch",
        )
        st.caption(
            f"Proxy: {proxy} · {proxy_kind} · Source: {proxy_result.source}. The ETF "
            "is a tradable proxy, not the exact equal-weight industry index used "
            "by the rotation model."
        )
    st.subheader("Industry liquidity flow")
    heatmap = px.treemap(
        industries,
        path=["Region", "Sector", "Industry"],
        values="Members",
        color="Liquidity composite",
        color_continuous_scale=["#d95d39", "#263238", "#49c28a"],
        range_color=[0, 100],
        hover_data=[
            "Liquidity 1W",
            "Liquidity 1M",
            "Liquidity 3M",
            "Liquidity 6M",
            "Flow 1W %",
            "Flow 1M %",
            "Flow 3M %",
            "Flow 6M %",
            "Momentum change",
            "Liquidity change",
            "Rotation state",
            "Above rising SMA150 %",
        ],
        custom_data=["Region", "Sector", "Industry"],
    )
    heatmap.update_layout(height=560, margin={"t": 15, "l": 0, "r": 0, "b": 0})
    heatmap_selection = st.plotly_chart(
        heatmap,
        width="stretch",
        key="industry_liquidity_heatmap",
        on_select="rerun",
        selection_mode="points",
    )
    st.subheader("Gaining industries with investable trends")
    winning_industries = industries[
        industries["Winning"] & (industries["Rotation state"] == "Gaining")
    ].head(10)
    winner_selection = st.dataframe(
        winning_industries,
        hide_index=True,
        width="stretch",
        key="market_winning_industries",
        on_select="rerun",
        selection_mode="single-row",
    )
    selected_context = _selected_rotation_context(
        heatmap_selection, winner_selection, winning_industries
    )
    if selected_context:
        st.session_state["selected_rotation_context"] = selected_context
        st.session_state["pending_workspace_page"] = "Rotation leaders"
        st.rerun()
    if st.button("Open rotation leaders", type="primary"):
        st.session_state["pending_workspace_page"] = "Rotation leaders"
        st.rerun()


def _industry_option_label(row: pd.Series) -> str:
    confirmation = " · established winner" if bool(row.get("Winning")) else ""
    return f"{row['Industry']} · {row['Sector']}{confirmation}"


def _industry_proxy(row: pd.Series) -> tuple[str, str]:
    industry = str(row["Industry"])
    sector = str(row["Sector"])
    proxy = INDUSTRY_ETFS.get(industry)
    if proxy:
        return proxy, "representative industry ETF"
    proxy = SECTOR_ETFS.get(sector, "SPY")
    return proxy, "sector ETF fallback"


def _industry_proxy_figure(
    proxy: str, history: pd.DataFrame, benchmark_history: pd.DataFrame
) -> go.Figure:
    close = history["Close"].dropna()
    benchmark = benchmark_history["Close"].dropna()
    normalized = close / close.iloc[0] * 100
    benchmark_normalized = benchmark / benchmark.iloc[0] * 100
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(x=normalized.index, y=normalized, name=proxy, line={"width": 3})
    )
    figure.add_trace(
        go.Scatter(
            x=normalized.index,
            y=normalized.rolling(50).mean(),
            name="SMA50",
            line={"color": "#2364aa"},
        )
    )
    figure.add_trace(
        go.Scatter(
            x=normalized.index,
            y=normalized.rolling(150).mean(),
            name="SMA150",
            line={"color": "#d4a017"},
        )
    )
    figure.add_trace(
        go.Scatter(
            x=benchmark_normalized.index,
            y=benchmark_normalized,
            name="SPY",
            line={"color": "#7d8990", "dash": "dot"},
        )
    )
    figure.update_layout(
        height=390,
        yaxis_title="Growth of 100",
        legend_title_text="",
        hovermode="x unified",
    )
    return figure


def _sector_page(load_mode: str) -> None:
    _journey_progress(2)
    _heading("Rotation leaders", "Gaining industries and fundamentally strong setups")
    st.caption(
        "Start with gaining short-horizon momentum or broaden the industry state "
        "to inspect European, Asian, and other listing markets. The Winning flag "
        "adds established trend, breadth, and liquidity confirmation."
    )
    _, sectors, industries, candidates, history_warning = _load_scan(load_mode)
    _scan_freshness_notice()
    _scan_coverage_warning(history_warning)
    stock_counts = (
        candidates.groupby(["Region", "Sector", "Industry"])
        .size()
        .rename("Stocks")
        if not candidates.empty
        else pd.Series(dtype=int, name="Stocks")
    )
    momentum_state = st.segmented_control(
        "Industry momentum",
        ["Gaining", "Winning", "Losing", "Mixed", "All"],
        default="Gaining",
    )
    if momentum_state == "Winning":
        winners = industries[industries["Winning"]].copy()
    elif momentum_state == "All":
        winners = industries.copy()
    else:
        winners = industries[industries["Rotation state"] == momentum_state].copy()
    winners = winners.join(
        stock_counts, on=["Region", "Sector", "Industry"]
    ).fillna({"Stocks": 0})
    winners["Stocks"] = winners["Stocks"].astype(int)
    sector_stocks = winners.groupby(["Region", "Sector"])["Stocks"].sum()
    gaining_winner_counts = winners.groupby(["Region", "Sector"]).size()
    sector_index_keys = sectors.set_index(["Region", "Sector"]).index
    winning_sectors = sectors[
        sector_index_keys.isin(gaining_winner_counts.index)
    ].copy()
    winning_sectors["Winners"] = (
        winning_sectors.set_index(["Region", "Sector"])
        .index.map(gaining_winner_counts)
        .fillna(0)
        .astype(int)
    )
    winning_sectors["Stocks"] = (
        winning_sectors.set_index(["Region", "Sector"])
        .index.map(sector_stocks)
        .fillna(0)
    )
    winning_sectors = winning_sectors.sort_values(
        ["Stocks", "Rotation score"], ascending=False
    )
    if winners.empty:
        st.info("No industries pass the current uptrend and liquidity filters.")
        return
    selected_context = st.session_state.pop("selected_rotation_context", None)
    region_options = winning_sectors["Region"].drop_duplicates().tolist()
    selected_region = selected_context[0] if selected_context else None
    region_index = (
        region_options.index(selected_region)
        if selected_region in region_options
        else 0
    )
    region = st.selectbox("Listing region", region_options, index=region_index)
    regional_sectors = winning_sectors[winning_sectors["Region"] == region]
    sector_options = regional_sectors["Sector"].tolist()
    selected_sector = selected_context[1] if selected_context else None
    sector_index = (
        sector_options.index(selected_sector)
        if selected_sector in sector_options
        else 0
    )
    sector = st.selectbox("Sector", sector_options, index=sector_index)
    sector_industries = winners[
        (winners["Region"] == region) & (winners["Sector"] == sector)
    ].sort_values(
        ["Stocks", "Rotation score"], ascending=False
    )
    st.subheader(f"{region} · {sector} industries")
    st.dataframe(sector_industries, hide_index=True, width="stretch")
    industry_options = sector_industries["Industry"].tolist()
    selected_industry = selected_context[2] if selected_context else None
    industry_index = (
        industry_options.index(selected_industry)
        if selected_industry in industry_options
        else 0
    )
    industry = st.selectbox("Industry", industry_options, index=industry_index)
    stocks = candidates[
        (candidates["Region"] == region)
        & (candidates["Sector"] == sector)
        & (candidates["Industry"] == industry)
    ]
    st.subheader(f"{industry} stock candidates")
    st.caption(
        "Enable or disable each core rule, then refine the remaining candidates "
        "with numeric thresholds."
    )
    if stocks.empty:
        st.info("No stocks with sufficient cached history are available.")
        return
    risk_profiles = _cached_risk_profiles()
    if not risk_profiles.empty:
        stocks = stocks.merge(
            risk_profiles[["Symbol", "Market risk", "Risk label", "ATR %"]],
            on="Symbol",
            how="left",
        )
    available_states = stocks["Setup state"].dropna().unique().tolist()
    with st.expander("Technical and price-chart filters", expanded=True):
        st.markdown("**Core rules**")
        (
            sma50_column,
            sma150_column,
            volume_rule_column,
            base_rule_column,
        ) = st.columns(4)
        require_sma50 = sma50_column.toggle("Price above SMA50", value=True)
        require_sma150 = sma150_column.toggle("Price above SMA150", value=True)
        require_volume = volume_rule_column.toggle("Volume Evidence", value=False)
        require_base = base_rule_column.toggle("Consolidation base", value=True)
        st.caption(
            "Volume Evidence requires at least 1.5x the 50-day average. "
            "Consolidation requires a base no wider than 15% with controlled volume."
        )
        setup_states = st.multiselect(
            "Setup states",
            available_states,
            default=available_states,
            help=(
                "Ready is below its pivot; breakout states are above it. Developing "
                "and rejected states remain available when core rules are disabled."
            ),
        )
        setup_column, volume_column = st.columns(2)
        minimum_setup = setup_column.slider(
            "Minimum setup score", 0, 100, 60, 5
        )
        minimum_volume = volume_column.slider(
            "Minimum volume / 50-day average",
            1.5,
            3.0,
            1.5,
            0.1,
            disabled=not require_volume,
        )
        volatility_column, risk_column = st.columns(2)
        maximum_volatility = volatility_column.slider(
            "Maximum annualized volatility %", 20, 200, 100, 5
        )
        maximum_risk = risk_column.slider(
            "Maximum cached market risk", 0, 100, 80, 5
        )
        base_column, pivot_column = st.columns(2)
        maximum_base_width = base_column.slider(
            "Maximum consolidation width %",
            5,
            20,
            15,
            1,
            disabled=not require_base,
        )
        maximum_pivot_distance = pivot_column.slider(
            "Maximum distance from pivot %",
            1,
            20,
            8,
            1,
            disabled=not require_base,
        )
    stocks = _filter_technical_candidates(
        stocks,
        tuple(setup_states),
        minimum_setup,
        minimum_volume,
        maximum_volatility,
        maximum_risk,
        maximum_base_width,
        maximum_pivot_distance,
        require_sma50,
        require_sma150,
        require_volume,
        require_base,
    )
    if stocks.empty:
        st.info("No stocks match the selected technical and risk filters.")
        return
    technical_count = len(stocks)
    with st.spinner("Adding reported quality and growth evidence..."):
        fundamentals = cached_candidate_fundamentals(tuple(stocks["Symbol"]))
    stocks = stocks.merge(fundamentals, on="Symbol", how="left")
    stocks["Fundamental signal"] = stocks.apply(_fundamental_signal, axis=1)
    stocks["Volume signal"] = stocks["Breakout volume"].map(_volume_signal)
    with st.expander("Fundamental filters", expanded=True):
        attributes = st.multiselect(
            "Fundamental attributes",
            ["Quality", "Growth", "Financial strength", "Valuation"],
            default=["Quality", "Growth", "Financial strength"],
            help="Select no attributes to disable fundamental score filtering.",
        )
        score_column, match_column = st.columns(2)
        minimum_fundamental = score_column.slider(
            "Minimum fundamental score", 0, 100, 65, 5
        )
        match_policy = match_column.segmented_control(
            "Attribute matching",
            ["Any selected", "All selected"],
            default="Any selected",
        )
    stocks = _filter_fundamental_candidates(
        stocks,
        tuple(attributes),
        minimum_fundamental,
        require_all=match_policy == "All selected",
    )
    if stocks.empty:
        st.info(
            "No technically eligible stocks match the selected fundamental "
            "attributes and score threshold."
        )
        return
    st.caption(
        f"{len(stocks)} of {technical_count} technically eligible stocks match "
        "the fundamental filters. Moat evidence remains a research-stage review."
    )
    stocks["Volatility context"] = stocks["Volatility %"].map(
        _candidate_volatility_context
    )
    stocks["Setup interpretation"] = stocks["Setup score"].map(
        _candidate_score_context
    )
    candidate_selection = st.dataframe(
        stocks,
        hide_index=True,
        width="stretch",
        row_height=82,
        key=f"winning_candidates_{sector}_{industry}",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Price · SMA50": st.column_config.ImageColumn(width=260),
            "Price above SMA50": st.column_config.CheckboxColumn(
                disabled=True,
                help="Latest close is above its 50-day moving average.",
            ),
            "Price above SMA150": st.column_config.CheckboxColumn(
                disabled=True,
                help="Latest close is above its 150-day moving average.",
            ),
            "Volume Evidence": st.column_config.CheckboxColumn(
                disabled=True,
                help="Latest volume is at least 1.5x its 50-day average.",
            ),
            "Consolidation base": st.column_config.CheckboxColumn(
                disabled=True,
                help="Base width is at most 15% and base volume is controlled.",
            ),
            "Price": st.column_config.NumberColumn(
                format="%.2f", help="Latest daily close in the listing currency."
            ),
            "Pivot": st.column_config.NumberColumn(
                format="$%.2f",
                help="Highest price in the selected 5–20 session base.",
            ),
            "From pivot %": st.column_config.NumberColumn(
                format="%.1f%%",
                help="Distance from pivot; within 5% below it passes the ready rule.",
            ),
            "Breakout volume": st.column_config.NumberColumn(
                format="%.2fx",
                help="Latest volume / 50-day average; 1.50x confirms.",
            ),
            "Volatility %": st.column_config.NumberColumn(
                format="%.1f%%",
                help=(
                    "Annualized daily-return volatility: <20% low, 20–35% "
                    "moderate, 35–50% high, ≥50% very high."
                ),
            ),
            "Max drawdown %": st.column_config.NumberColumn(
                format="%.1f%%",
                help="Largest peak-to-trough decline; nearer zero is better.",
            ),
            "Growth": st.column_config.ProgressColumn(
                min_value=0,
                max_value=100,
                help="Normalized growth; 65+ is positive and 80+ strong.",
            ),
            "Quality": st.column_config.ProgressColumn(
                min_value=0,
                max_value=100,
                help="Available fundamentals average; 65+ positive, 80+ strong.",
            ),
            "Financial strength": st.column_config.ProgressColumn(
                min_value=0,
                max_value=100,
                help="Normalized leverage/liquidity; 65+ positive, 80+ strong.",
            ),
            "Valuation": st.column_config.ProgressColumn(
                min_value=0,
                max_value=100,
                help="P/E normalized from 8 (best) to 55 (weakest); 65+ positive.",
            ),
            "Setup score": st.column_config.ProgressColumn(
                min_value=0,
                max_value=100,
                help="Percentage of 11 setup checks passed; 80+ is strong.",
            ),
            "Market risk": st.column_config.ProgressColumn(
                min_value=0,
                max_value=100,
                help=(
                    "Cached price-risk score from volatility and drawdown. Higher "
                    "is riskier; balance-sheet risk requires full research."
                ),
            ),
            "ATR %": st.column_config.NumberColumn(
                format="%.1f%%",
                help="14-day average true range as a percentage of price.",
            ),
            "Fundamental signal": st.column_config.TextColumn(
                help=(
                    "Strong when any core fundamental score is 80+; Positive at "
                    "65+. This is not a qualitative moat assessment."
                )
            ),
            "Volume signal": st.column_config.TextColumn(
                help=(
                    "Confirmed at 1.50x 50-day average volume, Building at 1.00x, "
                    "otherwise Unconfirmed."
                )
            ),
        },
    )
    selected_rows = _selected_rows(candidate_selection)
    selected_symbol = (
        str(stocks.iloc[selected_rows[0]]["Symbol"]) if selected_rows else None
    )
    selection_id = (sector, industry, selected_symbol) if selected_symbol else None
    if not selected_symbol:
        st.session_state.pop("processed_candidate", None)
    elif st.session_state.get("processed_candidate") != selection_id:
        st.session_state["processed_candidate"] = selection_id
        st.session_state["research_symbol"] = selected_symbol
        selected = stocks.iloc[selected_rows[0]]
        st.session_state["research_listing"] = {
            "Symbol": selected_symbol,
            "Region": selected.get("Region"),
            "Country": selected.get("Country"),
            "Exchange": selected.get("Exchange"),
            "Currency": selected.get("Currency"),
        }
        st.session_state["pending_stocks_workspace_view"] = "Research"
        st.session_state["pending_workspace_page"] = "Stocks"
        st.rerun()


def _scan_freshness_notice() -> None:
    metadata = st.session_state.get("scan_snapshot_meta")
    if not metadata:
        return
    completed_at = metadata["completed_at"].astimezone(UTC)
    st.caption(
        f"Analysis as of {completed_at.strftime('%Y-%m-%d %H:%M UTC')} · "
        f"{metadata['coverage']:.1f}% history coverage · "
        f"{metadata['mode'].title()} mode · {metadata['source']}"
    )


def _scan_coverage_warning(warning: str | None) -> None:
    if not warning:
        return
    if "History coverage:" in warning:
        coverage = warning.rsplit("History coverage:", 1)[-1]
        st.warning(f"Partial market data · History coverage: {coverage}")
    else:
        st.warning(warning)


def _research_page(risk_profile: str) -> None:
    pending_section = st.session_state.pop("pending_research_section", None)
    if pending_section:
        st.session_state["research_section"] = pending_section
    active_step = (
        4 if st.session_state.get("research_section") == "Risk & trade plan" else 3
    )
    _journey_progress(active_step)
    default_symbol = st.session_state.get("research_symbol") or "NVDA"
    _heading(
        "Stock research", "Fundamentals and risk first, technical confirmation second"
    )
    symbol = st.text_input("Ticker", value=default_symbol, max_chars=12).strip().upper()
    if not symbol:
        return
    with st.spinner(f"Building evidence record for {symbol}..."):
        result = cached_analysis(symbol)
    st.session_state["research_symbol"] = symbol
    _source_notice(result)

    profile = result.profile.data
    name = profile.get("longName", symbol)
    st.subheader(f"{name} · {symbol}")
    listing = st.session_state.get("research_listing", {})
    if isinstance(listing, dict) and symbol == listing.get("Symbol"):
        details = [
            str(listing.get(key))
            for key in ("Exchange", "Country", "Currency")
            if listing.get(key) and not pd.isna(listing.get(key))
        ]
        if details:
            st.caption(" · ".join(details))
    price, quality = st.columns(2)
    price.metric(
        "Last close",
        f"${result.latest_price:,.2f}",
        f"{result.daily_change:+.2f}%",
        help="Latest daily close and change from the preceding close.",
    )
    quality.metric(
        "Quality",
        f"{result.analysis.quality.value:.0f}/100",
        result.analysis.quality.label,
        help="Higher is better: <45 weak, 45–64 neutral, 65–79 positive, ≥80 strong.",
    )
    risk, technical = st.columns(2)
    risk.metric(
        "Observed risk",
        f"{result.analysis.risk.value:.0f}/100",
        result.analysis.risk.label,
        delta_color="inverse",
        help="Higher is riskier: <35 low, 35–59 moderate, 60–79 elevated, ≥80 high.",
    )
    technical.metric(
        "Technical",
        f"{result.analysis.technical.value:.0f}/100",
        result.analysis.technical.label,
        help="Higher is better: <45 weak, 45–64 neutral, 65–79 positive, ≥80 strong.",
    )
    volatility = _annualized_volatility(result.history.data)
    st.caption(
        f"Quality: {_score_context(result.analysis.quality.value)} "
        f"Technical: {_score_context(result.analysis.technical.value)} "
        f"Risk: {_score_context(result.analysis.risk.value, risk=True)} "
        f"{_volatility_context(volatility)}"
    )

    section = st.selectbox(
        "Research section",
        [
            "Overview",
            "Chart",
            "Quality & growth",
            "Business & moat",
            "News & catalysts",
            "Risk & trade plan",
            "Peers",
        ],
        key="research_section",
    )
    if section == "Overview":
        _research_overview(result)
    elif section == "Chart":
        st.plotly_chart(_price_chart(result), width="stretch")
    elif section == "Quality & growth":
        _quality_growth_panel(result)
    elif section == "Business & moat":
        _business_moat_panel(result.profile.data)
    elif section == "News & catalysts":
        _news_panel(symbol)
    elif section == "Risk & trade plan":
        _risk_panel(result, risk_profile)
    else:
        _peer_panel(symbol)

    st.divider()
    with st.form("research_watchlist"):
        st.subheader("Add to watchlist")
        notes = st.text_area(
            "Investment thesis", placeholder="Evidence, catalyst, and invalidation..."
        )
        entry, target, stop = st.columns(3)
        active_plan = st.session_state.get(f"active_trade_plan_{symbol}", {})
        entry_price = entry.number_input(
            "Planned entry",
            min_value=0.0,
            value=round(active_plan.get("entry", result.latest_price), 2),
        )
        target_price = target.number_input(
            "Target",
            min_value=0.0,
            value=round(active_plan.get("target", result.latest_price * 1.15), 2),
        )
        stop_price = stop.number_input(
            "Stop",
            min_value=0.0,
            value=round(
                active_plan.get("stop", result.latest_price - 2 * result.atr), 2
            ),
        )
        if st.form_submit_button("Save candidate", type="primary"):
            repository().save_watchlist(
                symbol, notes, entry_price, target_price, stop_price
            )
            st.success(f"{symbol} saved to the watchlist.")


def _research_overview(result: AnalysisResult) -> None:
    profile = result.profile.data
    setup = analyze_long_swing_setup(result.history.data)
    target = profile.get("targetMeanPrice")
    earnings = profile.get("earningsTimestampStart")
    next_earnings = (
        datetime.fromtimestamp(earnings, UTC).strftime("%Y-%m-%d")
        if isinstance(earnings, (int, float))
        else "Unavailable"
    )
    st.markdown(
        f"### Swing setup: {setup.state} · {setup.score:.0f}/100"
    )
    st.caption(
        f"{_score_context(setup.score)} The score is the percentage of 11 "
        "trend, base, pivot, and breakout checks that pass."
    )
    target_column, earnings_column = st.columns(2)
    target_column.metric(
        "Analyst mean target",
        f"${target:,.2f}" if isinstance(target, (int, float)) else "Unavailable",
        (
            f"{(target / result.latest_price - 1) * 100:+.1f}% vs price"
            if isinstance(target, (int, float))
            else None
        ),
    )
    earnings_column.metric("Next earnings", next_earnings)
    st.markdown("**Decision summary**")
    passed = sum(setup.checks.values())
    st.write(
        f"{passed} of {len(setup.checks)} technical setup checks pass. "
        f"Fundamental data is {result.analysis.quality.completeness:.0f}% complete; "
        f"risk data is {result.analysis.risk.completeness:.0f}% complete."
    )
    st.caption(
        "Analyst targets and automated states are evidence inputs, not price "
        "predictions or investment recommendations."
    )


def _quality_growth_panel(result: AnalysisResult) -> None:
    profile = result.profile.data
    pillars = {
        name: score_fundamentals(components)
        for name, components in fundamental_pillar_metrics(profile).items()
    }
    st.subheader("Fundamental scorecard")
    st.caption(
        "The overall quality score is the equal-weight average of available "
        "pillars. Each pillar is the average of its available reported metrics; "
        "missing values are excluded and shown through completeness."
    )
    _score_evidence("Overall fundamental score", result.analysis.quality)
    for start in range(0, len(pillars), 3):
        columns = st.columns(3)
        for column, (name, score) in zip(
            columns, list(pillars.items())[start : start + 3], strict=True
        ):
            column.metric(
                name,
                f"{score.value:.0f}/100" if score.completeness else "Unavailable",
                score.label if score.completeness else None,
                help=f"Reported metric coverage: {score.completeness:.0f}%.",
            )
    for name, score in pillars.items():
        with st.expander(
            f"{name} evidence · "
            + (f"{score.value:.0f}/100" if score.completeness else "Unavailable")
        ):
            if score.completeness:
                _score_evidence(name, score)
            else:
                st.info("No reported metrics are available for this pillar.")

    st.subheader("Reported fundamentals")
    fields = [
        (
            "Revenue growth",
            profile.get("revenueGrowth"),
            "percent",
            ">10% is supportive; compare with industry and consistency.",
        ),
        (
            "Earnings growth",
            profile.get("earningsGrowth"),
            "percent",
            ">10% is supportive; volatile or one-off earnings need review.",
        ),
        (
            "Gross margin",
            profile.get("grossMargins"),
            "percent",
            ">50% supports pricing-power evidence; industry norms vary.",
        ),
        (
            "Operating margin",
            profile.get("operatingMargins"),
            "percent",
            ">10% is supportive; compare with direct peers.",
        ),
        (
            "Profit margin",
            profile.get("profitMargins"),
            "percent",
            ">0% means profitable; stability matters more than one period.",
        ),
        (
            "Return on equity",
            profile.get("returnOnEquity"),
            "percent",
            ">15% is supportive unless driven by high leverage.",
        ),
        (
            "Return on assets",
            profile.get("returnOnAssets"),
            "percent",
            ">5% is a useful baseline; asset-heavy industries differ.",
        ),
        (
            "Free cash flow",
            profile.get("freeCashflow"),
            "currency",
            "Positive is supportive; scale against revenue and market value.",
        ),
        (
            "Operating cash flow",
            profile.get("operatingCashflow"),
            "currency",
            "Positive and recurring is supportive.",
        ),
        (
            "Debt to equity",
            profile.get("debtToEquity"),
            "number",
            "Lower is safer; the score maps 20 best to 200 weakest.",
        ),
        (
            "Current ratio",
            profile.get("currentRatio"),
            "number",
            "1.0 covers current liabilities; 1.5–2.5 is generally stronger.",
        ),
        (
            "Trailing P/E",
            profile.get("trailingPE"),
            "number",
            "Lower needs durable earnings; score range is 8 best to 55 weakest.",
        ),
    ]
    frame = pd.DataFrame(
        [
            (label, _format_research_value(value, kind), context)
            for label, value, kind, context in fields
        ],
        columns=["Measure", "Reported value", "How to read it"],
    )
    st.dataframe(frame, hide_index=True, width="stretch")


def _business_moat_panel(profile: dict[str, object]) -> None:
    summary = profile.get("longBusinessSummary")
    st.subheader("Business model")
    st.write(summary or "Business description is unavailable from the current source.")
    website = profile.get("website")
    if isinstance(website, str) and website:
        st.link_button("Company website", website)

    signals = [
        ("Gross margin", profile.get("grossMargins"), 0.50, "percent"),
        ("Operating margin", profile.get("operatingMargins"), 0.10, "percent"),
        ("Return on equity", profile.get("returnOnEquity"), 0.15, "percent"),
        ("Revenue growth", profile.get("revenueGrowth"), 0.10, "percent"),
        ("Positive free cash flow", profile.get("freeCashflow"), 0.0, "currency"),
    ]
    rows = []
    for label, value, threshold, kind in signals:
        available = isinstance(value, (int, float))
        rows.append(
            (
                label,
                _format_research_value(value, kind),
                "Supportive"
                if available and value > threshold
                else "Weak / unavailable",
            )
        )
    st.subheader("Moat evidence proxies")
    st.dataframe(
        pd.DataFrame(rows, columns=["Signal", "Evidence", "Interpretation"]),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "These quantitative signals may support pricing power or financial "
        "durability. They do not establish a competitive moat; qualitative "
        "research on switching costs, network effects, IP, brand, and regulation "
        "is still required."
    )


def _news_panel(symbol: str) -> None:
    result = cached_news(symbol)
    if result.warning:
        st.warning(result.warning)
    if result.data.empty:
        st.info("No recent news is available from the current provider.")
        return
    news = result.data.head(10).copy()
    news["Published"] = pd.to_datetime(news["Published"], errors="coerce").dt.strftime(
        "%Y-%m-%d %H:%M"
    )
    for article in news.itertuples(index=False):
        if article.URL:
            st.markdown(f"#### [{article.Title}]({article.URL})")
        else:
            st.markdown(f"#### {article.Title}")
        st.caption(f"{article.Published} · {article.Publisher}")
        if article.Summary:
            st.write(article.Summary)
        st.divider()
    st.caption(
        f"Source: {result.source} · retrieved "
        f"{result.retrieved_at.strftime('%Y-%m-%d %H:%M UTC')}"
    )


def _format_research_value(value: object, kind: str) -> str:
    if not isinstance(value, (int, float)):
        return "Unavailable"
    if kind == "percent":
        return f"{value * 100:+.1f}%"
    if kind == "currency":
        return f"${value:,.0f}"
    return f"{value:,.2f}"


def _annualized_volatility(history: pd.DataFrame) -> float:
    returns = history["Close"].pct_change().dropna()
    return float(returns.std() * (252**0.5) * 100) if not returns.empty else 0.0


def _candidate_volatility_context(value: object) -> str:
    if not isinstance(value, (int, float)) or pd.isna(value):
        return "Unavailable"
    return _volatility_context(float(value), concise=True)


def _candidate_score_context(value: object) -> str:
    if not isinstance(value, (int, float)) or pd.isna(value):
        return "Unavailable"
    return _score_context(float(value), concise=True)


def _fundamental_signal(row: pd.Series) -> str:
    values = pd.to_numeric(
        pd.Series(
            [row.get("Quality"), row.get("Growth"), row.get("Financial strength")]
        ),
        errors="coerce",
    ).dropna()
    if values.empty:
        return "Unavailable"
    peak = float(values.max())
    if peak >= 80:
        return "Strong"
    if peak >= 65:
        return "Positive"
    return "Weak"


def _filter_market_stocks(
    stocks: pd.DataFrame,
    *,
    search: str = "",
    regions: tuple[str, ...] = (),
    sectors: tuple[str, ...] = (),
    industries: tuple[str, ...] = (),
    exchanges: tuple[str, ...] = (),
    setup_states: tuple[str, ...] = (),
    minimum_price: float = 0.0,
    maximum_price: float = float("inf"),
    minimum_market_cap: float = 0.0,
    minimum_setup: float = 0.0,
    maximum_risk: float = 100.0,
    maximum_volatility: float = float("inf"),
    require_sma50: bool = False,
    require_sma150: bool = False,
) -> pd.DataFrame:
    """Apply composable discovery filters to cached global stock evidence."""
    if stocks.empty:
        return stocks.copy()
    mask = pd.Series(True, index=stocks.index)
    if search:
        query = search.strip()
        mask &= stocks["Symbol"].str.contains(
            query, case=False, regex=False, na=False
        ) | stocks["Company"].str.contains(query, case=False, regex=False, na=False)
    for column, selected in (
        ("Region", regions),
        ("Sector", sectors),
        ("Industry", industries),
        ("Exchange", exchanges),
        ("Setup state", setup_states),
    ):
        if selected:
            mask &= stocks[column].isin(selected)
    mask &= stocks["Price"].between(minimum_price, maximum_price)
    mask &= stocks["Market cap"].fillna(0) >= minimum_market_cap
    mask &= stocks["Setup score"].fillna(0) >= minimum_setup
    mask &= stocks["Market risk"].fillna(100) <= maximum_risk
    mask &= stocks["Volatility %"].fillna(float("inf")) <= maximum_volatility
    if require_sma50:
        mask &= stocks["Price above SMA50"].fillna(False)
    if require_sma150:
        mask &= stocks["Price above SMA150"].fillna(False)
    return stocks.loc[mask].copy()


def _filter_technical_candidates(
    stocks: pd.DataFrame,
    states: tuple[str, ...],
    minimum_setup: float,
    minimum_volume: float,
    maximum_volatility: float,
    maximum_risk: float,
    maximum_base_width: float,
    maximum_pivot_distance: float,
    require_sma50: bool,
    require_sma150: bool,
    require_volume: bool,
    require_base: bool,
) -> pd.DataFrame:
    mask = (
        stocks["Setup state"].isin(states)
        & (stocks["Setup score"] >= minimum_setup)
        & (stocks["Volatility %"] <= maximum_volatility)
    )
    if "Market risk" in stocks:
        mask &= stocks["Market risk"].isna() | (
            stocks["Market risk"] <= maximum_risk
        )
    for enabled, column in (
        (require_sma50, "Price above SMA50"),
        (require_sma150, "Price above SMA150"),
        (require_volume, "Volume Evidence"),
        (require_base, "Consolidation base"),
    ):
        if enabled:
            mask &= stocks[column].fillna(False).astype(bool)
    if require_volume:
        mask &= stocks["Breakout volume"] >= max(1.5, minimum_volume)
    if require_base:
        mask &= (stocks["Base range %"] <= maximum_base_width) & (
            stocks["From pivot %"].abs() <= maximum_pivot_distance
        )
    return stocks.loc[mask].copy()


def _filter_fundamental_candidates(
    stocks: pd.DataFrame,
    attributes: tuple[str, ...],
    minimum_score: float,
    require_all: bool,
) -> pd.DataFrame:
    if not attributes:
        return stocks.copy()
    evidence = stocks[list(attributes)].apply(pd.to_numeric, errors="coerce")
    passes = evidence.ge(minimum_score)
    mask = passes.all(axis=1) if require_all else passes.any(axis=1)
    return stocks.loc[mask].copy()


def _volume_signal(value: object) -> str:
    if not isinstance(value, (int, float)) or pd.isna(value):
        return "Unavailable"
    ratio = float(value)
    if ratio >= 1.5:
        return "Confirmed spike"
    if ratio >= 1.0:
        return "Building"
    return "Unconfirmed"


def _volatility_context(volatility: float, concise: bool = False) -> str:
    if volatility < 20:
        band, sizing = "Low", "price movement is relatively contained"
    elif volatility < 35:
        band, sizing = "Moderate", "allow normal room around technical levels"
    elif volatility < 50:
        band, sizing = "High", "wider stops and fewer shares may be needed"
    else:
        band, sizing = "Very high", "expect large swings; reduce size materially"
    if concise:
        return f"{band} ({volatility:.1f}% annualized)"
    return f"Volatility: {band} at {volatility:.1f}% annualized; {sizing}."


def _score_context(value: float, risk: bool = False, concise: bool = False) -> str:
    if risk:
        bands = [(80, "High"), (60, "Elevated"), (35, "Moderate"), (0, "Low")]
        thresholds = [(35, "moderate"), (60, "elevated"), (80, "high")]
    else:
        bands = [(80, "Strong"), (65, "Positive"), (45, "Neutral"), (0, "Weak")]
        thresholds = [(45, "neutral"), (65, "positive"), (80, "strong")]
    label = next(name for minimum, name in bands if value >= minimum)
    if concise:
        return f"{label} band"
    next_band = next(
        ((threshold, name) for threshold, name in thresholds if value < threshold),
        None,
    )
    if next_band is None:
        return f"{label} band; above the highest {bands[0][0]}-point threshold."
    threshold, name = next_band
    direction = "risk reaches" if risk else "score reaches"
    distance = threshold - value
    unit = "point" if distance == 1 else "points"
    return (
        f"{label} band; {distance:.0f} {unit} until "
        f"{direction} {name} at {threshold}."
    )


def _watchlist_page() -> None:
    _heading(
        "Watchlist", "Research candidates, planned entries, and invalidation levels"
    )
    watchlist = repository().watchlist()
    if watchlist.empty:
        st.info("Your watchlist is empty. Add a candidate from Stocks → Research.")
        return
    enriched = _enrich_with_cached_risk(watchlist)
    enriched["upside_%"] = (enriched["target_price"] / enriched["last_price"] - 1) * 100
    missing = int(enriched["last_price"].isna().sum())
    st.caption(
        "Prices and market-risk profiles come from the latest completed broad scan; "
        "opening this page does not fetch providers."
    )
    if missing:
        st.warning(
            f"{missing} symbol(s) are outside the cached scan. Use Refresh now in "
            "Data controls to fetch them as part of a new market scan."
        )
    st.dataframe(
        enriched,
        hide_index=True,
        width="stretch",
        column_config={
            "entry_price": st.column_config.NumberColumn("Entry", format="$%.2f"),
            "target_price": st.column_config.NumberColumn("Target", format="$%.2f"),
            "stop_price": st.column_config.NumberColumn("Stop", format="$%.2f"),
            "last_price": st.column_config.NumberColumn("Last", format="$%.2f"),
            "upside_%": st.column_config.NumberColumn("Upside", format="%.1f%%"),
            "market_risk": st.column_config.ProgressColumn(
                "Market risk", min_value=0, max_value=100
            ),
            "atr_%": st.column_config.NumberColumn("ATR", format="%.1f%%"),
        },
    )
    st.download_button(
        "Download CSV",
        enriched.to_csv(index=False),
        "stockfinder-watchlist.csv",
        "text/csv",
    )
    symbol = st.selectbox("Remove candidate", enriched["symbol"].tolist())
    if st.button("Remove", type="secondary") and symbol:
        repository().delete_watchlist(symbol)
        st.rerun()


def _portfolio_page() -> None:
    _heading("Portfolio", "Manual positions, live valuation, and concentration")
    with st.form("position"):
        symbol, quantity, entry_price, entry_date = st.columns(4)
        position_symbol = symbol.text_input("Symbol", "SPY").upper()
        position_quantity = quantity.number_input("Quantity", min_value=0.01, value=1.0)
        position_entry = entry_price.number_input(
            "Entry price", min_value=0.01, value=100.0
        )
        position_date = entry_date.date_input("Entry date", value=date.today())
        if st.form_submit_button("Save position", type="primary"):
            repository().save_position(
                position_symbol,
                position_quantity,
                position_entry,
                position_date.isoformat(),
            )
            st.rerun()

    positions = repository().positions()
    if positions.empty:
        st.info("No positions recorded.")
        return
    positions = _enrich_with_cached_risk(positions)
    missing = int(positions["last_price"].isna().sum())
    st.caption(
        "Valuation and market risk use the latest completed broad scan without "
        "fetching complete company research."
    )
    if missing:
        st.warning(
            f"{missing} position(s) have no cached market profile. Use Refresh now "
            "in Data controls to rebuild the market cache."
        )
    positions["market_value"] = positions["quantity"] * positions["last_price"]
    positions["cost"] = positions["quantity"] * positions["entry_price"]
    positions["pnl"] = positions["market_value"] - positions["cost"]
    positions["allocation_%"] = (
        positions["market_value"] / positions["market_value"].sum() * 100
    )
    total, pnl, concentration = st.columns(3)
    total.metric("Market value", f"${positions['market_value'].sum():,.2f}")
    pnl.metric("Unrealized P&L", f"${positions['pnl'].sum():,.2f}")
    concentration.metric("Largest position", f"{positions['allocation_%'].max():.1f}%")
    left, right = st.columns([2, 1])
    left.dataframe(positions, hide_index=True, width="stretch")
    allocation = px.pie(positions, values="market_value", names="symbol", hole=0.55)
    allocation.update_traces(textposition="inside", textinfo="label+percent")
    allocation.update_layout(showlegend=False, height=330)
    right.plotly_chart(allocation, width="stretch")
    remove = st.selectbox("Close/remove position", positions["symbol"].tolist())
    if st.button("Remove position") and remove:
        repository().delete_position(remove)
        st.rerun()


def _methodology_page(risk_profile: str, load_mode: str) -> None:
    _heading("Methodology", "Transparent assumptions, controls, and known limits")
    st.subheader("Current profile")
    first, second, third = st.columns(3)
    first.metric("Liquidity windows", "1W · 1M · 3M · 6M")
    second.metric("Risk preset", risk_profile)
    third.metric("Data mode", load_mode.title())
    st.subheader("Score policy")
    st.write(
        "Fundamental quality, observed risk, and technical confirmation remain "
        "separate. Missing inputs reduce completeness; they are never replaced by "
        "an unexplained average value."
    )
    st.write(
        "The fundamental scorecard groups reported metrics into Quality, Growth, "
        "Cash flow, Stability, Valuation, and Dividends. Available metrics are "
        "equally weighted within each pillar, and available pillars are equally "
        "weighted in the overall quality score."
    )
    st.write(
        "The broad scan combines classified NASDAQ and NYSE stocks with a curated "
        "set of liquid local listings from Europe, Asia, Asia-Pacific, Canada, "
        "Latin America, and Africa. Regional industries are analyzed separately."
    )
    st.write(
        "Industry liquidity uses aggregate member dollar volume and is always "
        "calculated over one week, one month, three months, and six months. Each "
        "horizon reports liquidity growth and up-day versus down-day flow balance."
    )
    st.write(
        "The active rotation model compares normalized 1W/1M momentum and "
        "liquidity with 3M/6M baselines. An industry is Gaining only when momentum "
        "change, liquidity change, and recent directional volume are all positive; "
        "it is Losing when all three are negative. Other combinations are Mixed."
    )
    st.write(
        "An industry is a winner only when its equal-weight price index is above a "
        "rising SMA150, its three- and six-month returns are positive, liquidity "
        "scores confirm in at least three of four horizons, and at least half of "
        "covered members are above rising SMA150. This established-trend flag is "
        "confirmation; stock discovery begins in every Gaining industry."
    )
    st.write(
        "The cached stock pool includes every stock with sufficient history in a "
        "Gaining industry. Rotation Leaders can independently require Price above "
        "SMA50, Price above SMA150, Volume Evidence, and a Consolidation base. "
        "Disabling a rule genuinely exposes stocks that fail that evidence check."
    )
    st.write(
        "Volume Evidence requires at least 1.5x the 50-day average. Consolidation "
        "requires an adaptive 5–20 session base no wider than 15%, with controlled "
        "base volume. Numeric thresholds and fundamental attributes can then refine "
        "the enabled core rules. Moat remains a separate qualitative review."
    )
    st.write(
        "Stock research classifies the long swing rule as Ready near pivot, "
        "Price breakout · volume unconfirmed, Breakout confirmed, Developing, or "
        "Reject: trend. Confirmation requires "
        "a close above the adaptive base pivot on at least 1.5x 50-day average "
        "volume, with the close in the upper quarter of the breakout-day range."
    )
    st.write(
        "The suggested entry is the base pivot plus 0.25 ATR. Candidate stops "
        "include an ATR stop, the structural base low, SMA50, the recent swing "
        "low, and a profile-based trailing stop. Shares equal the lesser of the "
        "risk-budget limit and the available-cash limit."
    )
    st.write(
        "Every successful broad scan also persists a market-risk profile for each "
        "usable cached history: last price, daily change, annualized volatility, "
        "maximum drawdown, ATR, swing low, and a price-risk score. Watchlist and "
        "Portfolio use this snapshot without provider requests. Balance-sheet risk, "
        "fundamentals, and moat evidence still require explicit Stock Research."
    )
    st.write(
        "Refresh now clears both provider and processed-scan caches. Standard "
        "loading requests one year in 200-symbol batches; extended loading "
        "requests two years in 100-symbol batches. Progress reports completed and "
        "usable symbols, then aggregation and setup-filtering stages."
    )
    st.subheader("Data providers")
    st.dataframe(
        pd.DataFrame(
            [
                ("Price and volume", "Yahoo Finance", "Synthetic, visibly labeled"),
                ("Company profile", "Yahoo Finance", "Synthetic, visibly labeled"),
                (
                    "US membership",
                    "Nasdaq public stock screener",
                    "Representative US fallback",
                ),
                (
                    "International listings",
                    "Curated Yahoo-compatible symbols",
                    "Licensed global membership provider",
                ),
                ("Broad price history", "Yahoo Finance batches", "Missing excluded"),
                ("Persistence", "Local SQLite", "Hosted database before cloud use"),
            ],
            columns=["Capability", "Current source", "Fallback / next step"],
        ),
        hide_index=True,
        width="stretch",
    )
    st.warning(
        "This is a research tool, not personalized financial advice. Synthetic "
        "fallback data must never be used for a trading decision. International "
        "listing availability and market access depend on your broker."
    )


def _price_chart(result: AnalysisResult) -> go.Figure:
    history = result.history.data.tail(378).copy()
    history["SMA 50"] = history["Close"].rolling(50).mean()
    history["SMA 150"] = history["Close"].rolling(150).mean()
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.74, 0.26],
    )
    figure.add_trace(
        go.Candlestick(
            x=history.index,
            open=history["Open"],
            high=history["High"],
            low=history["Low"],
            close=history["Close"],
            name="Price",
            increasing_line_color="#0b6e4f",
            decreasing_line_color="#d95d39",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=history.index,
            y=history["SMA 50"],
            name="SMA 50",
            line={"color": "#2364aa"},
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=history.index,
            y=history["SMA 150"],
            name="SMA 150",
            line={"color": "#d4a017"},
        ),
        row=1,
        col=1,
    )
    colors = [
        "#0b6e4f" if close >= open_ else "#d95d39"
        for close, open_ in zip(history["Close"], history["Open"], strict=True)
    ]
    figure.add_trace(
        go.Bar(
            x=history.index, y=history["Volume"], marker_color=colors, name="Volume"
        ),
        row=2,
        col=1,
    )
    figure.update_layout(
        height=620, xaxis_rangeslider_visible=False, hovermode="x unified"
    )
    return figure


def _score_evidence(title: str, score: Score) -> None:
    st.markdown(f"**{title}: {score.value:.0f}/100 · {score.label}**")
    is_risk = "risk" in title.lower()
    st.caption(
        f"{_score_context(score.value, risk=is_risk)} "
        + (
            "Higher scores mean more observed risk."
            if is_risk
            else "Higher scores mean stronger evidence."
        )
    )
    st.progress(
        score.completeness / 100, text=f"Data completeness {score.completeness:.0f}%"
    )
    if score.components:
        frame = pd.DataFrame(
            [
                (name, value, _score_context(value, risk=is_risk))
                for name, value in score.components.items()
            ],
            columns=["Component", "Score", "Threshold context"],
        )
        st.dataframe(
            frame,
            hide_index=True,
            width="stretch",
            column_config={
                "Score": st.column_config.ProgressColumn(min_value=0, max_value=100)
            },
        )


def _risk_panel(result: AnalysisResult, risk_profile: str) -> None:
    multiplier = {"Conservative": 1.5, "Balanced": 2.0, "Aggressive": 2.5}[risk_profile]
    setup = analyze_long_swing_setup(result.history.data)
    atr_stop = setup.suggested_entry - multiplier * result.atr
    sma50 = float(result.history.data["Close"].rolling(50).mean().iloc[-1])
    trailing = setup.suggested_entry * (
        1 - {"Conservative": 0.06, "Balanced": 0.09, "Aggressive": 0.12}[risk_profile]
    )
    state, setup_score, pivot = st.columns(3)
    state.metric(
        "Swing-rule state",
        setup.state,
        help="Overall state from the trend, base, pivot, and breakout rules.",
    )
    setup_score.metric(
        "Rule score",
        f"{setup.score:.0f}/100",
        help="Percentage of 11 setup checks passed; 65+ positive, 80+ strong.",
    )
    pivot.metric(
        "Base pivot",
        f"${setup.pivot:,.2f}",
        help="Highest price in the base; breakout must close above it.",
    )
    volatility = _annualized_volatility(result.history.data)
    atr_percent = result.atr / result.latest_price * 100
    st.caption(
        f"{_score_context(setup.score)} {_volatility_context(volatility)} "
        f"ATR14 is {atr_percent:.1f}% of price, so judge stop distances against "
        "this stock's normal daily range."
    )

    evidence = pd.DataFrame(
        [(name, "Pass" if passed else "Fail") for name, passed in setup.checks.items()],
        columns=["Rule", "Result"],
    )
    st.dataframe(evidence, hide_index=True, width="stretch")
    st.subheader("Pattern measurements")
    base_length, base_width, prior_advance, breakout_volume = st.columns(4)
    base_length.metric(
        "Base length",
        f"{setup.metrics.get('Base length sessions', 0):.0f} sessions",
        help="Longest valid base among 5, 7, 10, 15, and 20 sessions.",
    )
    base_width.metric(
        "Base width",
        f"{setup.metrics.get('Base range %', 0):.1f}%",
        help="High-to-low range of the base; no more than 15% passes.",
    )
    prior_advance.metric(
        "Prior advance",
        f"{setup.metrics.get('Prior advance %', 0):+.1f}%",
        help="Price advance before the base; at least 10% passes.",
    )
    breakout_volume.metric(
        "Breakout volume",
        f"{setup.metrics.get('Breakout volume ratio', 0):.2f}x",
        help="Latest volume / 50-day average; at least 1.50x confirms.",
    )

    stop_levels = {
        f"ATR ({multiplier:.1f}x)": atr_stop,
        "Structural base stop": setup.structural_stop,
        "50-day average": sma50,
        "Recent 20-day swing low": result.swing_low,
        "Trailing stop": trailing,
    }
    stops = pd.DataFrame(stop_levels.items(), columns=["Method", "Candidate level"])
    st.dataframe(
        stops,
        hide_index=True,
        width="stretch",
        column_config={
            "Candidate level": st.column_config.NumberColumn(format="$%.2f")
        },
    )
    st.subheader("Position plan")
    account, risk_percent, stop_method = st.columns(3)
    account_size = account.number_input(
        "Account value", min_value=1_000.0, value=100_000.0, step=1_000.0
    )
    default_risk = {"Conservative": 0.25, "Balanced": 0.5, "Aggressive": 1.0}[
        risk_profile
    ]
    risk_budget = risk_percent.slider("Account risk %", 0.25, 3.0, default_risk, 0.25)
    selected_method = stop_method.selectbox("Stop method", list(stop_levels))
    entry_column, stop_column = st.columns(2)
    entry_price = entry_column.number_input(
        "Planned entry",
        min_value=0.01,
        value=round(max(0.01, setup.suggested_entry), 2),
        key=f"plan_entry_{result.analysis.symbol}",
    )
    default_stop = min(entry_price - 0.01, stop_levels[selected_method])
    stop_price = stop_column.number_input(
        "Planned stop",
        min_value=0.0,
        value=round(max(0.0, default_stop), 2),
        key=f"plan_stop_{result.analysis.symbol}_{selected_method}",
    )
    try:
        plan = calculate_position_plan(
            account_size, risk_budget, entry_price, stop_price
        )
    except ValueError as error:
        st.warning(str(error))
        return
    base_low = setup.structural_stop + 0.25 * result.atr
    measured_move = setup.pivot + max(0.0, setup.pivot - base_low)
    risk_per_share = entry_price - stop_price
    target_options = {
        "2R target": entry_price + 2 * risk_per_share,
        "Measured move": measured_move,
    }
    analyst_target = result.profile.data.get("targetMeanPrice")
    if isinstance(analyst_target, (int, float)):
        target_options["Analyst mean target"] = float(analyst_target)
    target_method = st.selectbox("Target method", list(target_options))
    target_price = st.number_input(
        "Planned target",
        min_value=0.01,
        value=round(max(0.01, target_options[target_method]), 2),
        key=f"plan_target_{result.analysis.symbol}_{target_method}",
    )
    try:
        reward_risk = calculate_reward_risk(entry_price, stop_price, target_price)
    except ValueError as error:
        st.warning(str(error))
        reward_risk = None

    shares, loss, value, reward = st.columns(4)
    shares.metric(
        "Shares",
        f"{plan.shares:,}",
        help="Lower of risk-budget shares and cash-affordable shares.",
    )
    loss.metric(
        "Planned loss",
        f"${plan.planned_loss:,.2f}",
        help="Shares × (entry − stop); must stay within the risk budget.",
    )
    value.metric(
        "Position value",
        f"${plan.position_value:,.2f}",
        help="Shares × entry, constrained by the available account value.",
    )
    reward.metric(
        "Reward / risk",
        f"{reward_risk:.2f}R" if reward_risk is not None else "Invalid",
        help="Potential gain / planned loss per share; default minimum is 2R.",
    )
    if reward_risk is not None and reward_risk < 2:
        st.warning("Planned reward/risk is below the default 2R minimum.")
    st.session_state[f"active_trade_plan_{result.analysis.symbol}"] = {
        "entry": entry_price,
        "stop": stop_price,
        "target": target_price,
        "shares": plan.shares,
        "reward_risk": reward_risk,
    }
    st.caption(
        f"Risk budget ${plan.risk_budget:,.2f} · risk/share "
        f"${plan.risk_per_share:,.2f} · risk limit {plan.risk_limited_shares:,} "
        f"shares · cash limit {plan.capital_limited_shares:,} shares"
    )


def _peer_panel(symbol: str) -> None:
    snapshot = scan_snapshot_store().load()
    universe = snapshot.universe if snapshot is not None else SECURITY_UNIVERSE
    row = universe[universe["Symbol"] == symbol]
    if row.empty:
        st.info("This symbol is outside the latest broad-market snapshot.")
        return
    industry = row.iloc[0]["Industry"]
    peers = universe[
        (universe["Industry"] == industry) & (universe["Symbol"] != symbol)
    ].copy()
    if "Market cap" in peers:
        peers = peers.sort_values("Market cap", ascending=False)
    peer_symbols = peers["Symbol"].head(5).tolist()
    symbols = list(dict.fromkeys([symbol, *peer_symbols, "SPY"]))
    st.caption(f"Compared with leading available {industry} peers and SPY.")
    performance = normalized_performance(symbols)
    figure = px.line(
        performance,
        labels={"value": "Growth of 100", "variable": "Symbol", "index": "Date"},
    )
    figure.update_layout(height=430, hovermode="x unified")
    st.plotly_chart(figure, width="stretch")


def _source_notice(result: AnalysisResult) -> None:
    fallbacks = []
    if result.history.is_fallback:
        fallbacks.append("price history")
    if result.profile.is_fallback:
        fallbacks.append("company profile")
    if fallbacks:
        st.error(
            "Synthetic demonstration data is active for "
            + " and ".join(fallbacks)
            + ". Do not use this analysis for a trading decision."
        )
    else:
        timestamp = result.history.retrieved_at.strftime("%Y-%m-%d %H:%M UTC")
        st.caption(f"Source: Yahoo Finance · retrieved {timestamp}")


def _selected_rotation_context(
    heatmap_selection: object,
    winner_selection: object,
    winning_industries: pd.DataFrame,
) -> tuple[str, str, str] | None:
    points = _selected_points(heatmap_selection)
    if points:
        custom_data = points[0].get("customdata") or []
        if len(custom_data) >= 3 and all(custom_data[:3]):
            return tuple(str(value) for value in custom_data[:3])
    rows = _selected_rows(winner_selection)
    if rows:
        row = winning_industries.iloc[rows[0]]
        return str(row["Region"]), str(row["Sector"]), str(row["Industry"])
    return None


def _selected_rows(event: Any) -> list[int]:
    selection = event.get("selection", {})
    return list(selection.get("rows", []))


def _selected_points(event: Any) -> list[dict[str, Any]]:
    selection = event.get("selection", {})
    return list(selection.get("points", []))


def _journey_progress(active_step: int) -> None:
    steps = [
        ("Market", "Market pulse", None),
        ("Rotation", "Rotation leaders", None),
        ("Research", "Stocks", "Overview"),
        ("Trade plan", "Stocks", "Risk & trade plan"),
    ]
    columns = st.columns(4)
    for index, (column, step) in enumerate(zip(columns, steps, strict=True), start=1):
        label, page, section = step
        if index == active_step:
            column.button(
                f"{index}. {label}",
                disabled=True,
                key=f"journey_current_{active_step}_{index}",
                width="stretch",
            )
        elif column.button(
            f"{index}. {label}",
            key=f"journey_{active_step}_{index}",
            width="stretch",
        ):
            if section:
                st.session_state["pending_research_section"] = section
                st.session_state["pending_stocks_workspace_view"] = "Research"
            st.session_state["pending_workspace_page"] = page
            st.rerun()


def _heading(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="eyebrow">DECISION WORKSPACE</div>
        <h1>{title}</h1>
        <p class="subtitle">{subtitle}</p>
        """,
        unsafe_allow_html=True,
    )


def _theme() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Newsreader:opsz,wght@6..72,600&display=swap');
        :root {
            --canvas: #0d1418;
            --surface: #151e22;
            --surface-raised: #1a2529;
            --border: #2b3a3e;
            --text: #edf2ef;
            --muted: #a9b7b3;
            --green: #49c28a;
            --amber: #f4c95d;
            --coral: #ff8066;
            color-scheme: dark;
        }
        .stApp {
            background: linear-gradient(135deg, #0d1418 0%, #111b1e 58%, #151a1b 100%);
            color: var(--text);
            font-family: 'DM Sans', sans-serif;
        }
        [data-testid="stAppViewContainer"] > .main {
            background: transparent;
        }
        [data-testid="stHeader"] {
            background: rgba(9, 14, 17, 0.94);
            border-bottom: 1px solid var(--border);
        }
        h1, h2, h3 {
            font-family: 'Newsreader', serif !important;
            color: var(--text) !important;
            letter-spacing: 0 !important;
        }
        h1 { font-size: 2.6rem !important; margin: 0 !important; }
        [data-testid="stSidebar"] {
            background: #101b1e;
            border-right: 1px solid var(--border);
        }
        [data-testid="stSidebar"] * { color: var(--text); }
        [data-testid="stMetric"] {
            border-top: 3px solid var(--green);
            background: rgba(21, 30, 34, 0.66);
            border-bottom: 1px solid var(--border);
            padding: 0.9rem 0;
        }
        [data-testid="stMetricLabel"] p { color: var(--muted) !important; }
        [data-testid="stMetricValue"] { color: var(--text) !important; }
        .brand {
            font-family: 'Newsreader', serif;
            font-size: 1.35rem;
            letter-spacing: 0.08rem;
            color: var(--amber) !important;
            margin: 0.4rem 0 0;
        }
        .eyebrow {
            color: var(--green);
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.08rem;
            margin-top: 0.5rem;
        }
        .subtitle {
            color: var(--muted);
            margin-top: 0.15rem;
            margin-bottom: 1.7rem;
        }
        [data-testid="stCaptionContainer"] { color: var(--muted); }
        [data-baseweb="input"],
        [data-baseweb="textarea"],
        [data-baseweb="select"] > div {
            background: var(--surface) !important;
            border-color: var(--border) !important;
        }
        [data-baseweb="tab-list"] {
            border-bottom: 1px solid var(--border);
        }
        [data-baseweb="tab"] { color: var(--muted); }
        [aria-selected="true"][data-baseweb="tab"] { color: var(--green); }
        .stButton > button[kind="primary"],
        .stFormSubmitButton > button[kind="primary"] {
            background: var(--green);
            border-color: var(--green);
            color: #07120d;
        }
        .stButton > button[kind="secondary"],
        .stDownloadButton > button {
            background: var(--surface-raised);
            border-color: var(--border);
            color: var(--text);
        }
        [data-testid="stDataFrame"] {
            border: 1px solid var(--border);
            background: var(--surface);
        }
        hr { border-color: var(--border) !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
