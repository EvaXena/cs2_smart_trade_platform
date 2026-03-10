# -*- coding: utf-8 -*-
"""
交易机器人基类
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class BotStatus(str, Enum):
    """机器人状态"""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


class BotPlatform(str, Enum):
    """交易平台"""
    BUFF = "buff"
    STEAM = "steam"
    BUFF_TO_STEAM = "buff_to_steam"  # 搬砖


class TradingBotBase(ABC):
    """
    交易机器人基类
    
    提供通用的机器人框架：
    - 生命周期管理（启动/停止/暂停）
    - 状态管理
    - 日志记录
    - 错误处理
    """
    
    def __init__(
        self,
        bot_id: int,
        name: str,
        platform: BotPlatform,
        config: Optional[Dict[str, Any]] = None
    ):
        self.bot_id = bot_id
        self.name = name
        self.platform = platform
        self.config = config or {}
        
        # 状态
        self._status = BotStatus.STOPPED
        self._running = False
        self._paused = False
        
        # 任务
        self._task: Optional[asyncio.Task] = None
        
        # 统计
        self.stats = {
            "total_trades": 0,
            "successful_trades": 0,
            "failed_trades": 0,
            "total_profit": 0.0,
            "start_time": None,
            "last_trade_time": None,
        }
        
        # 日志
        self.logger = logging.getLogger(f"{__name__}.{name}")
    
    @property
    def status(self) -> BotStatus:
        """获取机器人状态"""
        return self._status
    
    @property
    def is_running(self) -> bool:
        """检查是否运行中"""
        return self._running
    
    @property
    def is_paused(self) -> bool:
        """检查是否暂停"""
        return self._paused
    
    async def start(self) -> Dict[str, Any]:
        """
        启动机器人
        
        Returns:
            启动结果
        """
        if self._running:
            return {
                "success": False,
                "message": "机器人已在运行中"
            }
        
        try:
            # 初始化
            await self._initialize()
            
            # 启动主循环
            self._running = True
            self._status = BotStatus.RUNNING
            self.stats["start_time"] = datetime.utcnow()
            
            self._task = asyncio.create_task(self._run_loop())
            
            self.logger.info(f"机器人 {self.name} 已启动")
            
            return {
                "success": True,
                "message": "机器人启动成功"
            }
            
        except Exception as e:
            self.logger.error(f"启动机器人失败: {e}")
            self._status = BotStatus.ERROR
            return {
                "success": False,
                "message": f"启动失败: {str(e)}"
            }
    
    async def stop(self) -> Dict[str, Any]:
        """
        停止机器人
        
        Returns:
            停止结果
        """
        if not self._running:
            return {
                "success": False,
                "message": "机器人未在运行"
            }
        
        try:
            self._running = False
            self._paused = False
            
            # 取消任务
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            
            # 清理资源
            await self._cleanup()
            
            self._status = BotStatus.STOPPED
            self.logger.info(f"机器人 {self.name} 已停止")
            
            return {
                "success": True,
                "message": "机器人已停止"
            }
            
        except Exception as e:
            self.logger.error(f"停止机器人失败: {e}")
            return {
                "success": False,
                "message": f"停止失败: {str(e)}"
            }
    
    async def pause(self) -> Dict[str, Any]:
        """
        暂停机器人
        
        Returns:
            暂停结果
        """
        if not self._running:
            return {
                "success": False,
                "message": "机器人未在运行"
            }
        
        if self._paused:
            return {
                "success": False,
                "message": "机器人已暂停"
            }
        
        self._paused = True
        self._status = BotStatus.PAUSED
        self.logger.info(f"机器人 {self.name} 已暂停")
        
        return {
            "success": True,
            "message": "机器人已暂停"
        }
    
    async def resume(self) -> Dict[str, Any]:
        """
        恢复机器人
        
        Returns:
            恢复结果
        """
        if not self._running:
            return {
                "success": False,
                "message": "机器人未在运行"
            }
        
        if not self._paused:
            return {
                "success": False,
                "message": "机器人未在暂停状态"
            }
        
        self._paused = False
        self._status = BotStatus.RUNNING
        self.logger.info(f"机器人 {self.name} 已恢复")
        
        return {
            "success": True,
            "message": "机器人已恢复"
        }
    
    async def get_status(self) -> Dict[str, Any]:
        """
        获取机器人状态
        
        Returns:
            状态信息
        """
        return {
            "bot_id": self.bot_id,
            "name": self.name,
            "platform": self.platform.value,
            "status": self._status.value,
            "is_running": self._running,
            "is_paused": self._paused,
            "stats": self.stats.copy(),
            "config": self._get_safe_config(),
        }
    
    async def execute_trade(self, trade_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行单笔交易
        
        Args:
            trade_data: 交易数据
            
        Returns:
            交易结果
        """
        if not self._running or self._paused:
            return {
                "success": False,
                "message": "机器人未在运行"
            }
        
        try:
            result = await self._execute_trade_impl(trade_data)
            
            # 更新统计
            self.stats["total_trades"] += 1
            if result.get("success"):
                self.stats["successful_trades"] += 1
                self.stats["total_profit"] += result.get("profit", 0)
                self.stats["last_trade_time"] = datetime.utcnow()
            else:
                self.stats["failed_trades"] += 1
            
            return result
            
        except Exception as e:
            self.logger.error(f"交易执行失败: {e}")
            self.stats["failed_trades"] += 1
            return {
                "success": False,
                "message": str(e)
            }
    
    # ============ 子类需要实现的方法 ============
    
    @abstractmethod
    async def _initialize(self) -> None:
        """
        初始化机器人
        """
        pass
    
    @abstractmethod
    async def _run_loop(self) -> None:
        """
        主循环（子类实现具体逻辑）
        """
        pass
    
    @abstractmethod
    async def _execute_trade_impl(self, trade_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行单笔交易的具体实现
        
        Args:
            trade_data: 交易数据
            
        Returns:
            交易结果
        """
        pass
    
    @abstractmethod
    async def _cleanup(self) -> None:
        """
        清理资源
        """
        pass
    
    # ============ 辅助方法 ============
    
    def _get_safe_config(self) -> Dict[str, Any]:
        """
        获取安全的配置（隐藏敏感信息）
        """
        safe_config = self.config.copy()
        sensitive_keys = ["password", "token", "cookie", "key", "secret"]
        
        for key in safe_config:
            for sensitive in sensitive_keys:
                if sensitive.lower() in key.lower():
                    safe_config[key] = "***"
                    break
        
        return safe_config
    
    async def _sleep_with_pause(self, seconds: float) -> None:
        """
        支持暂停的睡眠
        
        Args:
            seconds: 睡眠秒数
        """
        interval = 1.0  # 每秒检查一次
        remaining = seconds
        
        while remaining > 0 and self._running:
            if self._paused:
                await asyncio.sleep(interval)
                continue
            
            await asyncio.sleep(min(interval, remaining))
            remaining -= interval
    
    def _log_trade(self, action: str, details: Dict[str, Any]) -> None:
        """
        记录交易日志
        
        Args:
            action: 操作类型
            details: 详情
        """
        self.logger.info(
            f"[{action}] {details.get('item_name', 'Unknown')} - "
            f"Price: {details.get('price', 'N/A')} - "
            f"Result: {details.get('result', 'N/A')}"
        )
