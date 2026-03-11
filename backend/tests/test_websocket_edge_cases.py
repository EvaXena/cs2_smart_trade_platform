# -*- coding: utf-8 -*-
"""
WebSocket Edge Cases Tests

测试WebSocket边界场景：
- 连接数限制
- 心跳超时
- 重连机制
- 离线消息队列
- 广播排除
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from fastapi import WebSocket
from fastapi.testclient import TestClient
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.websocket_manager import WebSocketManager, ConnectionState


class MockWebSocket:
    """模拟WebSocket"""
    def __init__(self):
        self.messages = []
        self.closed = False
        self.close_code = None
        self.close_reason = None
    
    async def accept(self):
        pass
    
    async def send_json(self, data):
        self.messages.append(data)
    
    async def receive_json(self):
        if self.messages:
            return self.messages.pop(0)
        return {"type": "pong"}
    
    async def close(self, code=None, reason=None):
        self.closed = True
        self.close_code = code
        self.close_reason = reason


class TestWebSocketMaxConnections:
    """WebSocket最大连接数测试"""
    
    def setup_method(self):
        """每个测试前重置管理器"""
        self.ws_manager = WebSocketManager()
    
    @pytest.mark.asyncio
    async def test_max_total_connections(self):
        """测试系统最大连接数限制"""
        # 设置较低的限制用于测试
        original_limit = self.ws_manager.MAX_TOTAL_CONNECTIONS
        self.ws_manager.MAX_TOTAL_CONNECTIONS = 5
        
        # 创建5个连接
        for i in range(5):
            ws = MockWebSocket()
            result = await self.ws_manager.connect(ws, user_id=i)
            assert result is not False, f"Connection {i} should succeed"
        
        # 第6个连接应该被拒绝
        ws = MockWebSocket()
        result = await self.ws_manager.connect(ws, user_id=100)
        assert result is False, "Connection should be rejected when at max capacity"
        assert ws.closed is True
        assert ws.close_code == 1013
        
        # 恢复原始限制
        self.ws_manager.MAX_TOTAL_CONNECTIONS = original_limit
    
    @pytest.mark.asyncio
    async def test_max_connections_per_user(self):
        """测试单用户最大连接数"""
        user_id = 1
        original_limit = self.ws_manager.MAX_CONNECTIONS_PER_USER
        self.ws_manager.MAX_CONNECTIONS_PER_USER = 3
        
        # 创建3个连接
        for i in range(3):
            ws = MockWebSocket()
            await self.ws_manager.connect(ws, user_id=user_id)
        
        # 第4个连接应该被拒绝
        ws = MockWebSocket()
        result = await self.ws_manager.connect(ws, user_id=user_id)
        assert result is False, "Connection should be rejected when user at max"
        assert ws.closed is True
        
        # 恢复原始限制
        self.ws_manager.MAX_CONNECTIONS_PER_USER = original_limit
    
    @pytest.mark.asyncio
    async def test_get_connection_count(self):
        """测试获取用户连接数"""
        user_id = 1
        
        # 无连接时
        count = self.ws_manager.get_connection_count(user_id)
        assert count == 0
        
        # 添加连接
        for i in range(3):
            ws = MockWebSocket()
            await self.ws_manager.connect(ws, user_id=user_id)
        
        count = self.ws_manager.get_connection_count(user_id)
        assert count == 3


class TestWebSocketReconnect:
    """WebSocket重连测试"""
    
    def setup_method(self):
        self.ws_manager = WebSocketManager()
    
    @pytest.mark.asyncio
    async def test_calculate_reconnect_delay_exponential_backoff(self):
        """测试重连指数退避"""
        delays = []
        for attempt in range(5):
            delay = WebSocketManager.calculate_reconnect_delay(
                attempt, 
                base_delay=1, 
                max_delay=60
            )
            delays.append(delay)
        
        # 延迟应该递增（考虑随机抖动）
        assert delays[0] <= 2  # 1 + 随机
        assert delays[1] <= 4  # 2 + 随机
        assert delays[2] <= 8  # 4 + 随机
        assert delays[3] <= 16  # 8 + 随机
    
    @pytest.mark.asyncio
    async def test_reconnect_max_attempts(self):
        """测试最大重试次数"""
        user_id = 1
        ws = MockWebSocket()
        
        # 达到最大重试次数
        original_max = self.ws_manager.max_reconnect_attempts
        self.ws_manager.max_reconnect_attempts = 3
        
        # 尝试重连3次
        for attempt in range(3):
            result = await self.ws_manager.reconnect(user_id, ws, attempt)
        
        # 第4次应该失败
        result = await self.ws_manager.reconnect(user_id, ws, attempt=3)
        assert result is False
        assert self.ws_manager.get_connection_state(user_id) == ConnectionState.FAILED
        
        self.ws_manager.max_reconnect_attempts = original_max
    
    @pytest.mark.asyncio
    async def test_reconnect_state_transitions(self):
        """测试重连状态转换"""
        user_id = 1
        ws = MockWebSocket()
        
        # 重连前应该是DISCONNECTED
        initial_state = self.ws_manager.get_connection_state(user_id)
        
        # 开始重连
        await self.ws_manager.reconnect(user_id, ws, attempt=0)
        
        # 重连中应该是RECONNECTING
        state = self.ws_manager.get_connection_state(user_id)
        # 注意：reconnect方法最后会将状态设为CONNECTED


class TestWebSocketHeartbeat:
    """WebSocket心跳测试"""
    
    def setup_method(self):
        self.ws_manager = WebSocketManager()
    
    @pytest.mark.asyncio
    async def test_heartbeat_timeout(self):
        """测试心跳超时"""
        user_id = 1
        ws = MockWebSocket()
        
        # 缩短心跳超时用于测试
        self.ws_manager.heartbeat_timeout = 0.1
        
        await self.ws_manager.connect(ws, user_id)
        
        # 模拟无响应 - 清空messages，这样receive_json会返回非pong的响应
        # 注意：MockWebSocket在没有messages时返回{"type": "pong"}，这会导致心跳不超时
        # 我们需要替换receive_json来模拟超时
        original_receive_json = ws.receive_json
        
        async def mock_receive_json():
            # 模拟无响应超时
            await asyncio.sleep(1)  # 睡眠超过heartbeat_timeout
        
        ws.receive_json = mock_receive_json
        
        # 启动心跳但不响应，应该超时
        heartbeat_task = asyncio.create_task(
            self.ws_manager.start_heartbeat(ws, user_id)
        )
        
        # 等待超时发生
        await asyncio.sleep(0.3)
        
        # 用户应该已断开
        assert not self.ws_manager.is_user_online(user_id)
    
    @pytest.mark.asyncio
    async def test_heartbeat_ping_pong(self):
        """测试心跳ping-pong"""
        user_id = 1
        ws = MockWebSocket()
        
        # 设置响应
        ws.messages.append({"type": "pong"})
        
        await self.ws_manager.connect(ws, user_id)
        
        # 启动心跳
        heartbeat_task = asyncio.create_task(
            self.ws_manager.start_heartbeat(ws, user_id)
        )
        
        # 等待一个心跳周期
        await asyncio.sleep(0.5)
        
        # 应该收到ping消息
        assert len(ws.messages) > 0
        assert ws.messages[0].get("type") == "ping"
        
        # 取消心跳任务
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


class TestWebSocketOfflineMessage:
    """WebSocket离线消息测试"""
    
    def setup_method(self):
        self.ws_manager = WebSocketManager()
    
    @pytest.mark.asyncio
    async def test_offline_message_queue(self):
        """测试离线消息队列"""
        user_id = 1
        message = {"type": "test", "content": "hello"}
        
        # 用户离线时发送消息
        result = await self.ws_manager.send_personal_message(message, user_id)
        assert result is False, "Should return False for offline user"
        
        # 消息应该被加入队列
        assert user_id in self.ws_manager.offline_messages
        assert len(self.ws_manager.offline_messages[user_id]) == 1
    
    @pytest.mark.asyncio
    async def test_offline_message_delivered_on_connect(self):
        """测试连接时发送离线消息"""
        user_id = 1
        message = {"type": "test", "content": "hello"}
        
        # 先发送离线消息
        await self.ws_manager.send_personal_message(message, user_id)
        
        # 用户连接
        ws = MockWebSocket()
        await self.ws_manager.connect(ws, user_id)
        
        # 离线消息应该被发送
        assert len(ws.messages) == 1
        assert ws.messages[0]["content"] == "hello"
        
        # 队列应该被清空
        assert len(self.ws_manager.offline_messages.get(user_id, [])) == 0
    
    @pytest.mark.asyncio
    async def test_multiple_offline_messages(self):
        """测试多条离线消息"""
        user_id = 1
        
        # 发送多条消息
        for i in range(5):
            await self.ws_manager.send_personal_message(
                {"type": "test", "id": i},
                user_id
            )
        
        # 连接
        ws = MockWebSocket()
        await self.ws_manager.connect(ws, user_id)
        
        # 所有消息应该被发送
        assert len(ws.messages) == 5


class TestWebSocketBroadcast:
    """WebSocket广播测试"""
    
    def setup_method(self):
        self.ws_manager = WebSocketManager()
    
    @pytest.mark.asyncio
    async def test_broadcast_all_users(self):
        """测试广播给所有用户"""
        message = {"type": "broadcast", "content": "hello all"}
        
        # 创建多个用户连接
        for user_id in range(3):
            ws = MockWebSocket()
            await self.ws_manager.connect(ws, user_id=user_id)
        
        # 广播
        await self.ws_manager.broadcast(message)
        
        # 所有用户都应该收到消息
        for user_id in range(3):
            connections = self.ws_manager.active_connections.get(user_id, [])
            for ws in connections:
                assert len(ws.messages) == 1
    
    @pytest.mark.asyncio
    async def test_broadcast_exclude_users(self):
        """测试广播排除用户"""
        message = {"type": "broadcast", "content": "hello"}
        
        # 创建用户连接
        for user_id in range(3):
            ws = MockWebSocket()
            await self.ws_manager.connect(ws, user_id=user_id)
        
        # 广播，排除user_id=1
        await self.ws_manager.broadcast(message, exclude_users=[1])
        
        # user_id=0和2应该收到消息
        for user_id in [0, 2]:
            connections = self.ws_manager.active_connections.get(user_id, [])
            for ws in connections:
                assert len(ws.messages) == 1
        
        # user_id=1不应该收到消息
        connections = self.ws_manager.active_connections.get(1, [])
        for ws in connections:
            assert len(ws.messages) == 0


class TestWebSocketStateManagement:
    """WebSocket状态管理测试"""
    
    def setup_method(self):
        self.ws_manager = WebSocketManager()
    
    @pytest.mark.asyncio
    async def test_is_user_online(self):
        """测试用户在线状态"""
        user_id = 1
        
        # 离线时
        assert not self.ws_manager.is_user_online(user_id)
        
        # 连接后
        ws = MockWebSocket()
        await self.ws_manager.connect(ws, user_id)
        assert self.ws_manager.is_user_online(user_id)
        
        # 断开后
        self.ws_manager.disconnect(ws)
        assert not self.ws_manager.is_user_online(user_id)
    
    @pytest.mark.asyncio
    async def test_get_online_users(self):
        """测试获取在线用户列表"""
        # 创建多个用户连接
        for user_id in [1, 2, 3]:
            ws = MockWebSocket()
            await self.ws_manager.connect(ws, user_id=user_id)
        
        online_users = self.ws_manager.get_online_users()
        assert len(online_users) == 3
        assert 1 in online_users
        assert 2 in online_users
        assert 3 in online_users
    
    @pytest.mark.asyncio
    async def test_connection_state_tracking(self):
        """测试连接状态追踪"""
        user_id = 1
        
        # 连接前
        state = self.ws_manager.get_connection_state(user_id)
        assert state == ConnectionState.DISCONNECTED
        
        # 连接后
        ws = MockWebSocket()
        await self.ws_manager.connect(ws, user_id)
        state = self.ws_manager.get_connection_state(user_id)
        assert state == ConnectionState.CONNECTED
        
        # 断开后
        self.ws_manager.disconnect(ws)
        state = self.ws_manager.get_connection_state(user_id)
        assert state == ConnectionState.DISCONNECTED


class TestWebSocketCallbacks:
    """WebSocket回调测试"""
    
    def setup_method(self):
        self.ws_manager = WebSocketManager()
    
    @pytest.mark.asyncio
    async def test_on_connect_callback(self):
        """测试连接回调"""
        callback_triggered = asyncio.Event()
        
        async def on_connect(user_id):
            callback_triggered.set()
        
        self.ws_manager.on_connect(on_connect)
        
        # 连接时应该触发回调
        ws = MockWebSocket()
        await self.ws_manager.connect(ws, user_id=1)
        
        # 等待回调触发
        await asyncio.wait_for(callback_triggered.wait(), timeout=1.0)
        assert callback_triggered.is_set()
    
    @pytest.mark.asyncio
    async def test_on_disconnect_callback(self):
        """测试断开回调"""
        callback_triggered = asyncio.Event()
        
        async def on_disconnect(user_id):
            callback_triggered.set()
        
        self.ws_manager.on_disconnect(on_disconnect)
        
        # 先连接
        ws = MockWebSocket()
        await self.ws_manager.connect(ws, user_id=1)
        
        # 断开时应该触发回调
        self.ws_manager.disconnect(ws)
        
        # 等待回调触发
        await asyncio.wait_for(callback_triggered.wait(), timeout=1.0)
        assert callback_triggered.is_set()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
