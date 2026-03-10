# -*- coding: utf-8 -*-
"""
价格监控机器人

监控特定物品价格变化，触发交易或通知
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from enum import Enum

from .trading_bot_base import TradingBotBase, BotPlatform

logger = logging.getLogger(__name__)


class MonitorCondition(str, Enum):
    """监控条件"""
    BELOW = "below"      # 低于目标价格
    ABOVE = "above"      # 高于目标价格
    DROP = "drop"        # 价格下跌（百分比）
    RISE = "rise"        #价格上涨（百分比）


class AlertLevel(str, Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class PriceMonitorBot(TradingBotBase):
    """
    价格监控机器人
    
    功能：
    - 监控指定物品价格
    - 多种触发条件（高于/低于/涨跌幅）
    - 自动触发交易
    - 发送通知
    """
    
    def __init__(
        self,
        bot_id: int,
        name: str,
        config: Optional[Dict[str, Any]] = None
    ):
        # 默认配置
        default_config = {
            "check_interval": 60,        # 检查间隔（秒）
            "items": [],                  # 监控的物品列表
            "condition": MonitorCondition.BELOW.value,  # 监控条件
            "target_price": None,        # 目标价格
            "price_change_percent": 5.0,  # 价格变化百分比
            "auto_trade": False,         # 是否自动交易
            "max_trade_price": 1000.0,  # 自动交易最高价
            "alert_enabled": True,       # 是否启用告警
            "callback_url": None,        # 告警回调URL
        }
        
        if config:
            default_config.update(config)
        
        super().__init__(
            bot_id=bot_id,
            name=name,
            platform=BotPlatform.BUFF,
            config=default_config
        )
        
        # 运行时状态
        self._buff_client = None
        
        # 监控数据
        self._monitored_items: Dict[int, Dict[str, Any]] = {}
        self._price_history: Dict[int, List[Dict[str, Any]]] = {}
        self._alerts: List[Dict[str, Any]] = []
        
        # 回调函数
        self._alert_callback: Optional[Callable] = None
    
    async def _initialize(self) -> None:
        """
        初始化价格监控机器人
        """
        self.logger.info(f"初始化价格监控机器人: {self.name}")
        
        # 初始化 BUFF 客户端
        await self._init_buff_client()
        
        # 加载监控物品
        await self._load_monitored_items()
        
        self.logger.info("价格监控机器人初始化完成")
    
    async def _init_buff_client(self) -> None:
        """初始化 BUFF 客户端"""
        try:
            from app.services.buff_service import get_buff_client
            
            cookie = self.config.get("buff_cookie")
            if cookie:
                self._buff_client = get_buff_client(cookie)
            else:
                self.logger.warning("未配置 BUFF Cookie")
                
        except Exception as e:
            self.logger.error(f"初始化 BUFF 客户端失败: {e}")
    
    async def _load_monitored_items(self) -> None:
        """加载监控物品列表"""
        items = self.config.get("items", [])
        
        for item in items:
            item_id = item.get("id") or item.get("item_id")
            if item_id:
                self._monitored_items[item_id] = {
                    "name": item.get("name", ""),
                    "target_price": item.get("target_price"),
                    "condition": item.get("condition", self.config["condition"]),
                    "last_price": None,
                    "alert_count": 0,
                }
                
                # 初始化价格历史
                if item_id not in self._price_history:
                    self._price_history[item_id] = []
        
        self.logger.info(f"已加载 {len(self._monitored_items)} 个监控物品")
    
    async def _run_loop(self) -> None:
        """
        主循环：持续监控价格
        """
        self.logger.info("价格监控机器人主循环开始")
        
        while self._running:
            try:
                if not self._paused:
                    # 检查所有物品价格
                    await self._check_all_prices()
                
                # 等待下次检查
                await self._sleep_with_pause(self.config["check_interval"])
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"主循环异常: {e}")
                await self._sleep_with_pause(60)
        
        self.logger.info("价格监控机器人主循环结束")
    
    async def _check_all_prices(self) -> None:
        """
        检查所有监控物品的价格
        """
        if not self._buff_client:
            self.logger.warning("BUFF 客户端未初始化")
            return
        
        for item_id, item_info in list(self._monitored_items.items()):
            try:
                # 获取当前价格
                current_price = await self._get_item_price(item_id)
                
                if current_price is None:
                    continue
                
                # 更新价格历史
                self._update_price_history(item_id, current_price)
                
                # 检查是否触发条件
                await self._check_trigger_condition(item_id, item_info, current_price)
                
            except Exception as e:
                self.logger.error(f"检查物品 {item_id} 价格失败: {e}")
    
    async def _get_item_price(self, item_id: int) -> Optional[float]:
        """
        获取物品价格
        
        Args:
            item_id: 物品ID
            
        Returns:
            当前价格
        """
        try:
            # 优先从数据库获取
            if self._db_session:
                from sqlalchemy import select
                from app.models.item import Item
                
                result = await self._db_session.execute(
                    select(Item).where(Item.id == item_id)
                )
                item = result.scalar_one_or_none()
                
                if item:
                    return float(item.current_price)
            
            # 备用：从API获取
            if self._buff_client:
                # 这里需要根据实际情况调用
                pass
            
            return None
            
        except Exception as e:
            self.logger.error(f"获取物品价格失败: {e}")
            return None
    
    def _update_price_history(self, item_id: int, price: float) -> None:
        """
        更新价格历史
        
        Args:
            item_id: 物品ID
            price: 当前价格
        """
        if item_id not in self._price_history:
            self._price_history[item_id] = []
        
        history = self._price_history[item_id]
        
        # 添加新价格
        history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "price": price
        })
        
        # 保留最近100条
        if len(history) > 100:
            self._price_history[item_id] = history[-100:]
        
        # 更新物品信息中的最后价格
        if item_id in self._monitored_items:
            self._monitored_items[item_id]["last_price"] = price
    
    async def _check_trigger_condition(
        self,
        item_id: int,
        item_info: Dict[str, Any],
        current_price: float
    ) -> None:
        """
        检查是否触发监控条件
        
        Args:
            item_id: 物品ID
            item_info: 物品信息
            current_price: 当前价格
        """
        condition = item_info.get("condition", self.config["condition"])
        target_price = item_info.get("target_price", self.config.get("target_price"))
        last_price = item_info.get("last_price")
        
        triggered = False
        alert_level = AlertLevel.INFO
        message = ""
        
        if condition == MonitorCondition.BELOW.value:
            # 低于目标价格
            if target_price and current_price <= target_price:
                triggered = True
                alert_level = AlertLevel.CRITICAL
                message = f"{item_info['name']} 价格低于目标: {current_price}¥ <= {target_price}¥"
        
        elif condition == MonitorCondition.ABOVE.value:
            # 高于目标价格
            if target_price and current_price >= target_price:
                triggered = True
                alert_level = AlertLevel.WARNING
                message = f"{item_info['name']} 价格高于目标: {current_price}¥ >= {target_price}¥"
        
        elif condition == MonitorCondition.DROP.value:
            # 价格下跌
            if last_price:
                change_percent = (last_price - current_price) / last_price * 100
                if change_percent >= self.config["price_change_percent"]:
                    triggered = True
                    alert_level = AlertLevel.WARNING
                    message = f"{item_info['name']} 价格下跌 {change_percent:.1f}%"
        
        elif condition == MonitorCondition.RISE.value:
            # 价格上涨
            if last_price:
                change_percent = (current_price - last_price) / last_price * 100
                if change_percent >= self.config["price_change_percent"]:
                    triggered = True
                    alert_level = AlertLevel.WARNING
                    message = f"{item_info['name']} 价格上涨 {change_percent:.1f}%"
        
        if triggered:
            # 记录告警
            await self._trigger_alert(
                item_id=item_id,
                item_name=item_info["name"],
                current_price=current_price,
                target_price=target_price,
                level=alert_level,
                message=message
            )
            
            # 更新告警计数
            item_info["alert_count"] = item_info.get("alert_count", 0) + 1
            
            # 自动交易（如果启用）
            if self.config["auto_trade"] and current_price <= self.config["max_trade_price"]:
                await self._execute_auto_trade(item_id, current_price)
    
    async def _trigger_alert(
        self,
        item_id: int,
        item_name: str,
        current_price: float,
        target_price: Optional[float],
        level: AlertLevel,
        message: str
    ) -> None:
        """
        触发告警
        
        Args:
            item_id: 物品ID
            item_name: 物品名称
            current_price: 当前价格
            target_price: 目标价格
            level: 告警级别
            message: 告警消息
        """
        alert = {
            "timestamp": datetime.utcnow().isoformat(),
            "item_id": item_id,
            "item_name": item_name,
            "current_price": current_price,
            "target_price": target_price,
            "level": level.value,
            "message": message,
        }
        
        self._alerts.append(alert)
        
        # 记录日志
        self.logger.warning(f"[{level.value.upper()}] {message}")
        
        # 发送告警回调
        if self.config["alert_enabled"] and self._alert_callback:
            try:
                await self._alert_callback(alert)
            except Exception as e:
                self.logger.error(f"告警回调失败: {e}")
    
    async def _execute_auto_trade(
        self,
        item_id: int,
        current_price: float
    ) -> None:
        """
        执行自动交易
        
        Args:
            item_id: 物品ID
            current_price: 当前价格
        """
        self.logger.info(f"触发自动交易: item_id={item_id}, price={current_price}")
        
        # 这里可以调用交易机器人执行买入
        # 简化处理：记录交易意图
        self.stats["total_trades"] += 1
    
    async def _execute_trade_impl(
        self,
        trade_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行单笔交易（实现基类接口）
        """
        item_id = trade_data.get("item_id")
        if item_id:
            price = await self._get_item_price(item_id)
            if price:
                await self._execute_auto_trade(item_id, price)
                return {"success": True, "price": price}
        
        return {"success": False, "message": "无效的交易数据"}
    
    async def _cleanup(self) -> None:
        """
        清理资源
        """
        self._buff_client = None
        self._price_history.clear()
        self.logger.info("价格监控机器人已清理")
    
    def set_alert_callback(self, callback: Callable) -> None:
        """
        设置告警回调函数
        
        Args:
            callback: 回调函数
        """
        self._alert_callback = callback
    
    async def add_monitor_item(
        self,
        item_id: int,
        name: str,
        target_price: Optional[float] = None,
        condition: str = MonitorCondition.BELOW.value
    ) -> Dict[str, Any]:
        """
        添加监控物品
        
        Args:
            item_id: 物品ID
            name: 物品名称
            target_price: 目标价格
            condition: 监控条件
            
        Returns:
            添加结果
        """
        if item_id in self._monitored_items:
            return {"success": False, "message": "物品已在监控中"}
        
        self._monitored_items[item_id] = {
            "name": name,
            "target_price": target_price,
            "condition": condition,
            "last_price": None,
            "alert_count": 0,
        }
        
        self._price_history[item_id] = []
        
        return {"success": True, "message": "物品已添加"}
    
    async def remove_monitor_item(self, item_id: int) -> Dict[str, Any]:
        """
        移除监控物品
        
        Args:
            item_id: 物品ID
            
        Returns:
            移除结果
        """
        if item_id not in self._monitored_items:
            return {"success": False, "message": "物品不在监控中"}
        
        del self._monitored_items[item_id]
        
        if item_id in self._price_history:
            del self._price_history[item_id]
        
        return {"success": True, "message": "物品已移除"}
    
    async def get_monitored_items(self) -> List[Dict[str, Any]]:
        """
        获取监控物品列表
        
        Returns:
            监控物品列表
        """
        items = []
        
        for item_id, info in self._monitored_items.items():
            items.append({
                "id": item_id,
                "name": info["name"],
                "target_price": info["target_price"],
                "condition": info["condition"],
                "last_price": info["last_price"],
                "alert_count": info.get("alert_count", 0),
            })
        
        return items
    
    async def get_alerts(
        self,
        limit: int = 50,
        level: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取告警列表
        
        Args:
            limit: 返回数量限制
            level: 过滤告警级别
            
        Returns:
            告警列表
        """
        alerts = self._alerts
        
        if level:
            alerts = [a for a in alerts if a["level"] == level]
        
        return alerts[-limit:]
    
    async def get_price_history(
        self,
        item_id: int,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        获取价格历史
        
        Args:
            item_id: 物品ID
            limit: 返回数量限制
            
        Returns:
            价格历史
        """
        history = self._price_history.get(item_id, [])
        return history[-limit:]
