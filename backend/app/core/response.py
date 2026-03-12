# -*- coding: utf-8 -*-
"""
统一服务响应格式
"""
from typing import Any, Dict, Generic, Optional, TypeVar
from dataclasses import dataclass, field
from enum import Enum


class ResponseStatus(str, Enum):
    """响应状态枚举"""
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"


T = TypeVar('T')


@dataclass
class ServiceResponse(Generic[T]):
    """
    统一服务响应格式
    
    所有服务层方法都应返回此格式，确保响应格式一致性
    """
    # 响应状态
    status: ResponseStatus = ResponseStatus.SUCCESS
    
    # 响应数据
    data: Optional[T] = None
    
    # 错误消息
    message: str = ""
    
    # 错误码
    code: str = "0"
    
    # 额外元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def success(self) -> bool:
        """是否成功"""
        return self.status == ResponseStatus.SUCCESS
    
    @property
    def error(self) -> bool:
        """是否失败"""
        return self.status == ResponseStatus.ERROR
    
    def __getitem__(self, key: str):
        """支持字典式访问"""
        if key == "success":
            return self.success
        elif key == "error":
            return self.error
        elif key == "status":
            return self.status.value
        elif key == "message":
            return self.message
        elif key == "code":
            return self.code
        elif key == "data":
            return self.data
        elif key == "metadata":
            return self.metadata
        raise KeyError(f"'{key}'")
    
    def __contains__(self, key: str) -> bool:
        """支持in操作符"""
        return key in ["success", "error", "status", "message", "code", "data", "metadata"]
    
    def keys(self):
        """返回所有可用的键"""
        return ["success", "error", "status", "message", "code", "data", "metadata"]
    
    @classmethod
    def ok(cls, data: Any = None, message: str = "Success") -> "ServiceResponse":
        """创建成功响应"""
        return cls(
            status=ResponseStatus.SUCCESS,
            data=data,
            message=message,
            code="0"
        )
    
    @classmethod
    def err(cls, message: str, code: str = "-1", data: Any = None) -> "ServiceResponse":
        """创建错误响应"""
        return cls(
            status=ResponseStatus.ERROR,
            message=message,
            code=code,
            data=data
        )
    
    @classmethod
    def warning(cls, message: str, code: str = "1", data: Any = None) -> "ServiceResponse":
        """创建警告响应"""
        return cls(
            status=ResponseStatus.WARNING,
            message=message,
            code=code,
            data=data
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {
            "status": self.status.value,
            "code": self.code,
            "message": self.message,
        }
        if self.data is not None:
            result["data"] = self.data
        if self.metadata:
            result["metadata"] = self.metadata
        return result


# ============ 便捷函数 ============

def success_response(data: Any = None, message: str = "Success") -> ServiceResponse:
    """创建成功响应的便捷函数"""
    return ServiceResponse.ok(data, message)


def error_response(message: str, code: str = "-1", data: Any = None) -> ServiceResponse:
    """创建错误响应的便捷函数"""
    return ServiceResponse.err(message, code, data)


def warning_response(message: str, code: str = "1", data: Any = None) -> ServiceResponse:
    """创建警告响应的便捷函数"""
    return ServiceResponse.warning(message, code, data)
