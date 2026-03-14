# -*- coding: utf-8 -*-
"""
技术指标库

自实现常用技术指标，不依赖TA-Lib
"""
from typing import List, Tuple, Optional
import math


def validate_prices(prices: List[float], min_length: int = 1) -> bool:
    """验证价格数据"""
    if not prices or len(prices) < min_length:
        return False
    # 检查是否有有效数值
    return all(p is not None and not math.isnan(p) and p > 0 for p in prices)


def MA(prices: List[float], period: int = 20) -> List[Optional[float]]:
    """
    简单移动平均 (Moving Average)
    
    Args:
        prices: 价格列表
        period: 周期
    
    Returns:
        MA值列表，长度与输入相同，前period-1个为None
    """
    if not validate_prices(prices, period):
        return []
    
    result = [None] * (period - 1)
    
    for i in range(period - 1, len(prices)):
        ma = sum(prices[i - period + 1:i + 1]) / period
        result.append(round(ma, 4))
    
    return result


def EMA(prices: List[float], period: int = 20) -> List[Optional[float]]:
    """
    指数移动平均 (Exponential Moving Average)
    
    Args:
        prices: 价格列表
        period: 周期
    
    Returns:
        EMA值列表
    """
    if not validate_prices(prices, period):
        return []
    
    multiplier = 2 / (period + 1)
    result = [None] * (period - 1)
    
    # 初始SMA作为第一个EMA
    sma = sum(prices[:period]) / period
    result.append(sma)
    
    for i in range(period, len(prices)):
        ema = (prices[i] - result[-1]) * multiplier + result[-1]
        result.append(round(ema, 4))
    
    return result


def RSI(prices: List[float], period: int = 14) -> List[Optional[float]]:
    """
    相对强弱指数 (Relative Strength Index)
    
    Args:
        prices: 价格列表
        period: 周期，默认14
    
    Returns:
        RSI值列表，范围0-100
    """
    if not validate_prices(prices, period + 1):
        return []
    
    result = [None] * period
    
    # 计算价格变化
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    
    # 分离涨跌
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    # 计算初始平均涨跌幅
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(deltas)):
        if i == period:
            rs = avg_gain / avg_loss if avg_loss != 0 else 100
            rsi = 100 - (100 / (1 + rs)) if avg_loss != 0 else 100
            result.append(round(rsi, 4))
        else:
            # 平滑处理
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            
            rs = avg_gain / avg_loss if avg_loss != 0 else 100
            rsi = 100 - (100 / (1 + rs)) if avg_loss != 0 else 100
            result.append(round(rsi, 4))
    
    return result


def MACD(
    prices: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """
    移动平均收敛发散指标 (MACD)
    
    Args:
        prices: 价格列表
        fast: 快线周期，默认12
        slow: 慢线周期，默认26
        signal: 信号线周期，默认9
    
    Returns:
        (MACD线, 信号线, 柱状图)
    """
    if not validate_prices(prices, slow):
        return [], [], []
    
    # 计算快线和慢线的EMA
    fast_ema = EMA(prices, fast)
    slow_ema = EMA(prices, slow)
    
    # 计算MACD线
    macd_line = []
    for i in range(len(prices)):
        if slow_ema[i] is not None and fast_ema[i] is not None:
            macd_line.append(round(fast_ema[i] - slow_ema[i], 4))
        else:
            macd_line.append(None)
    
    # 计算信号线（MACD的EMA）
    # 先获取有效的MACD值
    valid_macd = [m for m in macd_line if m is not None]
    if len(valid_macd) < signal:
        return macd_line, [None] * len(prices), [None] * len(prices)
    
    signal_ema = EMA(valid_macd, signal)
    
    # 将信号线对齐到原始价格长度
    signal_line = [None] * len(prices)
    histogram = [None] * len(prices)
    
    valid_idx = 0
    for i in range(len(prices)):
        if macd_line[i] is not None and valid_idx < len(signal_ema):
            signal_line[i] = signal_ema[valid_idx]
            histogram[i] = round(macd_line[i] - signal_ema[valid_idx], 4)
            valid_idx += 1
    
    return macd_line, signal_line, histogram


def BollingerBands(
    prices: List[float],
    period: int = 20,
    std_dev: float = 2.0
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """
    布林带 (Bollinger Bands)
    
    Args:
        prices: 价格列表
        period: 周期，默认20
        std_dev: 标准差倍数，默认2.0
    
    Returns:
        (上轨, 中轨, 下轨)
    """
    if not validate_prices(prices, period):
        return [], [], []
    
    middle_band = MA(prices, period)
    
    upper_band = [None] * (period - 1)
    lower_band = [None] * (period - 1)
    
    for i in range(period - 1, len(prices)):
        # 计算标准差
        subset = prices[i - period + 1:i + 1]
        mean = sum(subset) / period
        variance = sum((x - mean) ** 2 for x in subset) / period
        std = math.sqrt(variance)
        
        middle = middle_band[i]
        if middle is not None:
            upper_band.append(round(middle + std_dev * std, 4))
            lower_band.append(round(middle - std_dev * std, 4))
    
    return upper_band, middle_band, lower_band


def ATR(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14
) -> List[Optional[float]]:
    """
    平均真实波幅 (Average True Range)
    
    Args:
        highs: 最高价列表
        lows: 最低价列表
        closes: 收盘价列表
        period: 周期，默认14
    
    Returns:
        ATR值列表
    """
    if not (validate_prices(highs) and validate_prices(lows) and validate_prices(closes)):
        return []
    
    if len(highs) != len(lows) or len(lows) != len(closes):
        return []
    
    # 计算True Range
    true_ranges = []
    for i in range(len(closes)):
        if i == 0:
            tr = highs[0] - lows[0]
        else:
            hl = highs[i] - lows[i]
            hc = abs(highs[i] - closes[i - 1])
            lc = abs(lows[i] - closes[i - 1])
            tr = max(hl, hc, lc)
        true_ranges.append(tr)
    
    if len(true_ranges) < period:
        return [None] * len(closes)
    
    # 计算ATR
    result = [None] * (period - 1)
    
    # 初始ATR
    atr = sum(true_ranges[:period]) / period
    result.append(round(atr, 4))
    
    for i in range(period, len(true_ranges)):
        atr = (atr * (period - 1) + true_ranges[i]) / period
        result.append(round(atr, 4))
    
    return result


def Stochastic(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    k_period: int = 14,
    d_period: int = 3
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """
    随机指标 (Stochastic Oscillator)
    
    Args:
        highs: 最高价列表
        lows: 最低价列表
        closes: 收盘价列表
        k_period: K线周期，默认14
        d_period: D线周期，默认3
    
    Returns:
        (%K, %D)
    """
    if not (validate_prices(highs) and validate_prices(lows) and validate_prices(closes)):
        return [], []
    
    if len(highs) != len(lows) or len(lows) != len(closes):
        return [], []
    
    # 计算%K
    k_values = []
    for i in range(len(closes)):
        if i < k_period - 1:
            k_values.append(None)
        else:
            high_max = max(highs[i - k_period + 1:i + 1])
            low_min = min(lows[i - k_period + 1:i + 1])
            
            if high_max == low_min:
                k_values.append(50.0)  # 避免除零
            else:
                k = ((closes[i] - low_min) / (high_max - low_min)) * 100
                k_values.append(round(k, 4))
    
    # 计算%D（%K的SMA）
    d_values = MA([k if k is not None else 0 for k in k_values], d_period)
    
    return k_values, d_values


def OBV(closes: List[float], volumes: List[float]) -> List[Optional[float]]:
    """
    能量潮 (On-Balance Volume)
    
    Args:
        closes: 收盘价列表
        volumes: 成交量列表
    
    Returns:
        OBV值列表
    """
    if not (validate_prices(closes) and volumes):
        return []
    
    if len(closes) != len(volumes):
        return []
    
    result = [volumes[0] if volumes[0] else 0]
    
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv = result[-1] + (volumes[i] if volumes[i] else 0)
        elif closes[i] < closes[i - 1]:
            obv = result[-1] - (volumes[i] if volumes[i] else 0)
        else:
            obv = result[-1]
        result.append(round(obv, 4))
    
    return result


def VWAP(prices: List[float], volumes: List[float]) -> List[Optional[float]]:
    """
    成交量加权平均价格 (Volume Weighted Average Price)
    
    Args:
        prices: 价格列表（通常用典型价 (high+low+close)/3）
        volumes: 成交量列表
    
    Returns:
        VWAP值列表
    """
    if not (validate_prices(prices) and volumes):
        return []
    
    if len(prices) != len(volumes):
        return []
    
    cumulative_pv = 0
    cumulative_volume = 0
    result = []
    
    for i in range(len(prices)):
        price = prices[i]
        volume = volumes[i] if volumes[i] else 0
        
        cumulative_pv += price * volume
        cumulative_volume += volume
        
        if cumulative_volume > 0:
            vwap = cumulative_pv / cumulative_volume
            result.append(round(vwap, 4))
        else:
            result.append(None)
    
    return result


# ============ 便捷函数 ============

def get_all_indicators(
    prices: List[float],
    highs: Optional[List[float]] = None,
    lows: Optional[List[float]] = None,
    volumes: Optional[List[float]] = None
) -> dict:
    """
    一次性计算所有常用指标
    
    Args:
        prices: 收盘价列表
        highs: 最高价列表（可选）
        lows: 最低价列表（可选）
        volumes: 成交量列表（可选）
    
    Returns:
        包含所有指标结果的字典
    """
    result = {}
    
    # 基础指标
    result['ma_5'] = MA(prices, 5)
    result['ma_10'] = MA(prices, 10)
    result['ma_20'] = MA(prices, 20)
    result['ma_60'] = MA(prices, 60)
    
    result['ema_5'] = EMA(prices, 5)
    result['ema_10'] = EMA(prices, 10)
    result['ema_20'] = EMA(prices, 20)
    result['ema_60'] = EMA(prices, 60)
    
    result['rsi_14'] = RSI(prices, 14)
    result['rsi_7'] = RSI(prices, 7)
    
    macd, signal, histogram = MACD(prices)
    result['macd'] = macd
    result['macd_signal'] = signal
    result['macd_histogram'] = histogram
    
    if highs and lows:
        upper, middle, lower = BollingerBands(prices)
        result['bb_upper'] = upper
        result['bb_middle'] = middle
        result['bb_lower'] = lower
        
        result['atr_14'] = ATR(highs, lows, prices, 14)
        
        k, d = Stochastic(highs, lows, prices)
        result['stoch_k'] = k
        result['stoch_d'] = d
    
    if volumes:
        result['obv'] = OBV(prices, volumes)
        if highs and lows:
            typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs, lows, prices)]
            result['vwap'] = VWAP(typical_prices, volumes)
    
    return result
