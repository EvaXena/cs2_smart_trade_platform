# -*- coding: utf-8 -*-
"""
WebSocket API 端点
提供实时双向通信支持
增强版：支持JWT认证、自动重连、心跳检测
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from typing import Optional, List
import json
import logging
from datetime import datetime
import asyncio
from jose import JWTError, jwt, ExpiredSignatureError

from app.services.notification_service import ws_manager, notification_service, NotificationType
from app.core.security import get_current_user, decode_token
from app.core.config import settings
from app.core.rate_limiter import RateLimiter
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


class TokenExpiredError(Exception):
    """Token过期异常"""
    pass


class WebSocketAuthManager:
    """WebSocket认证管理器"""
    
    @staticmethod
    def validate_token(token: str) -> Optional[dict]:
        """
        验证并解析JWT token
        返回payload或None
        """
        try:
            # 首先检查是否过期
            payload = jwt.decode(
                token, 
                settings.SECRET_KEY, 
                algorithms=[settings.ALGORITHM],
                options={"verify_exp": True}
            )
            return payload
        except ExpiredSignatureError:
            # Token已过期
            logger.warning("WebSocket token expired")
            return None
        except JWTError as e:
            logger.warning(f"WebSocket token validation failed: {e}")
            return None
    
    @staticmethod
    def get_token_expiry(token: str) -> Optional[datetime]:
        """获取token过期时间"""
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
                options={"verify_signature": False}
            )
            exp = payload.get("exp")
            if exp:
                return datetime.fromtimestamp(exp)
        except Exception:
            pass
        return None
    
    @staticmethod
    async def handle_token_refresh(websocket: WebSocket, old_token: str) -> Optional[str]:
        """
        处理token刷新
        返回新token或None
        """
        try:
            # 发送token刷新请求
            await websocket.send_json({
                "type": "token_refresh_request",
                "message": "Token即将过期，请刷新",
                "timestamp": datetime.utcnow().isoformat()
            })
            return None
        except Exception as e:
            logger.error(f"Token refresh handling failed: {e}")
            return None


class ConnectionManager:
    """WebSocket连接管理器"""
    
    # 心跳配置
    HEARTBEAT_INTERVAL = 30  # 心跳间隔(秒)
    HEARTBEAT_TIMEOUT = 10   # 心跳超时(秒)
    
    @staticmethod
    async def keep_alive(websocket: WebSocket, user_id: int):
        """保持连接活跃 - 发送ping，正确处理pong响应"""
        try:
            while True:
                await websocket.send_json({
                    "type": "ping",
                    "timestamp": datetime.utcnow().isoformat()
                })
                
                try:
                    data = await asyncio.wait_for(websocket.receive_json(), timeout=ConnectionManager.HEARTBEAT_TIMEOUT)
                    if data.get("type") == "pong":
                        # 收到有效的pong响应，重置心跳计时器
                        logger.debug(f"Received pong from user {user_id}")
                        continue
                    else:
                        # 收到非pong消息，可能需要处理其他消息
                        logger.warning(f"Unexpected message type during heartbeat: {data.get('type')}")
                except asyncio.TimeoutError:
                    logger.warning(f"Heartbeat timeout for user {user_id}, closing connection")
                    # 通知连接管理器断开连接并清理资源
                    ws_manager.disconnect(websocket)
                    # 尝试发送关闭消息
                    try:
                        await websocket.close(code=4002, reason="Heartbeat timeout")
                    except Exception:
                        pass
                    break
        except Exception as e:
            logger.error(f"Keep-alive error for user {user_id}: {e}")
            # 确保清理连接
            ws_manager.disconnect(websocket)
    
    @staticmethod
    async def handle_client_message(websocket: WebSocket, message: dict, current_user: User):
        """处理客户端消息"""
        msg_type = message.get("type")
        
        if msg_type == "ping":
            await websocket.send_json({
                "type": "pong",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        elif msg_type == "subscribe":
            topic = message.get("topic")
            logger.info(f"User {current_user.id} subscribed to {topic}")
            await websocket.send_json({
                "type": "subscribed",
                "topic": topic,
                "timestamp": datetime.utcnow().isoformat()
            })
        
        elif msg_type == "unsubscribe":
            topic = message.get("topic")
            logger.info(f"User {current_user.id} unsubscribed from {topic}")
            await websocket.send_json({
                "type": "unsubscribed",
                "topic": topic,
                "timestamp": datetime.utcnow().isoformat()
            })
        
        elif msg_type == "heartbeat":
            await websocket.send_json({
                "type": "heartbeat_ack",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        elif msg_type == "auth":
            # 处理认证消息(用于token刷新)
            new_token = message.get("token")
            if new_token:
                payload = WebSocketAuthManager.validate_token(new_token)
                if payload:
                    await websocket.send_json({
                        "type": "auth_success",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                else:
                    await websocket.send_json({
                        "type": "auth_failed",
                        "message": "Invalid token",
                        "timestamp": datetime.utcnow().isoformat()
                    })
        
        else:
            logger.warning(f"Unknown message type: {msg_type}")


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None, description="认证token（可选，用于需要认证的连接）")
):
    """
    WebSocket端点
    
    支持两种模式：
    1. 认证模式：使用token进行身份验证
    2. 匿名模式：无需认证（限制功能）
    
    增强功能：
    - JWT token解析和验证
    - token过期自动通知
    - 自动心跳检测
    """
    user_id: Optional[int] = None
    token_expiry: Optional[datetime] = None
    
    # 尝试认证
    if token:
        payload = WebSocketAuthManager.validate_token(token)
        if payload:
            user_id = payload.get("sub")
            if isinstance(user_id, str):
                user_id = int(user_id)
            # 获取token过期时间
            token_expiry = WebSocketAuthManager.get_token_expiry(token)
        else:
            # Token无效或过期
            logger.warning("WebSocket authentication failed: invalid or expired token")
    
    # 如果是认证用户，建立连接
    if user_id:
        await ws_manager.connect(websocket, user_id)
        
        try:
            # 发送连接成功消息
            connect_msg = {
                "type": "connected",
                "user_id": user_id,
                "timestamp": datetime.utcnow().isoformat(),
                "message": "WebSocket连接已建立"
            }
            
            # 添加token过期信息
            if token_expiry:
                connect_msg["token_expires_at"] = token_expiry.isoformat()
            
            await websocket.send_json(connect_msg)
            
            # 消息处理循环
            while True:
                try:
                    # 接收客户端消息
                    data = await websocket.receive_text()
                    
                    try:
                        message = json.loads(data)
                        
                        # 检查token是否即将过期(还有5分钟)
                        if token_expiry:
                            time_until_expiry = (token_expiry - datetime.utcnow()).total_seconds()
                            if 0 < time_until_expiry < 300:  # 5分钟内
                                await websocket.send_json({
                                    "type": "token_expiring",
                                    "expires_in": int(time_until_expiry),
                                    "timestamp": datetime.utcnow().isoformat()
                                })
                        
                        # 处理各类消息
                        await ConnectionManager.handle_client_message(
                            websocket, message, 
                            User(id=user_id, username="", email="") if user_id else None
                        )
                        
                    except json.JSONDecodeError:
                        await websocket.send_json({
                            "type": "error",
                            "message": "无效的JSON格式"
                        })
                        
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e)
                    })
                    
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected: user {user_id}")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            if user_id:
                ws_manager.disconnect(websocket)
    else:
        # 匿名模式（只读）- 添加限流
        # 为匿名连接创建限流器
        rate_limiter = RateLimiter()
        
        # 使用客户端IP作为限流标识
        client_ip = websocket.client.host if websocket.client else "unknown"
        rate_limit_key = f"ws_anonymous:{client_ip}"
        
        # 检查限流（匿名模式限制更严格）
        allowed, retry_after = await rate_limiter.check_rate_limit(
            rate_limit_key, user_id=None
        )
        
        if not allowed:
            await websocket.accept()
            await websocket.close(code=4003, reason="Too many anonymous connections")
            logger.warning(f"Anonymous WebSocket rate limit exceeded for {client_ip}")
            return
        
        await websocket.accept()
        
        try:
            await websocket.send_json({
                "type": "connected",
                "authenticated": False,
                "timestamp": datetime.utcnow().isoformat(),
                "message": "匿名连接已建立，功能受限"
            })
            
            # 保持连接但不处理认证消息
            while True:
                try:
                    data = await websocket.receive_text()
                    
                    # 对匿名消息也进行限流
                    allowed, retry_after = await rate_limiter.check_rate_limit(
                        rate_limit_key, user_id=None
                    )
                    if not allowed:
                        await websocket.send_json({
                            "type": "rate_limit_exceeded",
                            "message": "消息发送过于频繁，请稍后再试",
                            "retry_after": int(retry_after) if retry_after else 60
                        })
                        continue
                    
                    message = json.loads(data)
                    
                    if message.get("type") == "ping":
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": datetime.utcnow().isoformat()
                        })
                except WebSocketDisconnect:
                    break
                except Exception:
                    pass
                    
        except Exception as e:
            logger.error(f"Anonymous WebSocket error: {e}")


@router.websocket("/ws/notifications")
async def websocket_notifications(
    websocket: WebSocket,
    token: str = Query(..., description="认证token（必需）")
):
    """
    通知专用WebSocket端点
    
    专门用于接收实时通知推送
    """
    # 验证token
    user_id = None
    try:
        from app.core.security import decode_token
        payload = decode_token(token)
        if payload:
            user_id = payload.get("sub")
            if isinstance(user_id, str):
                user_id = int(user_id)
    except Exception as e:
        await websocket.close(code=4001, reason="认证失败")
        return
    
    if not user_id:
        await websocket.close(code=4001, reason="无效的token")
        return
    
    # 建立连接
    await ws_manager.connect(websocket, user_id)
    
    try:
        # 发送确认
        await websocket.send_json({
            "type": "notification_connected",
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # 保持连接
        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)
                
                if message.get("type") == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                elif message.get("type") == "mark_read":
                    # 标记通知为已读（可以扩展）
                    await websocket.send_json({
                        "type": "marked_read",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    
            except WebSocketDisconnect:
                break
            except Exception:
                pass
                
    except Exception as e:
        logger.error(f"Notification WebSocket error: {e}")
    finally:
        ws_manager.disconnect(websocket)


# API端点：获取在线状态
@router.get("/ws/status")
async def get_websocket_status(
    current_user: User = Depends(get_current_user)
):
    """获取WebSocket连接状态"""
    return {
        "online": ws_manager.is_user_online(current_user.id),
        "connection_count": ws_manager.get_connection_count(current_user.id),
        "online_users": ws_manager.get_online_users()
    }


# API端点：发送测试通知
@router.post("/ws/test-notification")
async def send_test_notification(
    current_user: User = Depends(get_current_user)
):
    """发送测试通知"""
    await notification_service.send_notification(
        user_id=current_user.id,
        notification_type=NotificationType.SYSTEM,
        title="测试通知",
        content="这是一条测试通知",
        priority="normal"
    )
    
    return {"status": "success", "message": "测试通知已发送"}
