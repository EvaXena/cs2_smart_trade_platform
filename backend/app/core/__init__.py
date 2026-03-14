# -*- coding: utf-8 -*-
"""
CS2 智能交易平台 - 核心模块
"""
from app.core.config import settings
from app.core.database import get_db, engine, Base
from app.core.security import get_current_user, get_password_hash, verify_password
from app.core.exceptions import APIError, ValidationError, NotFoundError

# 导出熔断器
from app.core.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerOpen,
    circuit_breaker,
    CircuitBreakerDecorator,
)

# 导出 Session 管理器
from app.core.session_manager import (
    SessionManager,
    get_session_manager,
    close_session_manager,
)

# 导出风险管理器
from app.core.risk_manager import (
    RiskManager,
    RiskLevel,
    RiskEventType,
    RiskRule,
    RiskEvent,
    get_risk_manager,
    # 风险检查器
    RiskCheckerBase,
    PriceDeviationChecker,
    WashTradeChecker,
    HighFrequencyChecker,
)

__all__ = [
    # Config
    "settings",
    # Database
    "get_db",
    "engine",
    "Base",
    # Security
    "get_current_user",
    "get_password_hash",
    "verify_password",
    # Exceptions
    "APIError",
    "ValidationError",
    "NotFoundError",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitState",
    "CircuitBreakerOpen",
    "circuit_breaker",
    "CircuitBreakerDecorator",
    # Session Manager
    "SessionManager",
    "get_session_manager",
    "close_session_manager",
    # Risk Manager
    "RiskManager",
    "RiskLevel",
    "RiskEventType",
    "RiskRule",
    "RiskEvent",
    "get_risk_manager",
    # Risk Checkers
    "RiskCheckerBase",
    "PriceDeviationChecker",
    "WashTradeChecker",
    "HighFrequencyChecker",
]
