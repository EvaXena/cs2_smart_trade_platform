# -*- coding: utf-8 -*-
"""
监控任务模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Index, Boolean, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class MonitorTask(Base):
    """监控任务模型"""
    __tablename__ = "monitor_tasks"

    id = Column(Integer, primary_key=True, index=True)
    
    # 任务信息
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    
    # 监控目标
    item_id = Column(Integer, ForeignKey("items.id"), nullable=True)
    item_pattern = Column(String(200), nullable=True)  # 支持正则匹配
    
    # 监控条件
    condition_type = Column(String(50), nullable=False)  
    # price_below: 价格低于
    # price_above: 价格高于
    # arbitrage: 套利机会
    # price_drop: 价格跌破
    # price_rise: 价格涨破
    
    threshold = Column(Numeric(12, 2), nullable=True)  # 阈值
    
    # 通知配置
    notify_enabled = Column(Boolean, default=True)
    notify_telegram = Column(Boolean, default=False)
    notify_email = Column(Boolean, default=False)
    notify_webhook = Column(Boolean, default=False)
    webhook_url = Column(String(500), nullable=True)
    
    # 操作配置
    action = Column(String(50), nullable=True)
    # alert: 仅通知
    # auto_buy: 自动购买
    # auto_sell: 自动出售
    
    # 状态
    enabled = Column(Boolean, default=True, index=True)
    status = Column(String(20), default='idle', index=True)  # idle/running/paused/error
    
    # 所有者
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # 关联的机器人 (可选)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=True, index=True)
    
    # 统计
    trigger_count = Column(Integer, default=0)
    last_triggered = Column(DateTime, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    user = relationship("User", back_populates="monitors")
    bot = relationship("Bot", back_populates="monitor_tasks")

    # 索引
    __table_args__ = (
        Index("idx_monitor_tasks_user", "user_id"),
        Index("idx_monitor_tasks_enabled", "enabled"),
    )

    def __repr__(self):
        return f"<MonitorTask {self.name} status={self.status}>"


class MonitorLog(Base):
    """监控日志模型"""
    __tablename__ = "monitor_logs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("monitor_tasks.id"), nullable=False, index=True)
    
    # 触发信息
    trigger_type = Column(String(50), nullable=False)  # triggered/skipped/error
    message = Column(Text, nullable=True)
    
    # 触发时的价格数据
    price_data = Column(Text, nullable=True)  # JSON
    
    # 动作结果
    action_result = Column(Text, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # 索引
    __table_args__ = (
        Index("idx_monitor_logs_task_id", "task_id"),
    )
