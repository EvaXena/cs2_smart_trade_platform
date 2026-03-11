# -*- coding: utf-8 -*-
"""
Locust 压测配置 - CS2智能交易平台
用于高并发压力测试

运行方式:
    locust -f tests/load/locustfile.py --host=http://localhost:8000
    locust -f tests/load/locustfile.py --host=http://localhost:8000 --headless -u 100 -r 10 -t 60s
"""
import random
import string
from locust import HttpUser, task, between, events
from locust.runners import MasterRunner
import logging

logger = logging.getLogger(__name__)


class CS2TradeUser(HttpUser):
    """CS2交易平台模拟用户"""
    
    wait_time = between(1, 3)  # 请求间隔 1-3秒
    
    def on_start(self):
        """用户启动时的初始化"""
        self.token = None
        self.user_id = None
        
        # 尝试登录获取token（可选）
        # self.login()
    
    def login(self):
        """登录获取token"""
        # 随机生成测试用户
        username = f"test_user_{random.randint(1000, 9999)}"
        password = "Test123456!"
        
        response = self.client.post("/api/v1/auth/login", json={
            "username": username,
            "password": password
        })
        
        if response.status_code == 200:
            data = response.json()
            if data.get("access_token"):
                self.token = data["access_token"]
    
    def get_headers(self):
        """获取请求头"""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
    
    # ========== 饰品相关 ==========
    
    @task(5)
    def get_items_list(self):
        """获取饰品列表（高频）"""
        page = random.randint(1, 10)
        self.client.get(
            f"/api/v1/items?page={page}&limit=20",
            headers=self.get_headers(),
            name="/api/v1/items [LIST]"
        )
    
    @task(3)
    def get_item_detail(self):
        """获取饰品详情"""
        item_id = random.randint(1, 100)
        self.client.get(
            f"/api/v1/items/{item_id}",
            headers=self.get_headers(),
            name="/api/v1/items/{id}"
        )
    
    @task(2)
    def search_items(self):
        """搜索饰品"""
        keywords = ["AK-47", "AWP", "M4A1", "蝴蝶刀", "手套"]
        keyword = random.choice(keywords)
        self.client.get(
            f"/api/v1/items/search?q={keyword}",
            headers=self.get_headers(),
            name="/api/v1/items/search"
        )
    
    # ========== 订单相关 ==========
    
    @task(4)
    def get_orders_list(self):
        """获取订单列表"""
        page = random.randint(1, 5)
        self.client.get(
            f"/api/v1/orders?page={page}&limit=20",
            headers=self.get_headers(),
            name="/api/v1/orders [LIST]"
        )
    
    @task(2)
    def get_order_detail(self):
        """获取订单详情"""
        order_id = random.randint(1, 50)
        self.client.get(
            f"/api/v1/orders/{order_id}",
            headers=self.get_headers(),
            name="/api/v1/orders/{id}"
        )
    
    # ========== 库存相关 ==========
    
    @task(3)
    def get_inventory(self):
        """获取用户库存"""
        self.client.get(
            "/api/v1/inventory/",
            headers=self.get_headers(),
            name="/api/v1/inventory/"
        )
    
    @task(1)
    def get_market_listings(self):
        """获取市场挂单"""
        self.client.get(
            "/api/v1/market/listings",
            headers=self.get_headers(),
            name="/api/v1/market/listings"
        )
    
    # ========== 监控相关 ==========
    
    @task(2)
    def get_monitors(self):
        """获取监控列表"""
        self.client.get(
            "/api/v1/monitors",
            headers=self.get_headers(),
            name="/api/v1/monitors"
        )
    
    @task(1)
    def get_monitor_detail(self):
        """获取监控详情"""
        monitor_id = random.randint(1, 20)
        self.client.get(
            f"/api/v1/monitors/{monitor_id}",
            headers=self.get_headers(),
            name="/api/v1/monitors/{id}"
        )
    
    # ========== 统计相关 ==========
    
    @task(2)
    def get_dashboard_stats(self):
        """获取仪表盘统计"""
        self.client.get(
            "/api/v1/stats/dashboard",
            headers=self.get_headers(),
            name="/api/v1/stats/dashboard"
        )
    
    @task(1)
    def get_price_history(self):
        """获取价格历史"""
        item_id = random.randint(1, 100)
        self.client.get(
            f"/api/v1/items/{item_id}/price-history?days=7",
            headers=self.get_headers(),
            name="/api/v1/items/{id}/price-history"
        )
    
    # ========== 机器人相关 ==========
    
    @task(1)
    def get_bots(self):
        """获取机器人列表"""
        self.client.get(
            "/api/v1/bots",
            headers=self.get_headers(),
            name="/api/v1/bots"
        )


class CS2TradeAdminUser(HttpUser):
    """CS2交易平台管理员用户"""
    
    wait_time = between(2, 5)
    
    def on_start(self):
        """管理员登录"""
        # 使用管理员账户登录
        self.client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "admin123"
        })
    
    def get_headers(self):
        return {"Content-Type": "application/json"}
    
    @task(3)
    def get_all_orders(self):
        """获取所有订单"""
        self.client.get(
            "/api/v1/orders?page=1&limit=50",
            headers=self.get_headers()
        )
    
    @task(2)
    def get_all_users(self):
        """获取所有用户"""
        self.client.get(
            "/api/v1/stats/users",
            headers=self.get_headers()
        )
    
    @task(1)
    def get_system_health(self):
        """获取系统健康状态"""
        self.client.get("/health/ready")


class CS2TradeHeavyUser(HttpUser):
    """高频交易用户 - 用于极限压测"""
    
    wait_time = between(0.1, 0.5)  # 非常短的间隔
    
    @task(10)
    def rapid_price_check(self):
        """快速价格检查"""
        item_id = random.randint(1, 50)
        self.client.get(f"/api/v1/items/{item_id}")
    
    @task(5)
    def rapid_order_list(self):
        """快速订单列表"""
        self.client.get("/api/v1/orders?page=1&limit=10")
    
    @task(3)
    def rapid_market_list(self):
        """快速市场列表"""
        self.client.get("/api/v1/items?page=1&limit=10")
    
    @task(2)
    def health_check(self):
        """健康检查"""
        self.client.get("/health")


# ========== 事件处理 ==========

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """测试开始事件"""
    logger.info("=== Locust 压测开始 ===")
    if isinstance(environment.runner, MasterRunner):
        logger.info(f"Master 模式运行，分片数: {environment.runner.target_user_count}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """测试结束事件"""
    logger.info("=== Locust 压测结束 ===")
    logger.info(f"总请求数: {environment.stats.total.num_requests}")
    logger.info(f"总失败数: {environment.stats.total.num_failures}")
    logger.info(f"平均响应时间: {environment.stats.total.avg_response_time:.2f}ms")


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, **kwargs):
    """请求事件（可选用于详细日志）"""
    pass


# ========== 自定义测试场景 ==========

def quick_test_scenario():
    """快速测试场景 - 用于开发调试"""
    return [
        {"method": "GET", "url": "/api/v1/items?page=1&limit=20", "weight": 10},
        {"method": "GET", "url": "/api/v1/orders?page=1&limit=20", "weight": 8},
        {"method": "GET", "url": "/api/v1/monitors", "weight": 5},
        {"method": "GET", "url": "/api/v1/stats/dashboard", "weight": 3},
        {"method": "GET", "url": "/health", "weight": 2},
    ]


def heavy_load_scenario():
    """高负载场景 - 模拟抢购"""
    return [
        {"method": "GET", "url": "/api/v1/items?page=1&limit=10", "weight": 50},
        {"method": "GET", "url": "/api/v1/items/{id}", "weight": 30},
        {"method": "POST", "url": "/api/v1/orders", "weight": 10},
        {"method": "GET", "url": "/api/v1/orders/{id}", "weight": 10},
    ]
