# -*- coding: utf-8 -*-
"""
监控端点 - 健康检查、指标和告警
"""
import time
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import APIRouter, Request
from collections import defaultdict
from sqlalchemy import text

from app.services.cache import get_cache

logger = logging.getLogger(__name__)

router = APIRouter()

# ============ 告警配置 ============

class AlertConfig:
    """告警配置"""
    
    def __init__(self):
        # 错误率告警阈值 (百分比)
        self.error_rate_threshold: float = 10.0  # 10% 错误率告警
        # 响应时间告警阈值 (毫秒)
        self.response_time_threshold: float = 2000.0  # 2秒告警
        # 缓存命中率告警阈值 (百分比)
        self.cache_hit_rate_threshold: float = 50.0  # 50% 缓存命中率告警
        # API调用失败计数阈值
        self.error_count_threshold: int = 50  # 50次错误告警
    
    def to_dict(self) -> Dict:
        return {
            "error_rate_threshold": self.error_rate_threshold,
            "response_time_threshold": self.response_time_threshold,
            "cache_hit_rate_threshold": self.cache_hit_rate_threshold,
            "error_count_threshold": self.error_count_threshold,
        }


# 全局告警配置
_alert_config = AlertConfig()


def get_alert_config() -> AlertConfig:
    return _alert_config


class Alert:
    """告警项"""
    
    def __init__(self, level: str, message: str, metric: str, value: float, threshold: float):
        self.level = level  # critical, warning, info
        self.message = message
        self.metric = metric
        self.value = value
        self.threshold = threshold
        self.timestamp = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        return {
            "level": self.level,
            "message": self.message,
            "metric": self.metric,
            "value": self.value,
            "threshold": self.threshold,
            "timestamp": self.timestamp,
        }


# ============ 指标存储 ============

class MetricsCollector:
    """指标收集器"""
    
    # 响应时间保留时间（秒）- 5分钟
    RESPONSE_TIME_TTL = 300
    # 每个端点最大记录数
    MAX_RESPONSE_TIME_RECORDS = 1000
    
    def __init__(self):
        self._api_calls: Dict[str, int] = defaultdict(int)
        self._api_errors: Dict[str, int] = defaultdict(int)
        self._response_times: Dict[str, list] = defaultdict(list)
        self._response_times_timestamps: Dict[str, list] = defaultdict(list)  # 记录时间戳
        self._status_codes: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self._start_time = time.time()
        self._last_cleanup = time.time()
    
    def record_api_call(self, endpoint: str, status_code: int = 200):
        """记录 API 调用"""
        self._api_calls[endpoint] += 1
        self._status_codes[endpoint][status_code] += 1
        
        # 记录错误
        if status_code >= 400:
            self._api_errors[endpoint] += 1
    
    def _cleanup_old_records(self):
        """清理过期的响应时间记录"""
        current_time = time.time()
        
        # 每60秒执行一次清理
        if current_time - self._last_cleanup < 60:
            return
        
        self._last_cleanup = current_time
        
        for endpoint in list(self._response_times.keys()):
            times = self._response_times[endpoint]
            timestamps = self._response_times_timestamps[endpoint]
            
            if not times:
                continue
            
            # 按时间清理过期记录
            valid_indices = [
                i for i, ts in enumerate(timestamps)
                if current_time - ts < self.RESPONSE_TIME_TTL
            ]
            
            if len(valid_indices) < len(times):
                self._response_times[endpoint] = [times[i] for i in valid_indices]
                self._response_times_timestamps[endpoint] = [timestamps[i] for i in valid_indices]
            
            # 限制最大记录数
            if len(self._response_times[endpoint]) > self.MAX_RESPONSE_TIME_RECORDS:
                self._response_times[endpoint] = self._response_times[endpoint][-self.MAX_RESPONSE_TIME_RECORDS:]
                self._response_times_timestamps[endpoint] = self._response_times_timestamps[endpoint][-self.MAX_RESPONSE_TIME_RECORDS:]
    
    def record_response_time(self, endpoint: str, duration_ms: float):
        """记录响应时间"""
        # 定期清理旧记录
        self._cleanup_old_records()
        
        # 记录响应时间和时间戳
        current_time = time.time()
        times = self._response_times[endpoint]
        timestamps = self._response_times_timestamps[endpoint]
        
        times.append(duration_ms)
        timestamps.append(current_time)
        
        # 限制最大记录数
        if len(times) > self.MAX_RESPONSE_TIME_RECORDS:
            times.pop(0)
            timestamps.pop(0)
    
    def check_alerts(self) -> List[Alert]:
        """检查告警"""
        alerts = []
        config = get_alert_config()
        
        # 检查错误率
        total_calls = sum(self._api_calls.values())
        total_errors = sum(self._api_errors.values())
        
        if total_calls > 0:
            error_rate = (total_errors / total_calls) * 100
            
            if error_rate >= config.error_rate_threshold:
                alerts.append(Alert(
                    level="critical",
                    message=f"错误率过高: {error_rate:.2f}%",
                    metric="error_rate",
                    value=error_rate,
                    threshold=config.error_rate_threshold,
                ))
            elif error_rate >= config.error_rate_threshold * 0.7:
                alerts.append(Alert(
                    level="warning",
                    message=f"错误率偏高: {error_rate:.2f}%",
                    metric="error_rate",
                    value=error_rate,
                    threshold=config.error_rate_threshold,
                ))
        
        # 检查错误计数
        for endpoint, errors in self._api_errors.items():
            if errors >= config.error_count_threshold:
                alerts.append(Alert(
                    level="critical",
                    message=f"端点 {endpoint} 错误数过高: {errors}",
                    metric="error_count",
                    value=errors,
                    threshold=config.error_count_threshold,
                ))
        
        # 检查响应时间
        for endpoint, times in self._response_times.items():
            if times:
                avg_time = sum(times) / len(times)
                max_time = max(times)
                
                if max_time >= config.response_time_threshold:
                    alerts.append(Alert(
                        level="critical",
                        message=f"端点 {endpoint} 最大响应时间过高: {max_time:.2f}ms",
                        metric="response_time_max",
                        value=max_time,
                        threshold=config.response_time_threshold,
                    ))
                elif avg_time >= config.response_time_threshold * 0.7:
                    alerts.append(Alert(
                        level="warning",
                        message=f"端点 {endpoint} 平均响应时间偏高: {avg_time:.2f}ms",
                        metric="response_time_avg",
                        value=avg_time,
                        threshold=config.response_time_threshold,
                    ))
        
        # 检查缓存命中率
        cache_stats = get_cache().get_stats()
        if "hit_rate" in cache_stats:
            hit_rate = cache_stats["hit_rate"]
            if hit_rate < config.cache_hit_rate_threshold:
                alerts.append(Alert(
                    level="warning",
                    message=f"缓存命中率过低: {hit_rate:.2f}%",
                    metric="cache_hit_rate",
                    value=hit_rate,
                    threshold=config.cache_hit_rate_threshold,
                ))
        
        return alerts
    
    def get_metrics(self) -> Dict[str, Any]:
        """获取所有指标"""
        # 计算平均响应时间
        avg_times = {}
        max_times = {}
        p95_times = {}
        for endpoint, times in self._response_times.items():
            if times:
                sorted_times = sorted(times)
                avg_times[endpoint] = round(sum(times) / len(times), 2)
                max_times[endpoint] = round(max(times), 2)
                # P95
                p95_idx = int(len(sorted_times) * 0.95)
                p95_times[endpoint] = round(sorted_times[p95_idx], 2) if sorted_times else 0
        
        # 计算错误率
        error_rates = {}
        for endpoint, calls in self._api_calls.items():
            errors = self._api_errors.get(endpoint, 0)
            if calls > 0:
                error_rates[endpoint] = round((errors / calls) * 100, 2)
        
        # 缓存统计
        cache_stats = get_cache().get_stats()
        
        # 计算总错误率
        total_calls = sum(self._api_calls.values())
        total_errors = sum(self._api_errors.values())
        total_error_rate = round((total_errors / total_calls) * 100, 2) if total_calls > 0 else 0
        
        return {
            "api_calls": dict(self._api_calls),
            "api_errors": dict(self._api_errors),
            "error_rates": error_rates,
            "total_api_calls": total_calls,
            "total_errors": total_errors,
            "total_error_rate": total_error_rate,
            "response_times_ms_avg": avg_times,
            "response_times_ms_max": max_times,
            "response_times_ms_p95": p95_times,
            "status_codes": {k: dict(v) for k, v in self._status_codes.items()},
            "cache_stats": cache_stats,
            "alerts": [a.to_dict() for a in self.check_alerts()],
            "alert_config": get_alert_config().to_dict(),
            "uptime_seconds": int(time.time() - self._start_time),
            "timestamp": datetime.now().isoformat(),
        }
    
    def reset(self):
        """重置指标"""
        self._api_calls.clear()
        self._api_errors.clear()
        self._response_times.clear()
        self._status_codes.clear()
        self._start_time = time.time()


# 全局指标收集器
_metrics = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """获取指标收集器实例"""
    return _metrics


# ============ 中间件 ============

async def metrics_middleware(request: Request, call_next):
    """指标收集中间件"""
    start_time = time.time()
    
    # 记录 API 调用
    endpoint = request.url.path
    
    # 处理请求
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as e:
        status_code = 500
        raise e
    
    # 记录响应时间
    duration_ms = (time.time() - start_time) * 1000
    _metrics.record_response_time(endpoint, duration_ms)
    _metrics.record_api_call(endpoint, status_code)
    
    return response


# ============ 端点 ============

@router.get("/health")
async def health_check():
    """
    健康检查端点
    
    返回服务健康状态
    """
    # 检查各项服务健康状态
    health_status = {
        "status": "healthy",
        "checks": {}
    }
    
    # 1. 检查缓存服务
    try:
        cache = get_cache()
        cache_stats = cache.get_stats()
        health_status["checks"]["cache"] = {
            "status": "healthy" if cache_stats.get("connected", True) else "unhealthy",
            "backend": cache_stats.get("backend", "memory"),
            "connected": cache_stats.get("connected", True)
        }
        if cache_stats.get("connected") == False:
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["checks"]["cache"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "unhealthy"
    
    # 2. 检查 Redis 连接（如果使用 Redis）
    if health_status["checks"]["cache"].get("backend") == "redis":
        try:
            from app.core.redis_manager import get_redis
            redis_client = await get_redis()
            await redis_client.ping()
            health_status["checks"]["redis"] = {"status": "healthy"}
        except Exception as e:
            health_status["checks"]["redis"] = {
                "status": "unhealthy",
                "error": str(e)
            }
            health_status["status"] = "unhealthy"
    
    # 3. 检查数据库
    try:
        from app.core.database import engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        health_status["checks"]["database"] = {"status": "healthy"}
    except Exception as e:
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "unhealthy"
    
    # 检查告警
    alerts = _metrics.check_alerts()
    has_critical = any(a.level == "critical" for a in alerts)
    
    if has_critical:
        health_status["status"] = "unhealthy"
    
    health_status["alerts_count"] = len(alerts)
    health_status["timestamp"] = datetime.now().isoformat()
    health_status["service"] = "cs2-trade-platform"
    
    return health_status


@router.get("/metrics")
async def get_metrics():
    """
    指标端点
    
    返回:
    - API 调用次数
    - API 错误数
    - 错误率
    - 缓存命中率
    - 平均/最大/P95响应时间
    - 当前告警列表
    - 告警配置
    """
    return _metrics.get_metrics()


@router.get("/alerts")
async def get_alerts():
    """
    告警端点
    
    返回当前告警列表
    """
    return {
        "alerts": [a.to_dict() for a in _metrics.check_alerts()],
        "alert_config": get_alert_config().to_dict(),
        "timestamp": datetime.now().isoformat(),
    }


@router.post("/alerts/config")
async def update_alert_config(
    error_rate_threshold: Optional[float] = None,
    response_time_threshold: Optional[float] = None,
    cache_hit_rate_threshold: Optional[float] = None,
    error_count_threshold: Optional[int] = None,
):
    """
    更新告警配置
    
    参数:
    - error_rate_threshold: 错误率告警阈值 (百分比)
    - response_time_threshold: 响应时间告警阈值 (毫秒)
    - cache_hit_rate_threshold: 缓存命中率告警阈值 (百分比)
    - error_count_threshold: 错误计数告警阈值
    """
    config = get_alert_config()
    
    if error_rate_threshold is not None:
        config.error_rate_threshold = error_rate_threshold
    if response_time_threshold is not None:
        config.response_time_threshold = response_time_threshold
    if cache_hit_rate_threshold is not None:
        config.cache_hit_rate_threshold = cache_hit_rate_threshold
    if error_count_threshold is not None:
        config.error_count_threshold = error_count_threshold
    
    return {
        "message": "告警配置已更新",
        "alert_config": config.to_dict(),
    }


@router.post("/metrics/reset")
async def reset_metrics():
    """重置指标"""
    _metrics.reset()
    return {"message": "指标已重置"}
