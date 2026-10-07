"""Core research engine for the leveraged MSCI World factor portfolio."""

from .benchmark import (
    BenchmarkComparison,
    build_same_leverage_comparison,
    calculate_risk_adjusted_metrics,
    load_benchmark_comparison,
    summarise_backtest,
    write_benchmark_comparison,
)
from .config import (
    ECB_USD_PER_CHF_2026_08_31,
    FeeSchedule,
    PortfolioConfig,
    SwissquoteStandardFeeSchedule,
)
from .confirmation import (
    ConfirmationEvaluation,
    build_confirmation_evaluation,
    load_confirmation_evaluation,
    write_confirmation_evaluation,
)
from .engine import BacktestResult, InsolventPortfolioError, run_backtest
from .dimensional import (
    ThreeWayComparison,
    build_three_way_comparison,
    load_three_way_comparison,
    write_three_way_comparison,
)
from .evaluation import (
    SplitEvaluation,
    build_split_evaluation,
    load_split_evaluation,
    write_split_evaluation,
)
from .grid import (
    CalibrationGrid,
    build_calibration_grid,
    generate_predeclared_grid,
    load_calibration_grid,
    write_calibration_grid,
)
from .reference import (
    InvestableReferenceComparison,
    build_investable_reference_comparison,
    load_investable_reference_comparison,
    write_investable_reference_comparison,
)

__all__ = [
    "BacktestResult",
    "BenchmarkComparison",
    "CalibrationGrid",
    "ConfirmationEvaluation",
    "ECB_USD_PER_CHF_2026_08_31",
    "FeeSchedule",
    "InsolventPortfolioError",
    "InvestableReferenceComparison",
    "PortfolioConfig",
    "SplitEvaluation",
    "SwissquoteStandardFeeSchedule",
    "ThreeWayComparison",
    "build_same_leverage_comparison",
    "calculate_risk_adjusted_metrics",
    "build_calibration_grid",
    "build_confirmation_evaluation",
    "build_split_evaluation",
    "build_investable_reference_comparison",
    "build_three_way_comparison",
    "load_benchmark_comparison",
    "load_calibration_grid",
    "load_confirmation_evaluation",
    "load_split_evaluation",
    "load_investable_reference_comparison",
    "load_three_way_comparison",
    "run_backtest",
    "summarise_backtest",
    "generate_predeclared_grid",
    "write_benchmark_comparison",
    "write_calibration_grid",
    "write_confirmation_evaluation",
    "write_split_evaluation",
    "write_investable_reference_comparison",
    "write_three_way_comparison",
]
