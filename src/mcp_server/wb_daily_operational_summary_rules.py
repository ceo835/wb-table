from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class WbDailyOperationalSummaryRules:
    minimum_impressions: int = 1000
    significant_pct_change: Decimal = Decimal("5")
    significant_pp_change: Decimal = Decimal("0.5")
    high_drr_threshold: Decimal = Decimal("25")
    zero_order_spend_threshold: Decimal = Decimal("500")
    low_stock_days: Decimal = Decimal("3")
    high_stock_days: Decimal = Decimal("45")
    minimum_sales_for_stock_signal: Decimal = Decimal("1")
    search_position_change_threshold: Decimal = Decimal("3")


def get_default_rules() -> WbDailyOperationalSummaryRules:
    return WbDailyOperationalSummaryRules()
