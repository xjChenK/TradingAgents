"""AkShare data source for TradingAgents.

AkShare is a Chinese financial data source that provides comprehensive
A-share market data, fundamentals, and news.
"""

from typing import Annotated
from datetime import datetime
import time
import pandas as pd
import akshare as ak
import requests


_EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_TRANSIENT_FETCH_ERRORS = (
    "RemoteDisconnected",
    "Connection aborted",
    "Connection reset",
    "ConnectionError",
    "Read timed out",
    "Max retries exceeded",
    "temporarily unavailable",
)


def _is_transient_fetch_error(exc: Exception) -> bool:
    message = f"{type(exc).__name__}: {exc}"
    return any(fragment.lower() in message.lower() for fragment in _TRANSIENT_FETCH_ERRORS)


def _with_retries(fetch, attempts: int = 3):
    last_error = None
    for attempt in range(attempts):
        try:
            return fetch()
        except Exception as exc:
            last_error = exc
            if not _is_transient_fetch_error(exc) or attempt == attempts - 1:
                raise
            time.sleep(0.8 * (2 ** attempt))
    raise last_error


def _normalize_a_stock_code(symbol: str) -> tuple[str, str]:
    """Normalize A-share stock code to akshare format.

    Args:
        symbol: Stock code in format XXXXXX.SS or XXXXXX.SZ

    Returns:
        Tuple of (market, code) where market is 'sh' or 'sz'
    """
    symbol = symbol.upper().strip()

    # Handle codes with .SS or .SZ suffix
    if '.' in symbol:
        code, suffix = symbol.rsplit('.', 1)
        if suffix in ('SS', 'SH'):
            return 'sh', code
        elif suffix == 'SZ':
            return 'sz', code

    # Try to guess from code range
    code = symbol
    if len(code) == 6:
        # Shanghai: 600000-609999, 510000-519999 (ETF)
        if code.startswith('6') or code.startswith('5'):
            return 'sh', code
        # Shenzhen: 000000-009999, 300000-309999 (ChiNext)
        elif code.startswith('0') or code.startswith('3'):
            return 'sz', code

    raise ValueError(f"Cannot normalize stock code: {symbol}")


def _is_etf(symbol: str) -> bool:
    """Check if the symbol is an ETF code.

    ETF code ranges:
    - Shanghai: 510000-519999 (e.g., 513060)
    - Shenzhen: 150000-169999 (e.g., 159707)
    """
    symbol = symbol.strip().upper()
    # Remove suffix if present
    if '.' in symbol:
        symbol = symbol.split('.')[0]

    if len(symbol) != 6:
        return False

    # Shanghai ETF: 51xxxx
    if symbol.startswith('51'):
        return True
    # Shenzhen ETF: 15xxxx or 16xxxx
    if symbol.startswith('15') or symbol.startswith('16'):
        return True

    return False


def _get_etf_secid(symbol: str) -> tuple[str, str]:
    """Get the correct secid for ETF.

    Returns:
        Tuple of (market, code) where market is 'sh' or 'sz'
    """
    symbol = symbol.strip().upper()
    if '.' in symbol:
        symbol = symbol.split('.')[0]

    # Shanghai ETF: secid starts with '0'
    if symbol.startswith('51'):
        return 'sh', symbol
    # Shenzhen ETF: secid starts with '1'
    elif symbol.startswith('15') or symbol.startswith('16'):
        return 'sz', symbol

    raise ValueError(f"Cannot normalize ETF code: {symbol}")


def _eastmoney_stock_secid(market: str, code: str) -> str:
    """Return Eastmoney secid for A-share stocks."""
    market_id = "1" if market == "sh" else "0"
    return f"{market_id}.{code}"


def _eastmoney_kline_df(secid: str, start_date: str, end_date: str) -> pd.DataFrame:
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": "101",
        "fqt": "1",
        "secid": secid,
        "beg": start_date.replace("-", ""),
        "end": end_date.replace("-", ""),
    }
    resp = _with_retries(lambda: requests.get(_EASTMONEY_KLINE_URL, params=params, timeout=15))
    resp.raise_for_status()
    payload = resp.json()
    klines = (payload.get("data") or {}).get("klines") or []
    if not klines:
        return pd.DataFrame()

    records = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 7:
            continue
        records.append({
            "日期": parts[0],
            "开盘": float(parts[1]),
            "收盘": float(parts[2]),
            "最高": float(parts[3]),
            "最低": float(parts[4]),
            "成交量": float(parts[5]),
            "成交额": float(parts[6]),
            "振幅": float(parts[7]) if len(parts) > 7 and parts[7] else 0,
            "涨跌幅": float(parts[8]) if len(parts) > 8 and parts[8] else 0,
            "涨跌额": float(parts[9]) if len(parts) > 9 and parts[9] else 0,
            "换手率": float(parts[10]) if len(parts) > 10 and parts[10] else 0,
        })
    return pd.DataFrame(records)


def _fetch_a_stock_hist_df(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    market, code = _normalize_a_stock_code(symbol)

    try:
        df = _with_retries(lambda: ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust="qfq",
        ))
        if df is not None and not df.empty:
            return df
    except Exception as exc:
        if not _is_transient_fetch_error(exc):
            raise

    return _eastmoney_kline_df(_eastmoney_stock_secid(market, code), start_date, end_date)


def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Get OHLCV stock data from AkShare.

    Args:
        symbol: Stock code (e.g., '600519.SS' for Kweichow Moutai, or ETF like '513060')
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        CSV string containing stock data
    """
    # Check if it's an ETF and route to get_etf_data
    if _is_etf(symbol):
        return get_etf_data(symbol, start_date, end_date)

    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")

    try:
        # Fetch historical data with retry and Eastmoney fallback.
        df = _fetch_a_stock_hist_df(symbol, start_date, end_date)

        if df.empty:
            return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

        # Rename columns to match expected format
        column_mapping = {
            '日期': 'Date',
            '开盘': 'Open',
            '收盘': 'Close',
            '最高': 'High',
            '最低': 'Low',
            '成交量': 'Volume',
            '成交额': 'Turnover',
            '振幅': 'Amplitude',
            '涨跌幅': 'Change_Pct',
            '涨跌额': 'Change',
            '换手率': 'Turnover_Rate'
        }
        df = df.rename(columns=column_mapping)

        # Format date
        df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')

        # Round numeric values
        numeric_cols = ['Open', 'High', 'Low', 'Close']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].round(2)

        # Convert to CSV
        csv_string = df.to_csv(index=False)

        header = f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
        header += f"# Total records: {len(df)}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + csv_string

    except Exception as e:
        return f"Error retrieving stock data for {symbol}: {str(e)}"


def get_etf_data(
    symbol: Annotated[str, "ticker symbol of the ETF"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Get OHLCV ETF data from AkShare.

    Args:
        symbol: ETF code (e.g., '513060' for Hangzhou Healthcare ETF)
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        CSV string containing ETF data
    """
    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")

    try:
        market, code = _get_etf_secid(symbol)

        # Try fund_etf_hist_em first - it works for most ETFs
        # Note: secid format in API is 0.xxxxx for Shanghai, 1.xxxxx for Shenzhen
        secid = f"0.{code}" if market == "sh" else f"1.{code}"

        try:
            df = ak.fund_etf_hist_em(
                symbol=code,
                period="daily",
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust="qfq"
            )
        except Exception:
            # Fallback: directly call eastmoney API with correct secid
            import requests
            url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "ut": "7eea3edcaed734bea9cbfc24409ed989",
                "klt": "101",  # daily
                "fqt": "1",   # qfq
                "secid": secid,
                "beg": start_date.replace('-', ''),
                "end": end_date.replace('-', ''),
            }
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()

            if data.get("data") is None or data["data"].get("klines") is None:
                return f"No data found for ETF '{symbol}' between {start_date} and {end_date}"

            klines = data["data"]["klines"]
            records = []
            for line in klines:
                parts = line.split(",")
                # Format: date,open,close,high,low,volume,amount,amp,pct,change,turnover
                records.append({
                    '日期': parts[0],
                    '开盘': float(parts[1]),
                    '收盘': float(parts[2]),
                    '最高': float(parts[3]),
                    '最低': float(parts[4]),
                    '成交量': float(parts[5]),
                    '成交额': float(parts[6]),
                    '涨跌幅': float(parts[8]) if len(parts) > 8 else 0,
                    '涨跌额': float(parts[9]) if len(parts) > 9 else 0,
                })
            df = pd.DataFrame(records)

        if df.empty:
            return f"No data found for ETF '{symbol}' between {start_date} and {end_date}"

        # Rename columns to match expected format
        column_mapping = {
            '日期': 'Date',
            '开盘': 'Open',
            '收盘': 'Close',
            '最高': 'High',
            '最低': 'Low',
            '成交量': 'Volume',
            '成交额': 'Turnover',
            '涨跌幅': 'Change_Pct',
            '涨跌额': 'Change',
        }
        df = df.rename(columns=column_mapping)

        # Format date
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')

        # Round numeric values
        numeric_cols = ['Open', 'High', 'Low', 'Close']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].round(2)

        # Convert to CSV
        csv_string = df.to_csv(index=False)

        header = f"# ETF data for {symbol.upper()} from {start_date} to {end_date}\n"
        header += f"# Total records: {len(df)}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + csv_string

    except Exception as e:
        return f"Error retrieving ETF data for {symbol}: {str(e)}"


def get_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """Get technical indicators from AkShare.

    Note: AkShare has limited technical indicator support compared to yfinance.
    This implementation provides MACD, RSI, and Bollinger Bands calculations.
    """
    # Indicator descriptions
    best_ind_params = {
        "close_50_sma": (
            "50 SMA: A medium-term trend indicator. "
            "Usage: Identify trend direction and serve as dynamic support/resistance. "
            "Tips: It lags price; combine with faster indicators for timely signals."
        ),
        "close_200_sma": (
            "200 SMA: A long-term trend benchmark. "
            "Usage: Confirm overall market trend and identify golden/death cross setups. "
            "Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries."
        ),
        "close_10_ema": (
            "10 EMA: A responsive short-term average. "
            "Usage: Capture quick shifts in momentum and potential entry points. "
            "Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals."
        ),
        "macd": (
            "MACD: Computes momentum via differences of EMAs. "
            "Usage: Look for crossovers and divergence as signals of trend changes. "
            "Tips: Confirm with other indicators in low-volatility or sideways markets."
        ),
        "macds": (
            "MACD Signal: An EMA smoothing of the MACD line. "
            "Usage: Use crossovers with the MACD line to trigger trades. "
            "Tips: Should be part of a broader strategy to avoid false positives."
        ),
        "macdh": (
            "MACD Histogram: Shows the gap between the MACD line and its signal. "
            "Usage: Visualize momentum strength and spot divergence early. "
            "Tips: Can be volatile; complement with additional filters in fast-moving markets."
        ),
        "rsi": (
            "RSI: Measures momentum to flag overbought/oversold conditions. "
            "Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. "
            "Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis."
        ),
        "boll": (
            "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. "
            "Usage: Acts as a dynamic benchmark for price movement. "
            "Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals."
        ),
        "boll_ub": (
            "Bollinger Upper Band: Typically 2 standard deviations above the middle line. "
            "Usage: Signals potential overbought conditions and breakout zones. "
            "Tips: Confirm signals with other tools; prices may ride the band in strong trends."
        ),
        "boll_lb": (
            "Bollinger Lower Band: Typically 2 standard deviations below the middle line. "
            "Usage: Indicates potential oversold conditions. "
            "Tips: Use additional analysis to avoid false reversal signals."
        ),
        "atr": (
            "ATR: Averages true range to measure volatility. "
            "Usage: Set stop-loss levels and adjust position sizes based on current market volatility. "
            "Tips: It's a reactive measure, so use it as part of a broader risk management strategy."
        ),
        "vwma": (
            "VWMA: A moving average weighted by volume. "
            "Usage: Confirm trends by integrating price action with volume data. "
            "Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses."
        ),
        "mfi": (
            "MFI: The Money Flow Index is a momentum indicator that uses both price and volume to measure buying and selling pressure. "
            "Usage: Identify overbought (>80) or oversold (<20) conditions and confirm the strength of trends or reversals. "
            "Tips: Use alongside RSI or MACD to confirm signals; divergence between price and MFI can indicate potential reversals."
        ),
    }

    if indicator not in best_ind_params:
        return f"Indicator '{indicator}' is not supported by AkShare. Supported indicators: {list(best_ind_params.keys())}"

    try:
        # Get stock data for calculation
        end_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        from dateutil.relativedelta import relativedelta
        warmup_days = max(30, _indicator_warmup_days(indicator))
        start_date_dt = end_date_dt - relativedelta(days=look_back_days + warmup_days)

        df = _fetch_a_stock_hist_df(
            symbol,
            start_date_dt.strftime("%Y-%m-%d"),
            curr_date,
        )

        if df.empty:
            return f"No data available for {symbol}"

        # Calculate indicators
        df = df.sort_values('日期')
        close_prices = df['收盘'].values

        result_lines = []
        curr_date_dt = end_date_dt

        # Calculate all needed values once
        if indicator in ['close_50_sma', 'close_200_sma', 'close_10_ema', 'macd', 'macds', 'macdh', 'rsi', 'boll', 'boll_ub', 'boll_lb', 'atr', 'vwma', 'mfi']:
            import numpy as np

            close = close_prices

            # Moving averages
            if indicator == 'close_50_sma':
                values = _sma(close, 50)
            elif indicator == 'close_200_sma':
                values = _sma(close, 200)
            elif indicator == 'close_10_ema':
                values = _ema(close, 10)
            # MACD
            elif indicator == 'macd':
                values = _macd(close)[0]
            elif indicator == 'macds':
                values = _macd(close)[1]
            elif indicator == 'macdh':
                values = _macd(close)[2]
            # RSI
            elif indicator == 'rsi':
                values = _rsi(close, 14)
            # Bollinger Bands
            elif indicator == 'boll':
                values = _bollinger_bands(close)[0]
            elif indicator == 'boll_ub':
                values = _bollinger_bands(close)[1]
            elif indicator == 'boll_lb':
                values = _bollinger_bands(close)[2]
            # ATR
            elif indicator == 'atr':
                high = df['最高'].values
                low = df['最低'].values
                values = _atr(high, low, close, 14)
            # VWMA
            elif indicator == 'vwma':
                volume = df['成交量'].values
                values = _vwma(close, volume, 20)
            # MFI
            elif indicator == 'mfi':
                high = df['最高'].values
                low = df['最低'].values
                volume = df['成交量'].values
                values = _mfi(high, low, close, volume, 14)

            # Generate date/value pairs for the look-back period
            dates = pd.to_datetime(df['日期']).dt.strftime('%Y-%m-%d').values
            valid_indicators = indicator in ['close_50_sma', 'close_200_sma', 'close_10_ema']

            for i, date_str in enumerate(dates):
                date_dt = datetime.strptime(date_str, '%Y-%m-%d')
                if date_dt <= end_date_dt and date_dt >= start_date_dt:
                    if i < len(values) and not np.isnan(values[i]):
                        result_lines.append(f"{date_str}: {values[i]:.2f}")
                    else:
                        result_lines.append(f"{date_str}: N/A")

        ind_string = "\n".join(result_lines[-look_back_days:]) if result_lines else "No data available"

        result_str = (
            f"## {indicator} values from {start_date_dt.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
            + ind_string + "\n\n"
            + best_ind_params.get(indicator, "No description available.")
        )

        return result_str

    except Exception as e:
        return f"Error getting indicators for {symbol}: {str(e)}"


def _sma(data, period):
    """Simple Moving Average"""
    import numpy as np
    result = np.full(len(data), np.nan)
    if len(data) < period:
        return result
    for i in range(period - 1, len(data)):
        result[i] = np.mean(data[i - period + 1:i + 1])
    return result


def _indicator_warmup_days(indicator: str) -> int:
    warmups = {
        "close_50_sma": 90,
        "close_200_sma": 320,
        "close_10_ema": 30,
        "macd": 90,
        "macds": 110,
        "macdh": 110,
        "rsi": 45,
        "boll": 45,
        "boll_ub": 45,
        "boll_lb": 45,
        "atr": 45,
        "vwma": 45,
        "mfi": 45,
    }
    return warmups.get(indicator, 30)


def _ema(data, period):
    """Exponential Moving Average"""
    import numpy as np
    result = np.full(len(data), np.nan)
    if len(data) < period:
        return result
    result[period - 1] = np.mean(data[:period])
    multiplier = 2 / (period + 1)
    for i in range(period, len(data)):
        result[i] = (data[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


def _macd(prices, fast=12, slow=26, signal=9):
    """MACD calculation"""
    import numpy as np
    ema_fast = np.full(len(prices), np.nan)
    ema_slow = np.full(len(prices), np.nan)
    if len(prices) < slow:
        return ema_fast, ema_slow, np.full(len(prices), np.nan)

    ema_fast[fast - 1] = np.mean(prices[:fast])
    ema_slow[slow - 1] = np.mean(prices[:slow])

    mult_fast = 2 / (fast + 1)
    mult_slow = 2 / (slow + 1)

    for i in range(fast, len(prices)):
        ema_fast[i] = (prices[i] - ema_fast[i - 1]) * mult_fast + ema_fast[i - 1]
    for i in range(slow, len(prices)):
        ema_slow[i] = (prices[i] - ema_slow[i - 1]) * mult_slow + ema_slow[i - 1]

    macd = ema_fast - ema_slow
    signal_line = _ema(macd[~np.isnan(macd)], signal)
    macd_signal = np.full(len(prices), np.nan)
    macd_signal[-len(signal_line):] = signal_line
    macd_hist = macd - macd_signal

    return macd, macd_signal, macd_hist


def _rsi(prices, period=14):
    """Relative Strength Index"""
    import numpy as np
    if len(prices) <= period:
        return np.full(len(prices), np.nan)
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    result = np.full(len(prices), np.nan)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        result[period] = 100
    else:
        rs = avg_gain / avg_loss
        result[period] = 100 - (100 / (1 + rs))

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100 - (100 / (1 + rs))

    return result


def _bollinger_bands(prices, period=20, std_dev=2):
    """Bollinger Bands"""
    import numpy as np
    middle = _sma(prices, period)
    std = np.full(len(prices), np.nan)
    for i in range(period - 1, len(prices)):
        std[i] = np.std(prices[i - period + 1:i + 1])
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return middle, upper, lower


def _atr(high, low, close, period=14):
    """Average True Range"""
    import numpy as np
    tr = np.full(len(high), np.nan)
    if len(high) == 0:
        return tr
    tr[0] = high[0] - low[0]
    for i in range(1, len(high)):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )
    return _sma(tr, period)


def _vwma(close, volume, period):
    """Volume Weighted Moving Average"""
    import numpy as np
    result = np.full(len(close), np.nan)
    if len(close) < period:
        return result
    for i in range(period - 1, len(close)):
        volume_sum = np.sum(volume[i - period + 1:i + 1])
        if volume_sum:
            result[i] = np.sum(close[i - period + 1:i + 1] * volume[i - period + 1:i + 1]) / volume_sum
    return result


def _mfi(high, low, close, volume, period=14):
    """Money Flow Index"""
    import numpy as np
    if len(close) <= period:
        return np.full(len(close), np.nan)
    typical_price = (high + low + close) / 3
    money_flow = typical_price * volume

    result = np.full(len(close), np.nan)
    positive_flow = np.where(typical_price[1:] > typical_price[:-1], money_flow[1:], 0)
    negative_flow = np.where(typical_price[1:] < typical_price[:-1], money_flow[1:], 0)

    for i in range(period, len(close)):
        pos_flow = np.sum(positive_flow[i - period:i])
        neg_flow = np.sum(negative_flow[i - period:i])
        if neg_flow == 0:
            result[i] = 100
        else:
            money_ratio = pos_flow / neg_flow
            result[i] = 100 - (100 / (1 + money_ratio))

    return result


def get_fundamentals(
    symbol: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "current date (not used for akshare)"] = None,
) -> str:
    """Get company fundamentals overview from AkShare."""
    try:
        market, code = _normalize_a_stock_code(symbol)

        # Get stock info
        df = ak.stock_individual_info_em(symbol=code)
        if df is None or df.empty:
            return f"No fundamentals data found for symbol '{symbol}'"

        # Convert to key-value format
        info_dict = dict(zip(df['item'], df['value']))

        # Common fields to display
        fields = [
            ("股票代码", "Code"),
            ("股票名称", "Name"),
            ("总市值", "Total_Market_Cap"),
            ("流通市值", "Circulating_Market_Cap"),
            ("市盈率-动态", "PE_TTM"),
            ("市净率", "PB"),
            ("换手率", "Turnover_Rate"),
            ("振幅", "Amplitude"),
            ("涨跌幅", "Change_Pct"),
            ("涨跌额", "Change"),
            ("成交量", "Volume"),
            ("成交额", "Turnover"),
            ("市盈率(动态)", "PE_Dynamic"),
            ("市销率(动态)", "PS_Dynamic"),
        ]

        lines = []
        for field_key, display_name in fields:
            if field_key in info_dict:
                lines.append(f"{display_name}: {info_dict[field_key]}")

        header = f"# Company Fundamentals for {symbol.upper()}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + "\n".join(lines) if lines else f"No fundamentals data for {symbol}"

    except Exception as e:
        return f"Error retrieving fundamentals for {symbol}: {str(e)}"


def get_balance_sheet(
    symbol: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get balance sheet data from AkShare."""
    try:
        market, code = _normalize_a_stock_code(symbol)

        period = "4" if freq.lower() == "annual" else "4"  # AkShare uses '4' for annual, '4' for quarterly by default
        df = ak.stock_balance_sheet_em(symbol=code)

        if df is None or df.empty:
            return f"No balance sheet data found for symbol '{symbol}'"

        # Convert to CSV string
        csv_string = df.to_csv(index=False)

        header = f"# Balance Sheet data for {symbol.upper()} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + csv_string

    except Exception as e:
        return f"Error retrieving balance sheet for {symbol}: {str(e)}"


def get_cashflow(
    symbol: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get cash flow data from AkShare."""
    try:
        market, code = _normalize_a_stock_code(symbol)

        df = ak.stock_cash_flow_em(symbol=code)

        if df is None or df.empty:
            return f"No cash flow data found for symbol '{symbol}'"

        csv_string = df.to_csv(index=False)

        header = f"# Cash Flow data for {symbol.upper()} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + csv_string

    except Exception as e:
        return f"Error retrieving cash flow for {symbol}: {str(e)}"


def get_income_statement(
    symbol: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get income statement data from AkShare."""
    try:
        market, code = _normalize_a_stock_code(symbol)

        df = ak.stock_profit_sheet_by_report_em(symbol=code)

        if df is None or df.empty:
            return f"No income statement data found for symbol '{symbol}'"

        csv_string = df.to_csv(index=False)

        header = f"# Income Statement data for {symbol.upper()} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + csv_string

    except Exception as e:
        return f"Error retrieving income statement for {symbol}: {str(e)}"


def get_news(
    ticker: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"] = None,
    end_date: Annotated[str, "End date in yyyy-mm-dd format"] = None,
) -> str:
    """Get news data from AkShare for a specific stock.

    Note: AkShare's news API doesn't support date filtering, so start_date
    and end_date are accepted for compatibility but not used.
    """
    try:
        market, code = _normalize_a_stock_code(ticker)

        df = ak.stock_news_em(symbol=code)

        if df is None or df.empty:
            return f"No news data found for symbol '{ticker}'"

        # Limit to recent news
        df = df.head(20)

        lines = []
        for _, row in df.iterrows():
            lines.append(f"### {row.get('发布时间', 'N/A')}: {row.get('新闻标题', 'No title')}")
            content = str(row.get('新闻内容', 'No content'))
            lines.append(content[:500] if len(content) > 500 else content)
            lines.append("")

        header = f"# News for {ticker.upper()}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + "\n".join(lines)

    except Exception as e:
        return f"Error retrieving news for {ticker}: {str(e)}"


def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"] = None,
    look_back_days: Annotated[int, "Number of days to look back"] = 7,
    limit: Annotated[int, "Maximum number of articles to return"] = 5,
) -> str:
    """Get global financial news from AkShare.

    Note: curr_date and look_back_days are accepted for compatibility but
    not used by AkShare's news API.
    """
    try:
        # AkShare doesn't support date-filtered global news, so we just fetch recent
        df = ak.stock_news_em(symbol="000001")  # Use a general symbol to get market news

        if df is None or df.empty:
            return "No global news available"

        lines = []
        for _, row in df.head(limit).iterrows():
            lines.append(f"### {row.get('发布时间', 'N/A')}: {row.get('新闻标题', 'No title')}")
            content = str(row.get('新闻内容', 'No content'))
            lines.append(content[:300] if len(content) > 300 else content)
            lines.append("")

        header = "# Global Financial News\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + "\n".join(lines)

    except Exception as e:
        return f"Error retrieving global news: {str(e)}"


def get_insider_transactions(
    symbol: Annotated[str, "ticker symbol of the company"]
) -> str:
    """Get insider transactions from AkShare (limited support)."""
    try:
        market, code = _normalize_a_stock_code(symbol)

        # Try to get index component changes as a proxy for insider activity
        df = ak.stock_changes_em(symbol=code)

        if df is None or df.empty:
            return f"No insider transaction data found for symbol '{symbol}'"

        csv_string = df.head(50).to_csv(index=False)

        header = f"# Stock Changes/Insider Activity for {symbol.upper()}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + csv_string

    except Exception as e:
        return f"Error retrieving insider transactions for {symbol}: {str(e)}"


# =============================================================================
# Tonghuashun (THS) Financial Data Sources - More Stable
# =============================================================================


def _parse_financial_number(val) -> float:
    """Parse Chinese financial number strings (e.g., '1.47亿' -> 147000000)."""
    if val is None:
        return None

    if isinstance(val, (int, float)):
        return float(val)

    val_str = str(val).strip()

    if val_str.upper() == "FALSE" or val_str == "":
        return None

    try:
        if "亿" in val_str:
            return float(val_str.replace("亿", "").replace(",", "")) * 1e8
        elif "万" in val_str:
            return float(val_str.replace("万", "").replace(",", "")) * 1e4
        elif "%" in val_str:
            return float(val_str.replace("%", "").replace(",", ""))
        else:
            return float(val_str.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def get_stock_financial_summary(
    symbol: Annotated[str, "ticker symbol of the company"],
    include_optional: Annotated[bool, "whether to include optional/auxiliary data"] = False,
) -> str:
    """Get comprehensive financial data from Tonghuashun (THS) sources.

    This includes:
    - Net income, revenue, profit margins
    - Total shares
    - Cash and equivalents
    - Interest-bearing debt
    - Free cash flow (FCF)

    Args:
        symbol: Stock code (e.g., '600519.SS' or '000001.SZ')
        include_optional: Whether to include auxiliary data (revenue, margins, etc.)

    Returns:
        Formatted string with financial data
    """
    try:
        market, code = _normalize_a_stock_code(symbol)

        result_lines = []
        result_lines.append(f"# Financial Summary for {symbol.upper()}")
        result_lines.append(f"# Data source: Tonghuashun (THS)")
        result_lines.append(f"# Retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        result_lines.append("")

        # 1. Financial abstract (net income, margins)
        try:
            df = ak.stock_financial_abstract_ths(symbol=code)
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                report_date = latest.get('报告期', 'N/A')
                result_lines.append(f"## Report Period: {report_date}")
                result_lines.append("")

                net_income = _parse_financial_number(latest.get("净利润"))
                if net_income is not None:
                    result_lines.append(f"Net Income (净利润): {net_income:,.2f} RMB")

                revenue = _parse_financial_number(latest.get("营业总收入"))
                if revenue is not None:
                    result_lines.append(f"Revenue (营业总收入): {revenue:,.2f} RMB")

                net_margin = _parse_financial_number(latest.get("销售净利率"))
                if net_margin is not None:
                    result_lines.append(f"Net Margin (销售净利率): {net_margin}%")

                gross_margin = _parse_financial_number(latest.get("销售毛利率"))
                if gross_margin is not None:
                    result_lines.append(f"Gross Margin (销售毛利率): {gross_margin}%")

                debt_ratio = _parse_financial_number(latest.get("资产负债率"))
                if debt_ratio is not None:
                    result_lines.append(f"Debt-to-Asset Ratio (资产负债率): {debt_ratio}%")

                op_cf_per_share = _parse_financial_number(latest.get("每股经营现金流"))
                if op_cf_per_share is not None:
                    result_lines.append(f"Operating CF per Share (每股经营现金流): {op_cf_per_share}")

                if include_optional:
                    result_lines.append("")
                    result_lines.append("## Additional Metrics")
                    if revenue is not None:
                        result_lines.append(f"Revenue: {revenue:,.2f}")
                    if gross_margin is not None:
                        result_lines.append(f"Gross Margin: {gross_margin}%")
                    if net_margin is not None:
                        result_lines.append(f"Net Margin: {net_margin}%")
                    if debt_ratio is not None:
                        result_lines.append(f"Debt-to-Asset Ratio: {debt_ratio}%")
        except Exception as e:
            result_lines.append(f"Financial abstract error: {e}")

        result_lines.append("")

        # 2. Total shares
        try:
            df = ak.stock_share_change_cninfo(symbol=code)
            if df is not None and not df.empty and "总股本" in df.columns:
                for i in range(len(df)):
                    val = df.iloc[i]["总股本"]
                    if val is not None and not pd.isna(val):
                        total_shares = float(val)
                        result_lines.append(f"Total Shares (总股本): {total_shares:,.0f} shares")
                        break
        except Exception as e:
            result_lines.append(f"Total shares error: {e}")

        result_lines.append("")

        # 3. Cash and equivalents
        try:
            df = ak.stock_financial_debt_ths(symbol=code)
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                cash = _parse_financial_number(latest.get("货币资金"))
                if cash is not None:
                    result_lines.append(f"Cash & Equivalents (货币资金): {cash:,.2f} RMB")
        except Exception as e:
            result_lines.append(f"Cash data error: {e}")

        result_lines.append("")

        # 4. Interest-bearing debt
        try:
            df = ak.stock_financial_debt_ths(symbol=code)
            if df is not None and not df.empty:
                latest = df.iloc[-1]

                short_term = _parse_financial_number(latest.get("短期借款")) or 0
                long_term = _parse_financial_number(latest.get("长期借款")) or 0
                bonds = _parse_financial_number(latest.get("应付债券")) or 0
                non_current_due = _parse_financial_number(latest.get("一年内到期的非流动负债")) or 0

                total_debt = short_term + long_term + bonds + non_current_due
                result_lines.append(f"Interest-Bearing Debt (有息负债): {total_debt:,.2f} RMB")
                result_lines.append(f"  - Short-term Loans (短期借款): {short_term:,.2f}")
                result_lines.append(f"  - Long-term Loans (长期借款): {long_term:,.2f}")
                result_lines.append(f"  - Bonds Payable (应付债券): {bonds:,.2f}")
                result_lines.append(f"  - Non-current Liabilities Due (一年内到期): {non_current_due:,.2f}")
        except Exception as e:
            result_lines.append(f"Debt data error: {e}")

        result_lines.append("")

        # 5. Free Cash Flow
        try:
            cash_df = ak.stock_financial_cash_ths(symbol=code)
            if cash_df is not None and not cash_df.empty:
                latest = cash_df.iloc[0]

                net_income = _parse_financial_number(latest.get("净利润")) or 0
                depreciation = _parse_financial_number(latest.get("固定资产折旧、油气资产折耗、生产性生物资产折旧")) or 0
                amortization = _parse_financial_number(latest.get("无形资产摊销")) or 0
                long_term_deferred = _parse_financial_number(latest.get("长期待摊费用摊销")) or 0
                capex = _parse_financial_number(latest.get("购建固定资产、无形资产和其他长期资产支付的现金")) or 0

                inventory_dec = _parse_financial_number(latest.get("存货的减少")) or 0
                op_receivable_dec = _parse_financial_number(latest.get("经营性应收项目的减少")) or 0
                op_payable_inc = _parse_financial_number(latest.get("经营性应付项目的增加")) or 0
                working_capital_change = inventory_dec + op_receivable_dec + op_payable_inc

                fcf = net_income + (depreciation + amortization + long_term_deferred) - capex + working_capital_change
                result_lines.append(f"Free Cash Flow (自由现金流): {fcf:,.2f} RMB")
                result_lines.append(f"  - Net Income: {net_income:,.2f}")
                result_lines.append(f"  - D&A: {depreciation + amortization + long_term_deferred:,.2f}")
                result_lines.append(f"  - Capex: {capex:,.2f}")
                result_lines.append(f"  - Working Capital Change: {working_capital_change:,.2f}")
        except Exception as e:
            result_lines.append(f"FCF calculation error: {e}")

        return "\n".join(result_lines)

    except Exception as e:
        return f"Error retrieving financial summary for {symbol}: {str(e)}"


def get_financial_data_json(
    symbol: Annotated[str, "ticker symbol of the company"],
    include_optional: Annotated[bool, "whether to include optional/auxiliary data"] = False,
) -> dict:
    """Get financial data as a dictionary (for programmatic use).

    Returns:
        Dictionary with financial data fields
    """
    import json

    try:
        market, code = _normalize_a_stock_code(symbol)

        result = {
            "stock_code": code,
            "market": market,
            "report_date": datetime.now().strftime("%Y-%m-%d"),
            "required_data": {},
            "optional_data": {},
            "errors": [],
        }

        # 1. Financial abstract
        try:
            df = ak.stock_financial_abstract_ths(symbol=code)
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                net_income = _parse_financial_number(latest.get("净利润"))
                if net_income is not None:
                    result["required_data"]["net_income"] = net_income

                revenue = _parse_financial_number(latest.get("营业总收入"))
                if revenue is not None:
                    result["optional_data"]["revenue"] = revenue

                net_margin = _parse_financial_number(latest.get("销售净利率"))
                if net_margin is not None:
                    result["optional_data"]["net_margin"] = net_margin

                gross_margin = _parse_financial_number(latest.get("销售毛利率"))
                if gross_margin is not None:
                    result["optional_data"]["gross_margin"] = gross_margin

                debt_ratio = _parse_financial_number(latest.get("资产负债率"))
                if debt_ratio is not None:
                    result["optional_data"]["debt_to_asset_ratio"] = debt_ratio
            else:
                result["errors"].append("Financial abstract unavailable")
        except Exception as e:
            result["errors"].append(f"Financial abstract: {e}")

        # 2. Total shares
        try:
            df = ak.stock_share_change_cninfo(symbol=code)
            if df is not None and not df.empty and "总股本" in df.columns:
                for i in range(len(df)):
                    val = df.iloc[i]["总股本"]
                    if val is not None and not pd.isna(val):
                        result["required_data"]["total_shares"] = float(val)
                        break
        except Exception as e:
            result["errors"].append(f"Total shares: {e}")

        # 3. Cash
        try:
            df = ak.stock_financial_debt_ths(symbol=code)
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                cash = _parse_financial_number(latest.get("货币资金"))
                if cash is not None:
                    result["required_data"]["cash_and_equivalents"] = cash
        except Exception as e:
            result["errors"].append(f"Cash data: {e}")

        # 4. Interest-bearing debt
        try:
            df = ak.stock_financial_debt_ths(symbol=code)
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                short_term = _parse_financial_number(latest.get("短期借款")) or 0
                long_term = _parse_financial_number(latest.get("长期借款")) or 0
                bonds = _parse_financial_number(latest.get("应付债券")) or 0
                non_current_due = _parse_financial_number(latest.get("一年内到期的非流动负债")) or 0
                total_debt = short_term + long_term + bonds + non_current_due
                result["required_data"]["interest_bearing_debt"] = total_debt
                result["required_data"]["_debt_detail"] = {
                    "short_term_loan": short_term,
                    "long_term_loan": long_term,
                    "bonds_payable": bonds,
                    "non_current_liabilities_due": non_current_due,
                }
        except Exception as e:
            result["errors"].append(f"Debt data: {e}")

        # 5. Free Cash Flow
        try:
            cash_df = ak.stock_financial_cash_ths(symbol=code)
            if cash_df is not None and not cash_df.empty:
                latest = cash_df.iloc[0]
                net_income = _parse_financial_number(latest.get("净利润")) or 0
                depreciation = _parse_financial_number(latest.get("固定资产折旧、油气资产折耗、生产性生物资产折旧")) or 0
                amortization = _parse_financial_number(latest.get("无形资产摊销")) or 0
                long_term_deferred = _parse_financial_number(latest.get("长期待摊费用摊销")) or 0
                capex = _parse_financial_number(latest.get("购建固定资产、无形资产和其他长期资产支付的现金")) or 0
                inventory_dec = _parse_financial_number(latest.get("存货的减少")) or 0
                op_receivable_dec = _parse_financial_number(latest.get("经营性应收项目的减少")) or 0
                op_payable_inc = _parse_financial_number(latest.get("经营性应付项目的增加")) or 0
                working_capital_change = inventory_dec + op_receivable_dec + op_payable_inc
                fcf = net_income + (depreciation + amortization + long_term_deferred) - capex + working_capital_change
                result["required_data"]["free_cash_flow"] = round(fcf, 2)
        except Exception as e:
            result["errors"].append(f"FCF calculation: {e}")

        return result

    except Exception as e:
        return {"error": str(e)}
