# -*- coding: utf-8 -*-
"""
策略回测模块

提供历史数据回测功能，支持多种策略的回测
"""
from app.services.backtest.engine import (
    BacktestEngine,
    BacktestResult,
    PriceData,
    Trade,
    Position,
    mean_reversion_strategy,
    grid_strategy,
    trend_following_strategy,
)
from app.services.backtest.report import BacktestReport

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "PriceData",
    "Trade",
    "Position",
    "BacktestReport",
    "mean_reversion_strategy",
    "grid_strategy",
    "trend_following_strategy",
]
