# 第26轮 CS2 智能交易平台改进方案

## 概述
- **轮次**: 第26轮
- **时间**: 2026-03-11
- **目标**: 解决第26轮调研发现的4个问题

---

## 问题清单与优先级

| 优先级 | 问题 | 预估工作量 |
|--------|------|-----------|
| P0 | Steam卖出功能未实现 | 8小时 |
| P1 | 缺乏高并发压力测试 | 4小时 |
| P2 | 缺乏API版本管理 | 6小时 |
| P4 | email-validator 依赖 | 0.5小时 |

---

## P0 - Steam卖出功能未实现

### 问题描述
`steam_service.py` 中的 `SteamTrade` 类缺少以下方法：
- `create_listing` - 创建市场挂单
- `cancel_listing` - 取消市场挂单  
- `get_my_listings` - 获取我的挂单列表

### 解决方案

#### 1. 实现 Steam 社区市场 API 交互

Steam 社区市场 API 需要模拟浏览器行为，使用 session cookie 进行认证：

```python
# 需要的方法
async def create_listing(
    self,
    app_id: int = 730,
    context_id: int = 2,
    asset_id: str,
    price: float
) -> Dict[str, Any]:
    """在 Steam 社区市场创建挂单"""
    # POST https://steamcommunity.com/market/sellitem/
    # Headers: 需要 Cookie: sessionid, steamLogin, steamLoginSecure
    # Form: appid, contextid, assetid, price
    pass

async def cancel_listing(self, listing_id: str) -> bool:
    """取消市场挂单"""
    # POST https://steamcommunity.com/market/removelisting/
    # Form: listingid
    pass

async def get_my_listings(
    self,
    start: int = 0,
    count: int = 100
) -> Dict[str, Any]:
    """获取当前账户的市场挂单"""
    # GET https://steamcommunity.com/market/mylistings/
    # Headers: 需要登录态 Cookie
    pass
```

#### 2. 实现步骤

1. **添加 Steam 市场认证机制**
   - 实现基于 session cookie 的认证
   - 支持 steamLogin/steamLoginSecure cookie
   - 添加 market_token 获取方法

2. **实现 create_listing 方法**
   - 构建 POST 请求到 `/market/sellitem/`
   - 处理 CSRF 保护
   - 返回 listing_id

3. **实现 cancel_listing 方法**
   - 构建 POST 请求到 `/market/removelisting/`
   - 返回成功状态

4. **实现 get_my_listings 方法**
   - 构建 GET 请求到 `/market/mylistings/`
   - 解析返回的 HTML/JSON 数据

5. **添加 API 端点**
   - 在 `app/api/v1/endpoints/` 中添加 market 路由
   - `POST /api/v1/market/listings` - 创建挂单
   - `DELETE /api/v1/market/listings/{listing_id}` - 取消挂单
   - `GET /api/v1/market/listings` - 获取我的挂单

### 预估工作量
- 认证机制: 2小时
- 核心方法实现: 3小时
- API 端点: 2小时
- 测试: 1小时
- **总计: 8小时**

---

## P1 - 缺乏高并发压力测试

### 问题描述
当前项目使用自定义 asyncio 实现的压力测试 (`stress_test.py`)，功能较为基础，缺少：
- 更专业的负载生成工具集成
- 分布式压测支持
- 详细的性能指标分析

### 解决方案

#### 1. 集成 Locust 进行高级压力测试

```python
# tests/load/locustfile.py
from locust import HttpUser, task, between

class CS2TradeUser(HttpUser):
    wait_time = between(1, 3)
    
    @task(3)
    def get_items(self):
        self.client.get("/api/v1/items?page=1&limit=20")
    
    @task(2)
    def get_orders(self):
        self.client.get("/api/v1/orders?page=1&limit=20")
    
    @task(1)
    def get_stats(self):
        self.client.get("/api/v1/stats/dashboard")
```

#### 2. 实现步骤

1. **安装 locust**
   ```bash
   pip install locust
   ```

2. **创建 locust 配置文件**
   - `tests/load/locustfile.py` - 主测试文件
   - `tests/load/advanced_tasks.py` - 复杂业务场景

3. **添加 pytest-benchmark 集成**
   - 用于 API 端点性能基准测试
   - `tests/test_benchmark.py`

4. **创建压测脚本**
   - `scripts/run_stress_test.sh` - 运行自定义压力测试
   - `scripts/run_locust.sh` - 运行 locust 压测

### 预估工作量
- Locust 配置: 2小时
- Benchmark 集成: 1小时
- 压测脚本: 1小时
- **总计: 4小时**

---

## P2 - 缺乏API版本管理

### 问题描述
当前所有 API 都在 `/api/v1/` 下，无法：
- 平滑演进 API 而不破坏客户端
- 同时维护多个 API 版本
- 对不同版本进行差异化配置

### 解决方案

#### 1. 实现多版本支持架构

```
/api/
  /v1/           # 当前版本
    /endpoints/
    /schemas/
  /v2/           # 新版本
    /endpoints/
    /schemas/
```

#### 2. 实现步骤

1. **重构路由结构**
   ```
   app/api/
     v1/
       endpoints/
       router.py
     v2/
       endpoints/
       router.py
     router.py          # 版本路由分发
   ```

2. **创建版本路由器**
   ```python
   # app/api/router.py
   from fastapi import APIRouter, Request
   from fastapi.responses import JSONResponse
   
   api_router = APIRouter()
   
   @api_router.get("/v1/{path:path}")
   async def v1_handler(request: Request, path: str):
       # 转发到 v1 路由器
       pass
   
   @api_router.get("/v2/{path:path}")
   async def v2_handler(request: str):
      : Request, path # 转发到 v2 路由器
       pass
   ```

3. **添加版本协商中间件**
   - 支持 `Accept-Version` header
   - 默认返回最新稳定版本

4. **创建 v2 版本的改进**
   - 响应格式标准化
   - 错误处理统一
   - 分页格式统一

5. **更新 main.py**
   - 注册新的路由结构

### 预估工作量
- 路由重构: 2小时
- 版本协商: 2小时
- v2 版本实现: 2小时
- **总计: 6小时**

---

## P4 - email-validator 依赖

### 问题描述
requirements.txt 中已包含 `email-validator>=2.1.0`，但可能未正确安装。

### 解决方案

1. **验证安装状态**
   ```bash
   cd backend
   pip show email-validator
   ```

2. **如未安装，执行安装**
   ```bash
   pip install email-validator
   ```

### 预估工作量
- **总计: 0.5小时**

---

## 实施计划

### 第一阶段：P0 核心功能
| 步骤 | 内容 | 负责人 | 时间 |
|------|------|--------|------|
| 1 | Steam 市场认证机制 | 22号 | 2h |
| 2 | create_listing 实现 | 22号 | 1.5h |
| 3 | cancel_listing 实现 | 22号 | 1h |
| 4 | get_my_listings 实现 | 22号 | 1.5h |
| 5 | API 端点 | 22号 | 2h |

### 第二阶段：P1 压力测试
| 步骤 | 内容 | 负责人 | 时间 |
|------|------|--------|------|
| 1 | Locust 配置 | 22号 | 2h |
| 2 | Benchmark 集成 | 22号 | 1h |
| 3 | 压测脚本 | 22号 | 1h |

### 第三阶段：P2 版本管理
| 步骤 | 内容 | 负责人 | 时间 |
|------|------|--------|------|
| 1 | 路由重构 | 22号 | 2h |
| 2 | 版本协商 | 22号 | 2h |
| 3 | v2 实现 | 22号 | 2h |

### 第四阶段：环境修复
| 步骤 | 内容 | 负责人 | 时间 |
|------|------|--------|------|
| 1 | email-validator 验证 | 22号 | 0.5h |

---

## 预期产出

1. **Steam 市场卖出功能**
   - `app/services/steam_market.py` - 市场交易服务
   - `app/api/v1/endpoints/market.py` - 市场 API 端点

2. **压力测试增强**
   - `tests/load/locustfile.py` - Locust 压测配置
   - `tests/test_benchmark.py` - 性能基准测试
   - `scripts/run_locust.sh` - 压测启动脚本

3. **API 版本管理**
   - `app/api/v2/` - v2 版本路由
   - `app/api/router.py` - 版本路由器

---

## 风险与注意事项

1. **Steam API 风险**
   - Steam 可能阻止自动化操作，需要控制请求频率
   - 需要处理验证码等反爬虫机制

2. **版本管理风险**
   - v2 需要与 v1 保持兼容或提供清晰的迁移路径

3. **压力测试风险**
   - 高并发测试可能影响生产环境，需要在测试环境执行
