"""Built-in dashboard widgets."""

from stockfinder.widget_registry import WidgetRegistry
from stockfinder.widgets.alert_center import render_alert_center
from stockfinder.widgets.cross_asset_conditions import render_cross_asset_conditions
from stockfinder.widgets.instrument_analysis import render_instrument_analysis
from stockfinder.widgets.liquidity_breadth import render_liquidity_breadth
from stockfinder.widgets.market_regime import render_market_regime
from stockfinder.widgets.peer_comparison import render_peer_comparison
from stockfinder.widgets.portfolio_exposure import render_portfolio_exposure
from stockfinder.widgets.ranked_stocks import render_ranked_stocks
from stockfinder.widgets.regional_markets import render_regional_markets
from stockfinder.widgets.rotation_explorer import render_rotation_explorer
from stockfinder.widgets.rule_profile_editor import render_rule_profile_editor
from stockfinder.widgets.security_score_evidence import render_security_score_evidence
from stockfinder.widgets.trade_plan import render_trade_plan


def built_in_widget_registry() -> WidgetRegistry:
    """Return a registry containing every built-in widget type."""
    registry = WidgetRegistry()
    registry.register("alert_center", render_alert_center)
    registry.register("market_regime", render_market_regime)
    registry.register("cross_asset_conditions", render_cross_asset_conditions)
    registry.register("regional_markets", render_regional_markets)
    registry.register("liquidity_breadth", render_liquidity_breadth)
    registry.register("rotation_explorer", render_rotation_explorer)
    registry.register("ranked_stocks", render_ranked_stocks)
    registry.register("instrument_analysis", render_instrument_analysis)
    registry.register("rule_profile_editor", render_rule_profile_editor)
    registry.register("security_score_evidence", render_security_score_evidence)
    registry.register("peer_comparison", render_peer_comparison)
    registry.register("trade_plan", render_trade_plan)
    registry.register("portfolio_exposure", render_portfolio_exposure)
    return registry