# -*- coding: utf-8 -*-
"""
交易服务
"""
import asyncio
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.item import Item
from app.models.order import Order
from app.models.inventory import Inventory
from app.services.buff_service import get_buff_client
from app.services.steam_service import SteamAPI, get_steam_api
from app.core.config import settings

logger = logging.getLogger(__name__)


# 输入验证常量
MIN_PRICE = 0.01       # 最低价格
MAX_PRICE = 100000.0   # 最高价格
MIN_QUANTITY = 1       # 最低数量
MAX_QUANTITY = 1000    # 最高数量


def validate_price(price: float, param_name: str = "price") -> None:
    """验证价格参数"""
    if not isinstance(price, (int, float)):
        raise ValueError(f"{param_name} 必须是数字类型")
    if price < MIN_PRICE:
        raise ValueError(f"{param_name} 不能低于 {MIN_PRICE}")
    if price > MAX_PRICE:
        raise ValueError(f"{param_name} 不能超过 {MAX_PRICE}")


def validate_quantity(quantity: int, param_name: str = "quantity") -> None:
    """验证数量参数"""
    if not isinstance(quantity, int):
        raise ValueError(f"{param_name} 必须是整数类型")
    if quantity < MIN_QUANTITY:
        raise ValueError(f"{param_name} 不能低于 {MIN_QUANTITY}")
    if quantity > MAX_QUANTITY:
        raise ValueError(f"{param_name} 不能超过 {MAX_QUANTITY}")


def validate_item_id(item_id: int) -> None:
    """验证物品ID"""
    if not isinstance(item_id, int) or item_id <= 0:
        raise ValueError("item_id 必须是正整数")


def validate_user_id(user_id: int) -> None:
    """验证用户ID"""
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id 必须是正整数")


def validate_min_profit(min_profit: float) -> None:
    """验证最小利润"""
    if not isinstance(min_profit, (int, float)):
        raise ValueError("min_profit 必须是数字类型")
    if min_profit < 0:
        raise ValueError("min_profit 不能为负数")


def validate_limit(limit: int) -> None:
    """验证返回数量限制"""
    if not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit 必须是正整数")
    if limit > 1000:
        raise ValueError("limit 不能超过 1000")


class TradingEngine:
    """交易引擎"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.buff_client = None
        self.steam_api = get_steam_api()
    
    def set_buff_client(self, cookie: str):
        """设置 BUFF 客户端"""
        self.buff_client = get_buff_client(cookie)
    
    async def get_arbitrage_opportunities(
        self,
        min_profit: float = settings.MIN_PROFIT,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """获取搬砖机会"""
        # 输入验证
        validate_min_profit(min_profit)
        validate_limit(limit)
        
        # 查询所有饰品
        result = await self.db.execute(
            select(Item).where(
                Item.current_price > 0,
                Item.steam_lowest_price > 0
            ).limit(limit * 2)
        )
        items = result.scalars().all()
        
        opportunities = []
        
        for item in items:
            # 计算搬砖利润 (Steam 出售需扣除 15% 手续费)
            steam_sell_price = item.steam_lowest_price * 0.85
            profit = steam_sell_price - item.current_price
            profit_percent = (profit / item.current_price * 100) if item.current_price > 0 else 0
            
            if profit >= min_profit:
                opportunities.append({
                    "item_id": item.id,
                    "name": item.name,
                    "buff_price": item.current_price,
                    "steam_price": item.steam_lowest_price,
                    "profit": round(profit, 2),
                    "profit_percent": round(profit_percent, 2),
                    "volume_24h": item.volume_24h,
                })
        
        # 按利润排序
        opportunities.sort(key=lambda x: x["profit"], reverse=True)
        
        return opportunities[:limit]
    
    async def execute_buy(
        self,
        item_id: int,
        max_price: float,
        quantity: int = 1,
        user_id: int = None
    ) -> Dict[str, Any]:
        """执行买入"""
        # 输入验证
        validate_item_id(item_id)
        validate_price(max_price, "max_price")
        validate_quantity(quantity)
        validate_user_id(user_id)
        
        if not self.buff_client:
            raise Exception("未设置 BUFF 客户端")
        
        if user_id is None:
            raise ValueError("execute_buy 必须提供 user_id 参数")
        
        # 获取饰品信息
        result = await self.db.execute(
            select(Item).where(Item.id == item_id)
        )
        item = result.scalar_one_or_none()
        
        if not item:
            raise Exception("饰品不存在")
        
        # 获取当前价格
        current_price = self.buff_client.get_price_overview(item.market_hash_name)
        if not current_price:
            raise Exception("无法获取价格")
        
        price = float(current_price.get("lowest_price", 0))
        
        if price > max_price:
            return {
                "success": False,
                "message": f"当前价格 {price} 高于最高价格 {max_price}",
            }
        
        # 创建订单
        try:
            order_result = await self.buff_client.create_order(
                goods_id=item.id,
                price=price,
                num=quantity
            )
            
            # 创建本地订单记录
            order = Order(
                order_id=f"BUY-{datetime.utcnow().timestamp()}",
                user_id=user_id,
                item_id=item_id,
                side="buy",
                price=price,
                quantity=quantity,
                source="buff",
                status="pending",
            )
            self.db.add(order)
            await self.db.commit()
            
            return {
                "success": True,
                "order_id": order.order_id,
                "price": price,
                "item": item.name,
            }
            
        except Exception as e:
            logger.error(f"买入失败: {e}")
            return {
                "success": False,
                "message": str(e),
            }
    
    async def execute_arbitrage(
        self,
        item_id: int,
        buy_platform: str = "buff",
        sell_platform: str = "steam"
    ) -> Dict[str, Any]:
        """执行搬砖"""
        if buy_platform == "buff" and not self.buff_client:
            raise Exception("未设置 BUFF 客户端")
        
        # 1. 买入
        buy_result = await self.execute_buy(item_id, max_price=999999)
        
        if not buy_result["success"]:
            return buy_result
        
        # 2. 等待到账 (实际需要轮询检查)
        await asyncio.sleep(10)
        
        # 3. 卖出 (上架到 Steam 市场)
        # 实际实现需要调用 Steam API
        
        return {
            "success": True,
            "buy_order_id": buy_result.get("order_id"),
            "message": "搬砖流程已启动",
        }
    
    async def auto_buy_by_monitor(
        self,
        item_id: int,
        max_price: float
    ) -> Dict[str, Any]:
        """根据监控规则自动买入"""
        return await self.execute_buy(item_id, max_price)
