"""Validated configuration objects for the portfolio engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Mapping


ECB_USD_PER_CHF_2026_08_31 = 1.1596 / 0.9376


def _cost_breakdown(
    *,
    commission_usd: float = 0.0,
    platform_fee_usd: float = 0.0,
    stamp_duty_usd: float = 0.0,
    spread_cost_usd: float = 0.0,
    other_fee_usd: float = 0.0,
) -> dict[str, float]:
    components = {
        "commission_usd": float(commission_usd),
        "platform_fee_usd": float(platform_fee_usd),
        "stamp_duty_usd": float(stamp_duty_usd),
        "spread_cost_usd": float(spread_cost_usd),
        "other_fee_usd": float(other_fee_usd),
    }
    components["total_usd"] = float(sum(components.values()))
    return components


@dataclass(frozen=True)
class FeeSchedule:
    """Simple per-leg transaction-cost schedule in USD."""

    proportional_rate: float = 0.0
    minimum_per_trade: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.proportional_rate < 1.0:
            raise ValueError("proportional_rate must be in [0, 1)")
        if self.minimum_per_trade < 0.0:
            raise ValueError("minimum_per_trade must be non-negative")

    def cost(self, notional: float, *, tolerance: float = 1e-12) -> float:
        """Return the fee for one ETF trade leg."""

        return self.breakdown(notional, tolerance=tolerance)["total_usd"]

    def breakdown(
        self, notional: float, *, tolerance: float = 1e-12
    ) -> dict[str, float]:
        """Return a component-compatible breakdown for one ETF trade leg."""

        magnitude = abs(float(notional))
        if magnitude <= tolerance:
            return _cost_breakdown()
        return _cost_breakdown(
            other_fee_usd=max(
                self.minimum_per_trade, magnitude * self.proportional_rate
            )
        )


@dataclass(frozen=True)
class SwissquoteStandardFeeSchedule:
    """Current-cost scenario for standard Swissquote ETF trades.

    The current CHF commission table is converted once at the fixed research
    endpoint. All other components are already expressed in USD or as a share of
    the USD trade notional. This is not a reconstruction of historical tariffs.
    """

    usd_per_chf: float = ECB_USD_PER_CHF_2026_08_31
    platform_fee_usd: float = 0.85
    stamp_duty_rate: float = 0.0015
    spread_rate: float = 0.0005

    def __post_init__(self) -> None:
        if not isfinite(self.usd_per_chf) or self.usd_per_chf <= 0.0:
            raise ValueError("usd_per_chf must be finite and positive")
        if not isfinite(self.platform_fee_usd) or self.platform_fee_usd < 0.0:
            raise ValueError("platform_fee_usd must be finite and non-negative")
        for name, value in {
            "stamp_duty_rate": self.stamp_duty_rate,
            "spread_rate": self.spread_rate,
        }.items():
            if not isfinite(value) or not 0.0 <= value < 1.0:
                raise ValueError(f"{name} must be finite and in [0, 1)")

    @staticmethod
    def commission_chf(notional: float) -> float:
        """Return the current standard Swissquote commission in CHF."""

        magnitude = abs(float(notional))
        if magnitude <= 500.0:
            return 3.0
        if magnitude <= 1_000.0:
            return 5.0
        if magnitude <= 2_000.0:
            return 10.0
        if magnitude <= 10_000.0:
            return 29.0
        if magnitude <= 15_000.0:
            return 49.0
        if magnitude <= 25_000.0:
            return 79.0
        if magnitude <= 50_000.0:
            return 129.0
        return 190.0

    def cost(self, notional: float, *, tolerance: float = 1e-12) -> float:
        """Return total modelled cost for one ETF trade leg in USD."""

        return self.breakdown(notional, tolerance=tolerance)["total_usd"]

    def breakdown(
        self, notional: float, *, tolerance: float = 1e-12
    ) -> dict[str, float]:
        """Return separately auditable USD cost components for one trade leg."""

        magnitude = abs(float(notional))
        if magnitude <= tolerance:
            return _cost_breakdown()
        return _cost_breakdown(
            commission_usd=self.commission_chf(magnitude) * self.usd_per_chf,
            platform_fee_usd=self.platform_fee_usd,
            stamp_duty_usd=magnitude * self.stamp_duty_rate,
            spread_cost_usd=magnitude * self.spread_rate,
        )


@dataclass(frozen=True)
class PortfolioConfig:
    """Economic and rebalancing assumptions for one backtest run."""

    target_weights: Mapping[str, float]
    initial_equity_usd: float = 10_000.0
    target_leverage: float = 1.25
    sleeve_band: float = 0.05
    leverage_band: float | None = 0.10
    reset_leverage_on_rebalance: bool = False
    max_leverage: float | None = None
    day_count: float = 360.0
    fee_schedule: FeeSchedule | SwissquoteStandardFeeSchedule = field(
        default_factory=SwissquoteStandardFeeSchedule
    )

    def __post_init__(self) -> None:
        weights = dict(self.target_weights)
        if not weights:
            raise ValueError("target_weights must not be empty")
        if any(not isfinite(value) or value <= 0.0 for value in weights.values()):
            raise ValueError("all target weights must be finite and positive")
        if abs(sum(weights.values()) - 1.0) > 1e-10:
            raise ValueError("target weights must sum to 1")
        if not isfinite(self.initial_equity_usd) or self.initial_equity_usd <= 0.0:
            raise ValueError("initial_equity_usd must be finite and positive")
        if not isfinite(self.target_leverage) or self.target_leverage < 1.0:
            raise ValueError("target_leverage must be finite and at least 1")
        if not isfinite(self.sleeve_band) or not 0.0 <= self.sleeve_band < 1.0:
            raise ValueError("sleeve_band must be in [0, 1)")
        if self.leverage_band is not None:
            if not isfinite(self.leverage_band) or self.leverage_band < 0.0:
                raise ValueError("leverage_band must be finite and non-negative")
        if self.max_leverage is not None:
            if self.max_leverage <= self.target_leverage:
                raise ValueError("max_leverage must exceed target_leverage")
        if not isfinite(self.day_count) or self.day_count <= 0.0:
            raise ValueError("day_count must be finite and positive")

        object.__setattr__(self, "target_weights", weights)
