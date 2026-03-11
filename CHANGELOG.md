# CHANGELOG

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [1.3.0] - 2026-03-11

### Added
- **前端WebSocket客户端**: 新增 `frontend/src/services/websocketClient.ts`
  - WebSocket连接管理
  - 断线自动重连（指数退避算法）
  - 心跳机制（30秒间隔，10秒超时）
  - 与后端 `/ws/notifications` 端点对接
  - 集成现有前端通知系统
- **日志脱敏测试**: 新增 `backend/tests/test_logging_sanitizer.py`
  - `SensitiveDataFilter` 各字段脱敏效果测试
  - JWT/Token/密码等敏感信息过滤验证
  - `SensitiveFieldFilter` 结构化字段脱敏测试
  - 集成测试覆盖
- **并发连接数限制**: 新增 `backend/app/middleware/rate_limit.py`
  - `ConnectionLimitMiddleware` 类
  - 使用Redis Set存储活跃连接
  - 最大并发连接数默认100
  - 内存降级方案

### Changed
- 前端通知系统集成WebSocket实时推送
- 后端限流中间件增强

### Fixed
- WebSocket客户端前端缺失问题
- 日志脱敏测试覆盖不足
- 并发连接数限制缺失

---

## [1.2.0] - 2026-03-11

### Added
- **V2 API 端点**: 新增完整的 RESTful API v2 版本
  - `auth.py` (296行) - 认证端点（登录/登出/令牌刷新）
  - `bots.py` (391行) - 机器人管理（列表/添加/移除/状态）
  - `inventory.py` (365行) - 库存管理（查询/上架/下架）
  - `monitors.py` (390行) - 监控端点（价格/库存监控）
  - `notifications.py` (322行) - 通知端点（CRUD/标记已读）
  - `websocket.py` - WebSocket 实时推送支持
- **通知模块**: 新增完整通知系统
  - `notification.py` (85行) - 通知数据模型
  - `notification_service.py` (225行) - 通知服务层
- **前端通知组件**:
  - `notifications.ts` (79行) - 通知 API 封装
  - `NotificationPanel.vue` (388行) - 通知面板组件
  - `apiClient.ts` (235行) - API 客户端工具
- **统一异常处理**: 新增 `exceptions.py` 异常类
  - APIError 基类及子类（ValidationError/NotFoundError/UnauthorizedError/ForbiddenError/ConflictError/RateLimitError/ExternalServiceError/BusinessError）
  - 统一错误处理器

### Changed
- **Market API 优化**: 精简 v1 market 端点
- **Router 重构**: V2 路由分组和中间件调整
- **Config 更新**: 新增通知相关配置项
- **Audit 中间件**: 优化日志格式
- **前端 API**: 重构 API 调用方式

### Fixed
- 前后端 API 对接一致性

---

## [1.1.0] - 2026-03-11

### Added
- **熔断器 (Circuit Breaker)**: 新增 `circuit_breaker.py` 实现，防止外部服务故障导致级联失败
  - 三态转换 (CLOSED → OPEN → HALF_OPEN → CLOSED)
  - 可配置失败阈值和恢复超时
- **Session 共享**: 新增 `session_manager.py`，支持分布式 Session 管理
- **CLI 管理工具**: 新增 `cli.py`，提供命令行管理接口
- **异步缓存操作**: cache.py 新增 `aset`、`adelete`、`aclear` 异步方法
- **部署文档**: 新增 `deployment.md`, `production.md`, `monitoring.md`, `troubleshooting.md`
- **Stats 图表**: 前端 Stats.vue 新增 ECharts 图表展示

### Changed
- **SQLite 优化**: database.py 新增 SQLite 专用配置
  - WAL 模式（提高并发性能）
  - busy_timeout 配置
  - 外键约束启用
  - 缓存和内存优化
- **Redis 连接检查**: `is_connected` 改为异步方法，使用 ping() 检测连接状态
- **Core 模块导出**: `__init__.py` 统一导出熔断器和 Session 管理器

### Fixed
- **P2-1**: Buff 客户端 LRU 缓存限制问题
- **P2-2**: 幂等性检查使用 SETNX 实现原子操作
- **P2-3**: 监控中间件添加定期清理机制

---

## [1.0.0] - 2026-03-11

### Added
- **统一响应格式**: 新增 `ServiceResponse` 类，统一所有服务的返回格式
- **审计日志加密**: 审计日志支持加密存储，从 `ENCRYPTION_KEY` 读取密钥

### Changed
- **Buff API 重试机制**: 线性退避 → 指数退避 + 随机抖动 (5s→10s→20s，最大60s)
- **Steam Session 健康检查**: 新增 `health_check()` 和 `ensure_healthy_session()` 方法
- **幂等性 Key 算法**: JSON 请求体排序后再生成 hash，支持乱序 JSON

### Fixed
- **P1-1**: Buff API 429 错误重试效率问题 - 使用指数退避算法
- **P1-2**: 交易服务返回格式不一致 - 统一使用 ServiceResponse
- **P1-3**: Steam Session 健康检查缺失 - 添加健康检查和自动重建
- **P1-4**: 幂等性 Key JSON 顺序问题 - 递归排序字典键
- **P1-5**: 审计日志明文存储 - 添加 Fernet 加密支持

### Security
- 审计日志敏感信息加密存储

---

## [0.9.0] - 2026-03-10

### Added
- 分布式限流支持
- 登录失败锁定机制
- 监控服务支持
- 加密 Salt 轮换支持

### Fixed
- 第17轮安全问题和技术债务修复

---

## [0.8.0] - 2026-03-10

### Added
- 加密异常处理降级策略
- 数据库连接池优化

---

## [0.7.0] - 2026-03-09

### Added
- 基础交易功能
- BUFF/Steam 双平台价格监控
- Web 管理面板 (Vue 3)
- RESTful API

---

[Unreleased]: https://github.com/yourusername/cs2-trade-platform/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/yourusername/cs2-trade-platform/releases/tag/v1.0.0
[0.9.0]: https://github.com/yourusername/cs2-trade-platform/compare/v0.9.0...v1.0.0
[0.8.0]: https://github.com/yourusername/cs2-trade-platform/compare/v0.8.0...v0.9.0
[0.7.0]: https://github.com/yourusername/cs2-trade-platform/compare/v0.7.0...v0.8.0
