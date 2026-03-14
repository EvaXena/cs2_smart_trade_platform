# -*- coding: utf-8 -*-
"""
交易服务
"""
import asyncio
import logging
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.item import Item
from app.models.order import Order
from app.models.inventory import Inventory
from app.services.buff_service import get_buff_client
from app.services.steam_service import SteamAPI, get_steam_api
from app.services.steam_market import get_steam_market_service
from app.core.config import settings
from app.core.response import ServiceResponse, success_response, error_response
from app.core.task_registry import get_task_registry
# 导入 RiskManager
from app.core.risk_manager import RiskManager, get_risk_manager
# 导入 validators 中的验证函数
from app.utils.validators import (
    validate_price,
    validate_quantity,
    validate_item_id,
    validate_user_id,
    validate_min_profit,
    validate_limit,
)
# 导入 Webhook 服务
from app.services.webhook_service import webhook_manager, WebhookEventType

logger = logging.getLogger(__name__)

# 默认超时配置
DEFAULT_TIMEOUT = 30  # 秒


class TradingEngine:
    """交易引擎"""
    
    # 类级别的全局锁字典，用于高频交易场景下的竞态条件保护
    _global_item_locks: Dict[int, asyncio.Lock] = {}
    _global_locks_lock: asyncio.Lock = None  # 锁的锁，用于创建新锁
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.buff_client = None
        self.steam_api = get_steam_api()
        self.steam_market = get_steam_market_service()
        self._task_registry = get_task_registry()
        # 初始化风险管理器
        self.risk_manager = RiskManager(db)
        # 并发控制 - 细粒度锁+信号量
        # 使用字典存储每个item_id的锁，实现不同交易对并行
        self._item_locks: Dict[int, asyncio.Lock] = {}
        self._item_locks_lock: asyncio.Lock = asyncio.Lock()  # 保护 _item_locks 字典
        # 使用信号量控制最大并发数
        self._max_concurrent = 5  # 最多5个并发任务
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        # 导入通知服务（使用全局单例）
        from app.services.notification_service import notification_service as global_notification_service, NotificationType, NotificationPriority
        self.notification_service = global_notification_service
        self.notification_type = NotificationType
        self.notification_priority = NotificationPriority
    
    @classmethod
    async def _get_global_item_lock(cls, item_id: int) -> asyncio.Lock:
        """获取全局的 item 锁（类级别，用于高频交易场景）"""
        if cls._global_locks_lock is None:
            cls._global_locks_lock = asyncio.Lock()
        
        async with cls._global_locks_lock:
            if item_id not in cls._global_item_locks:
                cls._global_item_locks[item_id] = asyncio.Lock()
            return cls._global_item_locks[item_id]
    
    async def _get_item_lock(self, item_id: int) -> asyncio.Lock:
        """获取指定 item_id 的锁"""
        async with self._item_locks_lock:
            if item_id not in self._item_locks:
                self._item_locks[item_id] = asyncio.Lock()
            return self._item_locks[item_id]
    
    async def _send_webhook_notification(
        self,
        event_type: WebhookEventType,
        order_id: str,
        user_id: int,
        data: Dict[str, Any]
    ) -> None:
        """发送 Webhook 通知（异步，不阻塞主流程）"""
        try:
            # 异步发送，不等待结果
            asyncio.create_task(
                webhook_manager.send_webhook(
                    event_type=event_type,
                    data=data,
                    user_id=user_id,
                    order_id=order_id
                )
            )
        except Exception as e:
            # Webhook 失败不应影响主流程
            logger.warning(f"Failed to send webhook notification: {e}")
    
    def set_buff_client(self, cookie: str):
        """设置 BUFF 客户端"""
        self.buff_client = get_buff_client(cookie)
    
    async def _rollback_buy_state(
        self,
        buy_order_id: str,
        user_id: int,
        item_id: int,
        quantity: int,
        error_message: str
    ):
        """回滚买入状态 - 事务性回滚机制
        
        当卖出失败时，执行完整的回滚：
        1. 更新订单状态为 'rollback'
        2. 回滚风险管理器的持仓
        3. 记录回滚日志
        """
        try:
            # 1. 查找并更新订单状态
            result = await self.db.execute(
                select(Order).where(Order.order_id == buy_order_id)
            )
            order = result.scalar_one_or_none()
            
            if order:
                order.status = "rollback"
                order.updated_at = datetime.utcnow()
                await self.db.commit()
                logger.warning(f"已回滚订单状态: order_id={buy_order_id}, 原状态={order.status}")
            
            # 2. 回滚风险管理器的持仓（卖出失败相当于买入未成交）
            # 通过传入负数量的买入来抵消之前的持仓
            await self.risk_manager.update_position(
                user_id=user_id,
                item_id=item_id,
                quantity=-quantity,  # 负数量表示回滚
                price=0,  # 回滚时不涉及价格
                side="buy"
            )
            
            logger.info(
                f"买入状态已回滚: buy_order_id={buy_order_id}, "
                f"item_id={item_id}, quantity={quantity}, user_id={user_id}, "
                f"reason={error_message}"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"回滚买入状态失败: buy_order_id={buy_order_id}, error={e}")
            # 回滚失败不应抛出异常，以免掩盖原始错误
            return False
        """卖出失败时发送告警通知"""
        try:
            # 查询物品信息
            result = await self.db.execute(
                select(Item).where(Item.id == item_id)
            )
            item = result.scalar_one_or_none()
            item_name = item.name if item else f"ID: {item_id}"
            
            # 发送告警通知
            await self.notification_service.send_notification(
                user_id=user_id,
                notification_type=self.notification_type.TRADE,
                title="卖出订单失败告警",
                content=f"买入订单 {buy_order_id} 的物品 {item_name} 卖出失败: {error_message}",
                priority=self.notification_priority.HIGH,
                data={
                    "buy_order_id": buy_order_id,
                    "item_id": item_id,
                    "item_name": item_name,
                    "error": error_message,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            logger.warning(f"已发送卖出失败告警: buy_order_id={buy_order_id}, item={item_name}, error={error_message}")
        except Exception as e:
            logger.error(f"发送卖出失败告警失败: {e}")
    
    async def get_arbitrage_opportunities(
        self,
        min_profit: float = settings.MIN_PROFIT,
        limit: int = 20
    ) -> ServiceResponse:
        """获取搬砖机会"""
        # 输入验证（使用 validators.py 中的函数）
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
            # 计算搬砖利润 (Steam 出售需扣除手续费)
            steam_sell_price = item.steam_lowest_price * settings.STEAM_FEE_RATE
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
        validate_item_id(item_id)
        validate_price(max_price)
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
        
        # ===== 风险检查 (P1-1: 独立RiskManager模块) =====
        # 获取实际价格进行风险检查
        price_for_check = max_price  # 使用用户设定的最高价格进行预检查
        passed, risk_events = await self.risk_manager.check_trade_risk(
            user_id=user_id,
            item_id=item_id,
            price=price_for_check,
            quantity=quantity,
            side="buy"
        )
        if not passed:
            # 记录风险事件并拒绝交易
            for event in risk_events:
                logger.warning(f"风险检查拒绝交易: user_id={user_id}, event={event.event_type.value}, details={event.details}")
            return ServiceResponse.err(
                message=f"风险检查未通过: {risk_events[0].details if risk_events else '未知风险'}",
                code="RISK_CHECK_FAILED"
            )
        # ===== 风险检查结束 =====
        
        # 获取当前价格 (带超时控制)
        try:
            current_price = await asyncio.wait_for(
                self.buff_client.get_price_overview(item.market_hash_name),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            # 修复：使用统一的错误响应格式
            logger.warning(f"获取价格超时: item_id={item_id}")
            return ServiceResponse.err(
                message=f"获取价格超时 (>{timeout}秒)",
                code="TIMEOUT"
            )
        except Exception as e:
            logger.error(f"获取价格失败: {e}")
            return ServiceResponse.err(
                message=f"获取价格失败: {str(e)}",
                code="GET_PRICE_FAILED"
            )
        
        if not current_price:
            return ServiceResponse.err(
                message="无法获取价格",
                code="PRICE_NOT_FOUND"
            )
        
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
            
            # ===== 更新持仓 (P1-1: RiskManager集成) =====
            await self.risk_manager.update_position(
                user_id=user_id,
                item_id=item_id,
                quantity=quantity,
                price=price,
                side="buy"
            )
            # ===== 持仓更新结束 =====
            
            # 提升成功日志级别为 info
            logger.info(
                f"买入订单创建成功: order_id={order.order_id}, "
                f"item={item.name}, price={price}, quantity={quantity}, user_id={user_id}"
            )
            
            # ===== Webhook 通知：订单创建 =====
            await self._send_webhook_notification(
                event_type=WebhookEventType.ORDER_CREATED,
                order_id=order.order_id,
                user_id=user_id,
                data={
                    "side": "buy",
                    "item_id": item_id,
                    "item_name": item.name,
                    "price": float(price),
                    "quantity": quantity,
                    "status": "pending"
                }
            )
            # ===== Webhook 通知结束 =====
            
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
            
            # ===== Webhook 通知：订单失败 =====
            if user_id:
                await self._send_webhook_notification(
                    event_type=WebhookEventType.ORDER_FAILED,
                    order_id="",
                    user_id=user_id,
                    data={
                        "side": "buy",
                        "item_id": item_id,
                        "error": str(e)
                    }
                )
            # ===== Webhook 通知结束 =====
            
            return ServiceResponse.err(
                message=str(e),
                code="BUY_FAILED"
            )
    
    async def execute_arbitrage(
        self,
        item_id: int,
        buy_platform: str = "buff",
        sell_platform: str = "steam",
        sell_price: float = None,
        quantity: int = 1,
        user_id: int = None,
        timeout: int = DEFAULT_TIMEOUT
    ) -> Dict[str, Any]:
        """执行搬砖（完整流程：买入 -> 等待到账 -> 卖出上架）"""
        if buy_platform == "buff" and not self.buff_client:
            raise Exception("未设置 BUFF 客户端")
        
        if user_id is None:
            raise ValueError("execute_arbitrage 必须提供 user_id 参数")
        
        # 使用细粒度锁+信号量控制并发执行
        # 获取或创建该item_id的锁
        if item_id not in self._item_locks:
            self._item_locks[item_id] = asyncio.Lock()
        item_lock = self._item_locks[item_id]
        
        # 使用信号量控制总体并发数，同时使用item锁保证同一物品串行
        async with self._semaphore:
            async with item_lock:
                # 注册任务到 TaskRegistry 以便追踪
                task_name = f"arbitrage_{item_id}_{datetime.utcnow().timestamp()}"
                
                async def do_arbitrage():
                    return await self._execute_arbitrage_internal(
                        item_id, buy_platform, sell_platform, 
                        sell_price, quantity, user_id, timeout
                    )
                
                # 使用 TaskRegistry 注册任务
                # 修改：TaskRegistry.register 需要传入函数和参数，而不是已执行的结果
                task_id = await self._task_registry.register(
                    task_name,
                    do_arbitrage  # 传入协程函数
                )
            
            # 异步执行任务
            await self._task_registry.run(task_id, wait=False)
            
            return ServiceResponse.ok(
                data={"task_id": task_id, "task_name": task_name},
                message="搬砖任务已启动"
            )
    
    async def _execute_arbitrage_internal(
        self,
        item_id: int,
        buy_platform: str,
        sell_platform: str,
        sell_price: float,
        quantity: int,
        user_id: int,
        timeout: int
    ) -> Dict[str, Any]:
        """执行搬砖的内部实现"""
        
        # 获取饰品信息用于后续卖出
        item_result = await self.db.execute(
            select(Item).where(Item.id == item_id)
        )
        item = item_result.scalar_one_or_none()
        
        if not item:
            return ServiceResponse.err(message="饰品不存在", code="ITEM_NOT_FOUND")
        
        # 1. 买入 (使用配置的最大交易价格)
        buy_result = await self.execute_buy(
            item_id, 
            max_price=settings.MAX_SINGLE_TRADE,
            quantity=quantity,
            user_id=user_id,
            timeout=timeout
        )
        
        if not buy_result.success:
            return buy_result
        
        buy_order_id = buy_result.data.get("order_id") if buy_result.data else None
        
        # 使用轮询方式等待到账
        logger.info(f"买入完成，开始等待到账: order_id={buy_order_id}")
        order_completed, buy_order = await self._wait_for_order_settlement(buy_order_id)
        
        if not order_completed:
            logger.warning(f"买入订单未完成到账: order_id={buy_order_id}, status={buy_order.status if buy_order else 'unknown'}")
            return ServiceResponse.ok(
                data={
                    "buy_order_id": buy_order_id,
                    "status": "buy_completed_waiting_settle",
                },
                message="买入完成，等待到账确认"
            )
        
        # 3. 检查到账状态并创建卖出订单
        sell_result = None
        if sell_platform == "steam":
            # 计算卖出价格（如果未指定，则使用 Steam 最低价）
            if sell_price is None:
                sell_price = item.steam_lowest_price
            
            # ===== 卖出前风险检查 (P1-1: RiskManager集成) =====
            passed, risk_events = await self.risk_manager.check_trade_risk(
                user_id=user_id,
                item_id=item_id,
                price=sell_price,
                quantity=quantity,
                side="sell"
            )
            if not passed:
                logger.warning(f"卖出风险检查未通过: user_id={user_id}, item_id={item_id}")
                for event in risk_events:
                    if event.event_type.value == "stop_loss_triggered":
                        logger.info(f"触发止损，建议卖出: {event.details}")
                    elif event.event_type.value == "take_profit_triggered":
                        logger.info(f"触发止盈，建议卖出: {event.details}")
            # ===== 风险检查结束 =====
            
            # 如果设置了自动卖出
            if settings.AUTO_CONFIRM:
                try:
                    # 修复状态检查逻辑 - 使用轮询后的订单状态
                    # 注意：轮询已确认订单状态为completed，这里直接创建卖出订单
                    
                    # 创建卖出订单记录
                    sell_order = Order(
                        order_id=f"SELL-{datetime.utcnow().timestamp()}",
                        user_id=user_id,
                        item_id=item_id,
                        side="sell",
                        price=sell_price,
                        quantity=quantity,
                        source="steam",
                        status="pending",
                    )
                    self.db.add(sell_order)
                    await self.db.commit()
                    
                    # ===== 更新持仓 (P1-1: RiskManager集成) =====
                    await self.risk_manager.update_position(
                        user_id=user_id,
                        item_id=item_id,
                        quantity=quantity,
                        price=sell_price,
                        side="sell"
                    )
                    # ===== 持仓更新结束 =====
                    
                    # 尝试上架到 Steam 市场（如果配置了 Steam 认证信息）
                    if self.steam_market.steam_login or self.steam_market.webcookie:
                        # 尝试获取库存以获取 asset_id
                        asset_id = None
                        try:
                            # 从 BUFF 获取已购物品信息
                            # 这里应该从 BUFF 订单确认后获取 asset_id
                            # 暂时通过 Steam API 获取库存
                            inventory_result = await self._get_inventory_for_sale(
                                market_hash_name=item.market_hash_name,
                                app_id=730
                            )
                            if inventory_result and len(inventory_result) > 0:
                                asset_id = inventory_result[0].get("asset_id")
                        except Exception as e:
                            logger.warning(f"获取库存失败: {e}")
                        
                        # 如果获取到 asset_id，尝试实际上架
                        if asset_id:
                            try:
                                listing_result = await self.steam_market.create_listing(
                                    asset_id=asset_id,
                                    app_id=730,
                                    price=sell_price,
                                    market_hash_name=item.market_hash_name,
                                    quantity=quantity
                                )
                                if listing_result.get("success"):
                                    sell_order.status = "listed"
                                    await self.db.commit()
                                    logger.info(
                                        f"卖出订单创建并实际上架成功: order_id={sell_order.order_id}, "
                                        f"listing_id={listing_result.get('listing_id')}"
                                    )
                                else:
                                    logger.warning(f"实际上架失败: {listing_result.get('error', '未知错误')}")
                            except Exception as e:
                                logger.warning(f"调用上架API异常: {e}")
                        else:
                            logger.info(
                                f"卖出订单创建成功（待上架）: order_id={sell_order.order_id}, "
                                f"item={item.name}, price={sell_price}, user_id={user_id}"
                            )
                        
                        sell_result = ServiceResponse.ok(
                            data={
                                "buy_order_id": buy_order_id,
                                "sell_order_id": sell_order.order_id,
                                "sell_price": sell_price,
                                "item": item.name,
                            },
                            message="搬砖流程完成，卖出订单已创建"
                        )
                    else:
                        # 未配置 Steam 认证，仅创建本地记录
                        logger.warning("未配置 Steam 认证信息，仅创建本地卖出记录")
                        sell_result = ServiceResponse.ok(
                            data={
                                "buy_order_id": buy_order_id,
                                "sell_order_id": sell_order.order_id,
                                "sell_price": sell_price,
                                "item": item.name,
                                "steam_listing_pending": True,
                            },
                            message="买入成功，待上架 Steam"
                        )
                        
                except Exception as e:
                    logger.error(f"卖出流程异常: {e}")
                    # 卖出失败时发送告警通知
                    await self._notify_sell_failure(user_id, item_id, buy_order_id, str(e))
                    
                    # ===== P1-B1: 执行完整的事务回滚 =====
                    # 卖出失败时回滚买入状态
                    rollback_success = await self._rollback_buy_state(
                        buy_order_id=buy_order_id,
                        user_id=user_id,
                        item_id=item_id,
                        quantity=quantity,
                        error_message=str(e)
                    )
                    
                    if rollback_success:
                        logger.info(f"卖出失败，已执行回滚: buy_order_id={buy_order_id}")
                        sell_result = ServiceResponse.ok(
                            data={
                                "buy_order_id": buy_order_id,
                                "sell_error": str(e),
                                "rollback": "success",
                            },
                            message="卖出失败，已回滚买入状态"
                        )
                    else:
                        logger.error(f"卖出失败，回滚执行失败: buy_order_id={buy_order_id}")
                        sell_result = ServiceResponse.ok(
                            data={
                                "buy_order_id": buy_order_id,
                                "sell_error": str(e),
                                "rollback": "failed",
                            },
                            message="卖出失败，回滚执行失败，请人工检查"
                        )
                    # ===== 回滚机制结束 =====
        
        return sell_result or ServiceResponse.ok(
            data={
                "buy_order_id": buy_order_id,
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
    
    async def _get_inventory_for_sale(
        self,
        market_hash_name: str,
        app_id: int = 730
    ) -> List[Dict[str, Any]]:
        """
        获取可用于出售的库存物品
        
        Args:
            market_hash_name: 物品的市场哈希名称
            app_id: Steam App ID
            
        Returns:
            可用于出售的物品列表
        """
        # 尝试获取 Steam 库存
        try:
            # 使用 Steam API 获取库存
            inventory = await self.steam_api.get_inventory(app_id=app_id)
            if inventory.get("success"):
                assets = inventory.get("assets", [])
                # 过滤出目标物品
                matching_items = [
                    {
                        "asset_id": asset.get("id"),
                        "market_hash_name": asset.get("market_hash_name", ""),
                        "app_id": asset.get("appid"),
                    }
                    for asset in assets
                    if market_hash_name in asset.get("market_hash_name", "")
                ]
                return matching_items
        except Exception as e:
            logger.warning(f"获取 Steam 库存失败: {e}")
        
        return []
    
    async def _wait_for_order_settlement(
        self,
        order_id: str,
        max_wait_time: int = None,
        check_interval: int = 5
    ) -> Tuple[bool, Optional[Order]]:
        """
        等待订单到账（轮询方式）
        
        Args:
            order_id: 订单ID
            max_wait_time: 最大等待时间（秒），默认使用配置
            check_interval: 检查间隔（秒）
        
        Returns:
            (是否到账, 订单对象)
        """
        max_wait_time = max_wait_time or settings.ARBITRAGE_SETTLE_WAIT
        waited_time = 0
        
        while waited_time < max_wait_time:
            await asyncio.sleep(check_interval)
            waited_time += check_interval
            
            # 查询订单状态
            result = await self.db.execute(
                select(Order).where(Order.order_id == order_id)
            )
            order = result.scalar_one_or_none()
            
            if order:
                if order.status == "completed":
                    return True, order
                elif order.status == "failed":
                    return False, order
                # pending状态继续等待
        
        # 超时，返回当前状态
        result = await self.db.execute(
            select(Order).where(Order.order_id == order_id)
        )
        order = result.scalar_one_or_none()
        return order.status == "completed" if order else False, order
