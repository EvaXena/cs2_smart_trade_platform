# -*- coding: utf-8 -*-
"""
工具函数
"""
from typing import Any, Dict, Optional, Union
import json
from datetime import datetime, date
from decimal import Decimal


def format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """格式化日期时间"""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_date(d: Optional[date]) -> Optional[str]:
    """格式化日期"""
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


def parse_json_safe(json_str: Optional[str]) -> Optional[Dict[str, Any]]:
    """安全解析 JSON"""
    if not json_str:
        return None
    try:
        return json.loads(json_str)
    except json.JSONError:
        return None


def _json_serializer(obj: Any) -> Any:
    """
    JSON 序列化处理器，处理特殊类型
    
    支持的类型:
    - datetime/date: 转换为 ISO 格式字符串
    - Decimal: 转换为 float
    - set/frozenset: 转换为 list
    - bytes: 转换为 base64 字符串
    - 其他对象: 尝试调用 to_dict() 或 __dict__
    """
    # 处理 datetime
    if isinstance(obj, datetime):
        return obj.isoformat()
    
    # 处理 date
    if isinstance(obj, date):
        return obj.isoformat()
    
    # 处理 Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    
    # 处理 set/frozenset
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    
    # 处理 bytes
    if isinstance(obj, bytes):
        import base64
        return base64.b64encode(obj).decode('ascii')
    
    # 尝试调用 to_dict 方法
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    
    # 尝试转换为字典
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    
    # 无法处理，抛出 TypeError
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def to_json_safe(obj: Any) -> Optional[str]:
    """
    安全转换为 JSON 字符串
    
    支持处理:
    - None: 返回 None
    - datetime/date: 转换为 ISO 格式字符串
    - Decimal: 转换为 float
    - set/frozenset: 转换为 list
    - bytes: 转换为 base64 字符串
    - 自定义对象: 尝试调用 to_dict() 或 __dict__
    
    Args:
        obj: 要序列化的对象
        
    Returns:
        JSON 字符串，如果序列化失败返回 None
    """
    if obj is None:
        return None
    try:
        return json.dumps(obj, ensure_ascii=False, default=_json_serializer)
    except (TypeError, ValueError) as e:
        import logging
        logging.getLogger(__name__).warning(f"JSON serialization failed: {e}")
        return None


def truncate_string(s: str, max_length: int = 100) -> str:
    """截断字符串"""
    if len(s) <= max_length:
        return s
    return s[:max_length - 3] + "..."
