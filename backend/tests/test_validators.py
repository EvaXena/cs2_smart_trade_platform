# -*- coding: utf-8 -*-
"""
增强的验证器测试
"""
import pytest
from app.utils.validators import (
    validate_price,
    validate_quantity,
    validate_item_id,
    validate_user_id,
    validate_min_profit,
    validate_limit,
    validate_username,
    validate_email,
    validate_password,
    validate_string_length,
    validate_order_id,
    validate_pagination,
    validate_order_data,
    validate_user_registration,
    MIN_PRICE,
    MAX_PRICE,
    MIN_QUANTITY,
    MAX_QUANTITY,
    MIN_USERNAME_LENGTH,
    MAX_USERNAME_LENGTH,
    MIN_PASSWORD_LENGTH,
)


class TestValidatePrice:
    """价格验证测试"""
    
    def test_valid_price_float(self):
        """测试有效浮点价格"""
        assert validate_price(100.0) == 100.0
        assert validate_price(0.01) == 0.01
        assert validate_price(99999.99) == 99999.99
    
    def test_valid_price_int(self):
        """测试有效整数价格"""
        assert validate_price(100) == 100.0
        assert validate_price(1) == 1.0
    
    def test_valid_price_string(self):
        """测试字符串价格"""
        assert validate_price("100.5") == 100.5
        assert validate_price("0.01") == 0.01
    
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
            validate_price("invalid")
        assert "必须是数字类型" in str(exc_info.value)
    
    def test_price_negative(self):
        """测试负数价格"""
        with pytest.raises(ValueError):
            validate_price(-10.0)
    
    def test_price_boundary(self):
        """测试边界值"""
        assert validate_price(MIN_PRICE) == MIN_PRICE
        assert validate_price(MAX_PRICE) == MAX_PRICE


class TestValidateQuantity:
    """数量验证测试"""
    
    def test_valid_quantity(self):
        """测试有效数量"""
        assert validate_quantity(1) == 1
        assert validate_quantity(100) == 100
        assert validate_quantity(1000) == 1000
    
    def test_quantity_string(self):
        """测试字符串数量"""
        assert validate_quantity("10") == 10
    
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
    
    def test_quantity_negative(self):
        """测试负数数量"""
        with pytest.raises(ValueError):
            validate_quantity(-1)


class TestValidateItemId:
    """物品ID验证测试"""
    
    def test_valid_item_id(self):
        """测试有效物品ID"""
        assert validate_item_id(1) == 1
        assert validate_item_id(100) == 100
    
    def test_item_id_string(self):
        """测试字符串物品ID"""
        assert validate_item_id("123") == 123
    
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
            validate_item_id("abc")


class TestValidateUserId:
    """用户ID验证测试"""
    
    def test_valid_user_id(self):
        """测试有效用户ID"""
        assert validate_user_id(1) == 1
        assert validate_user_id(100) == 100
    
    def test_invalid_user_id_zero(self):
        """测试ID为0"""
        with pytest.raises(ValueError):
            validate_user_id(0)
    
    def test_invalid_user_id_negative(self):
        """测试负数ID"""
        with pytest.raises(ValueError):
            validate_user_id(-1)


class TestValidateMinProfit:
    """最小利润验证测试"""
    
    def test_valid_min_profit(self):
        """测试有效最小利润"""
        assert validate_min_profit(0.0) == 0.0
        assert validate_min_profit(10.0) == 10.0
    
    def test_valid_min_profit_string(self):
        """测试字符串最小利润"""
        assert validate_min_profit("5.5") == 5.5
    
    def test_invalid_min_profit_negative(self):
        """测试负数最小利润"""
        with pytest.raises(ValueError) as exc_info:
            validate_min_profit(-1.0)
        assert "不能为负数" in str(exc_info.value)


class TestValidateLimit:
    """返回数量限制验证测试"""
    
    def test_valid_limit(self):
        """测试有效限制"""
        assert validate_limit(1) == 1
        assert validate_limit(100) == 100
        assert validate_limit(1000) == 1000
    
    def test_limit_string(self):
        """测试字符串限制"""
        assert validate_limit("50") == 50
    
    def test_limit_too_high(self):
        """测试限制过高"""
        with pytest.raises(ValueError) as exc_info:
            validate_limit(2000)
        assert "不能超过 1000" in str(exc_info.value)
    
    def test_limit_zero(self):
        """测试限制为0"""
        with pytest.raises(ValueError):
            validate_limit(0)
    
    def test_limit_negative(self):
        """测试限制为负数"""
        with pytest.raises(ValueError):
            validate_limit(-1)


class TestValidateUsername:
    """用户名验证测试"""
    
    def test_valid_username(self):
        """测试有效用户名"""
        assert validate_username("user123") == "user123"
        assert validate_username("test_user") == "test_user"
    
    def test_username_with_spaces(self):
        """测试带空格的用户名（应该被去除）"""
        assert validate_username("  user123  ") == "user123"
    
    def test_username_too_short(self):
        """测试用户名过短"""
        with pytest.raises(ValueError) as exc_info:
            validate_username("ab")
        assert "不能少于" in str(exc_info.value)
    
    def test_username_too_long(self):
        """测试用户名过长"""
        long_name = "a" * (MAX_USERNAME_LENGTH + 1)
        with pytest.raises(ValueError):
            validate_username(long_name)
    
    def test_username_invalid_chars(self):
        """测试用户名包含非法字符"""
        with pytest.raises(ValueError) as exc_info:
            validate_username("user@123")
        assert "只能包含" in str(exc_info.value)
    
    def test_username_empty(self):
        """测试空用户名"""
        with pytest.raises(ValueError):
            validate_username("")


class TestValidateEmail:
    """邮箱验证测试"""
    
    def test_valid_email(self):
        """测试有效邮箱"""
        assert validate_email("test@example.com") == "test@example.com"
        assert validate_email("USER@EXAMPLE.COM") == "user@example.com"
    
    def test_email_strip_spaces(self):
        """测试邮箱去除空格"""
        assert validate_email("  test@example.com  ") == "test@example.com"
    
    def test_email_invalid_format(self):
        """测试无效邮箱格式"""
        with pytest.raises(ValueError) as exc_info:
            validate_email("invalid-email")
        assert "格式不正确" in str(exc_info.value)
    
    def test_email_empty(self):
        """测试空邮箱"""
        with pytest.raises(ValueError):
            validate_email("")


class TestValidatePassword:
    """密码验证测试"""
    
    def test_valid_password(self):
        """测试有效密码"""
        assert validate_password("Password123") == "Password123"
        assert validate_password("test1234") == "test1234"
    
    def test_password_too_short(self):
        """测试密码过短"""
        with pytest.raises(ValueError) as exc_info:
            validate_password("Pass1")
        assert "不能少于" in str(exc_info.value)
    
    def test_password_weak(self):
        """测试弱密码"""
        with pytest.raises(ValueError) as exc_info:
            validate_password("password")  # 只有小写字母
        assert "必须包含" in str(exc_info.value)
    
    def test_password_empty(self):
        """测试空密码"""
        with pytest.raises(ValueError):
            validate_password("")


class TestValidateStringLength:
    """字符串长度验证测试"""
    
    def test_valid_length(self):
        """测试有效长度"""
        result = validate_string_length("hello", "string")
        assert result == "hello"
    
    def test_strip_spaces(self):
        """测试去除空格"""
        result = validate_string_length("  hello  ", "string")
        assert result == "hello"
    
    def test_too_long(self):
        """测试过长字符串"""
        with pytest.raises(ValueError):
            validate_string_length("a" * 1001, "string", max_length=1000)


class TestValidateOrderId:
    """订单ID验证测试"""
    
    def test_valid_order_id(self):
        """测试有效订单ID"""
        assert validate_order_id("ORD-12345678") == "ORD-12345678"
        assert validate_order_id("ord-abcdef12") == "ORD-ABCDEF12"
    
    def test_order_id_lowercase(self):
        """测试小写订单ID"""
        assert validate_order_id("ord-12345678") == "ORD-12345678"
    
    def test_order_id_invalid_format(self):
        """测试无效订单ID格式"""
        with pytest.raises(ValueError):
            validate_order_id("INVALID")
    
    def test_order_id_empty(self):
        """测试空订单ID"""
        with pytest.raises(ValueError):
            validate_order_id("")


class TestValidatePagination:
    """分页验证测试"""
    
    def test_valid_pagination(self):
        """测试有效分页"""
        page, page_size = validate_pagination(1, 20)
        assert page == 1
        assert page_size == 20
    
    def test_string_pagination(self):
        """测试字符串分页"""
        page, page_size = validate_pagination("2", "50")
        assert page == 2
        assert page_size == 50
    
    def test_invalid_page(self):
        """测试无效页码"""
        with pytest.raises(ValueError):
            validate_pagination(0, 20)
    
    def test_invalid_page_size(self):
        """测试无效每页数量"""
        with pytest.raises(ValueError):
            validate_pagination(1, 0)


class TestValidateOrderData:
    """订单数据验证测试"""
    
    def test_valid_order_data(self):
        """测试有效订单数据"""
        data = {
            "item_id": 123,
            "price": 100.0,
            "quantity": 1,
            "side": "buy"
        }
        
        result = validate_order_data(data)
        
        assert result["item_id"] == 123
        assert result["price"] == 100.0
        assert result["quantity"] == 1
        assert result["side"] == "buy"
    
    def test_invalid_side(self):
        """测试无效订单方向"""
        data = {"side": "invalid"}
        
        with pytest.raises(ValueError):
            validate_order_data(data)


class TestValidateUserRegistration:
    """用户注册验证测试"""
    
    def test_valid_registration(self):
        """测试有效注册数据"""
        data = {
            "username": "testuser",
            "email": "test@example.com",
            "password": "Password123"
        }
        
        result = validate_user_registration(data)
        
        assert result["username"] == "testuser"
        assert result["email"] == "test@example.com"
    
    def test_partial_registration(self):
        """测试部分注册数据"""
        data = {
            "username": "testuser",
            "password": "Password123"
        }
        
        result = validate_user_registration(data)
        
        assert result["username"] == "testuser"
        assert "email" not in result
