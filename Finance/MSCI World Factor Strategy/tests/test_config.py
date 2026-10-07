import pytest

from factor_portfolio import FeeSchedule, PortfolioConfig


def test_target_weights_must_sum_to_one() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        PortfolioConfig(target_weights={"core": 0.7, "value": 0.2})


def test_fee_schedule_applies_minimum_per_leg() -> None:
    fees = FeeSchedule(proportional_rate=0.001, minimum_per_trade=5.0)

    assert fees.cost(100.0) == 5.0
    assert fees.cost(-10_000.0) == 10.0
    assert fees.cost(0.0) == 0.0
