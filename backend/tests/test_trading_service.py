# -*- coding: utf-8 -*-
"""
交易服务测试
"""
import pytest
import pytest_asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from app.services.trading_service import TradingEngine
from app.models.item import Item
from app.models.order import Order


class TestTradingEngine:
    """交易引擎测试"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock数据库会话"""
        db = AsyncMock()
        return db
    
    @pytest.fixture
    def mock_buff_client(self):
        """Mock BUFF客户端"""
        client = MagicMock()
        client.get_price_overview = Mock(return_value={
            "lowest_price": "100.00",
            "highest_price": "150.00",
        })
        client.create_order = AsyncMock(return_value={
            "code": "OK",
            "data": {"id": "order_123"}
        })
        return client
    
    @pytest.fixture
    def mock_item(self):
        """Mock物品数据"""
        item = Item(
            id=1,
            market_hash_name="AK-47 | Redline",
            current_price=100.0,
            steam_lowest_price=130.0,
            volume_24h=100,
        )
        return item
    
    @pytest.mark.asyncio
    async def test_get_arbitrage_opportunities(self, mock_db, mock_item):
        """测试获取搬砖机会"""
        # Mock查询结果
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_item]
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        engine = TradingEngine(mock_db)
        
        opportunities = await engine.get_arbitrage_opportunities(
            min_profit=10.0,
            limit=10
        )
        
        assert len(opportunities) == 1
        assert opportunities[0]["profit"] > 0
        assert opportunities[0]["name"] == "AK-47 | Redline"
    
    @pytest.mark.asyncio
    async def test_get_arbitrage_opportunities_no_items(self, mock_db):
        """测试无搬砖机会"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        engine = TradingEngine(mock_db)
        
        opportunities = await engine.get_arbitrage_opportunities()
        
        assert len(opportunities) == 0
    
    @pytest.mark.asyncio
    async def test_get_arbitrage_opportunities_below_min_profit(self, mock_db, mock_item):
        """测试低于最小利润门槛"""
        # 修改价格为接近Steam价格，无利润空间
        mock_item.current_price = 120.0
        mock_item.steam_lowest_price = 130.0
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_item]
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        engine = TradingEngine(mock_db)
        
        opportunities = await engine.get_arbitrage_opportunities(
            min_profit=50.0,
            limit=10
        )
        
        assert len(opportunities) == 0
    
    @pytest.mark.asyncio
    async def test_execute_buy_without_client(self, mock_db):
        """测试未设置BUFF客户端"""
        engine = TradingEngine(mock_db)
        
        with pytest.raises(Exception) as exc_info:
            await engine.execute_buy(
                item_id=1,
                max_price=100.0,
                user_id=1
            )
        
        assert "未设置 BUFF 客户端" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_execute_buy_without_user_id(self, mock_db):
        """测试未提供user_id"""
        engine = TradingEngine(mock_db)
        engine.set_buff_client("test_cookie")
        
        with pytest.raises(ValueError) as exc_info:
            await engine.execute_buy(
                item_id=1,
                max_price=100.0
            )
        
        assert "user_id" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_execute_buy_item_not_found(self, mock_db, mock_buff_client):
        """测试物品不存在"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        engine = TradingEngine(mock_db)
        engine.buff_client = mock_buff_client
        
        result = await engine.execute_buy(
            item_id=999,
            max_price=100.0,
            user_id=1
        )
        
        assert result["success"] is False
        assert "不存在" in result["message"]
    
    @pytest.mark.asyncio
    async def test_execute_buy_price_too_high(self, mock_db, mock_buff_client, mock_item):
        """测试价格过高"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_item
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        # 设置返回的价格高于max_price
        mock_buff_client.get_price_overview = Mock(return_value={
            "lowest_price": "200.00",  # 高于max_price=100
        })
        
        engine = TradingEngine(mock_db)
        engine.buff_client = mock_buff_client
        
        result = await engine.execute_buy(
            item_id=1,
            max_price=100.0,
            user_id=1
        )
        
        assert result["success"] is False
        assert "高于" in result["message"]
    
    @pytest.mark.asyncio
    async def test_execute_buy_success(self, mock_db, mock_buff_client, mock_item):
        """测试买入成功"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_item
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        engine = TradingEngine(mock_db)
        engine.buff_client = mock_buff_client
        
        # Mock commit
        mock_db.commit = AsyncMock()
        
        result = await engine.execute_buy(
            item_id=1,
            max_price=150.0,  # 高于当前价格100
            user_id=1
        )
        
        assert result["success"] is True
        assert "order_id" in result
        assert result["price"] == 100.0
        assert result["item"] == "AK-47 | Redline"
        
        # 验证订单被添加到db
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_buy_api_error(self, mock_db, mock_buff_client, mock_item):
        """测试买入API错误"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_item
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        # 设置API返回错误
        mock_buff_client.create_order = AsyncMock(
            side_effect=Exception("API错误")
        )
        
        engine = TradingEngine(mock_db)
        engine.buff_client = mock_buff_client
        
        result = await engine.execute_buy(
            item_id=1,
            max_price=150.0,
            user_id=1
        )
        
        assert result["success"] is False
        assert "API错误" in result["message"]
    
    @pytest.mark.asyncio
    async def test_execute_arbitrage_without_client(self, mock_db):
        """测试执行搬砖未设置客户端"""
        engine = TradingEngine(mock_db)
        
        with pytest.raises(Exception) as exc_info:
            await engine.execute_arbitrage(
                item_id=1,
                buy_platform="buff"
            )
        
        assert "未设置 BUFF 客户端" in str(exc_info.value)
    
    @pytest.mark.asyncio
    @patch('asyncio.sleep', new_callable=AsyncMock)
    async def test_execute_arbitrage_success(self, mock_sleep, mock_db, mock_buff_client, mock_item):
        """测试搬砖流程成功"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_item
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        engine = TradingEngine(mock_db)
        engine.buff_client = mock_buff_client
        mock_db.commit = AsyncMock()
        
        result = await engine.execute_arbitrage(
            item_id=1,
            buy_platform="buff",
            sell_platform="steam"
        )
        
        assert result["success"] is True
        assert "buy_order_id" in result
    
    @pytest.mark.asyncio
    async def test_auto_buy_by_monitor(self, mock_db, mock_buff_client, mock_item):
        """测试根据监控自动买入"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_item
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        engine = TradingEngine(mock_db)
        engine.buff_client = mock_buff_client
        mock_db.commit = AsyncMock()
        
        result = await engine.auto_buy_by_monitor(
            item_id=1,
            max_price=150.0
        )
        
        assert result["success"] is True


class TestArbitrageCalculation:
    """搬砖利润计算测试"""
    
    @pytest.fixture
    def mock_db(self):
        return AsyncMock()
    
    @pytest.mark.asyncio
    async def test_profit_calculation(self, mock_db):
        """测试利润计算（含15%Steam手续费）"""
        # 场景：BUFF买入100，Steam卖出130
        # 130 * 0.85 = 110.5 (扣除15%手续费)
        # 利润 = 110.5 - 100 = 10.5
        
        item = Item(
            id=1,
            market_hash_name="Test Item",
            current_price=100.0,
            steam_lowest_price=130.0,
            volume_24h=50,
        )
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [item]
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        engine = TradingEngine(mock_db)
        opportunities = await engine.get_arbitrage_opportunities(
            min_profit=0,
            limit=10
        )
        
        assert len(opportunities) == 1
        assert opportunities[0]["profit"] == 10.5
        # 利润率 = 10.5 / 100 * 100% = 10.5%
        assert opportunities[0]["profit_percent"] == 10.5
    
    @pytest.mark.asyncio
    async def test_profit_percent_zero_price(self, mock_db):
        """测试价格为0时的利润率计算"""
        item = Item(
            id=1,
            market_hash_name="Test Item",
            current_price=0,  # 价格为0
            steam_lowest_price=100.0,
            volume_24h=10,
        )
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [item]
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        engine = TradingEngine(mock_db)
        opportunities = await engine.get_arbitrage_opportunities(
            min_profit=0,
            limit=10
        )
        
        # 价格为0时不应该产生机会
        assert len(opportunities) == 0


class TestOrderCreation:
    """订单创建测试"""
    
    @pytest_asyncio.fixture
    async def test_db(self):
        """使用真实数据库进行测试"""
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.pool import StaticPool
        from app.core.database import Base
        
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        async_session = AsyncSession(engine, expire_on_commit=False)
        
        yield async_session
        
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        
        await engine.dispose()
    
    @pytest.mark.asyncio
    async def test_order_creation_fields(self, test_db):
        """测试订单创建字段"""
        from sqlalchemy import select
        
        order = Order(
            order_id="TEST-001",
            user_id=1,
            item_id=1,
            side="buy",
            price=100.0,
            quantity=1,
            source="buff",
            status="pending",
        )
        
        test_db.add(order)
        await test_db.commit()
        
        # 查询验证
        result = await test_db.execute(
            select(Order).where(Order.order_id == "TEST-001")
        )
        saved_order = result.scalar_one_or_none()
        
        assert saved_order is not None
        assert saved_order.order_id == "TEST-001"
        assert saved_order.side == "buy"
        assert saved_order.price == 100.0
