# -*- coding: utf-8 -*-
"""
批量验证器测试
"""
import pytest
from unittest.mock import MagicMock
from pydantic import BaseModel, Field
from fastapi import HTTPException

from app.validators.batch_validator import BatchValidator


# 测试用的 Pydantic 模型
class ValidTestItem(BaseModel):
    """测试用的物品模型"""
    item_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1)
    price: float = Field(..., gt=0)


class ValidTestOrder(BaseModel):
    """测试用的订单模型"""
    order_id: str = Field(..., min_length=1)
    user_id: int = Field(..., gt=0)
    amount: float = Field(..., ge=0)


class TestBatchValidator:
    """批量验证器测试"""
    
    def test_validate_within_limit(self):
        """测试在限制范围内的批量数据"""
        validator = BatchValidator(ValidTestItem, max_size=10, min_size=1)
        
        items = [
            {"item_id": 1, "name": "Item 1", "price": 100.0},
            {"item_id": 2, "name": "Item 2", "price": 200.0},
            {"item_id": 3, "name": "Item 3", "price": 300.0},
        ]
        
        # 使用同步版本进行测试
        validated = validator.validate_sync(items)
        
        assert len(validated) == 3
        assert isinstance(validated[0], ValidTestItem)
        assert validated[0].item_id == 1
        assert validated[0].name == "Item 1"
    
    def test_validate_empty_list(self):
        """测试空列表 - 应抛出异常"""
        validator = BatchValidator(ValidTestItem, max_size=10, min_size=1)
        
        with pytest.raises(HTTPException) as exc_info:
            validator.validate_sync([])
        
        assert exc_info.value.status_code == 400
        assert "不能为空" in exc_info.value.detail
    
    def test_validate_exceeds_max_size(self):
        """测试超过最大批量大小"""
        validator = BatchValidator(ValidTestItem, max_size=5, min_size=1)
        
        items = [
            {"item_id": i, "name": f"Item {i}", "price": 100.0}
            for i in range(1, 8)  # 7项，超过5的限制
        ]
        
        with pytest.raises(HTTPException) as exc_info:
            validator.validate_sync(items)
        
        assert exc_info.value.status_code == 400
        assert "超过限制" in exc_info.value.detail
        assert "最大5条" in exc_info.value.detail
    
    def test_validate_invalid_item(self):
        """测试包含无效数据的批量"""
        validator = BatchValidator(ValidTestItem, max_size=10, min_size=1)
        
        items = [
            {"item_id": 1, "name": "Item 1", "price": 100.0},
            {"item_id": -1, "name": "Invalid", "price": 100.0},  # 无效: item_id <= 0
            {"item_id": 3, "name": "Item 3", "price": 100.0},
        ]
        
        with pytest.raises(HTTPException) as exc_info:
            validator.validate_sync(items)
        
        assert exc_info.value.status_code == 400
        assert "验证失败" in exc_info.value.detail
        assert "第2项" in exc_info.value.detail
    
    def test_validate_multiple_errors(self):
        """测试多个错误项"""
        validator = BatchValidator(ValidTestItem, max_size=10, min_size=1)
        
        items = [
            {"item_id": -1, "name": "", "price": -10},  # 全错
            {"item_id": 0, "name": "Short", "price": 5},  # item_id=0 无效
            {"item_id": 3},  # 缺少必需字段 name
        ]
        
        with pytest.raises(HTTPException) as exc_info:
            validator.validate_sync(items)
        
        assert exc_info.value.status_code == 400
        # 应该能检测到多项错误
        assert "验证失败" in exc_info.value.detail
    
    def test_validate_not_list(self):
        """测试非列表输入"""
        validator = BatchValidator(ValidTestItem, max_size=10, min_size=1)
        
        with pytest.raises(HTTPException) as exc_info:
            validator.validate_sync({"item_id": 1, "name": "Test"})
        
        assert exc_info.value.status_code == 400
        assert "必须是列表类型" in exc_info.value.detail
    
    def test_validate_boundary_size(self):
        """测试边界大小"""
        # 测试刚好等于最大值
        validator = BatchValidator(ValidTestItem, max_size=3, min_size=1)
        
        items = [
            {"item_id": 1, "name": "Item 1", "price": 100.0},
            {"item_id": 2, "name": "Item 2", "price": 200.0},
            {"item_id": 3, "name": "Item 3", "price": 300.0},
        ]
        
        validated = validator.validate_sync(items)
        assert len(validated) == 3
    
    def test_validate_with_dict_input(self):
        """测试使用字典作为输入"""
        validator = BatchValidator(ValidTestItem, max_size=10, min_size=1)
        
        items_dict = {
            "items": [
                {"item_id": 1, "name": "Item 1", "price": 100.0},
            ]
        }
        
        # 直接传递字典列表应该工作
        validated = validator.validate_sync([items_dict["items"][0]])
        assert len(validated) == 1
    
    def test_validate_pydantic_model_input(self):
        """测试直接传入 Pydantic 模型"""
        validator = BatchValidator(ValidTestItem, max_size=10, min_size=1)
        
        # 创建已验证的模型
        item = ValidTestItem(item_id=1, name="Item 1", price=100.0)
        
        # 应该能直接通过
        validated = validator.validate_sync([item])
        assert len(validated) == 1
        assert validated[0].item_id == 1


class TestBatchValidatorEdgeCases:
    """边界情况测试"""
    
    def test_validate_single_item(self):
        """测试单项目批量"""
        validator = BatchValidator(ValidTestItem, max_size=10, min_size=1)
        
        items = [{"item_id": 1, "name": "Single", "price": 100.0}]
        
        validated = validator.validate_sync(items)
        assert len(validated) == 1
    
    def test_validate_custom_min_size(self):
        """测试自定义最小大小"""
        validator = BatchValidator(ValidTestItem, max_size=10, min_size=2)
        
        items = [{"item_id": 1, "name": "Item 1", "price": 100.0}]
        
        with pytest.raises(HTTPException) as exc_info:
            validator.validate_sync(items)
        
        assert exc_info.value.status_code == 400
    
    def test_validate_preserves_order(self):
        """测试保持原始顺序"""
        validator = BatchValidator(ValidTestItem, max_size=10, min_size=1)
        
        items = [
            {"item_id": 3, "name": "Third", "price": 300.0},
            {"item_id": 1, "name": "First", "price": 100.0},
            {"item_id": 2, "name": "Second", "price": 200.0},
        ]
        
        validated = validator.validate_sync(items)
        
        # 顺序应该保持
        assert validated[0].item_id == 3
        assert validated[1].item_id == 1
        assert validated[2].item_id == 2


class TestBatchValidatorIntegration:
    """集成测试"""
    
    def test_with_order_model(self):
        """测试订单模型"""
        validator = BatchValidator(ValidTestOrder, max_size=50, min_size=1)
        
        orders = [
            {"order_id": "ORD-001", "user_id": 1, "amount": 100.0},
            {"order_id": "ORD-002", "user_id": 1, "amount": 200.0},
            {"order_id": "ORD-003", "user_id": 2, "amount": 300.0},
        ]
        
        validated = validator.validate_sync(orders)
        
        assert len(validated) == 3
        assert validated[0].order_id == "ORD-001"
        assert validated[2].user_id == 2
