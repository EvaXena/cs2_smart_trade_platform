# -*- coding: utf-8 -*-
"""
搬砖机器人实现

基于 BUFF 和 Steam 之间的价格差进行自动化交易
"""
import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime

from .trading_bot_base import TradingBotBase, BotPlatform, BotStatus

logger = logging.getLogger(__name__)


class ArbitrageBot(TradingBotBase):
    """
    搬砖机器人
    
    功能：
    - 监控 BUFF 和 Steam 价格
    - 自动计算搬砖利润
    - 执行买入/卖出操作
    - 支持多种搬砖策略
    """
    
    def __init__(
        self,
        bot_id: int,
        name: str,
        config: Optional[Dict[str, Any]] = None
    ):
        # 默认配置
        default_config = {
            "min_profit": 1.0,           # 最小利润（元）
            "min_profit_percent": 5.0,  # 最小利润率（%）
            "max_single_trade": 1000.0,  # 单笔最大金额
            "check_interval": 30,        # 检查间隔（秒）
            "max_trades_per_hour": 10,   # 每小时最大交易数
            "buy_platform": "buff",      # 买入平台
            "sell_platform": "steam",    # 卖出平台
            "auto_confirm": True,        # 自动确认订单
            "enabled_items": None,       # 监控的物品列表（None=全部）
            "excluded_items": [],        # 排除的物品
        }
        
        if config:
            default_config.update(config)
        
        super().__init__(
            bot_id=bot_id,
            name=name,
            platform=BotPlatform.BUFF_TO_STEAM,
            config=default_config
        )
        
        # 运行时状态
        self._buff_client = None
        self._steam_api = None
        self._db_session = None
        
        # 问题9：价格缓存无过期机制 - 实现带TTL的缓存
        self._price_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 300  # 缓存5分钟
        self._trade_history: List[Dict[str, Any]] = []
    
    def _set_cache(self, key: str, value: Any) -> None:
        """设置缓存（带过期时间）- 问题9"""
        self._price_cache[key] = {
            "value": value,
            "timestamp": time.time()
        }
    
    def _get_cache(self, key: str) -> Optional[Any]:
        """获取缓存（检查过期）- 问题9"""
        if key not in self._price_cache:
            return None
        
        cache_entry = self._price_cache[key]
        elapsed = time.time() - cache_entry["timestamp"]
        
        if elapsed > self._cache_ttl:
            # 缓存过期，删除
            del self._price_cache[key]
            return None
        
        return cache_entry["value"]
    
    def _cleanup_expired_cache(self) -> int:
        """清理过期缓存 - 问题9"""
        now = time.time()
        expired_keys = [
            key for key, entry in self._price_cache.items()
            if now - entry["timestamp"] > self._cache_ttl
        ]
        
        for key in expired_keys:
            del self._price_cache[key]
        
        return len(expired_keys)
    
    async def _initialize(self) -> None:
        """
        初始化搬砖机器人
        """
        self.logger.info(f"初始化搬砖机器人: {self.name}")
        
        # 初始化 BUFF 客户端
        await self._init_buff_client()
        
        # 初始化 Steam API
        await self._init_steam_api()
        
        self.logger.info("搬砖机器人初始化完成")
    
    async def _init_buff_client(self) -> None:
        """初始化 BUFF 客户端"""
        try:
            # 延迟导入避免循环依赖
            from app.services.buff_service import get_buff_client
            
            cookie = self.config.get("buff_cookie")
            if cookie:
                self._buff_client = get_buff_client(cookie)
                self.logger.info("BUFF 客户端已初始化")
            else:
                self.logger.warning("未配置 BUFF Cookie")
                
        except Exception as e:
            self.logger.error(f"初始化 BUFF 客户端失败: {e}")
    
    async def _init_steam_api(self) -> None:
        """初始化 Steam API"""
        try:
            from app.services.steam_service import get_steam_api
            
            self._steam_api = get_steam_api()
            self.logger.info("Steam API 已初始化")
            
        except Exception as e:
            self.logger.error(f"初始化 Steam API 失败: {e}")
    
    async def _run_loop(self) -> None:
        """
        主循环：持续监控价格并执行搬砖 - 问题9：定期清理过期缓存
        """
        self.logger.info("搬砖机器人主循环开始")
        
        cache_cleanup_interval = 300  # 每5分钟清理一次
        last_cleanup = 0
        
        while self._running:
            try:
                if not self._paused:
                    # 检查是否超过每小时交易限制
                    if await self._check_trade_limit():
                        self.logger.info("已达到每小时交易限制，暂停")
                        await self._sleep_with_pause(60)
                        continue
                    
                    # 执行搬砖逻辑
                    await self._scan_and_trade()
                
                # 定期清理过期缓存
                if time.time() - last_cleanup > cache_cleanup_interval:
                    cleaned = self._cleanup_expired_cache()
                    if cleaned > 0:
                        self.logger.debug(f"清理了 {cleaned} 个过期缓存")
                    last_cleanup = time.time()
                
                # 等待下次检查
                await self._sleep_with_pause(self.config["check_interval"])
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"主循环异常: {e}")
                await self._sleep_with_pause(60)  # 出错后等待1分钟
        
        self.logger.info("搬砖机器人主循环结束")
    
    async def _scan_and_trade(self) -> None:
        """
        扫描并执行搬砖
        """
        try:
            # 1. 获取搬砖机会
            opportunities = await self._get_arbitrage_opportunities()
            
            if not opportunities:
                self.logger.debug("当前无搬砖机会")
                return
            
            # 2. 过滤有效机会
            valid_opportunities = self._filter_opportunities(opportunities)
            
            self.logger.info(f"发现 {len(valid_opportunities)} 个有效搬砖机会")
            
            # 3. 执行交易
            for opp in valid_opportunities:
                if not self._running or self._paused:
                    break
                
                await self._execute_arbitrage_trade(opp)
                
                # 避免过快交易
                await asyncio.sleep(5)
                
        except Exception as e:
            self.logger.error(f"扫描并交易失败: {e}")
    
    async def _get_arbitrage_opportunities(self) -> List[Dict[str, Any]]:
        """
        获取搬砖机会
        
        Returns:
            搬砖机会列表
        """
        if not self._buff_client:
            self.logger.warning("BUFF 客户端未初始化")
            return []
        
        try:
            # 调用交易引擎获取机会
            from app.services.trading_service import TradingEngine
            
            if self._db_session:
                engine = TradingEngine(self._db_session)
                opportunities = await engine.get_arbitrage_opportunities(
                    min_profit=self.config["min_profit"],
                    limit=50
                )
                return opportunities
            
            # 无数据库时直接从API获取
            return []
            
        except Exception as e:
            self.logger.error(f"获取搬砖机会失败: {e}")
            return []
    
    def _filter_opportunities(
        self,
        opportunities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        过滤有效的搬砖机会
        
        Args:
            opportunities: 原始机会列表
            
        Returns:
            过滤后的机会列表
        """
        filtered = []
        
        for opp in opportunities:
            # 检查利润门槛
            if opp["profit"] < self.config["min_profit"]:
                continue
            
            # 检查利润率
            if opp["profit_percent"] < self.config["min_profit_percent"]:
                continue
            
            # 检查单笔金额限制
            if opp["buff_price"] > self.config["max_single_trade"]:
                continue
            
            # 检查是否在排除列表
            if opp["name"] in self.config["excluded_items"]:
                continue
            
            # 检查是否在启用列表（如果有）
            if self.config["enabled_items"]:
                if opp["name"] not in self.config["enabled_items"]:
                    continue
            
            filtered.append(opp)
        
        # 按利润排序
        filtered.sort(key=lambda x: x["profit"], reverse=True)
        
        return filtered[:10]  # 最多处理10个
    
    async def _execute_arbitrage_trade(
        self,
        opportunity: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行单笔搬砖交易
        
        Args:
            opportunity: 搬砖机会
            
        Returns:
            交易结果
        """
        item_name = opportunity["name"]
        item_id = opportunity["item_id"]
        buff_price = opportunity["buff_price"]
        steam_price = opportunity["steam_price"]
        profit = opportunity["profit"]
        
        self.logger.info(
            f"执行搬砖: {item_name} - "
            f"BUFF: {buff_price}¥, Steam: {steam_price}¥, "
            f"利润: {profit}¥"
        )
        
        try:
            # 1. 买入（BUFF）
            buy_result = await self._buy_from_buff(item_id, buff_price)
            
            if not buy_result.get("success"):
                self.logger.warning(f"买入失败: {buy_result.get('message')}")
                return buy_result
            
            # 2. 等待到账（简化处理，实际需要轮询）
            await asyncio.sleep(30)
            
            # 3. 卖出（Steam）- 实际需要更复杂逻辑
            sell_result = await self._sell_to_steam(item_id, steam_price)
            
            # 记录交易
            trade_record = {
                "timestamp": datetime.utcnow().isoformat(),
                "item_name": item_name,
                "item_id": item_id,
                "buy_price": buff_price,
                "sell_price": steam_price,
                "profit": profit,
                "buy_result": buy_result,
                "sell_result": sell_result,
            }
            
            self._trade_history.append(trade_record)
            
            # 更新统计
            self.stats["total_trades"] += 1
            self.stats["successful_trades"] += 1
            self.stats["total_profit"] += profit
            self.stats["last_trade_time"] = datetime.utcnow()
            
            self.logger.info(f"搬砖成功: {item_name}, 利润: {profit}¥")
            
            return {
                "success": True,
                "profit": profit,
                "trade": trade_record
            }
            
        except Exception as e:
            self.logger.error(f"搬砖交易失败: {e}")
            return {
                "success": False,
                "message": str(e)
            }
    
    async def _buy_from_buff(
        self,
        item_id: int,
        max_price: float
    ) -> Dict[str, Any]:
        """
        从 BUFF 买入
        
        Args:
            item_id: 物品ID
            max_price: 最高价格
            
        Returns:
            买入结果
        """
        if not self._buff_client:
            return {"success": False, "message": "BUFF 客户端未初始化"}
        
        try:
            from app.services.trading_service import TradingEngine
            
            if self._db_session:
                engine = TradingEngine(self._db_session)
                engine.buff_client = self._buff_client
                
                return await engine.execute_buy(
                    item_id=item_id,
                    max_price=max_price,
                    user_id=self.config.get("user_id", 1)
                )
            
            return {"success": False, "message": "无数据库会话"}
            
        except Exception as e:
            return {"success": False, "message": str(e)}
    
    async def _sell_to_steam(
        self,
        item_id: int,
        price: float = None,
        item_name: str = None,
        buy_price: float = None
    ) -> Dict[str, Any]:
        """
        卖出到 Steam - 问题6：实现完整的上架流程
        
        流程：
        1. 获取Steam库存中的物品
        2. 计算智能卖出价格
        3. 创建市场上架列表
        
        Args:
            item_id: 物品ID
            price: 指定价格（可选，如果不指定则使用智能定价）
            item_name: 物品名称（用于智能定价）
            buy_price: 买入价格（用于计算目标利润）
            
        Returns:
            卖出结果
        """
        if not self._steam_api:
            self.logger.warning("Steam API未初始化")
            return {"success": False, "message": "Steam API未初始化"}
        
        try:
            # 1. 获取Steam库存
            inventory = await self._get_steam_inventory(item_id)
            
            if not inventory:
                self.logger.warning(f"Steam库存中未找到该物品: item_id={item_id}")
                return {
                    "success": False,
                    "message": "Steam库存中未找到该物品",
                    "retry": True  # 标记需要重试
                }
            
            # 2. 如果未指定价格，使用智能定价
            if price is None:
                smart_pricing = await self._calculate_smart_sell_price(
                    item_id=item_id,
                    item_name=item_name,
                    buy_price=buy_price
                )
                if smart_pricing.get("success"):
                    price = smart_pricing["recommended_price"]
                    self.logger.info(f"智能定价: item={item_name}, 推荐价格={price}¥")
                else:
                    # 智能定价失败，使用默认定价
                    self.logger.warning(f"智能定价失败，使用默认价格: {smart_pricing.get('message')}")
                    price = smart_pricing.get("fallback_price", 0)
            
            if price <= 0:
                return {"success": False, "message": "无效的卖出价格"}
            
            # 3. 创建上架列表
            for item in inventory:
                listing_result = await self._create_steam_listing(
                    asset_id=item["asset_id"],
                    context_id=item["context_id"],
                    price=price
                )
                
                if listing_result.get("success"):
                    self.logger.info(
                        f"Steam上架成功: asset_id={item['asset_id']}, "
                        f"price={price}, listing_id={listing_result.get('listing_id')}"
                    )
                    return {
                        "success": True,
                        "listing_id": listing_result.get("listing_id"),
                        "price": price
                    }
            
            return {"success": False, "message": "上架失败"}
            
        except Exception as e:
            self.logger.error(f"Steam卖出异常: {e}")
            return {"success": False, "message": str(e)}
    
    async def _get_steam_inventory(self, item_id: int) -> List[Dict]:
        """
        获取Steam库存
        
        Args:
            item_id: 物品ID
            
        Returns:
            库存物品列表
        """
        try:
            if not self._steam_api:
                return []
            
            # 调用Steam API获取库存
            # 需要根据item_id查找对应的market_hash_name
            # 这里简化处理：直接获取库存
            inventory = await self._steam_api.get_inventory(
                app_id=730,  # CSGO
                context_id=2  # 市场库存
            )
            
            if inventory and "assets" in inventory:
                return inventory.get("assets", [])
            
            return []
            
        except Exception as e:
            self.logger.error(f"获取Steam库存失败: {e}")
            return []
    
    async def _create_steam_listing(
        self,
        asset_id: str,
        context_id: str,
        price: float
    ) -> Dict[str, Any]:
        """
        创建Steam市场列表
        
        Args:
            asset_id: 资产ID
            context_id: 上下文ID
            price: 价格
            
        Returns:
            创建结果
        """
        try:
            if not self._steam_api:
                return {"success": False, "message": "Steam API未初始化"}
            
            # 调用Steam市场API创建列表
            # 需要使用steam_login和webcookie进行认证
            # 这里需要完成实际的API调用
            
            # 尝试调用创建列表方法
            result = await self._steam_api.create_market_listing(
                asset_id=asset_id,
                context_id=context_id,
                price=price
            )
            
            if result:
                return {
                    "success": True,
                    "listing_id": result.get("listing_id")
                }
            
            return {"success": False, "message": "创建列表失败"}
            
        except Exception as e:
            self.logger.error(f"创建Steam列表失败: {e}")
            return {"success": False, "message": str(e)}
    
    async def _check_trade_limit(self) -> bool:
        """
        检查是否达到交易限制
        
        Returns:
            是否达到限制
        """
        if not self.stats["last_trade_time"]:
            return False
        
        # 计算过去1小时的交易数
        one_hour_ago = datetime.utcnow().timestamp() - 3600
        recent_trades = [
            t for t in self._trade_history
            if datetime.fromisoformat(t["timestamp"]).timestamp() > one_hour_ago
        ]
        
        return len(recent_trades) >= self.config["max_trades_per_hour"]
    
    async def _execute_trade_impl(
        self,
        trade_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行单笔交易（实现基类接口）
        """
        return await self._execute_arbitrage_trade(trade_data)
    
    async def _cleanup(self) -> None:
        """
        清理资源
        """
        self._buff_client = None
        self._steam_api = None
        self._price_cache.clear()
        self.logger.info("搬砖机器人已清理")
    
    async def get_opportunities(self) -> Dict[str, Any]:
        """
        获取当前搬砖机会（API接口）
        
        Returns:
            搬砖机会数据
        """
        opportunities = await self._get_arbitrage_opportunities()
        valid = self._filter_opportunities(opportunities)
        
        return {
            "total": len(opportunities),
            "valid": len(valid),
            "opportunities": valid[:20]
        }
    
    async def get_trade_history(
        self,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        获取交易历史
        
        Args:
            limit: 返回数量限制
            
        Returns:
            交易历史列表
        """
        return self._trade_history[-limit:]
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            统计数据
        """
        base_stats = self.stats.copy()
        
        # 添加额外统计
        if self._trade_history:
            avg_profit = sum(t["profit"] for t in self._trade_history) / len(self._trade_history)
            base_stats["avg_profit"] = round(avg_profit, 2)
            base_stats["success_rate"] = round(
                self.stats["successful_trades"] / self.stats["total_trades"] * 100
                if self.stats["total_trades"] > 0 else 0,
                2
            )
        
        return base_stats
