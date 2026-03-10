# -*- coding: utf-8 -*-
"""
输入验证测试
"""
import pytest
from app.services.trading_service import (
    validate_price,
    validate_quantity,
    validate_item_id,
    validate_user_id,
    validate_min_profit,
    validate_limit,
    MIN_PRICE,
    MAX_PRICE,
    MIN_QUANTITY,
    MAX_QUANTITY,
)


class TestValidatePrice:
    """价格验证测试"""
    
    def test_valid_price(self):
        """测试有效价格"""
        validate_price(100.0)
        validate_price(0.01)
        validate_price(100000.0)
    
    def test_price_too_low(self):
        """测试价格过低"""
        with pytest.raises(ValueError) as exc_info:
            validate_price(0.001)
        assert "不能低于" in str(exc_info.value)
    
    def test_price_too_high(self):
        """测试价格过高"""
        with pytest.raises(ValueError) as exc_info:
            validate_price(200000.0)
        assert "不能超过" in str(exc_info.value)
    
    def test_price_invalid_type(self):
        """测试无效类型"""
        with pytest.raises(ValueError) as exc_info:
            validate_price("100")
        assert "必须是数字类型" in str(exc_info.value)
    
    def test_price_negative(self):
        """测试负数价格"""
        with pytest.raises(ValueError):
            validate_price(-10.0)


class TestValidateQuantity:
    """数量验证测试"""
    
    def test_valid_quantity(self):
        """测试有效数量"""
        validate_quantity(1)
        validate_quantity(100)
        validate_quantity(1000)
    
    def test_quantity_too_low(self):
        """测试数量过低"""
        with pytest.raises(ValueError) as exc_info:
            validate_quantity(0)
        assert "不能低于" in str(exc_info.value)
    
    def test_quantity_too_high(self):
        """测试数量过高"""
        with pytest.raises(ValueError) as exc_info:
            validate_quantity(2000)
        assert "不能超过" in str(exc_info.value)
    
    def test_quantity_invalid_type(self):
        """测试无效类型"""
        with pytest.raises(ValueError) as exc_info:
            validate_quantity(1.5)
        assert "必须是整数类型" in str(exc_info.value)


class TestValidateItemId:
    """物品ID验证测试"""
    
    def test_valid_item_id(self):
        """测试有效物品ID"""
        validate_item_id(1)
        validate_item_id(100)
    
    def test_invalid_item_id_zero(self):
        """测试ID为0"""
        with pytest.raises(ValueError):
            validate_item_id(0)
    
    def test_invalid_item_id_negative(self):
        """测试负数ID"""
        with pytest.raises(ValueError):
            validate_item_id(-1)
    
    def test_invalid_item_id_type(self):
        """测试无效类型"""
        with pytest.raises(ValueError):
            validate_item_id("1")


class TestValidateUserId:
    """用户ID验证测试"""
    
    def test_valid_user_id(self):
        """测试有效用户ID"""
        validate_user_id(1)
        validate_user_id(100)
    
    def test_invalid_user_id(self):
        """测试无效用户ID"""
        with pytest.raises(ValueError):
            validate_user_id(0)
        with pytest.raises(ValueError):
            validate_user_id(-1)


class TestValidateMinProfit:
    """最小利润验证测试"""
    
    def test_valid_min_profit(self):
        """测试有效最小利润"""
        validate_min_profit(0.0)
        validate_min_profit(10.0)
    
    def test_invalid_min_profit(self):
        """测试无效最小利润"""
        with pytest.raises(ValueError) as exc_info:
            validate_min_profit(-1.0)
        assert "不能为负数" in str(exc_info.value)


class TestValidateLimit:
    """返回数量限制验证测试"""
    
    def test_valid_limit(self):
        """测试有效限制"""
        validate_limit(1)
        validate_limit(100)
        validate_limit(1000)
    
    def test_limit_too_high(self):
        """测试限制过高"""
        with pytest.raises(ValueError) as exc_info:
            validate_limit(2000)
        assert "不能超过 1000" in str(exc_info.value)
    
    def test_limit_invalid(self):
        """测试无效限制"""
        with pytest.raises(ValueError):
            validate_limit(0)
        with pytest.raises(ValueError):
            validate_limit(-1)
        with pytest.raises(ValueError):
            validate_limit("10")
