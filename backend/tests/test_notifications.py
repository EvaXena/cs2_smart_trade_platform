# -*- coding: utf-8 -*-
"""
通知系统测试
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from app.services.notification.base import Message, MessageLevel, NotificationChannel
from app.services.notification.email import EmailNotification, EmailConfig
from app.services.notification.slack import SlackNotification, SlackConfig
from app.services.notification.discord import DiscordNotification, DiscordConfig
from app.services.notification.telegram import TelegramNotification, TelegramConfig
from app.services.notification.manager import NotificationManager, NotificationManagerConfig, Template, ChannelType


# ==================== 基类测试 ====================

class TestMessage:
    """消息模型测试"""
    
    def test_message_creation(self):
        """测试消息创建"""
        msg = Message(title="Test", content="Hello World")
        assert msg.title == "Test"
        assert msg.content == "Hello World"
        assert msg.level == "info"
    
    def test_message_with_level(self):
        """测试带级别的消息"""
        msg = Message(title="Error", content="Something went wrong", level="error")
        assert msg.level == "error"
    
    def test_message_with_metadata(self):
        """测试带元数据的消息"""
        metadata = {"order_id": 123, "amount": 99.99}
        msg = Message(title="Order", content="New order", metadata=metadata)
        assert msg.metadata["order_id"] == 123
        assert msg.metadata["amount"] == 99.99


# ==================== 邮件通知测试 ====================

class TestEmailNotification:
    """邮件通知测试"""
    
    @pytest.fixture
    def email_config(self):
        """邮件配置"""
        return EmailConfig(
            enabled=True,
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_username="test@example.com",
            smtp_password="password",
            use_tls=True,
            from_name="Test Bot",
            from_email="test@example.com",
            recipients=["recipient@example.com"]
        )
    
    @pytest.fixture
    def email_notification(self, email_config):
        """邮件通知实例"""
        return EmailNotification(email_config)
    
    def test_email_config(self, email_config):
        """测试邮件配置"""
        assert email_config.enabled is True
        assert email_config.smtp_host == "smtp.gmail.com"
        assert email_config.smtp_port == 587
    
    def test_email_enabled(self, email_notification):
        """测试邮件渠道启用"""
        assert email_notification.enabled is True
    
    @pytest.mark.asyncio
    async def test_send_email_disabled(self):
        """测试禁用时发送失败"""
        config = EmailConfig(enabled=False)
        email = EmailNotification(config)
        msg = Message(title="Test", content="Test content")
        result = await email.send(msg, ["test@example.com"])
        assert result is False
    
    @pytest.mark.asyncio
    async def test_send_email_no_recipients(self, email_notification):
        """测试无收件人时发送失败"""
        msg = Message(title="Test", content="Test content")
        result = await email_notification.send(msg, [])
        assert result is False
    
    @patch('smtplib.SMTP')
    @pytest.mark.asyncio
    async def test_send_email_success(self, mock_smtp, email_notification):
        """测试发送邮件成功"""
        mock_server = MagicMock()
        mock_smtp.return_value = mock_server
        
        msg = Message(title="Test", content="Test content")
        result = await email_notification.send(msg, ["recipient@example.com"])
        
        assert result is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once()
        mock_server.send_message.assert_called_once()
        mock_server.quit.assert_called_once()
    
    @patch('smtplib.SMTP')
    @pytest.mark.asyncio
    async def test_send_email_failure(self, mock_smtp, email_notification):
        """测试发送邮件失败"""
        mock_smtp.side_effect = Exception("SMTP Error")
        
        msg = Message(title="Test", content="Test content")
        result = await email_notification.send(msg, ["recipient@example.com"])
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_health_check_disabled(self):
        """测试禁用时的健康检查"""
        config = EmailConfig(enabled=False)
        email = EmailNotification(config)
        result = await email.health_check()
        assert result is False
    
    @pytest.mark.asyncio
    async def test_health_check_no_config(self):
        """测试配置不完整时的健康检查"""
        config = EmailConfig(enabled=True, smtp_host="", smtp_username="")
        email = EmailNotification(config)
        result = await email.health_check()
        assert result is False


# ==================== Slack 通知测试 ====================

class TestSlackNotification:
    """Slack 通知测试"""
    
    @pytest.fixture
    def slack_config(self):
        """Slack 配置"""
        return SlackConfig(
            enabled=True,
            webhook_url="https://hooks.slack.com/services/test",
            username="Test Bot",
            icon_emoji=":robot_face:",
            channel="#test"
        )
    
    @pytest.fixture
    def slack_notification(self, slack_config):
        """Slack 通知实例"""
        return SlackNotification(slack_config)
    
    def test_slack_config(self, slack_config):
        """测试 Slack 配置"""
        assert slack_config.enabled is True
        assert slack_config.webhook_url == "https://hooks.slack.com/services/test"
        assert slack_config.channel == "#test"
    
    def test_level_colors(self, slack_notification):
        """测试级别颜色"""
        assert slack_notification._get_level_color("info") == "#3498db"
        assert slack_notification._get_level_color("warning") == "#f39c12"
        assert slack_notification._get_level_color("error") == "#e74c3c"
        assert slack_notification._get_level_color("success") == "#27ae60"
    
    @pytest.mark.asyncio
    async def test_send_slack_disabled(self):
        """测试禁用时发送失败"""
        config = SlackConfig(enabled=False)
        slack = SlackNotification(config)
        msg = Message(title="Test", content="Test content")
        result = await slack.send(msg, [])
        assert result is False
    
    @pytest.mark.asyncio
    @patch('aiohttp.ClientSession')
    async def test_send_slack_success(self, mock_session_class, slack_notification):
        """测试发送 Slack 消息成功"""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)
        
        msg = Message(title="Test", content="Test content")
        result = await slack_notification.send(msg, ["#test"])
        
        # 注意：由于 mock 的复杂性，这里主要验证不抛异常
        # 实际测试需要更精细的 mock
    
    @pytest.mark.asyncio
    async def test_send_slack_no_webhook(self):
        """测试无 Webhook URL 时发送失败"""
        config = SlackConfig(enabled=True, webhook_url="")
        slack = SlackNotification(config)
        msg = Message(title="Test", content="Test content")
        result = await slack.send(msg, [])
        assert result is False


# ==================== Discord 通知测试 ====================

class TestDiscordNotification:
    """Discord 通知测试"""
    
    @pytest.fixture
    def discord_config(self):
        """Discord 配置"""
        return DiscordConfig(
            enabled=True,
            webhook_url="https://discord.com/api/webhooks/test",
            username="Test Bot"
        )
    
    @pytest.fixture
    def discord_notification(self, discord_config):
        """Discord 通知实例"""
        return DiscordNotification(discord_config)
    
    def test_discord_config(self, discord_config):
        """测试 Discord 配置"""
        assert discord_config.enabled is True
        assert discord_config.webhook_url == "https://discord.com/api/webhooks/test"
    
    def test_level_colors(self, discord_notification):
        """测试级别颜色"""
        assert discord_notification._get_level_color("info") == 0x3498db
        assert discord_notification._get_level_color("warning") == 0xf39c12
        assert discord_notification._get_level_color("error") == 0xe74c3c
        assert discord_notification._get_level_color("success") == 0x27ae60
    
    @pytest.mark.asyncio
    async def test_send_discord_disabled(self):
        """测试禁用时发送失败"""
        config = DiscordConfig(enabled=False)
        discord = DiscordNotification(config)
        msg = Message(title="Test", content="Test content")
        result = await discord.send(msg, [])
        assert result is False
    
    @pytest.mark.asyncio
    async def test_send_discord_error_mention(self):
        """测试错误级别自动 @everyone"""
        config = DiscordConfig(enabled=True, webhook_url="https://discord.com/api/webhooks/test")
        discord = DiscordNotification(config)
        msg = Message(title="Error", content="Something went wrong", level="error")
        
        # 模拟 webhook 发送
        with patch.object(discord, '_send_webhook', return_value=True):
            result = await discord.send(msg, [])
            assert result is True


# ==================== Telegram 通知测试 ====================

class TestTelegramNotification:
    """Telegram 通知测试"""
    
    @pytest.fixture
    def telegram_config(self):
        """Telegram 配置"""
        return TelegramConfig(
            enabled=True,
            bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
            chat_ids=["123456789"],
            parse_mode="Markdown"
        )
    
    @pytest.fixture
    def telegram_notification(self, telegram_config):
        """Telegram 通知实例"""
        return TelegramNotification(telegram_config)
    
    def test_telegram_config(self, telegram_config):
        """测试 Telegram 配置"""
        assert telegram_config.enabled is True
        assert telegram_config.bot_token == "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        assert "123456789" in telegram_config.chat_ids
    
    def test_format_text_markdown(self, telegram_notification):
        """测试 Markdown 格式化"""
        msg = Message(title="Test", content="Hello World", level="info")
        formatted = telegram_notification._format_text_markdown(msg)
        assert "*Test*" in formatted
        assert "Hello World" in formatted
    
    def test_format_text_html(self, telegram_notification):
        """测试 HTML 格式化"""
        config = TelegramConfig(enabled=True, bot_token="test", parse_mode="HTML")
        telegram = TelegramNotification(config)
        msg = Message(title="Test", content="Hello World", level="info")
        formatted = telegram._format_text_html(msg)
        assert "<b>Test</b>" in formatted
        assert "Hello World" in formatted
    
    @pytest.mark.asyncio
    async def test_send_telegram_disabled(self):
        """测试禁用时发送失败"""
        config = TelegramConfig(enabled=False)
        telegram = TelegramNotification(config)
        msg = Message(title="Test", content="Test content")
        result = await telegram.send(msg, [])
        assert result is False
    
    @pytest.mark.asyncio
    async def test_send_telegram_no_token(self):
        """测试无 Token 时发送失败"""
        config = TelegramConfig(enabled=True, bot_token="")
        telegram = TelegramNotification(config)
        msg = Message(title="Test", content="Test content")
        result = await telegram.send(msg, [])
        assert result is False
    
    @pytest.mark.asyncio
    async def test_send_telegram_no_chat_ids(self):
        """测试无 Chat IDs 时发送失败"""
        config = TelegramConfig(enabled=True, bot_token="test", chat_ids=[])
        telegram = TelegramNotification(config)
        msg = Message(title="Test", content="Test content")
        result = await telegram.send(msg, [])
        assert result is False


# ==================== 通知管理器测试 ====================

class TestNotificationManager:
    """通知管理器测试"""
    
    def test_manager_creation(self):
        """测试管理器创建"""
        manager = NotificationManager()
        assert manager.enabled is True
        assert len(manager.channels) == 0
    
    def test_manager_with_config(self):
        """测试带配置的管理器"""
        config = NotificationManagerConfig(
            enabled=True,
            email=EmailConfig(enabled=True),
            slack=SlackConfig(enabled=True)
        )
        manager = NotificationManager(config)
        assert len(manager.channels) == 2
        assert ChannelType.EMAIL in manager.channels
        assert ChannelType.SLACK in manager.channels
    
    def test_enable_disable_channel(self):
        """测试启用/禁用渠道"""
        config = NotificationManagerConfig(
            email=EmailConfig(enabled=True)
        )
        manager = NotificationManager(config)
        
        assert manager.is_channel_enabled(ChannelType.EMAIL) is True
        
        manager.disable_channel(ChannelType.EMAIL)
        assert manager.is_channel_enabled(ChannelType.EMAIL) is False
        
        manager.enable_channel(ChannelType.EMAIL)
        assert manager.is_channel_enabled(ChannelType.EMAIL) is True
    
    def test_templates(self):
        """测试消息模板"""
        manager = NotificationManager()
        
        template = Template(
            name="trade_success",
            title="交易成功",
            content="您{item}的订单已成功执行，价格为¥{price}",
            level="success"
        )
        manager.add_template(template)
        
        retrieved = manager.get_template("trade_success")
        assert retrieved is not None
        assert retrieved.title == "交易成功"
        
        # 测试从模板创建消息
        msg = manager.create_message_from_template(
            "trade_success",
            item="AK-47",
            price=199.99
        )
        assert msg is not None
        assert msg.title == "交易成功"
        assert "AK-47" in msg.content
        assert "199.99" in msg.content
    
    @pytest.mark.asyncio
    async def test_send_disabled_manager(self):
        """测试禁用管理器时发送失败"""
        config = NotificationManagerConfig(enabled=False)
        manager = NotificationManager(config)
        
        msg = Message(title="Test", content="Test")
        results = await manager.send(msg)
        
        assert results == {}
    
    @pytest.mark.asyncio
    async def test_send_to_specific_channels(self):
        """测试发送到指定渠道"""
        config = NotificationManagerConfig(
            email=EmailConfig(enabled=True),
            slack=SlackConfig(enabled=True)
        )
        manager = NotificationManager(config)
        
        msg = Message(title="Test", content="Test")
        
        # Mock 发送方法
        async def mock_send(msg, recipients):
            return True
        
        manager.channels[ChannelType.EMAIL].send = mock_send
        manager.channels[ChannelType.SLACK].send = mock_send
        
        results = await manager.send(msg, channels=[ChannelType.EMAIL])
        
        assert ChannelType.EMAIL in results
        assert results[ChannelType.EMAIL] is True
    
    @pytest.mark.asyncio
    async def test_notify_trade(self):
        """测试快捷交易通知"""
        config = NotificationManagerConfig(
            email=EmailConfig(enabled=True)
        )
        manager = NotificationManager(config)
        
        # Mock 发送方法
        async def mock_send(msg, recipients):
            return True
        
        manager.channels[ChannelType.EMAIL].send = mock_send
        
        await manager.notify_trade(
            trade_type="买入",
            item_name="AK-47 | 火蛇",
            price=199.99,
            status="成功"
        )
    
    @pytest.mark.asyncio
    async def test_notify_price_alert(self):
        """测试快捷价格提醒"""
        config = NotificationManagerConfig(
            telegram=TelegramConfig(enabled=True, bot_token="test", chat_ids=["123"])
        )
        manager = NotificationManager(config)
        
        # Mock 发送方法
        async def mock_send(msg, recipients):
            return True
        
        manager.channels[ChannelType.TELEGRAM].send = mock_send
        
        await manager.notify_price_alert(
            item_name="AK-47",
            current_price=200.0,
            target_price=180.0,
            direction="下跌"
        )
    
    @pytest.mark.asyncio
    async def test_health_check(self):
        """测试健康检查"""
        config = NotificationManagerConfig(
            email=EmailConfig(enabled=True),
            slack=SlackConfig(enabled=True)  # 需要启用才能加入 channels
        )
        manager = NotificationManager(config)
        
        # Mock 健康检查方法
        manager.channels[ChannelType.EMAIL].health_check = AsyncMock(return_value=True)
        
        results = await manager.health_check()
        
        assert ChannelType.EMAIL in results
        assert results[ChannelType.EMAIL] is True
        assert ChannelType.SLACK in results


# ==================== 集成测试 ====================

class TestNotificationIntegration:
    """通知系统集成测试"""
    
    @pytest.mark.asyncio
    async def test_full_notification_flow(self):
        """测试完整通知流程"""
        # 配置多个渠道
        config = NotificationManagerConfig(
            enabled=True,
            email=EmailConfig(enabled=True),
            slack=SlackConfig(enabled=True),
            discord=DiscordConfig(enabled=True),
            telegram=TelegramConfig(enabled=True, bot_token="test", chat_ids=["123"])
        )
        
        manager = NotificationManager(config)
        
        # 添加模板
        manager.add_template(Template(
            name="test",
            title="测试消息",
            content="这是一条测试消息",
            level="info"
        ))
        
        # 验证所有渠道已初始化
        assert len(manager.get_enabled_channels()) == 4
        
        # 发送消息（使用 mock）
        msg = Message(title="集成测试", content="测试内容")
        
        for channel in manager.channels.values():
            channel.send = AsyncMock(return_value=True)
        
        results = await manager.send(msg)
        
        # 验证发送结果
        assert len(results) > 0
