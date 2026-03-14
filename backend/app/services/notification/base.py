# -*- coding: utf-8 -*-
"""
通知渠道抽象基类
定义所有通知渠道的通用接口
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class MessageLevel(str):
    """消息级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


class Message(BaseModel):
    """通知消息模型"""
    title: str = Field(..., description="消息标题")
    content: str = Field(..., description="消息内容")
    level: str = Field(default=MessageLevel.INFO, description="消息级别")
    timestamp: Optional[datetime] = Field(default_factory=datetime.utcnow, description="时间戳")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="额外元数据")
    
    model_config = ConfigDict(use_enum_values=True)


class ChannelConfig(BaseModel):
    """渠道配置基类"""
    enabled: bool = Field(default=False, description="是否启用")


class NotificationChannel(ABC):
    """通知渠道抽象基类"""
    
    def __init__(self, config: ChannelConfig):
        self.config = config
        self.enabled = config.enabled
        self._logger = logging.getLogger(self.__class__.__name__)
    
    @abstractmethod
    async def send(self, message: Message, recipients: List[str]) -> bool:
        """
        发送单条消息
        
        Args:
            message: 消息对象
            recipients: 接收者列表
        
        Returns:
            bool: 发送是否成功
        """
        pass
    
    @abstractmethod
    async def send_batch(self, messages: List[Message], recipients: List[str]) -> bool:
        """
        批量发送消息
        
        Args:
            messages: 消息列表
            recipients: 接收者列表
        
        Returns:
            bool: 发送是否成功
        """
        pass
    
    async def format_message(self, message: Message) -> str:
        """
        格式化消息为渠道特定格式
        
        Args:
            message: 消息对象
        
        Returns:
            str: 格式化后的消息
        """
        level_emoji = {
            MessageLevel.INFO: "ℹ️",
            MessageLevel.WARNING: "⚠️",
            MessageLevel.ERROR: "❌",
            MessageLevel.SUCCESS: "✅",
        }
        emoji = level_emoji.get(message.level, "ℹ️")
        return f"{emoji} *{message.title}*\n{message.content}"
    
    def is_enabled(self) -> bool:
        """检查渠道是否启用"""
        return self.enabled
    
    async def health_check(self) -> bool:
        """
        健康检查
        
        Returns:
            bool: 渠道是否健康可用
        """
        return self.enabled
