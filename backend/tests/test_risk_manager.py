# -*- coding: utf-8 -*-
"""
RiskManager 单元测试
"""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.risk_manager import (
    RiskManager,
    RiskLevel,
    RiskEventType,
    RiskRule,
    RiskEvent,
    get_risk_manager,
)


class TestRiskRule:
    """RiskRule 数据类测试"""
    
    def test_risk_rule_creation(self):
        """测试风险规则创建"""
        rule = RiskRule(
            name="test_rule",
            enabled=True,
            max_single_trade=1000.0,
            stop_loss_percent=10.0,
            take_profit_percent=30.0,
        )
        
        assert rule.name == "test_rule"
        assert rule.enabled is True
        assert rule.max_single_trade == 1000.0
        assert rule.stop_loss_percent == 10.0
        assert rule.take_profit_percent == 30.0
    
    def test_risk_rule_defaults(self):
        """测试风险规则默认值"""
        rule = RiskRule(name="default_rule")
        
        assert rule.enabled is True
        assert rule.max_position_size == 0
        assert rule.max_single_trade == 0
        assert rule.max_daily_loss == 0
        assert rule.max_daily_trade_amount == 0
        assert rule.stop_loss_percent == 0
        assert rule.take_profit_percent == 0
        assert rule.max_position_concentration == 0.3


class TestRiskEvent:
    """RiskEvent 数据类测试"""
    
    def test_risk_event_creation(self):
        """测试风险事件创建"""
        event = RiskEvent(
            event_type=RiskEventType.SINGLE_TRADE_EXCEEDED,
            risk_level=RiskLevel.HIGH,
            user_id=123,
            item_id=456,
            details="测试详情",
            metadata={"amount": 1000, "limit": 500}
        )
        
        assert event.event_type == RiskEventType.SINGLE_TRADE_EXCEEDED
        assert event.risk_level == RiskLevel.HIGH
        assert event.user_id == 123
        assert event.item_id == 456
        assert event.details == "测试详情"
        assert event.metadata["amount"] == 1000
        assert isinstance(event.timestamp, datetime)


class TestRiskManager:
    """RiskManager 测试"""
    
    @pytest.fixture
    def mock_db(self):
        """创建模拟数据库会话"""
        db = AsyncMock()
        return db
    
    @pytest.fixture
    def risk_manager(self, mock_db):
        """创建RiskManager实例"""
        return RiskManager(mock_db)
    
    def test_risk_manager_creation(self, risk_manager):
        """测试RiskManager创建"""
        assert risk_manager is not None
        assert risk_manager.db is not None
        assert len(risk_manager._rules) > 0
    
    def test_default_rules_loaded(self, risk_manager):
        """测试默认规则加载"""
        rules = risk_manager.get_rules()
        
        assert "position_size" in rules
        assert "single_trade" in rules
        assert "daily_limit" in rules
        assert "stop_loss" in rules
        assert "take_profit" in rules
        assert "concentration" in rules
    
    def test_update_rule(self, risk_manager):
        """测试规则更新"""
        result = risk_manager.update_rule(
            "single_trade",
            max_single_trade=2000.0
        )
        
        assert result is True
        assert risk_manager._rules["single_trade"].max_single_trade == 2000.0
    
    def test_update_nonexistent_rule(self, risk_manager):
        """测试更新不存在的规则"""
        result = risk_manager.update_rule(
            "nonexistent_rule",
            max_single_trade=2000.0
        )
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_check_single_trade_limit_pass(self, risk_manager):
        """测试单笔交易限额检查 - 通过"""
        passed, event = await risk_manager._check_single_trade_limit(
            user_id=123,
            price=100.0,
            quantity=1
        )
        
        assert passed is True
        assert event is None
    
    @pytest.mark.asyncio
    async def test_check_single_trade_limit_fail(self, risk_manager):
        """测试单笔交易限额检查 - 失败"""
        # 设置一个较低的单笔限额
        risk_manager._rules["single_trade"].max_single_trade = 50.0
        
        passed, event = await risk_manager._check_single_trade_limit(
            user_id=123,
            price=100.0,
            quantity=1
        )
        
        assert passed is False
        assert event is not None
        assert event.event_type == RiskEventType.SINGLE_TRADE_EXCEEDED
        assert event.risk_level == RiskLevel.HIGH
        assert event.user_id == 123
    
    @pytest.mark.asyncio
    async def test_check_daily_limit_pass(self, risk_manager):
        """测试每日限额检查 - 通过"""
        with patch.object(risk_manager, '_get_daily_trade_amount', return_value=0):
            passed, event = await risk_manager._check_daily_limit(
                user_id=123,
                amount=1000.0
            )
            
            assert passed is True
            assert event is None
    
    @pytest.mark.asyncio
    async def test_check_daily_limit_fail(self, risk_manager):
        """测试每日限额检查 - 失败"""
        # 设置每日限额为1000
        risk_manager._rules["daily_limit"].max_daily_trade_amount = 1000.0
        
        with patch.object(risk_manager, '_get_daily_trade_amount', return_value=500.0):
            passed, event = await risk_manager._check_daily_limit(
                user_id=123,
                amount=600.0
            )
            
            assert passed is False
            assert event is not None
            assert event.event_type == RiskEventType.DAILY_LIMIT_EXCEEDED
            assert event.risk_level == RiskLevel.CRITICAL
    
    @pytest.mark.asyncio
    async def test_check_stop_loss_triggered(self, risk_manager):
        """测试止损触发"""
        # 设置止损阈值为10%
        risk_manager._rules["stop_loss"].stop_loss_percent = 10.0
        
        # 模拟持仓成本价为100，当前价格为85（亏损15%）
        with patch.object(risk_manager, '_get_user_position', return_value={"quantity": 1, "avg_price": 85}):
            with patch.object(risk_manager, '_get_cost_basis', return_value=100.0):
                passed, event = await risk_manager._check_stop_loss(
                    user_id=123,
                    item_id=456,
                    current_price=85.0
                )
                
                assert passed is False
                assert event is not None
                assert event.event_type == RiskEventType.STOP_LOSS_TRIGGERED
                assert event.risk_level == RiskLevel.CRITICAL
    
    @pytest.mark.asyncio
    async def test_check_stop_loss_not_triggered(self, risk_manager):
        """测试止损未触发"""
        # 设置止损阈值为10%
        risk_manager._rules["stop_loss"].stop_loss_percent = 10.0
        
        # 模拟持仓成本价为100，当前价格为95（亏损5%，未达到止损）
        with patch.object(risk_manager, '_get_user_position', return_value={"quantity": 1, "avg_price": 95}):
            with patch.object(risk_manager, '_get_cost_basis', return_value=100.0):
                passed, event = await risk_manager._check_stop_loss(
                    user_id=123,
                    item_id=456,
                    current_price=95.0
                )
                
                assert passed is True
                assert event is None
    
    @pytest.mark.asyncio
    async def test_check_take_profit_triggered(self, risk_manager):
        """测试止盈触发"""
        # 设置止盈阈值为30%
        risk_manager._rules["take_profit"].take_profit_percent = 30.0
        
        # 模拟持仓成本价为100，当前价格为135（盈利35%）
        with patch.object(risk_manager, '_get_user_position', return_value={"quantity": 1, "avg_price": 135}):
            with patch.object(risk_manager, '_get_cost_basis', return_value=100.0):
                passed, event = await risk_manager._check_take_profit(
                    user_id=123,
                    item_id=456,
                    current_price=135.0
                )
                
                assert passed is False
                assert event is not None
                assert event.event_type == RiskEventType.TAKE_PROFIT_TRIGGERED
                assert event.risk_level == RiskLevel.LOW
    
    @pytest.mark.asyncio
    async def test_check_concentration_risk_pass(self, risk_manager):
        """测试持仓集中度检查 - 通过"""
        risk_manager._rules["concentration"].max_position_concentration = 0.3
        
        # 模拟总持仓1000，新持仓100，占比9%（未超过30%）
        with patch.object(risk_manager, '_get_total_position', return_value=1000.0):
            with patch.object(risk_manager, '_get_item_position', return_value=0.0):
                passed, event = await risk_manager._check_concentration_risk(
                    user_id=123,
                    item_id=456,
                    amount=100.0
                )
                
                assert passed is True
                assert event is None
    
    @pytest.mark.asyncio
    async def test_check_concentration_risk_fail(self, risk_manager):
        """测试持仓集中度检查 - 失败"""
        risk_manager._rules["concentration"].max_position_concentration = 0.3
        
        # 模拟总持仓1000，新持仓400，占比40%（超过30%）
        with patch.object(risk_manager, '_get_total_position', return_value=1000.0):
            with patch.object(risk_manager, '_get_item_position', return_value=300.0):
                passed, event = await risk_manager._check_concentration_risk(
                    user_id=123,
                    item_id=456,
                    amount=100.0
                )
                
                assert passed is False
                assert event is not None
                assert event.event_type == RiskEventType.CONCENTRATION_RISK
                assert event.risk_level == RiskLevel.MEDIUM
    
    @pytest.mark.asyncio
    async def test_check_trade_risk_buy(self, risk_manager):
        """测试买入交易风险检查"""
        # 设置限额
        risk_manager._rules["single_trade"].max_single_trade = 10000.0
        risk_manager._rules["daily_limit"].max_daily_trade_amount = 50000.0
        
        with patch.object(risk_manager, '_get_daily_trade_amount', return_value=0.0):
            with patch.object(risk_manager, '_get_total_position', return_value=0.0):
                with patch.object(risk_manager, '_get_item_position', return_value=0.0):
                    passed, events = await risk_manager.check_trade_risk(
                        user_id=123,
                        item_id=456,
                        price=100.0,
                        quantity=1,
                        side="buy"
                    )
                    
                    # 应该通过检查
                    assert passed is True
                    # 可能有风险事件记录但级别不高
    
    @pytest.mark.asyncio
    async def test_check_trade_risk_sell_with_stop_loss(self, risk_manager):
        """测试卖出交易风险检查 - 触发止损"""
        risk_manager._rules["stop_loss"].stop_loss_percent = 10.0
        risk_manager._rules["single_trade"].max_single_trade = 10000.0
        
        with patch.object(risk_manager, '_get_total_position', return_value=100.0):
            with patch.object(risk_manager, '_get_daily_trade_amount', return_value=0.0):
                with patch.object(risk_manager, '_get_user_position', return_value={"quantity": 1, "avg_price": 85.0}):
                    with patch.object(risk_manager, '_get_cost_basis', return_value=100.0):
                        passed, events = await risk_manager.check_trade_risk(
                            user_id=123,
                            item_id=456,
                            price=85.0,
                            quantity=1,
                            side="sell"
                        )
                        
                        # 应该返回止损事件
                        assert any(e.event_type == RiskEventType.STOP_LOSS_TRIGGERED for e in events)
    
    @pytest.mark.asyncio
    async def test_check_position_risk(self, risk_manager):
        """测试持仓风险检查"""
        # 模拟有持仓
        with patch.object(risk_manager, '_get_user_position', return_value={"quantity": 2, "avg_price": 100.0}):
            with patch.object(risk_manager, '_get_cost_basis', return_value=100.0):
                result = await risk_manager.check_position_risk(
                    user_id=123,
                    item_id=456
                )
                
                assert result["has_position"] is True
                assert result["quantity"] == 2
                assert result["avg_price"] == 100.0
                assert result["cost_basis"] == 100.0
    
    @pytest.mark.asyncio
    async def test_check_position_risk_no_position(self, risk_manager):
        """测试持仓风险检查 - 无持仓"""
        with patch.object(risk_manager, '_get_user_position', return_value=None):
            result = await risk_manager.check_position_risk(
                user_id=123,
                item_id=456
            )
            
            assert result["has_position"] is False
            assert result["quantity"] == 0
    
    def test_get_rules(self, risk_manager):
        """测试获取规则"""
        rules = risk_manager.get_rules()
        
        assert "single_trade" in rules
        assert "enabled" in rules["single_trade"]
        assert rules["single_trade"]["enabled"] is True


class TestGetRiskManager:
    """get_risk_manager 便捷函数测试"""
    
    @pytest.mark.asyncio
    async def test_get_risk_manager(self):
        """测试获取RiskManager实例"""
        mock_db = AsyncMock()
        manager = await get_risk_manager(mock_db)
        
        assert manager is not None
        assert manager.db == mock_db


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestRiskCheckerBase:
    """RiskCheckerBase 测试"""
    
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        return db
    
    @pytest.fixture
    def risk_manager(self, mock_db):
        return RiskManager(mock_db)
    
    @pytest.fixture
    def mock_checker(self, risk_manager):
        from app.core.risk_manager import RiskCheckerBase
        return RiskCheckerBase(risk_manager)
    
    def test_checker_creation(self, mock_checker):
        assert mock_checker is not None
        assert mock_checker.enabled is True
    
    def test_checker_enable_disable(self, mock_checker):
        mock_checker.enabled = False
        assert mock_checker.enabled is False
        mock_checker.enabled = True
        assert mock_checker.enabled is True
    
    @pytest.mark.asyncio
    async def test_checker_check_not_implemented(self, mock_checker):
        with pytest.raises(NotImplementedError):
            await mock_checker.check(user_id=123)


class TestPriceDeviationChecker:
    """PriceDeviationChecker 测试"""
    
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        return db
    
    @pytest.fixture
    def risk_manager(self, mock_db):
        return RiskManager(mock_db)
    
    @pytest.fixture
    def price_checker(self, risk_manager):
        from app.core.risk_manager import PriceDeviationChecker
        return PriceDeviationChecker(risk_manager, threshold=10.0)
    
    def test_price_checker_creation(self, price_checker):
        assert price_checker is not None
        assert price_checker.threshold == 10.0
        assert price_checker.enabled is True
    
    def test_price_checker_enable_disable(self, price_checker):
        price_checker.enabled = False
        assert price_checker.enabled is False
    
    @pytest.mark.asyncio
    async def test_price_checker_disabled_passes(self, price_checker):
        price_checker.enabled = False
        passed, event = await price_checker.check(
            user_id=123,
            item_id=456,
            proposed_price=200.0
        )
        assert passed is True
        assert event is None
    
    @pytest.mark.asyncio
    async def test_price_checker_no_market_price(self, price_checker):
        # 模拟无市场价格
        with patch.object(price_checker, '_get_market_price', return_value=None):
            passed, event = await price_checker.check(
                user_id=123,
                item_id=456,
                proposed_price=100.0
            )
            assert passed is True
    
    @pytest.mark.asyncio
    async def test_price_checker_deviation_exceeds_threshold(self, price_checker):
        # 模拟市场价格为100，提议价格200（偏离100%）
        with patch.object(price_checker, '_get_market_price', return_value=100.0):
            passed, event = await price_checker.check(
                user_id=123,
                item_id=456,
                proposed_price=200.0
            )
            assert passed is False
            assert event is not None
            assert event.risk_level == RiskLevel.HIGH
    
    @pytest.mark.asyncio
    async def test_price_checker_deviation_within_threshold(self, price_checker):
        # 模拟市场价格为100，提议价格105（偏离5%）
        with patch.object(price_checker, '_get_market_price', return_value=100.0):
            passed, event = await price_checker.check(
                user_id=123,
                item_id=456,
                proposed_price=105.0
            )
            assert passed is True


class TestWashTradeChecker:
    """WashTradeChecker 测试"""
    
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        return db
    
    @pytest.fixture
    def risk_manager(self, mock_db):
        return RiskManager(mock_db)
    
    @pytest.fixture
    def wash_checker(self, risk_manager):
        from app.core.risk_manager import WashTradeChecker
        return WashTradeChecker(risk_manager, min_trades=3, time_window=300, max_trades=10)
    
    def test_wash_checker_creation(self, wash_checker):
        assert wash_checker is not None
        assert wash_checker.min_trades == 3
        assert wash_checker.time_window == 300
        assert wash_checker.max_trades == 10
    
    @pytest.mark.asyncio
    async def test_wash_checker_disabled_passes(self, wash_checker):
        wash_checker.enabled = False
        passed, event = await wash_checker.check(user_id=123)
        assert passed is True
        assert event is None
    
    @pytest.mark.asyncio
    async def test_wash_checker_normal_trades(self, wash_checker):
        # 模拟正常交易次数
        with patch.object(wash_checker, '_get_recent_trade_count', return_value=5):
            passed, event = await wash_checker.check(user_id=123)
            assert passed is True
    
    @pytest.mark.asyncio
    async def test_wash_checker_wash_trade_detected(self, wash_checker):
        # 模拟刷单（超过max_trades）
        with patch.object(wash_checker, '_get_recent_trade_count', return_value=15):
            passed, event = await wash_checker.check(user_id=123)
            assert passed is False
            assert event is not None
            assert event.risk_level == RiskLevel.CRITICAL
            assert "刷单" in event.details


class TestHighFrequencyChecker:
    """HighFrequencyChecker 测试"""
    
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        return db
    
    @pytest.fixture
    def risk_manager(self, mock_db):
        return RiskManager(mock_db)
    
    @pytest.fixture
    def hf_checker(self, risk_manager):
        from app.core.risk_manager import HighFrequencyChecker
        return HighFrequencyChecker(risk_manager, time_window=60, max_trades=5)
    
    def test_hf_checker_creation(self, hf_checker):
        assert hf_checker is not None
        assert hf_checker.time_window == 60
        assert hf_checker.max_trades == 5
    
    @pytest.mark.asyncio
    async def test_hf_checker_disabled_passes(self, hf_checker):
        hf_checker.enabled = False
        passed, event = await hf_checker.check(user_id=123)
        assert passed is True
        assert event is None
    
    @pytest.mark.asyncio
    async def test_hf_checker_normal_trades(self, hf_checker):
        # 模拟正常交易次数
        with patch.object(hf_checker, '_get_recent_trade_count', return_value=3):
            passed, event = await hf_checker.check(user_id=123)
            assert passed is True
    
    @pytest.mark.asyncio
    async def test_hf_checker_high_frequency_detected(self, hf_checker):
        # 模拟高频交易（超过max_trades）
        with patch.object(hf_checker, '_get_recent_trade_count', return_value=10):
            passed, event = await hf_checker.check(user_id=123)
            assert passed is False
            assert event is not None
            assert event.risk_level == RiskLevel.HIGH
            assert "高频" in event.details


class TestRiskManagerCheckers:
    """RiskManager 检查器集成测试"""
    
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        return db
    
    @pytest.fixture
    def risk_manager(self, mock_db):
        return RiskManager(mock_db)
    
    def test_checkers_initialized(self, risk_manager):
        assert hasattr(risk_manager, 'checkers')
        assert 'price_deviation' in risk_manager.checkers
        assert 'wash_trade' in risk_manager.checkers
        assert 'high_frequency' in risk_manager.checkers
    
    def test_get_checkers(self, risk_manager):
        checkers = risk_manager.get_checkers()
        assert 'price_deviation' in checkers
        assert checkers['price_deviation']['enabled'] is True
        assert checkers['price_deviation']['type'] == 'PriceDeviationChecker'
    
    def test_enable_checker(self, risk_manager):
        result = risk_manager.enable_checker('price_deviation')
        assert result is True
        assert risk_manager.checkers['price_deviation'].enabled is True
    
    def test_disable_checker(self, risk_manager):
        risk_manager.enable_checker('price_deviation')
        result = risk_manager.disable_checker('price_deviation')
        assert result is True
        assert risk_manager.checkers['price_deviation'].enabled is False
    
    def test_enable_nonexistent_checker(self, risk_manager):
        result = risk_manager.enable_checker('nonexistent')
        assert result is False
    
    def test_configure_checker(self, risk_manager):
        result = risk_manager.configure_checker('price_deviation', threshold=20.0)
        assert result is True
        assert risk_manager.checkers['price_deviation'].threshold == 20.0
    
    def test_configure_nonexistent_checker(self, risk_manager):
        result = risk_manager.configure_checker('nonexistent', threshold=20.0)
        assert result is False
