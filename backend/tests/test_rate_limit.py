# -*- coding: utf-8 -*-
"""
限流中间件测试
"""
import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch
from starlette.requests import Request
from starlette.responses import JSONResponse
from app.middleware.rate_limit import RateLimitMiddleware, create_rate_limit_middleware


class MockRequest:
    """模拟请求对象"""
    def __init__(self, path="/api/v1/test", client_ip="127.0.0.1"):
        self.url = MagicMock()
        self.url.path = path
        self.headers = {}
        self.client = MagicMock()
        self.client.host = client_ip


class TestRateLimitMiddleware:
    """限流中间件测试"""
    
    def test_init_default_config(self):
        """测试默认配置"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        assert middleware.default_config["requests"] == 60
        assert middleware.default_config["window"] == 60
        assert middleware.default_config["burst"] == 10
    
    def test_init_custom_config(self):
        """测试自定义配置"""
        app = MagicMock()
        custom_config = {
            "/api/v1/custom": {
                "requests": 10,
                "window": 60,
                "burst": 5
            }
        }
        middleware = RateLimitMiddleware(app, custom_config)
        
        assert middleware.endpoint_config["/api/v1/custom"]["requests"] == 10
    
    def test_get_client_ip_forwarded(self):
        """测试从X-Forwarded-For获取IP"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        request = MockRequest()
        request.headers["X-Forwarded-For"] = "192.168.1.100, 10.0.0.1"
        
        ip = middleware._get_client_ip(request)
        assert ip == "192.168.1.100"
    
    def test_get_client_ip_no_forwarded(self):
        """测试无X-Forwarded-For时获取IP"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        request = MockRequest(client_ip="192.168.1.50")
        
        ip = middleware._get_client_ip(request)
        assert ip == "192.168.1.50"
    
    def test_get_rate_limit_key(self):
        """测试限流key生成"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        request = MockRequest("/api/v1/test", "192.168.1.100")
        key = middleware._get_rate_limit_key(request, "/api/v1/test")
        
        assert key == "192.168.1.100:/api/v1/test"
    
    def test_get_endpoint_config_exact_match(self):
        """测试精确匹配端点配置"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        config = middleware._get_endpoint_config("/api/v1/auth/login")
        
        assert config["requests"] == 5
        assert config["window"] == 60
    
    def test_get_endpoint_config_prefix_match(self):
        """测试前缀匹配端点配置"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        config = middleware._get_endpoint_config("/api/v1/orders/create")
        
        assert config["requests"] == 120
        assert config["window"] == 60
    
    def test_get_endpoint_config_default(self):
        """测试默认配置"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        config = middleware._get_endpoint_config("/api/v1/unknown")
        
        assert config == middleware.default_config
    
    def test_check_rate_limit_first_request(self):
        """测试首次请求通过"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        key = "test_key"
        config = {"requests": 60, "window": 60, "burst": 10}
        
        allowed, info = middleware._check_rate_limit(key, config)
        
        assert allowed is True
        assert info is None
    
    def test_check_rate_limit_exceeded(self):
        """测试超过限流"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        key = "test_key"
        config = {"requests": 5, "window": 60, "burst": 3}
        
        # 模拟已有5个请求
        middleware._requests[key] = [time.time() - 10] * 5
        
        allowed, info = middleware._check_rate_limit(key, config)
        
        assert allowed is False
        assert info is not None
        assert info["requests"] == 5
        assert info["limit"] == 5
    
    def test_check_rate_limit_window_expired(self):
        """测试窗口过期后重置"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        key = "test_key"
        config = {"requests": 5, "window": 60, "burst": 3}
        
        # 模拟旧请求（超过窗口时间）
        middleware._requests[key] = [time.time() - 120] * 5
        
        allowed, info = middleware._check_rate_limit(key, config)
        
        # 旧请求已清理，可以通过
        assert allowed is True
    
    def test_check_rate_limit_burst_warning(self):
        """测试突发限制警告"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        key = "test_key"
        config = {"requests": 10, "window": 60, "burst": 5}
        
        # 模拟请求数达到突发限制
        middleware._requests[key] = [time.time() - 5] * 5
        
        allowed, info = middleware._check_rate_limit(key, config)
        
        # 应该通过但有警告
        assert allowed is True
    
    @pytest.mark.asyncio
    async def test_dispatch_non_api_request(self):
        """测试非API请求跳过限流"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        request = MockRequest("/static/test.js")
        
        async def mock_call_next(req):
            return JSONResponse({"status": "ok"})
        
        response = await middleware.dispatch(request, mock_call_next)
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_dispatch_rate_limited(self):
        """测试被限流的请求"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        request = MockRequest("/api/v1/auth/login", "192.168.1.1")
        
        # 模拟已有5个请求（达到登录限制）
        middleware._requests["192.168.1.1:/api/v1/auth/login"] = [time.time() - 10] * 5
        
        async def mock_call_next(req):
            return JSONResponse({"status": "ok"})
        
        response = await middleware.dispatch(request, mock_call_next)
        
        assert response.status_code == 429
        assert "X-RateLimit-Limit" in response.headers
        assert response.headers["X-RateLimit-Remaining"] == "0"
    
    @pytest.mark.asyncio
    async def test_dispatch_success(self):
        """测试成功请求"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        request = MockRequest("/api/v1/auth/login", "192.168.1.1")
        
        async def mock_call_next(req):
            return JSONResponse({"status": "ok"})
        
        response = await middleware.dispatch(request, mock_call_next)
        
        assert response.status_code == 200
        assert "X-RateLimit-Limit" in response.headers
    
    def test_create_rate_limit_middleware(self):
        """测试工厂函数"""
        factory = create_rate_limit_middleware()
        
        app = MagicMock()
        middleware = factory(app)
        
        assert isinstance(middleware, RateLimitMiddleware)


class TestRateLimitEdgeCases:
    """限流边界情况测试"""
    
    def test_empty_client_ip(self):
        """测试空客户端IP"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        request = MockRequest()
        request.client = None
        
        ip = middleware._get_client_ip(request)
        assert ip == "unknown"
    
    def test_concurrent_requests_same_key(self):
        """测试同一key的并发请求"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        key = "concurrent_test"
        config = {"requests": 3, "window": 60, "burst": 3}
        
        results = []
        for _ in range(3):
            allowed, _ = middleware._check_rate_limit(key, config)
            results.append(allowed)
        
        # 前3个应该通过
        assert results[0] is True
        assert results[1] is True
        assert results[2] is True
    
    def test_different_ips_separate_limits(self):
        """测试不同IP独立限流"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        config = {"requests": 1, "window": 60, "burst": 1}
        
        # IP1
        key1 = "192.168.1.1:/api/v1/test"
        allowed1, _ = middleware._check_rate_limit(key1, config)
        
        # IP2 - 应该独立计数
        key2 = "192.168.1.2:/api/v1/test"
        allowed2, _ = middleware._check_rate_limit(key2, config)
        
        assert allowed1 is True
        assert allowed2 is True
    
    def test_cleanup_expired_records(self):
        """测试清理过期记录"""
        app = MagicMock()
        middleware = RateLimitMiddleware(app)
        
        key = "cleanup_test"
        
        # 混合新旧请求
        old_time = time.time() - 120  # 2分钟前
        new_time = time.time() - 10   # 10秒前
        middleware._requests[key] = [old_time, new_time, old_time]
        
        config = {"requests": 5, "window": 60, "burst": 3}
        allowed, _ = middleware._check_rate_limit(key, config)
        
        # 旧请求应该被清理
        assert allowed is True
        assert len(middleware._requests[key]) == 1
