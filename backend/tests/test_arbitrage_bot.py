# -*- coding: utf-8 -*-
"""
搬砖机器人测试
"""
import sys
import os
# Add parent directory to path for bot imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
import pytest_asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from bot.internal.arbitrage_bot import ArbitrageBot
from bot.internal.trading_bot_base import BotStatus, BotPlatform


class TestArbitrageBot:
    """搬砖机器人测试"""
    
    @pytest.fixture
    def bot_config(self):
        """机器人配置"""
        return {
            "min_profit": 5.0,
            "min_profit_percent": 10.0,
            "max_single_trade": 500.0,
            "check_interval": 10,
            "max_trades_per_hour": 5,
        }
    
    @pytest.fixture
    def arbitrage_bot(self, bot_config):
        """创建搬砖机器人实例"""
        return ArbitrageBot(
            bot_id=1,
            name="Test Arbitrage Bot",
            config=bot_config
        )
    
    def test_bot_initialization(self, arbitrage_bot):
        """测试机器人初始化"""
        assert arbitrage_bot.bot_id == 1
        assert arbitrage_bot.name == "Test Arbitrage Bot"
        assert arbitrage_bot.status == BotStatus.STOPPED
        assert arbitrage_bot.platform == BotPlatform.BUFF_TO_STEAM
    
    def test_bot_config_defaults(self, arbitrage_bot):
        """测试默认配置"""
        assert arbitrage_bot.config["min_profit"] == 5.0
        assert arbitrage_bot.config["min_profit_percent"] == 10.0
        assert arbitrage_bot.config["max_single_trade"] == 500.0
    
    @pytest.mark.asyncio
    async def test_bot_start_stop(self, arbitrage_bot):
        """测试机器人启动和停止"""
        # 启动
        await arbitrage_bot.start()
        assert arbitrage_bot.status == BotStatus.RUNNING
        
        # 停止
        await arbitrage_bot.stop()
        assert arbitrage_bot.status == BotStatus.STOPPED
    
    @pytest.mark.asyncio
    async def test_bot_pause_resume(self, arbitrage_bot):
        """测试机器人暂停和恢复"""
        await arbitrage_bot.start()
        assert arbitrage_bot.status == BotStatus.RUNNING
        
        # 暂停
        await arbitrage_bot.pause()
        assert arbitrage_bot.status == BotStatus.PAUSED
        assert arbitrage_bot._paused is True
        
        # 恢复
        await arbitrage_bot.resume()
        assert arbitrage_bot.status == BotStatus.RUNNING
        assert arbitrage_bot._paused is False
    
    def test_filter_opportunities(self, arbitrage_bot):
        """测试搬砖机会过滤"""
        opportunities = [
            {"name": "Item A", "profit": 20.0, "profit_percent": 15.0, "buff_price": 100.0},
            {"name": "Item B", "profit": 3.0, "profit_percent": 5.0, "buff_price": 50.0},  # 利润太低
            {"name": "Item C", "profit": 8.0, "profit_percent": 8.0, "buff_price": 100.0},  # 利润率太低
            {"name": "Item D", "profit": 10.0, "profit_percent": 10.0, "buff_price": 600.0},  # 超单笔限制
        ]
        
        filtered = arbitrage_bot._filter_opportunities(opportunities)
        
        # 应该只保留 Item A
        assert len(filtered) == 1
        assert filtered[0]["name"] == "Item A"
    
    def test_filter_opportunities_exclude_list(self, arbitrage_bot):
        """测试排除列表过滤"""
        arbitrage_bot.config["excluded_items"] = ["AK-47 | Redline"]
        
        opportunities = [
            {"name": "AK-47 | Redline", "profit": 20.0, "profit_percent": 15.0, "buff_price": 100.0},
            {"name": "M4A4 | Howl", "profit": 20.0, "profit_percent": 15.0, "buff_price": 100.0},
        ]
        
        filtered = arbitrage_bot._filter_opportunities(opportunities)
        
        assert len(filtered) == 1
        assert filtered[0]["name"] == "M4A4 | Howl"
    
    def test_filter_opportunities_enabled_list(self, arbitrage_bot):
        """测试启用列表过滤"""
        arbitrage_bot.config["enabled_items"] = ["AK-47 | Redline"]
        
        opportunities = [
            {"name": "AK-47 | Redline", "profit": 20.0, "profit_percent": 15.0, "buff_price": 100.0},
            {"name": "M4A4 | Howl", "profit": 20.0, "profit_percent": 15.0, "buff_price": 100.0},
        ]
        
        filtered = arbitrage_bot._filter_opportunities(opportunities)
        
        assert len(filtered) == 1
        assert filtered[0]["name"] == "AK-47 | Redline"
    
    @pytest.mark.asyncio
    async def test_check_trade_limit_not_reached(self, arbitrage_bot):
        """测试未达到交易限制"""
        arbitrage_bot.stats["last_trade_time"] = datetime.utcnow()
        
        # 无交易历史，应该返回False
        result = await arbitrage_bot._check_trade_limit()
        assert result is False
    
    @pytest.mark.asyncio
    async def test_check_trade_limit_reached(self, arbitrage_bot):
        """测试达到交易限制"""
        arbitrage_bot.config["max_trades_per_hour"] = 2
        
        # 添加2笔交易记录（在过去1小时内）
        now = datetime.utcnow()
        arbitrage_bot._trade_history = [
            {"timestamp": now.isoformat(), "profit": 10.0},
            {"timestamp": (now - timedelta(minutes=30)).isoformat(), "profit": 15.0},
        ]
        arbitrage_bot.stats["last_trade_time"] = now
        
        result = await arbitrage_bot._check_trade_limit()
        assert result is True
    
    @pytest.mark.asyncio
    async def test_check_trade_limit_old_trades(self, arbitrage_bot):
        """测试旧交易记录不计入限制"""
        arbitrage_bot.config["max_trades_per_hour"] = 2
        
        # 添加2笔交易记录（超过1小时）
        now = datetime.utcnow()
        arbitrage_bot._trade_history = [
            {"timestamp": (now - timedelta(hours=2)).isoformat(), "profit": 10.0},
            {"timestamp": (now - timedelta(hours=2)).isoformat(), "profit": 15.0},
        ]
        arbitrage_bot.stats["last_trade_time"] = now - timedelta(hours=2)
        
        result = await arbitrage_bot._check_trade_limit()
        assert result is False
    
    @pytest.mark.asyncio
    async def test_get_stats(self, arbitrage_bot):
        """测试获取统计信息"""
        # 添加交易历史
        arbitrage_bot._trade_history = [
            {"timestamp": datetime.utcnow().isoformat(), "profit": 10.0},
            {"timestamp": datetime.utcnow().isoformat(), "profit": 15.0},
        ]
        arbitrage_bot.stats["total_trades"] = 2
        arbitrage_bot.stats["successful_trades"] = 2
        
        stats = await arbitrage_bot.get_stats()
        
        assert stats["total_trades"] == 2
        assert stats["successful_trades"] == 2
        assert "avg_profit" in stats
        assert stats["avg_profit"] == 12.5
    
    @pytest.mark.asyncio
    async def test_get_trade_history(self, arbitrage_bot):
        """测试获取交易历史"""
        now = datetime.utcnow()
        arbitrage_bot._trade_history = [
            {"timestamp": now.isoformat(), "profit": 10.0, "item_name": "Item A"},
            {"timestamp": now.isoformat(), "profit": 15.0, "item_name": "Item B"},
        ]
        
        history = await arbitrage_bot.get_trade_history(limit=1)
        
        assert len(history) == 1


class TestBotTradingLogic:
    """机器人交易逻辑测试"""
    
    @pytest.fixture
    def arbitrage_bot(self):
        return ArbitrageBot(
            bot_id=1,
            name="Test Bot",
            config={"max_trades_per_hour": 10}
        )
    
    @pytest.mark.asyncio
    async def test_buy_from_buff_without_client(self, arbitrage_bot):
        """测试未初始化BUFF客户端"""
        result = await arbitrage_bot._buy_from_buff(1, 100.0)
        
        assert result["success"] is False
        assert "未初始化" in result["message"]
    
    @pytest.mark.asyncio
    async def test_sell_to_steam(self, arbitrage_bot):
        """测试Steam卖出"""
        result = await arbitrage_bot._sell_to_steam(1, 100.0)
        
        # Steam卖出功能待实现
        assert result["success"] is True
