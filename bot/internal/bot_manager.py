# -*- coding: utf-8 -*-
"""
机器人管理器

管理多个交易机器人的生命周期
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List, Type
from datetime import datetime
from enum import Enum

from .trading_bot_base import TradingBotBase, BotStatus
from .arbitrage_bot import ArbitrageBot
from .price_monitor_bot import PriceMonitorBot

logger = logging.getLogger(__name__)


class BotType(str, Enum):
    """机器人类型"""
    ARBITRAGE = "arbitrage"
    PRICE_MONITOR = "price_monitor"


class BotManager:
    """
    机器人管理器
    
    功能：
    - 创建/删除机器人
    - 启动/停止/暂停/恢复
    - 状态查询
    - 统一日志
    """
    
    # 机器人类型映射
    BOT_CLASSES = {
        BotType.ARBITRAGE: ArbitrageBot,
        BotType.PRICE_MONITOR: PriceMonitorBot,
    }
    
    def __init__(self):
        self._bots: Dict[int, TradingBotBase] = {}
        self._lock = asyncio.Lock()
        
        # 统计
        self._total_bots_created = 0
    
    async def create_bot(
        self,
        bot_type: str,
        name: str,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        创建机器人
        
        Args:
            bot_type: 机器人类型
            name: 机器人名称
            config: 配置
            
        Returns:
            创建结果
        """
        async with self._lock:
            try:
                # 获取机器人类型
                if isinstance(bot_type, str):
                    bot_type = BotType(bot_type)
                
                # 获取机器人类
                bot_class = self.BOT_CLASSES.get(bot_type)
                if not bot_class:
                    return {
                        "success": False,
                        "message": f"未知的机器人类型: {bot_type}"
                    }
                
                # 创建机器人
                bot_id = self._total_bots_created + 1
                bot = bot_class(
                    bot_id=bot_id,
                    name=name,
                    config=config
                )
                
                # 注册机器人
                self._bots[bot_id] = bot
                self._total_bots_created += 1
                
                logger.info(f"创建机器人成功: {name} (ID: {bot_id}, 类型: {bot_type.value})")
                
                return {
                    "success": True,
                    "bot_id": bot_id,
                    "name": name,
                    "type": bot_type.value,
                    "status": bot.status.value
                }
                
            except Exception as e:
                logger.error(f"创建机器人失败: {e}")
                return {
                    "success": False,
                    "message": str(e)
                }
    
    async def delete_bot(self, bot_id: int) -> Dict[str, Any]:
        """
        删除机器人
        
        Args:
            bot_id: 机器人ID
            
        Returns:
            删除结果
        """
        async with self._lock:
            if bot_id not in self._bots:
                return {
                    "success": False,
                    "message": "机器人不存在"
                }
            
            bot = self._bots[bot_id]
            
            # 如果运行中，先停止
            if bot.is_running:
                await bot.stop()
            
            # 删除
            del self._bots[bot_id]
            
            logger.info(f"删除机器人: {bot_id}")
            
            return {
                "success": True,
                "message": "机器人已删除"
            }
    
    async def start_bot(self, bot_id: int) -> Dict[str, Any]:
        """
        启动机器人
        
        Args:
            bot_id: 机器人ID
            
        Returns:
            启动结果
        """
        if bot_id not in self._bots:
            return {
                "success": False,
                "message": "机器人不存在"
            }
        
        bot = self._bots[bot_id]
        
        if bot.is_running:
            return {
                "success": False,
                "message": "机器人已在运行"
            }
        
        result = await bot.start()
        
        logger.info(f"启动机器人: {bot_id}, 结果: {result.get('success')}")
        
        return result
    
    async def stop_bot(self, bot_id: int) -> Dict[str, Any]:
        """
        停止机器人
        
        Args:
            bot_id: 机器人ID
            
        Returns:
            停止结果
        """
        if bot_id not in self._bots:
            return {
                "success": False,
                "message": "机器人不存在"
            }
        
        bot = self._bots[bot_id]
        
        if not bot.is_running:
            return {
                "success": False,
                "message": "机器人未在运行"
            }
        
        result = await bot.stop()
        
        logger.info(f"停止机器人: {bot_id}, 结果: {result.get('success')}")
        
        return result
    
    async def pause_bot(self, bot_id: int) -> Dict[str, Any]:
        """
        暂停机器人
        
        Args:
            bot_id: 机器人ID
            
        Returns:
            暂停结果
        """
        if bot_id not in self._bots:
            return {
                "success": False,
                "message": "机器人不存在"
            }
        
        bot = self._bots[bot_id]
        result = await bot.pause()
        
        return result
    
    async def resume_bot(self, bot_id: int) -> Dict[str, Any]:
        """
        恢复机器人
        
        Args:
            bot_id: 机器人ID
            
        Returns:
            恢复结果
        """
        if bot_id not in self._bots:
            return {
                "success": False,
                "message": "机器人不存在"
            }
        
        bot = self._bots[bot_id]
        result = await bot.resume()
        
        return result
    
    async def get_bot_status(self, bot_id: int) -> Optional[Dict[str, Any]]:
        """
        获取机器人状态
        
        Args:
            bot_id: 机器人ID
            
        Returns:
            状态信息
        """
        if bot_id not in self._bots:
            return None
        
        bot = self._bots[bot_id]
        return await bot.get_status()
    
    async def get_all_bots_status(self) -> List[Dict[str, Any]]:
        """
        获取所有机器人状态
        
        Returns:
            状态列表
        """
        status_list = []
        
        for bot_id, bot in self._bots.items():
            status = await bot.get_status()
            status_list.append(status)
        
        return status_list
    
    async def execute_trade(
        self,
        bot_id: int,
        trade_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行交易
        
        Args:
            bot_id: 机器人ID
            trade_data: 交易数据
            
        Returns:
            交易结果
        """
        if bot_id not in self._bots:
            return {
                "success": False,
                "message": "机器人不存在"
            }
        
        bot = self._bots[bot_id]
        result = await bot.execute_trade(trade_data)
        
        return result
    
    async def stop_all(self) -> Dict[str, Any]:
        """
        停止所有机器人
        
        Returns:
            停止结果
        """
        stopped = 0
        failed = 0
        
        for bot_id, bot in list(self._bots.items()):
            if bot.is_running:
                result = await bot.stop()
                if result.get("success"):
                    stopped += 1
                else:
                    failed += 1
        
        return {
            "success": failed == 0,
            "stopped": stopped,
            "failed": failed
        }
    
    @property
    def bot_count(self) -> int:
        """获取机器人数量"""
        return len(self._bots)
    
    @property
    def running_bot_count(self) -> int:
        """获取运行中的机器人数量"""
        return sum(1 for bot in self._bots.values() if bot.is_running)


# 全局机器人管理器实例
_bot_manager: Optional[BotManager] = None


def get_bot_manager() -> BotManager:
    """
    获取全局机器人管理器
    
    Returns:
        机器人管理器实例
    """
    global _bot_manager
    if _bot_manager is None:
        _bot_manager = BotManager()
    return _bot_manager
