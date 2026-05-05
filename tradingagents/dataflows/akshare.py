"""AkShare data source for TradingAgents.

AkShare is a Chinese financial data source that provides comprehensive
A-share market data, fundamentals, and news.
"""

from typing import Annotated
from datetime import datetime
import pandas as pd
import akshare as ak


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


def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Get OHLCV stock data from AkShare.

    Args:
        symbol: Stock code (e.g., '600519.SS' for Kweichow Moutai)
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        CSV string containing stock data
    """
    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")

    try:
        market, code = _normalize_a_stock_code(symbol)

        # Fetch historical data
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
            adjust="qfq"
        )

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
        market, code = _normalize_a_stock_code(symbol)

        # Get stock data for calculation
        end_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        from dateutil.relativedelta import relativedelta
        start_date_dt = end_date_dt - relativedelta(days=look_back_days + 30)  # Extra buffer

        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date_dt.strftime('%Y%m%d'),
            end_date=curr_date.replace('-', ''),
            adjust="qfq"
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
    for i in range(period - 1, len(data)):
        result[i] = np.mean(data[i - period + 1:i + 1])
    return result


def _ema(data, period):
    """Exponential Moving Average"""
    import numpy as np
    result = np.full(len(data), np.nan)
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
    for i in range(period - 1, len(close)):
        result[i] = np.sum(close[i - period + 1:i + 1] * volume[i - period + 1:i + 1]) / np.sum(volume[i - period + 1:i + 1])
    return result


def _mfi(high, low, close, volume, period=14):
    """Money Flow Index"""
    import numpy as np
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
    symbol: Annotated[str, "ticker symbol of the company"],
) -> str:
    """Get news data from AkShare for a specific stock."""
    try:
        market, code = _normalize_a_stock_code(symbol)

        df = ak.stock_news_em(symbol=code)

        if df is None or df.empty:
            return f"No news data found for symbol '{symbol}'"

        # Limit to recent news
        df = df.head(20)

        lines = []
        for _, row in df.iterrows():
            lines.append(f"### {row.get('发布时间', 'N/A')}: {row.get('新闻标题', 'No title')}")
            lines.append(f"{row.get('新闻内容', 'No content')[:500]}")
            lines.append("")

        header = f"# News for {symbol.upper()}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + "\n".join(lines)

    except Exception as e:
        return f"Error retrieving news for {symbol}: {str(e)}"


def get_global_news() -> str:
    """Get global financial news from AkShare."""
    try:
        df = ak.stock_news_read_news(link="")

        if df is None or df.empty:
            return "No global news available"

        lines = []
        for _, row in df.head(20).iterrows():
            lines.append(f"### {row.get('发布时间', 'N/A')}: {row.get('新闻标题', 'No title')}")
            lines.append(f"{row.get('新闻内容', 'No content')[:300]}")
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
