# -*- coding: utf-8 -*-
"""
回测报告生成
"""
import json
from typing import Optional, Dict, Any
from datetime import datetime

from app.services.backtest.engine import BacktestResult


class BacktestReport:
    """回测报告生成器"""
    
    def __init__(self, results: BacktestResult):
        self.results = results
    
    def print_summary(self) -> None:
        """打印回测摘要"""
        r = self.results
        
        print("\n" + "=" * 60)
        print("                    回 测 报 告")
        print("=" * 60)
        
        # 基本信息
        print(f"\n【基本信息】")
        print(f"  回测期间: {r.start_date.strftime('%Y-%m-%d')} ~ {r.end_date.strftime('%Y-%m-%d')}")
        print(f"  回测天数: {r.total_days} 天")
        print(f"  初始资金: ¥{r.initial_capital:,.2f}")
        print(f"  最终资金: ¥{r.final_capital:,.2f}")
        
        # 收益率
        print(f"\n【收益率】")
        print(f"  总收益率: {r.total_return*100:.2f}%")
        print(f"  年化收益率: {r.annual_return*100:.2f}%")
        
        # 风险指标
        print(f"\n【风险指标】")
        print(f"  最大回撤: {r.max_drawdown_pct:.2f}%")
        print(f"  夏普比率: {r.sharpe_ratio:.2f}")
        
        # 交易统计
        print(f"\n【交易统计】")
        print(f"  总交易次数: {r.total_trades}")
        print(f"  盈利次数: {r.winning_trades}")
        print(f"  亏损次数: {r.losing_trades}")
        print(f"  胜率: {r.win_rate*100:.2f}%")
        
        if r.winning_trades > 0:
            print(f"  平均盈利: ¥{r.avg_win:,.2f}")
        if r.losing_trades > 0:
            print(f"  平均亏损: ¥{r.avg_loss:,.2f}")
        
        print(f"  盈利因子: {r.profit_factor:.2f}")
        print(f"  平均持仓天数: {r.avg_trade_duration:.1f} 天")
        
        print("\n" + "=" * 60)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        r = self.results
        
        return {
            "summary": {
                "start_date": r.start_date.isoformat(),
                "end_date": r.end_date.isoformat(),
                "total_days": r.total_days,
                "initial_capital": r.initial_capital,
                "final_capital": r.final_capital,
            },
            "returns": {
                "total_return": round(r.total_return * 100, 2),
                "annual_return": round(r.annual_return * 100, 2),
            },
            "risk": {
                "max_drawdown": round(r.max_drawdown_pct, 2),
                "sharpe_ratio": round(r.sharpe_ratio, 2),
                "sortino_ratio": round(r.sortino_ratio, 2) if r.sortino_ratio else None,
            },
            "trading": {
                "total_trades": r.total_trades,
                "winning_trades": r.winning_trades,
                "losing_trades": r.losing_trades,
                "win_rate": round(r.win_rate * 100, 2),
                "avg_win": round(r.avg_win, 2),
                "avg_loss": round(r.avg_loss, 2),
                "profit_factor": round(r.profit_factor, 2),
                "avg_trade_duration": round(r.avg_trade_duration, 1),
            },
            "trades": [
                {
                    "entry_time": t.entry_time.isoformat(),
                    "exit_time": t.exit_time.isoformat(),
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "profit": round(t.profit, 2),
                    "commission": round(t.commission, 2),
                }
                for t in r.trades
            ],
            "equity_curve": [
                {
                    "timestamp": e["timestamp"].isoformat(),
                    "total_value": round(e["total_value"], 2),
                    "drawdown": round(e["drawdown"] * 100, 2),
                }
                for e in r.equity_curve
            ],
        }
    
    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
    
    def to_html(self) -> str:
        """转换为HTML报告"""
        r = self.results
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>回测报告</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 40px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            text-align: center;
            margin-bottom: 30px;
        }}
        h2 {{
            color: #666;
            border-bottom: 2px solid #eee;
            padding-bottom: 10px;
            margin-top: 30px;
        }}
        .stat-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
        }}
        .stat-item {{
            padding: 15px;
            background: #f9f9f9;
            border-radius: 8px;
        }}
        .stat-label {{
            color: #999;
            font-size: 14px;
            margin-bottom: 5px;
        }}
        .stat-value {{
            color: #333;
            font-size: 24px;
            font-weight: bold;
        }}
        .positive {{
            color: #4caf50;
        }}
        .negative {{
            color: #f44336;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background: #f5f5f5;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 回测报告</h1>
        
        <h2>📅 基本信息</h2>
        <div class="stat-grid">
            <div class="stat-item">
                <div class="stat-label">回测期间</div>
                <div class="stat-value" style="font-size: 18px;">
                    {r.start_date.strftime('%Y-%m-%d')} ~ {r.end_date.strftime('%Y-%m-%d')}
                </div>
            </div>
            <div class="stat-item">
                <div class="stat-label">回测天数</div>
                <div class="stat-value" style="font-size: 18px;">{r.total_days} 天</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">初始资金</div>
                <div class="stat-value" style="font-size: 18px;">¥{r.initial_capital:,.2f}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">最终资金</div>
                <div class="stat-value" style="font-size: 18px;">¥{r.final_capital:,.2f}</div>
            </div>
        </div>
        
        <h2>💰 收益率</h2>
        <div class="stat-grid">
            <div class="stat-item">
                <div class="stat-label">总收益率</div>
                <div class="stat-value {'positive' if r.total_return > 0 else 'negative'}">
                    {r.total_return*100:.2f}%
                </div>
            </div>
            <div class="stat-item">
                <div class="stat-label">年化收益率</div>
                <div class="stat-value {'positive' if r.annual_return > 0 else 'negative'}">
                    {r.annual_return*100:.2f}%
                </div>
            </div>
        </div>
        
        <h2>⚠️ 风险指标</h2>
        <div class="stat-grid">
            <div class="stat-item">
                <div class="stat-label">最大回撤</div>
                <div class="stat-value negative">{r.max_drawdown_pct:.2f}%</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">夏普比率</div>
                <div class="stat-value">{r.sharpe_ratio:.2f}</div>
            </div>
        </div>
        
        <h2>📈 交易统计</h2>
        <div class="stat-grid">
            <div class="stat-item">
                <div class="stat-label">总交易次数</div>
                <div class="stat-value">{r.total_trades}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">胜率</div>
                <div class="stat-value">{r.win_rate*100:.2f}%</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">盈利次数</div>
                <div class="stat-value positive">{r.winning_trades}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">亏损次数</div>
                <div class="stat-value negative">{r.losing_trades}</div>
            </div>
        </div>
        
        <h2>📋 交易记录</h2>
        <table>
            <thead>
                <tr>
                    <th>入场时间</th>
                    <th>出场时间</th>
                    <th>入场价</th>
                    <th>出场价</th>
                    <th>盈亏</th>
                </tr>
            </thead>
            <tbody>
"""
        
        for trade in r.trades[:20]:  # 只显示前20条
            profit_class = "positive" if trade.profit > 0 else "negative"
            html += f"""
                <tr>
                    <td>{trade.entry_time.strftime('%Y-%m-%d')}</td>
                    <td>{trade.exit_time.strftime('%Y-%m-%d')}</td>
                    <td>¥{trade.entry_price:.2f}</td>
                    <td>¥{trade.exit_price:.2f}</td>
                    <td class="{profit_class}">¥{trade.profit:.2f}</td>
                </tr>
"""
        
        if len(r.trades) > 20:
            html += f"""
                <tr>
                    <td colspan="5" style="text-align: center; color: #999;">
                        ... 还有 {len(r.trades) - 20} 笔交易未显示
                    </td>
                </tr>
"""
        
        html += """
            </tbody>
        </table>
        
    </div>
</body>
</html>
"""
        return html
    
    def save_html(self, filepath: str) -> None:
        """保存HTML报告"""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self.to_html())
        print(f"HTML报告已保存: {filepath}")
    
    def save_json(self, filepath: str) -> None:
        """保存JSON报告"""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self.to_json())
        print(f"JSON报告已保存: {filepath}")
