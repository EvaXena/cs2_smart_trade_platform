# CS2 智能交易平台

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-00.svg)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3.4+-4FC08D.svg)](https://vuejs.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A comprehensive CS2/CS:GO trading platform with automated arbitrage, price monitoring, and Steam integration.

[English](./README.md) | [中文](./README_CN.md)

</div>

## ✨ 特性

- 🔍 **实时价格监控** - BUFF/Steam 双平台价格监控
- 🤖 **自动化交易** - 智能搬砖机器人，自动低价买入高价卖出
- 📊 **数据分析** - 价格走势、历史记录、利润统计
- 🔐 **账户安全** - Steam 令牌支持、多因素认证
- 🌐 **Web 管理面板** - 直观的可视化操作界面
- 📱 **RESTful API** - 完整的 API 接口支持二次开发

## 📋 目录

- [架构](#架构)
- [快速开始](#快速开始)
- [配置](#配置)
- [API 文档](#api-文档)
- [项目结构](#项目结构)
- [贡献](#贡献)
- [许可证](#许可证)

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────────────┐
│                     前端 (Vue 3 + TS)                       │
│   Dashboard | 饰品市场 | 订单管理 | 库存 | 自动化 | 统计      │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTP/WebSocket
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    API 网关 (FastAPI)                        │
│         认证 | 限流 | 负载均衡 | 路由                         │
└────────────────────────────┬────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│  监控服务      │   │  交易服务      │   │  账户服务      │
│  Price Monitor│   │   Trading    │   │   Account    │
└───────┬───────┘   └───────┬───────┘   └───────┬───────┘
        │                   │                    │
        ▼                   ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│    BUFF API   │   │  Steam API    │   │  Database     │
│               │   │  (SteamKit)   │   │  PostgreSQL   │
└───────────────┘   └───────────────┘   └───────────────┘
```

## 🚀 快速开始

### 前置要求

- Python 3.11+
- Node.js 18+
- PostgreSQL 15+
- Redis 7+

### 1. 克隆项目

```bash
git clone https://github.com/yourusername/cs2-trade-platform.git
cd cs2-trade-platform
```

### 2. 后端设置

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# ⚠️ 重要：在虚拟环境中安装依赖（推荐使用 Python 3.8-3.11）
pip install -r backend/requirements.txt

# ⚠️ 注意：如果 bcrypt 版本不兼容，手动安装兼容版本
# pip install "bcrypt>=4.0.0,<5.0.0"

# 配置环境变量
cp backend/.env.example backend/.env
# 编辑 .env 文件填入配置

# 初始化数据库
cd backend
alembic upgrade head

# 启动服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 前端设置

```bash
cd frontend

# 安装依赖
npm install

# 配置环境变量
cp .env.example .env

# 启动开发服务器
npm run dev
```

### 4. Docker 部署（推荐）

```bash
# 使用 docker-compose 一键启动
docker-compose up -d
```

## ⚙️ 配置

### 环境变量 (Backend)

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接字符串 | `postgresql://user:pass@localhost/cs2trade` |
| `REDIS_URL` | Redis 连接字符串 | `redis://localhost:6379/0` |
| `SECRET_KEY` | JWT 密钥 | 自动生成 |
| `STEAM_API_KEY` | Steam Web API Key | - |
| `BUFF_COOKIE` | BUFF 登录 Cookie | - |
| `ENCRYPTION_KEY` | 加密密钥（**必需**） | - |
| `ENCRYPTION_SALT` | 加密盐值，至少16字符（**必需**） | - |

### 环境变量 (Frontend)

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `VITE_API_BASE` | API 基础地址 | `http://localhost:8000` |

## 📚 API 文档

启动服务后访问：

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### API 版本

平台提供两个 API 版本：

| 版本 | 前缀 | 状态 | 说明 |
|------|------|------|------|
| V1 | `/api/v1/` | 稳定 | 生产环境使用 |
| V2 | `/api/v2/` | 增强 | 新增功能，扩展参数 |

### 核心接口 (V1)

#### 认证
```
POST   /api/v1/auth/login          # 用户登录
POST   /api/v1/auth/logout         # 登出
GET    /api/v1/auth/me             # 当前用户
```

#### 饰品
```
GET    /api/v1/items               # 饰品列表
GET    /api/v1/items/{id}          # 饰品详情
GET    /api/v1/items/search        # 搜索饰品
GET    /api/v1/items/{id}/price    # 价格历史
```

#### 订单
```
GET    /api/v1/orders              # 订单列表
POST   /api/v1/orders              # 创建订单
DELETE /api/v1/orders/{id}         # 取消订单
```

#### 库存
```
GET    /api/v1/inventory           # 我的库存
POST   /api/v1/inventory/list      # 上架到市场
POST   /api/v1/inventory/unlist    # 下架
```

#### 监控
```
GET    /api/v1/monitors            # 监控列表
POST   /api/v1/monitors            # 创建监控
PUT    /api/v1/monitors/{id}       # 更新监控
DELETE /api/v1/monitors/{id}       # 删除监控
```

#### 机器人
```
GET    /api/v1/bots                # 机器人列表
POST   /api/v1/bots                # 添加机器人
POST   /api/v1/bots/{id}/login     # 登录机器人
POST   /api/v1/bots/{id}/trade     # 发起交易
```

### 核心接口 (V2)

V2 API 在 V1 基础上增加了更多功能和过滤参数。所有 V2 端点需要 Bearer Token 认证。

#### 增强的饰品接口
```
# 获取饰品列表 - 支持排序和分页
GET    /api/v2/items?page=1&limit=20&sort_by=price&sort_order=asc

# 搜索过滤
GET    /api/v2/items?search=龙狙&rarity=legendary&exterior=久经沙场

# 批量操作
POST   /api/v2/items/batch
```

#### 增强的库存接口
```
# 获取库存 - 支持多维度过滤
GET    /api/v2/inventory?status=onsale&rarity=uncommon&sort_by=price&sort_order=desc

# 批量操作
POST   /api/v2/inventory/batch
```

#### 批量操作请求示例

```bash
# 批量操作请求
curl -X POST "http://localhost:8000/api/v2/items/batch" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "delete",
    "item_ids": [1, 2, 3]
  }'
```

#### V2 API 使用示例

```python
import requests

BASE_URL = "http://localhost:8000/api/v2"

# 获取认证令牌
def login(username, password):
    response = requests.post(
        f"{BASE_URL}/auth/login",
        data={"username": username, "password": password}
    )
    return response.json()["access_token"]

# 获取饰品列表 (V2)
def get_items(token, page=1, limit=20, sort_by="price", sort_order="asc"):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"{BASE_URL}/items",
        params={
            "page": page,
            "limit": limit,
            "sort_by": sort_by,
            "sort_order": sort_order
        },
        headers=headers
    )
    return response.json()

# 获取库存列表 (V2)
def get_inventory(token, status=None, rarity=None):
    headers = {"Authorization": f"Bearer {token}"}
    params = {}
    if status:
        params["status"] = status
    if rarity:
        params["rarity"] = rarity
    response = requests.get(
        f"{BASE_URL}/inventory",
        params=params,
        headers=headers
    )
    return response.json()

# 使用示例
token = login("your_username", "your_password")
items = get_items(token, page=1, limit=50, sort_by="price", sort_order="asc")
inventory = get_inventory(token, status="onsale")
```

```javascript
// JavaScript/TypeScript 示例
const BASE_URL = 'http://localhost:8000/api/v2';

const api = {
  async login(username, password) {
    const response = await fetch(`${BASE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    const data = await response.json();
    return data.access_token;
  },

  async getItems(token, options = {}) {
    const params = new URLSearchParams({
      page: options.page || 1,
      limit: options.limit || 20,
      sort_by: options.sortBy || 'price',
      sort_order: options.sortOrder || 'asc'
    });
    
    const response = await fetch(`${BASE_URL}/items?${params}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    return response.json();
  },

  async getInventory(token, filters = {}) {
    const params = new URLSearchParams(filters);
    const response = await fetch(`${BASE_URL}/inventory?${params}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    return response.json();
  }
};

// 使用示例
const token = await api.login('username', 'password');
const items = await api.getItems(token, { page: 1, limit: 50 });
const inventory = await api.getInventory(token, { status: 'onsale' });
```

## 📁 项目结构

```
cs2-trade-platform/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── endpoints/
│   │   │       │   ├── auth.py
│   │   │       │   ├── items.py
│   │   │       │   ├── orders.py
│   │   │       │   ├── inventory.py
│   │   │       │   ├── monitors.py
│   │   │       │   └── bots.py
│   │   │       └── router.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── security.py
│   │   │   └── database.py
│   │   ├── models/
│   │   │   ├── user.py
│   │   │   ├── item.py
│   │   │   ├── order.py
│   │   │   ├── inventory.py
│   │   │   └── bot.py
│   │   ├── schemas/
│   │   │   ├── user.py
│   │   │   ├── item.py
│   │   │   ├── order.py
│   │   │   └── ...
│   │   ├── services/
│   │   │   ├── buff_service.py
│   │   │   ├── steam_service.py
│   │   │   ├── monitor_service.py
│   │   │   └── trading_service.py
│   │   ├── utils/
│   │   │   ├── rate_limiter.py
│   │   │   └── ...
│   │   └── main.py
│   ├── alembic/
│   ├── requirements.txt
│   ├── .env.example
│   └── alembic.ini
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── views/
│   │   ├── stores/
│   │   ├── router/
│   │   └── App.vue
│   ├── public/
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── bot/
│   ├── cmd/
│   │   └── main.go
│   └── internal/
│       ├── steam/
│       ├── buff/
│       └── trading/
├── docker-compose.yml
├── LICENSE
├── README.md
└── README_CN.md
```

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add some amazing feature'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 打开 Pull Request

## ⚠️ 风险提示

- **账号风险**：Steam 可能封禁异常交易账号
- **价格风险**：饰品价格波动可能导致亏损
- **政策风险**：请遵守 Steam 和 BUFF 服务条款
- **技术风险**：自动化交易可能产生意外订单

> ⚡ 使用本项目即表示您同意自行承担所有风险。作者不对任何损失负责。

## 📄 许可证

本项目基于 MIT 许可证开源。详见 [LICENSE](LICENSE) 文件。

---

<div align="center">

⭐ Star 本项目表示支持 | 🐛 报告 Bug 请开 Issue

</div>
