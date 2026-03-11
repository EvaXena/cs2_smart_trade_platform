# -*- coding: utf-8 -*-
"""
WebSocket连接管理器
支持自动重连、心跳检测、连接状态管理
"""
from typing import Dict, Set, Optional, Callable
from fastapi import WebSocket
from datetime import datetime
import json
import logging
import asyncio
from enum import Enum

logger = logging.getLogger(__name__)


class ConnectionState(str, Enum):
    """连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class WebSocketManager:
    """WebSocket连接管理器 - 增强版"""
    
    # 类级别的最大连接数限制 (P1-3)
    MAX_TOTAL_CONNECTIONS: int = 1000  # 系统最大连接数
    MAX_CONNECTIONS_PER_USER: int = 5  # 单用户最大连接数
    
    def __init__(self):
        # user_id -> Set[WebSocket]
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        # websocket -> user_id
        self.connection_users: Dict[WebSocket, int] = {}
        # 离线消息队列
        self.offline_messages: Dict[int, list] = {}
        
        # 连接状态管理
        self.connection_states: Dict[int, ConnectionState] = {}
        
        # 心跳配置
        self.heartbeat_interval = 30  # 心跳间隔(秒)
        self.heartbeat_timeout = 10    # 心跳超时(秒)
        
        # 重连配置
        self.max_reconnect_attempts = 5
        self.base_reconnect_delay = 1  # 基础重连延迟(秒)
        self.max_reconnect_delay = 60  # 最大重连延迟(秒)
        
        # 回调函数
        self.on_connect_callbacks: list = []
        self.on_disconnect_callbacks: list = []
        self.on_message_callbacks: list = []
    
    # ========== 连接管理 ==========
    
    async def connect(self, websocket: WebSocket, user_id: int):
        """WebSocket连接 (P1-3: 添加连接数限制)"""
        # 检查系统最大连接数
        total_connections = sum(len(conns) for conns in self.active_connections.values())
        if total_connections >= self.MAX_TOTAL_CONNECTIONS:
            await websocket.close(code=1013, reason="Server at max capacity")
            logger.warning(f"Rejected connection: max total connections {self.MAX_TOTAL_CONNECTIONS} reached")
            return False
        
        # 检查单用户最大连接数
        if user_id in self.active_connections:
            if len(self.active_connections[user_id]) >= self.MAX_CONNECTIONS_PER_USER:
                await websocket.close(code=1013, reason="Too many connections from this user")
                logger.warning(f"Rejected connection from user {user_id}: max per-user connections {self.MAX_CONNECTIONS_PER_USER} reached")
                return False
        
        await websocket.accept()
        
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        
        self.active_connections[user_id].add(websocket)
        self.connection_users[websocket] = user_id
        self.connection_states[user_id] = ConnectionState.CONNECTED
        
        logger.info(f"User {user_id} connected via WebSocket. Total connections: {len(self.active_connections[user_id])}")
        
        # 触发连接回调
        for callback in self.on_connect_callbacks:
            try:
                await callback(user_id)
            except Exception as e:
                logger.error(f"Connect callback error: {e}")
        
        # 发送离线消息
        if user_id in self.offline_messages and self.offline_messages[user_id]:
            for message in self.offline_messages[user_id]:
                await self.send_personal_message(message, user_id)
            self.offline_messages[user_id] = []
    
    def disconnect(self, websocket: WebSocket):
        """WebSocket断开"""
        user_id = self.connection_users.pop(websocket, None)
        
        if user_id and user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
                self.connection_states[user_id] = ConnectionState.DISCONNECTED
                logger.info(f"User {user_id} disconnected. All connections closed.")
                
                # 触发断开回调
                for callback in self.on_disconnect_callbacks:
                    try:
                        asyncio.create_task(callback(user_id))
                    except Exception as e:
                        logger.error(f"Disconnect callback error: {e}")
    
    # ========== 消息发送 ==========
    
    async def send_personal_message(self, message: dict, user_id: int) -> bool:
        """发送个人消息"""
        if user_id not in self.active_connections:
            # 存储离线消息
            if user_id not in self.offline_messages:
                self.offline_messages[user_id] = []
            self.offline_messages[user_id].append(message)
            logger.info(f"User {user_id} offline. Message queued.")
            return False
        
        disconnected = set()
        
        for websocket in self.active_connections[user_id]:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send message to user {user_id}: {e}")
                disconnected.add(websocket)
        
        # 清理断开的连接
        for ws in disconnected:
            self.disconnect(ws)
        
        return True
    
    async def broadcast(self, message: dict, exclude_users: Optional[list] = None):
        """广播消息"""
        exclude_set = set(exclude_users or [])
        
        for user_id, connections in self.active_connections.items():
            if user_id in exclude_set:
                continue
            
            for websocket in connections:
                try:
                    await websocket.send_json(message)
                except Exception as e:
                    logger.error(f"Failed to broadcast to user {user_id}: {e}")
    
    # ========== 状态查询 ==========
    
    def get_online_users(self) -> list:
        """获取在线用户列表"""
        return list(self.active_connections.keys())
    
    def is_user_online(self, user_id: int) -> bool:
        """检查用户是否在线"""
        return user_id in self.active_connections and len(self.active_connections[user_id]) > 0
    
    def get_connection_count(self, user_id: int) -> int:
        """获取用户连接数"""
        return len(self.active_connections.get(user_id, set()))
    
    def get_connection_state(self, user_id: int) -> ConnectionState:
        """获取用户连接状态"""
        return self.connection_states.get(user_id, ConnectionState.DISCONNECTED)
    
    # ========== 回调管理 ==========
    
    def on_connect(self, callback: Callable):
        """注册连接回调"""
        self.on_connect_callbacks.append(callback)
    
    def on_disconnect(self, callback: Callable):
        """注册断开连接回调"""
        self.on_disconnect_callbacks.append(callback)
    
    # ========== 心跳检测 ==========
    
    async def start_heartbeat(self, websocket: WebSocket, user_id: int):
        """启动心跳检测"""
        try:
            while user_id in self.active_connections and websocket in self.active_connections.get(user_id, set()):
                # 发送ping
                await websocket.send_json({
                    "type": "ping",
                    "timestamp": datetime.utcnow().isoformat()
                })
                
                # 等待pong响应
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=self.heartbeat_timeout
                    )
                    if data.get("type") != "pong":
                        logger.warning(f"Invalid heartbeat response from user {user_id}")
                except asyncio.TimeoutError:
                    logger.warning(f"Heartbeat timeout for user {user_id}, disconnecting")
                    self.disconnect(websocket)
                    break
                
                await asyncio.sleep(self.heartbeat_interval)
        except Exception as e:
            logger.error(f"Heartbeat error for user {user_id}: {e}")
            self.disconnect(websocket)
    
    # ========== 重连机制 ==========
    
    @staticmethod
    def calculate_reconnect_delay(attempt: int, base_delay: int = 1, max_delay: int = 60) -> int:
        """计算指数退避延迟"""
        delay = min(base_delay * (2 ** attempt), max_delay)
        # 添加随机抖动(0-1秒)
        import random
        delay += random.uniform(0, 1)
        return int(delay)
    
    async def reconnect(self, user_id: int, websocket: WebSocket, attempt: int = 0) -> bool:
        """
        尝试重连
        返回是否重连成功
        """
        if attempt >= self.max_reconnect_attempts:
            logger.warning(f"User {user_id} reached max reconnect attempts")
            self.connection_states[user_id] = ConnectionState.FAILED
            return False
        
        self.connection_states[user_id] = ConnectionState.RECONNECTING
        
        delay = self.calculate_reconnect_delay(attempt, self.base_reconnect_delay, self.max_reconnect_delay)
        logger.info(f"User {user_id} reconnecting in {delay}s (attempt {attempt + 1}/{self.max_reconnect_attempts})")
        
        await asyncio.sleep(delay)
        
        # 重新建立连接
        if self.is_user_online(user_id):
            logger.info(f"User {user_id} already has active connection")
            self.connection_states[user_id] = ConnectionState.CONNECTED
            return True
        
        # 注意: 实际的重连需要客户端配合，这里只是记录状态
        # 客户端应该在断线后自动重连
        self.connection_states[user_id] = ConnectionState.CONNECTED
        return True


# 全局实例
ws_manager = WebSocketManager()
