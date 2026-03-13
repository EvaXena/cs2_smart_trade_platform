# -*- coding: utf-8 -*-
"""
批量验证器模块

提供统一的批量数据验证功能，支持：
- 批量大小限制
- 逐项数据验证
- 泛型类型支持
"""
from __future__ import annotations

import logging
from typing import TypeVar, Generic, List, Type, Any, Dict
from pydantic import BaseModel, ValidationError
from fastapi import HTTPException

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class BatchValidationError(Exception):
    """批量验证错误"""
    
    def __init__(self, message: str, errors: List[Dict[str, Any]] = None):
        self.message = message
        self.errors = errors or []
        super().__init__(self.message)


class BatchValidator(Generic[T]):
    """
    批量验证器
    
    用于验证批量提交的请求数据，确保：
    - 批量大小不超过限制
    - 批量数据不为空
    - 每个数据项都通过 Pydantic 模型验证
    
    Usage:
        validator = BatchValidator(OrderCreate, max_size=100)
        validated_items = await validator.validate(request_items)
    
    Attributes:
        model: Pydantic 模型类
        max_size: 最大批量大小
    """
    
    def __init__(
        self,
        model: Type[T],
        max_size: int = 100,
        min_size: int = 1
    ):
        """
        初始化批量验证器
        
        Args:
            model: Pydantic 模型类，用于验证每个数据项
            max_size: 最大批量大小，默认100
            min_size: 最小批量大小，默认1
        """
        self.model = model
        self.max_size = max_size
        self.min_size = min_size
    
    async def validate(self, items: List[Any]) -> List[T]:
        """
        验证批量数据
        
        Args:
            items: 待验证的数据项列表
        
        Returns:
            验证通过的数据项列表 (List[T])
        
        Raises:
            HTTPException: 验证失败时抛出 400 错误
        """
        # 1. 检查是否为列表
        if not isinstance(items, list):
            raise HTTPException(
                status_code=400,
                detail="请求数据必须是列表类型"
            )
        
        # 2. 批量大小校验
        item_count = len(items)
        
        if item_count > self.max_size:
            logger.warning(
                f"批量大小超限: 最大{self.max_size}条，当前{item_count}条"
            )
            raise HTTPException(
                status_code=400,
                detail=f"批量大小超过限制: 最大{self.max_size}条，当前{item_count}条"
            )
        
        if item_count < self.min_size:
            logger.warning(f"批量大小不足: 最小{self.min_size}条，当前{item_count}条")
            raise HTTPException(
                status_code=400,
                detail=f"批量数据不能为空"
            )
        
        # 3. 逐项验证
        validated_items = []
        errors = []
        
        for idx, item in enumerate(items):
            try:
                if isinstance(item, dict):
                    validated_item = self.model(**item)
                elif isinstance(item, self.model):
                    validated_item = item
                else:
                    raise ValueError(f"第{idx + 1}项数据类型错误")
                
                validated_items.append(validated_item)
            except ValidationError as e:
                error_detail = e.errors()
                errors.append({
                    "index": idx + 1,
                    "errors": error_detail
                })
            except Exception as e:
                errors.append({
                    "index": idx + 1,
                    "errors": [{"type": "value_error", "msg": str(e)}]
                })
        
        # 4. 如果有错误，返回详细信息
        if errors:
            error_messages = []
            for err in errors[:10]:  # 最多显示10个错误
                idx = err["index"]
                err_msgs = [e.get("msg", str(e)) for e in err["errors"]]
                error_messages.append(f"第{idx}项: {'; '.join(err_msgs)}")
            
            detail = f"批量数据验证失败，共{len(errors)}项错误: {'; '.join(error_messages)}"
            if len(errors) > 10:
                detail += f" ... (还有{len(errors) - 10}项错误)"
            
            logger.warning(f"批量验证失败: {detail}")
            raise HTTPException(
                status_code=400,
                detail=detail
            )
        
        return validated_items
    
    def validate_sync(self, items: List[Any]) -> List[T]:
        """
        同步版本的验证方法
        
        Args:
            items: 待验证的数据项列表
        
        Returns:
            验证通过的数据项列表 (List[T])
        
        Raises:
            HTTPException: 验证失败时抛出 400 错误
        """
        # 1. 检查是否为列表
        if not isinstance(items, list):
            raise HTTPException(
                status_code=400,
                detail="请求数据必须是列表类型"
            )
        
        # 2. 批量大小校验
        item_count = len(items)
        
        if item_count > self.max_size:
            raise HTTPException(
                status_code=400,
                detail=f"批量大小超过限制: 最大{self.max_size}条，当前{item_count}条"
            )
        
        if item_count < self.min_size:
            raise HTTPException(
                status_code=400,
                detail=f"批量数据不能为空"
            )
        
        # 3. 逐项验证
        validated_items = []
        errors = []
        
        for idx, item in enumerate(items):
            try:
                if isinstance(item, dict):
                    validated_item = self.model(**item)
                elif isinstance(item, self.model):
                    validated_item = item
                else:
                    raise ValueError(f"第{idx + 1}项数据类型错误")
                
                validated_items.append(validated_item)
            except ValidationError as e:
                errors.append({
                    "index": idx + 1,
                    "errors": e.errors()
                })
            except Exception as e:
                errors.append({
                    "index": idx + 1,
                    "errors": [{"type": "value_error", "msg": str(e)}]
                })
        
        # 4. 如果有错误，返回详细信息
        if errors:
            error_messages = []
            for err in errors[:10]:
                idx = err["index"]
                err_msgs = [e.get("msg", str(e)) for e in err["errors"]]
                error_messages.append(f"第{idx}项: {'; '.join(err_msgs)}")
            
            detail = f"批量数据验证失败: {'; '.join(error_messages)}"
            raise HTTPException(
                status_code=400,
                detail=detail
            )
        
        return validated_items


# ============ 预定义的批量验证器 ============

def create_batch_validator(
    model: Type[BaseModel],
    max_size: int = 100,
    min_size: int = 1
) -> BatchValidator:
    """
    创建批量验证器的工厂函数
    
    Args:
        model: Pydantic 模型类
        max_size: 最大批量大小
        min_size: 最小批量大小
    
    Returns:
        BatchValidator 实例
    """
    return BatchValidator(model=model, max_size=max_size, min_size=min_size)
