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
from app.core.response import ServiceResponse, success_response, error_response
# 导入 validators 中的验证函数
from app.utils.validators import (
    validate_price as validator_validate_price,
    validate_quantity as validator_validate_quantity,
    validate_item_id as validator_validate_item_id,
    validate_user_id as validator_validate_user_id,
    validate_min_profit as validator_validate_min_profit,
    validate_limit as validator_validate_limit,
)

logger = logging.getLogger(__name__)

# 默认超时配置
DEFAULT_TIMEOUT = 30  # 秒


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
    ) -> ServiceResponse:
        """获取搬砖机会"""
        # 输入验证（使用 validators.py 中的函数）
        validator_validate_min_profit(min_profit)
        validator_validate_limit(limit)
        
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
        
        return ServiceResponse.ok(
            data=opportunities[:limit],
            message=f"找到 {len(opportunities[:limit])} 个搬砖机会"
        )
    
    async def execute_buy(
        self,
        item_id: int,
        max_price: float,
        quantity: int = 1,
        user_id: int = None,
        timeout: int = DEFAULT_TIMEOUT
    ) -> Dict[str, Any]:
        """执行买入 (带超时控制)"""
        # 输入验证（使用 validators.py 中的函数）
        validator_validate_item_id(item_id)
        validator_validate_price(max_price, "max_price")
        validator_validate_quantity(quantity)
        validator_validate_user_id(user_id)
        
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
        
        # 获取当前价格 (带超时控制)
        try:
            current_price = await asyncio.wait_for(
                self.buff_client.get_price_overview(item.market_hash_name),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return ServiceResponse.err(
                message="获取价格超时",
                code="TIMEOUT"
            )
        
        if not current_price:
            raise Exception("无法获取价格")
        
        price = float(current_price.get("lowest_price", 0))
        
        if price > max_price:
            return ServiceResponse.err(
                message=f"当前价格 {price} 高于最高价格 {max_price}",
                code="PRICE_TOO_HIGH"
            )
        
        # 交易限额校验 (P0-1)
        total_price = price * quantity
        if total_price > settings.MAX_SINGLE_TRADE:
            return ServiceResponse.err(
                message=f"交易金额 {total_price:.2f} 超过单笔限额 {settings.MAX_SINGLE_TRADE}",
                code="EXCEEDS_MAX_TRADE"
            )
        
        # 创建订单 (带超时控制)
        try:
            order_result = await asyncio.wait_for(
                self.buff_client.create_order(
                    goods_id=item.id,
                    price=price,
                    num=quantity
                ),
                timeout=timeout
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
            
            return ServiceResponse.ok(
                data={
                    "order_id": order.order_id,
                    "price": price,
                    "item": item.name,
                },
                message="买入订单创建成功"
            )
            
        except Exception as e:
            logger.error(f"买入失败: {e}")
            return ServiceResponse.err(
                message=str(e),
                code="BUY_FAILED"
            )
    
    async def execute_arbitrage(
        self,
        item_id: int,
        buy_platform: str = "buff",
        sell_platform: str = "steam"
    ) -> Dict[str, Any]:
        """执行搬砖"""
        if buy_platform == "buff" and not self.buff_client:
            raise Exception("未设置 BUFF 客户端")
        
        # 1. 买入 (使用配置的最大交易价格 P1-问题4)
        buy_result = await self.execute_buy(item_id, max_price=settings.MAX_SINGLE_TRADE)
        
        if not buy_result.success:
            return buy_result
        
        # 2. 等待到账 (实际需要轮询检查)
        await asyncio.sleep(10)
        
        # 3. 卖出 (上架到 Steam 市场)
        # 实际实现需要调用 Steam API
        
        return ServiceResponse.ok(
            data={
                "buy_order_id": buy_result.data.get("order_id") if buy_result.data else None,
            },
            message="搬砖流程已启动"
        )
    
    async def auto_buy_by_monitor(
        self,
        item_id: int,
        max_price: float
    ) -> Dict[str, Any]:
        """根据监控规则自动买入"""
        return await self.execute_buy(item_id, max_price)
