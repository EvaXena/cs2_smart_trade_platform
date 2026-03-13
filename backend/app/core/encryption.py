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
        
        use_fallback = False
        
        # 检查是否在生产环境
        is_production = os.environ.get("DEBUG", "").lower() != "true"
        
        if not key:
            # 生产环境强制要求 ENCRYPTION_KEY
            if is_production:
                logger.error("生产环境必须设置 ENCRYPTION_KEY 环境变量！")
                logger.error("请设置: export ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')")
                raise ValueError(
                    "生产环境未设置 ENCRYPTION_KEY 环境变量。"
                    "为保护敏感数据安全，请设置 ENCRYPTION_KEY 后再启动服务。"
                )
            else:
                # 开发环境允许临时密钥
                logger.warning("ENCRYPTION_KEY 环境变量未设置，使用临时密钥（开发模式）")
                logger.warning("生产环境请设置: export ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')")
                key = b"cs2_trade_temp_key_do_not_use_in_production_32bytes"
                use_fallback = True
        
        # 从环境变量获取 salt
        salt_env = os.environ.get("ENCRYPTION_SALT")
        
        if not salt_env:
            # 优雅降级：使用默认开发用 salt
            logger.warning("ENCRYPTION_SALT 环境变量未设置，使用默认开发用 salt（开发模式）")
            logger.warning("生产环境请设置: export ENCRYPTION_SALT=<随机字符串，至少16字符>")
            salt_env = "cs2_trade_salt_dev"
            use_fallback = True
        
        salt = salt_env.encode()
        
        # 检查是否使用默认开发用 salt
        if salt == "cs2_trade_salt_dev".encode():
            if use_fallback:
                logger.warning("检测到默认开发用 salt (cs2_trade_salt_dev)，这是开发模式下的正常行为")
            else:
                logger.error("检测到默认开发用 salt (cs2_trade_salt_dev)！生产环境必须设置唯一的 salt。")
                logger.error("请设置环境变量: export ENCRYPTION_SALT=<随机字符串，至少16字符>")
                # 降级：仍然允许启动但记录错误
                logger.warning("继续使用默认 salt，服务将在开发模式下运行")
        
        # 使用 PBKDF2 派生密钥
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,  # 从环境变量读取
            iterations=480000,
        )
        derived_key = base64.urlsafe_b64encode(kdf.derive(key))
        self._fernet = Fernet(derived_key)
        
        if use_fallback:
            logger.warning("加密模块运行在开发模式（降级状态），生产环境请设置 ENCRYPTION_KEY 和 ENCRYPTION_SALT")
    
    def encrypt(self, data: str) -> str:
        """加密字符串"""
        if not self._fernet:
            self.initialize()
        if not data:
            return ""
        return self._fernet.encrypt(data.encode()).decode()
    
    def decrypt(self, encrypted_data: str) -> str:
        """解密字符串
        
        Returns:
            str: 解密后的字符串，空数据返回空字符串
            
        Raises:
            DecryptionError: 解密失败时抛出异常（仅非空数据解密失败时）
        """
        if not self._fernet:
            self.initialize()
        # 优雅处理空数据：返回空字符串而非抛出异常
        if not encrypted_data:
            return ""
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
