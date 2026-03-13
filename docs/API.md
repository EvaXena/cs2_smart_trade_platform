# CS2 智能交易平台 API 文档

## 概述

CS2 智能交易平台提供完整的 RESTful API，支持饰品交易、库存管理、价格监控等功能。

**Base URL**: `http://localhost:8000`

**API 版本**:
- V1: `/api/v1/` (稳定版)
- V2: `/api/v2/` (增强版)

**在线文档**:
- Swagger UI: `/docs`
- ReDoc: `/redoc`

---

## 认证

### 登录获取 Token

```http
POST /api/v1/auth/login
Content-Type: application/x-www-form-urlencoded

username=your_username&password=your_password
```

**响应**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

### 使用 Token

```http
GET /api/v1/items
Authorization: Bearer YOUR_ACCESS_TOKEN
```

---

## 错误响应

所有 API 错误返回统一格式：

```json
{
  "code": "ERROR_CODE",
  "message": "错误描述",
  "detail": {}
}
```

**常见错误码**:
| 错误码 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| VALIDATION_ERROR | 400 | 参数验证失败 |
| NOT_FOUND | 404 | 资源不存在 |
| UNAUTHORIZED | 401 | 未认证 |
| FORBIDDEN | 403 | 无权限 |
| INTERNAL_ERROR | 500 | 服务器内部错误 |

---

## API 端点参考

### 1. 认证 (Auth)

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/register` | 用户注册 |
| POST | `/api/v1/auth/login` | 用户登录 |
| POST | `/api/v1/auth/logout` | 登出 |
| GET | `/api/v1/auth/me` | 获取当前用户 |
| PUT | `/api/v1/auth/me` | 更新用户信息 |

### 2. 饰品 (Items)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/items` | 获取饰品列表（支持分页、筛选、排序） |
| GET | `/api/v1/items/search` | 搜索饰品 |
| GET | `/api/v1/items/{item_id}` | 获取饰品详情 |
| GET | `/api/v1/items/{item_id}/price` | 获取价格历史 |
| GET | `/api/v1/items/{item_id}/overview` | 获取价格概览（BUFF vs Steam） |
| POST | `/api/v1/items/batch` | 批量获取饰品 |

**饰品列表参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| page | int | 页码，默认1 |
| page_size | int | 每页数量，默认20，最大100 |
| category | string | 分类筛选 |
| rarity | string | 稀有度筛选 |
| exterior | string | 外观筛选 |
| min_price | float | 最低价格 |
| max_price | float | 最高价格 |
| sort_by | string | 排序字段 |
| sort_order | string | 排序方向 |

### 3. 订单 (Orders)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/orders` | 获取订单列表 |
| POST | `/api/v1/orders` | 创建订单 |
| GET | `/api/v1/orders/{order_id}` | 获取订单详情 |
| DELETE | `/api/v1/orders/{order_id}` | 取消订单 |
| POST | `/api/v1/orders/batch` | 批量创建订单 |
| POST | `/api/v1/orders/batch/cancel` | 批量取消订单 |
| GET | `/api/v1/orders/statistics` | 获取订单统计 |

### 4. 库存 (Inventory)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/inventory` | 获取用户库存 |
| POST | `/api/v1/inventory/sync` | 同步库存 |
| POST | `/api/v1/inventory/list` | 上架到市场 |
| POST | `/api/v1/inventory/unlist` | 下架 |
| POST | `/api/v1/inventory/batch_list` | 批量上架 |
| POST | `/api/v1/inventory/batch_unlist` | 批量下架 |
| GET | `/api/v1/inventory/{inventory_id}` | 获取库存详情 |
| PUT | `/api/v1/inventory/{inventory_id}` | 更新库存 |
| DELETE | `/api/v1/inventory/{inventory_id}` | 删除库存 |

### 5. 监控 (Monitors)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/monitors` | 获取监控列表 |
| POST | `/api/v1/monitors` | 创建监控 |
| GET | `/api/v1/monitors/{monitor_id}` | 获取监控详情 |
| PUT | `/api/v1/monitors/{monitor_id}` | 更新监控 |
| DELETE | `/api/v1/monitors/{monitor_id}` | 删除监控 |
| POST | `/api/v1/monitors/{monitor_id}/start` | 启动监控 |
| POST | `/api/v1/monitors/{monitor_id}/stop` | 停止监控 |
| GET | `/api/v1/monitors/{monitor_id}/logs` | 获取监控日志 |

### 6. 机器人 (Bots)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/bots` | 获取机器人列表 |
| POST | `/api/v1/bots` | 添加机器人 |
| GET | `/api/v1/bots/{bot_id}` | 获取机器人详情 |
| PUT | `/api/v1/bots/{bot_id}` | 更新机器人 |
| DELETE | `/api/v1/bots/{bot_id}` | 删除机器人 |
| POST | `/api/v1/bots/{bot_id}/login` | 登录机器人 |
| POST | `/api/v1/bots/{bot_id}/logout` | 登出机器人 |
| POST | `/api/v1/bots/{bot_id}/refresh` | 刷新机器人状态 |
| GET | `/api/v1/bots/{bot_id}/inventory` | 获取机器人库存 |
| GET | `/api/v1/bots/{bot_id}/trades` | 获取机器人交易记录 |

### 7. 统计 (Stats)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/stats` | 获取总体统计 |
| GET | `/api/v1/stats/user/{user_id}` | 获取用户统计 |
| GET | `/api/v1/stats/trades` | 获取交易统计 |
| GET | `/api/v1/stats/profit` | 获取利润统计 |
| GET | `/api/v1/stats/inventory_value` | 获取库存价值 |
| GET | `/api/v1/stats/dashboard` | 获取仪表盘数据 |

### 8. 监控 (Monitoring)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/monitoring/health` | 健康检查 |
| GET | `/api/v1/monitoring/metrics` | 获取指标 |
| GET | `/api/v1/monitoring/alerts` | 获取告警 |
| POST | `/api/v1/monitoring/alerts/config` | 配置告警 |
| POST | `/api/v1/monitoring/metrics/reset` | 重置指标 |

### 9. 市场 (Market)

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/v1/market/listings` | 创建上架 |
| DELETE | `/api/v1/market/listings/{listing_id}` | 取消上架 |
| GET | `/api/v1/market/listings` | 获取我的上架列表 |
| GET | `/api/v1/market/listings/{listing_id}` | 获取上架详情 |

---

## 请求/响应示例

### 登录

```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123"
```

### 获取饰品列表

```bash
curl -X GET "http://localhost:8000/api/v1/items?page=1&page_size=20&sort_by=current_price&sort_order=asc" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 搜索饰品

```bash
curl -X GET "http://localhost:8000/api/v1/items/search?keyword=AK-47&limit=10" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 批量获取饰品

```bash
curl -X POST "http://localhost:8000/api/v1/items/batch" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"item_ids": [1, 2, 3, 100, 200]}'
```

### 创建订单

```bash
curl -X POST "http://localhost:8000/api/v1/orders" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "item_id": 100,
    "price": 150.00,
    "action": "buy"
  }'
```

### 批量上架库存

```bash
curl -X POST "http://localhost:8000/api/v1/inventory/batch_list" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "inventory_ids": [1, 2, 3],
    "price": 100.00
  }'
```

---

## V2 API 增强功能

V2 API 在 V1 基础上提供更多功能：

### 增强的查询参数

```bash
# 排序和分页
GET /api/v2/items?page=1&limit=50&sort_by=price&sort_order=asc

# 搜索过滤
GET /api/v2/items?search=龙狙&rarity=legendary&exterior=久经沙场

# 多维度过滤
GET /api/v2/inventory?status=onsale&rarity=uncommon&sort_by=price
```

### 批量操作

```bash
POST /api/v2/items/batch
POST /api/v2/inventory/batch
```

---

## 速率限制

| 端点类型 | 限制 |
|----------|------|
| 认证 | 5次/分钟 |
| 读取 | 60次/分钟 |
| 写入 | 30次/分钟 |
| 批量操作 | 10次/分钟 |

---

## 数据模型

### Item (饰品)

```json
{
  "id": 1,
  "name": "AK-47 | 红线 (久经沙场)",
  "name_cn": "AK-47 | 红线",
  "market_hash_name": "AK-47 | Redline (Field-Tested)",
  "category": "weapon",
  "rarity": "class",
  "exterior": "Field-Tested",
  "current_price": 150.00,
  "steam_lowest_price": 180.00,
  "volume_24h": 500,
  "price_change_percent": 2.5,
  "image_url": "https://..."
}
```

### Order (订单)

```json
{
  "id": 1,
  "user_id": 1,
  "item_id": 100,
  "price": 150.00,
  "action": "buy",
  "status": "pending",
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:00:00"
}
```

### Inventory (库存)

```json
{
  "id": 1,
  "user_id": 1,
  "item_id": 100,
  "market_value": 150.00,
  "listing_price": 155.00,
  "status": "onsale",
  "is_listed": true,
  "listed_at": "2024-01-01T00:00:00"
}
```

---

## 错误码详解

| 错误码 | 说明 | 解决方案 |
|--------|------|----------|
| INVALID_CREDENTIALS | 用户名或密码错误 | 检查登录凭据 |
| TOKEN_EXPIRED | Token 已过期 | 重新登录获取新 Token |
| ITEM_NOT_FOUND | 饰品不存在 | 检查 item_id 是否正确 |
| INSUFFICIENT_BALANCE | 余额不足 | 充值后再操作 |
| INVENTORY_NOT_FOUND | 库存不存在 | 检查 inventory_id |
| MONITOR_NOT_FOUND | 监控不存在 | 检查 monitor_id |
| BATCH_SIZE_EXCEEDED | 批量大小超限 | 减少批量数量 |
| PRICE_OUT_OF_RANGE | 价格超出范围 | 调整价格 |

---

## 附录

### 稀有度枚举
- `common` - 普通
- `uncommon` - 受限
- `rare` - 保密
- `mythical` - 机密
- `legendary` - 隐秘
- `ancient` - 绝版

### 外观条件
- `Factory New` - 全新
- `Minimal Wear` - 略有磨损
- `Field-Tested` - 久经沙场
- `Well-Worn` - 破损不堪
- `Battle-Scarred` - 战痕累累

### 状态枚举
- `pending` - 待处理
- `processing` - 处理中
- `completed` - 已完成
- `cancelled` - 已取消
- `failed` - 失败
- `onsale` - 上架中
- `sold` - 已售出
- `unsold` - 未售出

---

*最后更新: 2024-03-14*
