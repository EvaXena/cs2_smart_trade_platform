# -*- coding: utf-8 -*-
"""
加密工具模块
使用 Fernet 对称加密保护敏感信息
"""
import os
import base64
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging

logger = logging.getLogger(__name__)


class EncryptionManager:
    """加密管理器"""
    
    _instance: Optional["EncryptionManager"] = None
    _fernet: Optional[Fernet] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def initialize(self, key: Optional[bytes] = None):
        """初始化加密器"""
        if key is None:
            # 从环境变量获取密钥
            key = os.environ.get("ENCRYPTION_KEY", "").encode()
        
        if not key:
            # 生成一个新密钥（仅首次使用）
            logger.warning("未设置 ENCRYPTION_KEY，将生成临时密钥（重启后会失效）")
            key = os.urandom(32)
        
        # 从环境变量获取 salt，如果未设置则使用默认值（仅用于开发环境）
        salt = os.environ.get("ENCRYPTION_SALT", "cs2_trade_salt_dev").encode()
        
        if salt == "cs2_trade_salt_dev".encode():
            logger.warning("未设置 ENCRYPTION_SALT，使用默认开发用 salt，生产环境应设置唯一的 salt")
        
        # 使用 PBKDF2 派生密钥
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,  # 从环境变量读取
            iterations=480000,
        )
        derived_key = base64.urlsafe_b64encode(kdf.derive(key))
        self._fernet = Fernet(derived_key)
    
    def encrypt(self, data: str) -> str:
        """加密字符串"""
        if not self._fernet:
            self.initialize()
        if not data:
            return ""
        return self._fernet.encrypt(data.encode()).decode()
    
    def decrypt(self, encrypted_data: str) -> str:
        """解密字符串"""
        if not self._fernet:
            self.initialize()
        if not encrypted_data:
            return ""
        try:
            return self._fernet.decrypt(encrypted_data.encode()).decode()
        except Exception:
            logger.error("解密失败")
            return ""
    
    @property
    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._fernet is not None


# 全局实例
encryption_manager = EncryptionManager()


def encrypt_sensitive_data(data: str) -> str:
    """加密敏感数据"""
    return encryption_manager.encrypt(data)


def decrypt_sensitive_data(encrypted_data: str) -> str:
    """解密敏感数据"""
    return encryption_manager.decrypt(encrypted_data)
