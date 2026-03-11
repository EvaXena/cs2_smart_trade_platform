# -*- coding: utf-8 -*-
"""
用户模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    """用户模型"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    
    # Steam 账户信息
    steam_id = Column(String(64), unique=True, index=True, nullable=True)
    steam_cookie_encrypted = Column(Text, nullable=True, comment="加密存储")
    
    # BUFF 账户信息
    buff_cookie_encrypted = Column(Text, nullable=True, comment="加密存储")
    
    # Steam 令牌 (MaFile JSON) - 加密存储
    ma_file_encrypted = Column(Text, nullable=True, comment="加密存储")
    
    # 账户余额
    balance = Column(Numeric(12, 2), default=0)
    
    # 账户状态
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    orders = relationship("Order", back_populates="user")
    inventory = relationship("Inventory", back_populates="user")
    monitors = relationship("MonitorTask", back_populates="user")

    # 属性：用于解密访问（使用延迟解密，避免模块加载时调用）
    @property
    def steam_cookie(self) -> str:
        """解密获取 steam_cookie"""
        if not self.steam_cookie_encrypted:
            return ""
        from app.core.encryption import decrypt_sensitive_data
        return decrypt_sensitive_data(self.steam_cookie_encrypted)
    
    @steam_cookie.setter
    def steam_cookie(self, value: str):
        """加密存储 steam_cookie"""
        if not value:
            self.steam_cookie_encrypted = None
            return
        from app.core.encryption import encrypt_sensitive_data
        self.steam_cookie_encrypted = encrypt_sensitive_data(value)
    
    @property
    def buff_cookie(self) -> str:
        """解密获取 buff_cookie"""
        if not self.buff_cookie_encrypted:
            return ""
        from app.core.encryption import decrypt_sensitive_data
        return decrypt_sensitive_data(self.buff_cookie_encrypted)
    
    @buff_cookie.setter
    def buff_cookie(self, value: str):
        """加密存储 buff_cookie"""
        if not value:
            self.buff_cookie_encrypted = None
            return
        from app.core.encryption import encrypt_sensitive_data
        self.buff_cookie_encrypted = encrypt_sensitive_data(value)
    
    @property
    def ma_file(self) -> str:
        """解密获取 ma_file"""
        if not self.ma_file_encrypted:
            return ""
        from app.core.encryption import decrypt_sensitive_data
        return decrypt_sensitive_data(self.ma_file_encrypted)
    
    @ma_file.setter
    def ma_file(self, value: str):
        """加密存储 ma_file"""
        if not value:
            self.ma_file_encrypted = None
            return
        from app.core.encryption import encrypt_sensitive_data
        self.ma_file_encrypted = encrypt_sensitive_data(value)
    
    def clear_sensitive_data(self):
        """清除敏感数据"""
        self.steam_cookie_encrypted = None
        self.buff_cookie_encrypted = None
        self.ma_file_encrypted = None

    def __repr__(self):
        return f"<User {self.username}>"


class UserSession(Base):
    """用户会话模型"""
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 索引
    __table_args__ = (
        Index("idx_user_sessions_user_id", "user_id"),
        Index("idx_user_sessions_token", "token"),
    )
