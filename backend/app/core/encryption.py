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


class DecryptionError(Exception):
    """解密失败异常"""
    pass


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
        import sys
        
        if key is None:
            # 从环境变量获取密钥
            key = os.environ.get("ENCRYPTION_KEY", "").encode()
        
        if not key:
            # 强制要求设置 ENCRYPTION_KEY，不允许使用临时密钥
            logger.error("未设置 ENCRYPTION_KEY 环境变量！这是生产环境的安全风险。")
            logger.error("请设置环境变量: export ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')")
            raise ValueError(
                "ENCRYPTION_KEY 环境变量未设置！"
                "请设置环境变量: export ENCRYPTION_KEY=<生成的密钥>"
            )
        
        # 从环境变量获取 salt，必须设置
        salt_env = os.environ.get("ENCRYPTION_SALT")
        if not salt_env:
            logger.error("未设置 ENCRYPTION_SALT 环境变量！这是生产环境的安全风险。")
            logger.error("请设置环境变量: export ENCRYPTION_SALT=<随机字符串，至少16字符>")
            raise ValueError(
                "ENCRYPTION_SALT 环境变量未设置！"
                "请设置环境变量: export ENCRYPTION_SALT=<随机字符串>"
            )
        
        salt = salt_env.encode()
        
        # 检查是否使用默认开发用 salt
        if salt == "cs2_trade_salt_dev".encode():
            logger.error("检测到默认开发用 salt (cs2_trade_salt_dev)！生产环境必须设置唯一的 salt。")
            logger.error("请设置环境变量: export ENCRYPTION_SALT=<随机字符串，至少16字符>")
            raise ValueError(
                "检测到默认开发用 salt！生产环境必须设置唯一的 ENCRYPTION_SALT。"
            )
        
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
        """解密字符串
        
        Raises:
            DecryptionError: 解密失败时抛出异常
        """
        if not self._fernet:
            self.initialize()
        if not encrypted_data:
            raise DecryptionError("加密数据为空")
        try:
            return self._fernet.decrypt(encrypted_data.encode()).decode()
        except Exception as e:
            logger.error(f"解密失败: {e}")
            raise DecryptionError(f"解密失败: {str(e)}")
    
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
