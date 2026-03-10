# -*- coding: utf-8 -*-
"""
输入验证器模块
"""
import re
from typing import Any, Optional, List, Dict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pydantic import Field, validator
from pydantic.types import conint, confloat


# ============ 基础验证常量 ============
MIN_PRICE = 0.01
MAX_PRICE = 100000.0
MIN_QUANTITY = 1
MAX_QUANTITY = 1000
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 50
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_STRING_LENGTH = 1000
MAX_EMAIL_LENGTH = 255


# ============ 验证函数 ============

def validate_price(price: Any) -> float:
    """
    验证价格
    
    Args:
        price: 价格值
    
    Returns:
        验证通过的价格（float）
    
    Raises:
        ValueError: 价格验证失败
    """
    # 类型检查
    if isinstance(price, str):
        try:
            price = float(price)
        except (ValueError, TypeError):
            raise ValueError(f"价格必须是数字类型，无法转换为浮点数: {price}")
    
    if not isinstance(price, (int, float, Decimal)):
        raise ValueError(f"价格必须是数字类型，当前类型: {type(price).__name__}")
    
    # 转换为浮点数
    price = float(price)
    
    # 范围检查
    if price < MIN_PRICE:
        raise ValueError(f"价格不能低于 {MIN_PRICE}")
    if price > MAX_PRICE:
        raise ValueError(f"价格不能超过 {MAX_PRICE}")
    
    return round(price, 2)


def validate_quantity(quantity: Any) -> int:
    """
    验证数量
    
    Args:
        quantity: 数量值
    
    Returns:
        验证通过的数量（int）
    
    Raises:
        ValueError: 数量验证失败
    """
    # 类型检查
    if isinstance(quantity, str):
        try:
            quantity = int(quantity)
        except (ValueError, TypeError):
            raise ValueError(f"数量必须是整数类型，无法转换为整数: {quantity}")
    
    if not isinstance(quantity, int):
        raise ValueError(f"数量必须是整数类型，当前类型: {type(quantity).__name__}")
    
    # 范围检查
    if quantity < MIN_QUANTITY:
        raise ValueError(f"数量不能低于 {MIN_QUANTITY}")
    if quantity > MAX_QUANTITY:
        raise ValueError(f"数量不能超过 {MAX_QUANTITY}")
    
    return quantity


def validate_item_id(item_id: Any) -> int:
    """
    验证物品ID
    
    Args:
        item_id: 物品ID
    
    Returns:
        验证通过的ID（int）
    
    Raises:
        ValueError: ID验证失败
    """
    if isinstance(item_id, str):
        try:
            item_id = int(item_id)
        except ValueError:
            raise ValueError(f"物品ID必须是整数类型: {item_id}")
    
    if not isinstance(item_id, int):
        raise ValueError(f"物品ID必须是整数类型，当前类型: {type(item_id).__name__}")
    
    if item_id <= 0:
        raise ValueError(f"物品ID必须大于0")
    
    return item_id


def validate_user_id(user_id: Any) -> int:
    """
    验证用户ID
    
    Args:
        user_id: 用户ID
    
    Returns:
        验证通过的ID（int）
    
    Raises:
        ValueError: ID验证失败
    """
    if isinstance(user_id, str):
        try:
            user_id = int(user_id)
        except ValueError:
            raise ValueError(f"用户ID必须是整数类型: {user_id}")
    
    if not isinstance(user_id, int):
        raise ValueError(f"用户ID必须是整数类型，当前类型: {type(user_id).__name__}")
    
    if user_id <= 0:
        raise ValueError(f"用户ID必须大于0")
    
    return user_id


def validate_min_profit(min_profit: Any) -> float:
    """
    验证最小利润
    
    Args:
        min_profit: 最小利润值
    
    Returns:
        验证通过的值（float）
    
    Raises:
        ValueError: 验证失败
    """
    if isinstance(min_profit, str):
        try:
            min_profit = float(min_profit)
        except ValueError:
            raise ValueError(f"最小利润必须是数字类型: {min_profit}")
    
    if not isinstance(min_profit, (int, float)):
        raise ValueError(f"最小利润必须是数字类型")
    
    if min_profit < 0:
        raise ValueError(f"最小利润不能为负数")
    
    return float(min_profit)


def validate_limit(limit: Any) -> int:
    """
    验证返回数量限制
    
    Args:
        limit: 限制值
    
    Returns:
        验证通过的限制值（int）
    
    Raises:
        ValueError: 验证失败
    """
    if isinstance(limit, str):
        try:
            limit = int(limit)
        except ValueError:
            raise ValueError(f"限制值必须是整数类型: {limit}")
    
    if not isinstance(limit, int):
        raise ValueError(f"限制值必须是整数类型，当前类型: {type(limit).__name__}")
    
    if limit < 1:
        raise ValueError(f"限制值必须大于0")
    if limit > 1000:
        raise ValueError(f"限制值不能超过 1000")
    
    return limit


def validate_username(username: str) -> str:
    """
    验证用户名
    
    Args:
        username: 用户名
    
    Returns:
        验证通过的用户名
    
    Raises:
        ValueError: 验证失败
    """
    if not username:
        raise ValueError("用户名不能为空")
    
    username = username.strip()
    
    if len(username) < MIN_USERNAME_LENGTH:
        raise ValueError(f"用户名长度不能少于{MIN_USERNAME_LENGTH}个字符")
    if len(username) > MAX_USERNAME_LENGTH:
        raise ValueError(f"用户名长度不能超过{MAX_USERNAME_LENGTH}个字符")
    
    # 用户名只能包含字母、数字、下划线
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        raise ValueError("用户名只能包含字母、数字和下划线")
    
    return username


def validate_email(email: str) -> str:
    """
    验证邮箱地址
    
    Args:
        email: 邮箱地址
    
    Returns:
        验证通过的邮箱地址
    
    Raises:
        ValueError: 验证失败
    """
    if not email:
        raise ValueError("邮箱不能为空")
    
    email = email.strip().lower()
    
    if len(email) > MAX_EMAIL_LENGTH:
        raise ValueError(f"邮箱长度不能超过{MAX_EMAIL_LENGTH}个字符")
    
    # 邮箱格式验证
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        raise ValueError("邮箱格式不正确")
    
    return email


def validate_password(password: str) -> str:
    """
    验证密码强度
    
    Args:
        password: 密码
    
    Returns:
        验证通过的密码
    
    Raises:
        ValueError: 验证失败
    """
    if not password:
        raise ValueError("密码不能为空")
    
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"密码长度不能少于{MIN_PASSWORD_LENGTH}个字符")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"密码长度不能超过{MAX_PASSWORD_LENGTH}个字符")
    
    # 检查密码复杂度
    has_upper = bool(re.search(r'[A-Z]', password))
    has_lower = bool(re.search(r'[a-z]', password))
    has_digit = bool(re.search(r'\d', password))
    has_special = bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', password))
    
    strength_score = sum([has_upper, has_lower, has_digit, has_special])
    
    if strength_score < 2:
        raise ValueError("密码必须包含字母和数字，建议包含大小写字母和特殊字符")
    
    return password


def validate_string_length(value: str, field_name: str, max_length: int = MAX_STRING_LENGTH) -> str:
    """
    验证字符串长度
    
    Args:
        value: 字符串值
        field_name: 字段名称
        max_length: 最大长度
    
    Returns:
        验证通过的字符串
    
    Raises:
        ValueError: 验证失败
    """
    if value is None:
        return value
    
    value = str(value).strip()
    
    if len(value) > max_length:
        raise ValueError(f"{field_name}长度不能超过{max_length}个字符")
    
    return value


def validate_order_id(order_id: str) -> str:
    """
    验证订单ID格式
    
    Args:
        order_id: 订单ID
    
    Returns:
        验证通过的订单ID
    
    Raises:
        ValueError: 验证失败
    """
    if not order_id:
        raise ValueError("订单ID不能为空")
    
    order_id = order_id.strip()
    
    # 订单ID格式: ORD-XXXXXXXXXXXX
    if not re.match(r'^ORD-[A-Z0-9]{8,20}$', order_id.upper()):
        raise ValueError("订单ID格式不正确")
    
    return order_id.upper()


def validate_pagination(page: Any, page_size: Any) -> tuple:
    """
    验证分页参数
    
    Args:
        page: 页码
        page_size: 每页数量
    
    Returns:
        (page, page_size) 元组
    
    Raises:
        ValueError: 验证失败
    """
    page = int(page) if isinstance(page, str) else page
    page_size = int(page_size) if isinstance(page_size, str) else page_size
    
    if page < 1:
        raise ValueError("页码必须大于0")
    
    if page_size < 1:
        raise ValueError("每页数量必须大于0")
    if page_size > 100:
        raise ValueError("每页数量不能超过100")
    
    return page, page_size


# ============ Pydantic 验证器 ============

class ValidatedModelMixin:
    """Pydantic 模型验证器混入类"""
    
    @validator('*', pre=True)
    def strip_strings(cls, v):
        """去除字符串首尾空格"""
        if isinstance(v, str):
            return v.strip()
        return v


# ============ 批量验证 ============

def validate_order_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    验证订单数据
    
    Args:
        data: 订单数据字典
    
    Returns:
        验证后的数据字典
    
    Raises:
        ValueError: 验证失败
    """
    validated = {}
    
    # 验证 item_id
    if 'item_id' in data:
        validated['item_id'] = validate_item_id(data['item_id'])
    
    # 验证 price
    if 'price' in data:
        validated['price'] = validate_price(data['price'])
    
    # 验证 quantity
    if 'quantity' in data:
        validated['quantity'] = validate_quantity(data['quantity'])
    
    # 验证 side
    if 'side' in data:
        side = str(data['side']).lower()
        if side not in ['buy', 'sell']:
            raise ValueError("订单方向必须是 'buy' 或 'sell'")
        validated['side'] = side
    
    return validated


def validate_user_registration(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    验证用户注册数据
    
    Args:
        data: 用户注册数据
    
    Returns:
        验证后的数据
    
    Raises:
        ValueError: 验证失败
    """
    validated = {}
    
    if 'username' in data:
        validated['username'] = validate_username(data['username'])
    
    if 'email' in data:
        validated['email'] = validate_email(data['email'])
    
    if 'password' in data:
        validated['password'] = validate_password(data['password'])
    
    return validated
