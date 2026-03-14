# -*- coding: utf-8 -*-
"""
Webhook 服务 - 交易完成回调通知机制

支持:
- Webhook URL 注册和管理
- 异步 HTTP 回调通知
- 重试机制
- 签名验证
- 回调日志
"""
import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class WebhookEventType(str, Enum):
    """Webhook 事件类型"""
    ORDER_CREATED = "order.created"
    ORDER_COMPLETED = "order.completed"
    ORDER_FAILED = "order.failed"
    ORDER_CANCELLED = "order.cancelled"
    ORDER_ROLLBACK = "order.rollback"
    TRADE_EXECUTED = "trade.executed"
    TRADE_FAILED = "trade.failed"
    INVENTORY_CHANGED = "inventory.changed"
    PRICE_ALERT = "price.alert"


class WebhookStatus(str, Enum):
    """Webhook 回调状态"""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    INVALID_SIGNATURE = "invalid_signature"


@dataclass
class WebhookConfig:
    """Webhook 配置"""
    url: str
    secret: str = ""  # 用于签名验证
    enabled: bool = True
    timeout: int = 10  # 超时时间（秒）
    retry_count: int = 3  # 重试次数
    retry_delay: float = 1.0  # 重试延迟（秒）


@dataclass
class WebhookPayload:
    """Webhook 载荷"""
    event_type: WebhookEventType
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)
    user_id: Optional[int] = None
    order_id: Optional[str] = None
    idempotency_key: Optional[str] = None


@dataclass
class WebhookResult:
    """Webhook 回调结果"""
    event_type: WebhookEventType
    url: str
    status: WebhookStatus
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    attempts: int = 1
    duration_ms: float = 0


class WebhookManager:
    """
    Webhook 管理器
    
    功能:
    - 管理多个 Webhook URL
    - 发送异步回调通知
    - 自动重试机制
    - 签名生成和验证
    - 回调日志记录
    """
    
    def __init__(self):
        self._webhooks: Dict[int, Dict[str, WebhookConfig]] = {}  # user_id -> {webhook_url: config}
        self._global_webhooks: List[WebhookConfig] = []  # 全局 Webhook（所有用户）
        self._callback_history: List[WebhookResult] = []  # 回调历史
        self._max_history: int = 1000  # 最大历史记录数
        self._lock = asyncio.Lock()
        
        # HTTP 客户端配置
        self._http_timeout = httpx.Timeout(10.0, connect=5.0)
        
        # 回调函数注册表（用于内部处理）
        self._callbacks: Dict[WebhookEventType, List[Callable]] = {}
    
    def register_webhook(
        self,
        user_id: int,
        url: str,
        secret: str = "",
        enabled: bool = True
    ) -> bool:
        """
        注册用户的 Webhook URL
        
        Args:
            user_id: 用户 ID
            url: Webhook URL
            secret: 签名密钥
            enabled: 是否启用
            
        Returns:
            是否注册成功
        """
        if not url:
            logger.warning(f"Invalid webhook URL: {url}")
            return False
        
        # 验证 URL 格式
        if not url.startswith(("http://", "https://")):
            logger.warning(f"Invalid webhook URL format: {url}")
            return False
        
        if user_id not in self._webhooks:
            self._webhooks[user_id] = {}
        
        self._webhooks[user_id][url] = WebhookConfig(
            url=url,
            secret=secret,
            enabled=enabled
        )
        
        logger.info(f"Registered webhook for user {user_id}: {url}")
        return True
    
    def unregister_webhook(self, user_id: int, url: str) -> bool:
        """注销用户的 Webhook URL"""
        if user_id in self._webhooks and url in self._webhooks[user_id]:
            del self._webhooks[user_id][url]
            logger.info(f"Unregistered webhook for user {user_id}: {url}")
            return True
        return False
    
    def register_global_webhook(
        self,
        url: str,
        secret: str = "",
        enabled: bool = True
    ) -> bool:
        """注册全局 Webhook（所有用户事件都会触发）"""
        if not url:
            return False
        
        # 验证 URL 格式
        if not url.startswith(("http://", "https://")):
            return False
        
        self._global_webhooks.append(WebhookConfig(
            url=url,
            secret=secret,
            enabled=enabled
        ))
        
        logger.info(f"Registered global webhook: {url}")
        return True
    
    def get_user_webhooks(self, user_id: int) -> List[WebhookConfig]:
        """获取用户的所有 Webhook 配置"""
        return list(self._webhooks.get(user_id, {}).values())
    
    def generate_signature(self, payload: str, secret: str) -> str:
        """生成 HMAC 签名"""
        if not secret:
            return ""
        return hmac.new(
            secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _build_payload(self, event_type: WebhookEventType, data: Dict[str, Any]) -> str:
        """构建 JSON 载荷"""
        payload = {
            "event": event_type.value,
            "timestamp": time.time(),
            "data": data
        }
        return json.dumps(payload, ensure_ascii=False)
    
    async def _send_webhook(
        self,
        url: str,
        payload: str,
        secret: str,
        timeout: int,
        retry_count: int,
        retry_delay: float
    ) -> WebhookResult:
        """发送 Webhook 回调"""
        # 生成签名
        signature = self.generate_signature(payload, secret)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "CS2-Trading-Platform/1.0"
        }
        if signature:
            headers["X-Webhook-Signature"] = signature
        
        start_time = time.time()
        
        for attempt in range(retry_count):
            try:
                async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                    response = await client.post(
                        url,
                        content=payload,
                        headers=headers
                    )
                    
                    duration_ms = (time.time() - start_time) * 1000
                    
                    if response.status_code < 400:
                        return WebhookResult(
                            event_type=WebhookEventType.ORDER_COMPLETED,  # 临时
                            url=url,
                            status=WebhookStatus.SUCCESS,
                            status_code=response.status_code,
                            response_body=response.text[:500],  # 截断响应
                            attempts=attempt + 1,
                            duration_ms=duration_ms
                        )
                    else:
                        logger.warning(
                            f"Webhook callback failed (attempt {attempt + 1}/{retry_count}): "
                            f"status={response.status_code}, url={url}"
                        )
                        
            except asyncio.TimeoutError:
                duration_ms = (time.time() - start_time) * 1000
                logger.warning(f"Webhook callback timeout (attempt {attempt + 1}/{retry_count}): {url}")
                
                if attempt < retry_count - 1:
                    await asyncio.sleep(retry_delay * (2 ** attempt))  # 指数退避
                    
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                logger.error(f"Webhook callback error (attempt {attempt + 1}/{retry_count}): {e}")
                
                if attempt < retry_count - 1:
                    await asyncio.sleep(retry_delay * (2 ** attempt))  # 指数退避
                else:
                    return WebhookResult(
                        event_type=WebhookEventType.ORDER_COMPLETED,  # 临时
                        url=url,
                        status=WebhookStatus.FAILED,
                        error_message=str(e),
                        attempts=attempt + 1,
                        duration_ms=duration_ms
                    )
        
        # 所有重试都失败
        duration_ms = (time.time() - start_time) * 1000
        return WebhookResult(
            event_type=WebhookEventType.ORDER_COMPLETED,  # 临时
            url=url,
            status=WebhookStatus.FAILED,
            error_message="All retries failed",
            attempts=retry_count,
            duration_ms=duration_ms
        )
    
    async def send_webhook(
        self,
        event_type: WebhookEventType,
        data: Dict[str, Any],
        user_id: Optional[int] = None,
        order_id: Optional[str] = None,
        idempotency_key: Optional[str] = None
    ) -> List[WebhookResult]:
        """
        发送 Webhook 回调
        
        Args:
            event_type: 事件类型
            data: 事件数据
            user_id: 用户 ID（可选，用于用户级 Webhook）
            order_id: 订单 ID
            idempotency_key: 幂等性密钥
            
        Returns:
            回调结果列表
        """
        results = []
        
        # 构建载荷
        payload_data = {
            **data,
            "order_id": order_id,
            "user_id": user_id
        }
        payload = self._build_payload(event_type, payload_data)
        
        async with self._lock:
            # 收集所有要发送的 Webhook
            webhooks_to_send = []
            
            # 添加用户级 Webhook
            if user_id and user_id in self._webhooks:
                for url, config in self._webhooks[user_id].items():
                    if config.enabled:
                        webhooks_to_send.append(config)
            
            # 添加全局 Webhook
            for config in self._global_webhooks:
                if config.enabled:
                    webhooks_to_send.append(config)
            
            # 如果没有 Webhook，直接返回
            if not webhooks_to_send:
                logger.debug(f"No webhooks configured for event {event_type.value}")
                return results
            
            # 发送 Webhook（并行）
            tasks = [
                self._send_webhook(
                    url=config.url,
                    payload=payload,
                    secret=config.secret,
                    timeout=config.timeout,
                    retry_count=config.retry_count,
                    retry_delay=config.retry_delay
                )
                for config in webhooks_to_send
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Webhook task failed: {result}")
                    results[i] = WebhookResult(
                        event_type=event_type,
                        url=webhooks_to_send[i].url,
                        status=WebhookStatus.FAILED,
                        error_message=str(result)
                    )
                else:
                    # 设置正确的事件类型
                    results[i].event_type = event_type
            
            # 记录到历史
            self._callback_history.extend(results)
            
            # 限制历史记录数量
            if len(self._callback_history) > self._max_history:
                self._callback_history = self._callback_history[-self._max_history:]
        
        # 记录日志
        success_count = sum(1 for r in results if r.status == WebhookStatus.SUCCESS)
        logger.info(
            f"Webhook sent: event={event_type.value}, "
            f"success={success_count}/{len(results)}, order_id={order_id}"
        )
        
        return results
    
    def get_callback_history(
        self,
        user_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取回调历史"""
        history = self._callback_history[-limit:]
        
        if user_id:
            # 过滤用户相关的记录（这里简化处理，实际可能需要更复杂的过滤）
            pass
        
        return [
            {
                "event_type": r.event_type.value,
                "url": r.url,
                "status": r.status.value,
                "status_code": r.status_code,
                "attempts": r.attempts,
                "duration_ms": r.duration_ms,
                "timestamp": time.time() - r.duration_ms / 1000  # 近似
            }
            for r in history
        ]
    
    # ============ 便捷方法 ============
    
    async def notify_order_completed(
        self,
        order_id: str,
        user_id: int,
        order_data: Dict[str, Any]
    ) -> List[WebhookResult]:
        """通知订单完成"""
        return await self.send_webhook(
            event_type=WebhookEventType.ORDER_COMPLETED,
            data={
                "order": order_data,
                "message": "Order completed successfully"
            },
            user_id=user_id,
            order_id=order_id,
            idempotency_key=f"order:{order_id}"
        )
    
    async def notify_trade_executed(
        self,
        trade_id: str,
        user_id: int,
        trade_data: Dict[str, Any]
    ) -> List[WebhookResult]:
        """通知交易执行"""
        return await self.send_webhook(
            event_type=WebhookEventType.TRADE_EXECUTED,
            data={
                "trade": trade_data,
                "message": "Trade executed successfully"
            },
            user_id=user_id,
            order_id=trade_id,
            idempotency_key=f"trade:{trade_id}"
        )
    
    async def notify_inventory_changed(
        self,
        user_id: int,
        item_id: int,
        item_name: str,
        quantity: int,
        change_type: str
    ) -> List[WebhookResult]:
        """通知库存变更"""
        return await self.send_webhook(
            event_type=WebhookEventType.INVENTORY_CHANGED,
            data={
                "item_id": item_id,
                "item_name": item_name,
                "quantity": quantity,
                "change_type": change_type
            },
            user_id=user_id
        )


# 全局 Webhook 管理器
webhook_manager = WebhookManager()


# ============ 便捷函数 ============

async def send_webhook(
    event_type: WebhookEventType,
    data: Dict[str, Any],
    user_id: Optional[int] = None,
    order_id: Optional[str] = None
) -> List[WebhookResult]:
    """发送 Webhook 回调的便捷函数"""
    return await webhook_manager.send_webhook(
        event_type=event_type,
        data=data,
        user_id=user_id,
        order_id=order_id
    )


async def notify_order_completed(
    order_id: str,
    user_id: int,
    order_data: Dict[str, Any]
) -> List[WebhookResult]:
    """通知订单完成的便捷函数"""
    return await webhook_manager.notify_order_completed(
        order_id=order_id,
        user_id=user_id,
        order_data=order_data
    )


async def notify_trade_executed(
    trade_id: str,
    user_id: int,
    trade_data: Dict[str, Any]
) -> List[WebhookResult]:
    """通知交易执行的便捷函数"""
    return await webhook_manager.notify_trade_executed(
        trade_id=trade_id,
        user_id=user_id,
        trade_data=trade_data
    )
