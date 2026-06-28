"""China MM Fear & Greed Index fetcher — A-share market sentiment.

Primary source: MacroMicro China Fear & Greed Index (market-wide, 0-100 scale).
The Macromicro chart is rendered client-side via JS, so we use DrissionPage
(headless Chromium) to load the page and extract the actual current value.

Fallback chain (all paths return a string):
  1. DrissionPage → scrape macromicro.me page for actual Fear & Greed value
  2. Per-ticker sentiment from AKShare (东方财富综合评分, 参与意愿, etc.)
  3. Market-wide sentiment composite from AKShare (up/down ratio, fund flow)
  4. Shanghai / Shenzhen composite index performance as a rough proxy
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_FEAR_GREED_URL = "https://en.macromicro.me/series/46919/china-mm-fear-and-greed-index"

# Cached browser instance for DrissionPage
_browser_cache: dict = {}
_BROWSER_TIMEOUT = 30


def _get_browser_page():
    """Return a configured DrissionPage ChromiumPage, reusing the cached browser."""
    if "page" in _browser_cache:
        return _browser_cache["page"]

    from DrissionPage import ChromiumPage, ChromiumOptions

    co = ChromiumOptions()
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-gpu")
    co.set_argument("--disable-dev-shm-usage")
    co.set_user_agent(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    co.set_load_mode("normal")
    co.set_argument("--lang=en-US")

    page = ChromiumPage(co)
    _browser_cache["page"] = page
    return page


def _teardown_browser():
    """Close cached browser instance if active."""
    page = _browser_cache.pop("page", None)
    if page is not None:
        try:
            page.quit()
        except Exception:
            pass


def fetch_fear_greed_index(ticker: str = "", curr_date: str | None = None) -> str:
    """Fetch China market fear & greed sentiment data.

    Args:
        ticker: Stock symbol. When provided, per-stock sentiment from
            AKShare (东方财富) is included.
        curr_date: Reference date (yyyy-mm-dd). Defaults to today.

    Returns:
        A formatted plaintext block describing current market sentiment,
        ready for prompt injection. Returns a placeholder string when all
        sources are unreachable.
    """
    if curr_date is None:
        curr_date = datetime.now().strftime("%Y-%m-%d")

    # --- Strategy 1: DrissionPage → MacroMicro Fear & Greed Index value ---
    macro_value = _fetch_macromicro_value()
    if macro_value is not None:
        # Include per-stock data as supplement
        per_stock = _fetch_per_stock_sentiment(ticker) if ticker else None
        if per_stock:
            return macro_value + "\n\n" + per_stock
        return macro_value

    # --- Strategy 2: per-ticker sentiment from AKShare (东方财富综合评分) ---
    if ticker:
        per_stock = _fetch_per_stock_sentiment(ticker)
        if per_stock is not None:
            return per_stock

    # --- Strategy 3: market-wide sentiment composite from AKShare ---
    market_data = _fetch_market_sentiment_composite(curr_date)
    if market_data is not None:
        return market_data

    # --- Strategy 4: fall back to index performance proxy ---
    return _fetch_index_performance_proxy(ticker, curr_date)


# ---------------------------------------------------------------------------
# Strategy 1: DrissionPage → MacroMicro Fear & Greed value
# ---------------------------------------------------------------------------

def _fetch_macromicro_value() -> str | None:
    """Load the MacroMicro chart page via DrissionPage and extract the
    actual China MM Fear & Greed Index value from the rendered DOM.

    The page renders the current value (0-100 scale) client-side via
    Highcharts. DrissionPage lets the JS execute, then we extract the
    number from elements matching the "Fear and Greed Index" + numeric
    value pattern.
    """
    try:
        page = _get_browser_page()
        logger.info("Macromicro: loading %s", _FEAR_GREED_URL)
        page.get(_FEAR_GREED_URL, timeout=_BROWSER_TIMEOUT)
        time.sleep(10)  # wait for JS rendering + Cloudflare

        body = page.run_js("return document.body.innerText")

        # Extract: body text contains pattern:
        #   "China - MM Fear and Greed Index\n2026 W26\n44.81\n 10.59"
        match = re.search(
            r"Fear\s+and\s+Greed\s+Index\s*\n"
            r"[^\n]*\n"       # period line (e.g. "2026 W26")
            r"\s*([\d.]+)",   # the actual index value
            body, re.IGNORECASE
        )
        if not match:
            # Fallback: find any 2-3 digit number near "Fear and Greed"
            nums = re.findall(
                r"Fear\s+and\s+Greed.{0,200}?(\d+\.?\d*)",
                body, re.DOTALL | re.IGNORECASE
            )
            if not nums:
                logger.debug("Could not extract F&G value from macro page")
                return None
            value = nums[0]
        else:
            value = match.group(1)

        # Extract the period (week label)
        period_match = re.search(r"(\d{4}\s+W\d+)", body)
        period = period_match.group(1) if period_match else ""

        # Extract change
        change_match = re.search(
            r"Fear\s+and\s+Greed\s+Index\s*\n"
            r"[^\n]*\n"
            r"\s*[\d.]+\s*\n"
            r"\s*([+\-–—]?[\d.]+)",
            body, re.IGNORECASE
        )
        change_str = change_match.group(1).strip() if change_match else ""

        # Determine sentiment band
        try:
            val_f = float(value)
        except ValueError:
            val_f = 50.0  # fallback

        if val_f >= 70:
            band = "🟢 Greed (贪婪)"
            zone = "Greed"
        elif val_f >= 55:
            band = "🟡 Mild Greed (偏贪婪)"
            zone = "Greed"
        elif val_f >= 45:
            band = "⚪ Neutral (中性)"
            zone = "Neutral"
        elif val_f >= 30:
            band = "🟠 Mild Fear (偏恐惧)"
            zone = "Fear"
        else:
            band = "🔴 Fear (恐惧)"
            zone = "Fear"

        result = (
            f"## China MM Fear & Greed Index\n"
            f"Source: MacroMicro (en.macromicro.me/series/46919)\n"
            f"Period: {period}\n"
            f"Current Value: **{value}** / 100 — {band}\n"
        )
        if change_str:
            # Remove leading + for consistent display
            change_str = change_str.lstrip("+")
            result += f"Weekly Change: {change_str}\n"

        result += (
            f"\nScale: 0 (Extreme Fear) to 100 (Extreme Greed)\n"
            f"Reading: Values above 70 indicate market optimism (greed); "
            f"below 30 indicate market pessimism (fear).\n"
            f"The current value of **{value}** is in the "
            f"{zone} zone.\n"
        )

        return result

    except ImportError:
        logger.debug("DrissionPage not installed; skipping Macromicro browser scrape")
        return None
    except Exception as exc:
        logger.debug("Macromicro browser scrape failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Strategy 2-4: AKShare-based strategies
# ---------------------------------------------------------------------------

def _fetch_per_stock_sentiment(ticker: str) -> str | None:
    """Fetch per-stock sentiment from 东方财富 (East Money) composite score.

    Uses AKShare's stock_comment_em() which provides 综合得分 (composite score),
    关注指数 (attention index), 机构参与度 (institutional participation).
    """
    try:
        import akshare as ak
        import pandas as pd

        # Normalize to 6-digit code
        code = ticker.upper().replace(".SS", "").replace(".SZ", "").replace(".SH", "").replace(".BJ", "")
        if not code.isdigit() or len(code) != 6:
            return None

        df = ak.stock_comment_em()
        if df is None or df.empty:
            return None

        row = df[df["代码"] == code]
        if row.empty:
            return None

        r = row.iloc[0]
        trade_date = r.get("交易日", "")
        if hasattr(trade_date, "strftime"):
            trade_date = trade_date.strftime("%Y-%m-%d")
        return (
            f"## 个股综合情绪 — {r.get('名称', ticker)} ({code})\n"
            f"Source: 东方财富 (East Money) — 综合评分系统\n"
            f"Date: {trade_date}\n\n"
            f"| 指标 | 数值 |\n"
            f"|------|------|\n"
            f"| 综合得分 | {r.get('综合得分', 'N/A')} (0-100, 越高越积极) |\n"
            f"| 机构参与度 | {r.get('机构参与度', 'N/A')} |\n"
            f"| 关注指数 | {r.get('关注指数', 'N/A')} |\n"
            f"| 目前排名 | {r.get('目前排名', 'N/A')} |\n"
            f"| 上升/下降 | {r.get('上升', 'N/A')} |\n"
            f"| 涨跌幅 | {r.get('涨跌幅', 'N/A')}% |\n"
            f"| 换手率 | {r.get('换手率', 'N/A')}% |\n"
            f"| 市盈率 | {r.get('市盈率', 'N/A')} |\n"
            f"| 最新价 | {r.get('最新价', 'N/A')} |\n"
        )
    except Exception as exc:
        logger.debug("Per-stock sentiment failed for %s: %s", ticker, exc)
        return None


def _fetch_market_sentiment_composite(curr_date: str) -> str | None:
    """Build a market-wide sentiment composite from AKShare data.

    Combines fund flow data, market activity (up/down/limit-up), and
    overall market temperature.
    """
    try:
        import akshare as ak

        lines = ["## 中国市场整体情绪", "Source: AKShare (东方财富)", f"Date: {curr_date}", ""]

        # --- Market activity ---
        try:
            activity = ak.stock_market_activity_legu()
            if activity is not None and not activity.empty:
                act_map = dict(zip(activity["item"], activity["value"]))
                lines.append("### 市场活跃度")
                lines.append(f"- 上涨家数: {act_map.get('上涨', 'N/A')}")
                lines.append(f"- 涨停家数: {act_map.get('涨停', 'N/A')}")
                lines.append(f"- 真实涨停: {act_map.get('真实涨停', 'N/A')}")
                lines.append(f"- 下跌家数: {act_map.get('下跌', 'N/A')}")
                lines.append(f"- 跌停家数: {act_map.get('跌停', 'N/A')}")
                lines.append(f"- 真实跌停: {act_map.get('真实跌停', 'N/A')}")
                lines.append("")
        except Exception as exc:
            logger.debug("Market activity fetch failed: %s", exc)

        # --- Fund flow (主力资金流向) ---
        try:
            fund_flow = ak.stock_market_fund_flow()
            if fund_flow is not None and not fund_flow.empty:
                latest = fund_flow.iloc[-1]
                lines.append("### 资金流向")
                lines.append(f"- 上证指数: {latest.get('上证-收盘价', 'N/A')} ({latest.get('上证-涨跌幅', 'N/A')}%)")
                lines.append(f"- 深证成指: {latest.get('深证-收盘价', 'N/A')} ({latest.get('深证-涨跌幅', 'N/A')}%)")
                # Format fund flow in 亿
                net = latest.get("主力净流入-净额", 0)
                if isinstance(net, (int, float)):
                    net_yi = net / 1e8
                    lines.append(f"- 主力净流入: {net_yi:+.2f}亿")
                net_pct = latest.get("主力净流入-净占比", "")
                lines.append(f"- 主力净占比: {net_pct}%")
                lines.append("")
        except Exception as exc:
            logger.debug("Fund flow fetch failed: %s", exc)

        return "\n".join(lines) if len(lines) > 3 else None

    except Exception as exc:
        logger.debug("Market sentiment composite failed: %s", exc)
        return None


def _fetch_index_performance_proxy(ticker: str, curr_date: str) -> str:
    """Fallback: return Shanghai/Shenzhen composite performance as sentiment proxy.

    When stock-specific data is unavailable, use the broader market index
    (SH for Shanghai-listed stocks, SZ for Shenzhen-listed) as a rough
    sentiment proxy.
    """
    # Determine which index to query based on ticker
    code_upper = ticker.upper() if ticker else ""
    if code_upper.endswith(".SZ") or (code_upper[:1] in ("0", "2", "3") and code_upper[:6].isdigit()):
        index_code = "399001"  # 深证成指
        index_name = "深证成指 (Shenzhen Composite)"
    else:
        index_code = "000001"  # 上证指数
        index_name = "上证指数 (Shanghai Composite)"

    return (
        f"## 市场情绪参考 — {index_name}\n"
        f"(个股情绪数据暂时不可用，使用市场指数作为情绪代理)\n\n"
        f"被分析的个股 ({ticker or '未指定'}) 属于{index_name}覆盖范围。\n"
        f"建议参考大盘走势、涨跌比和资金流向判断当前市场情绪。\n"
        f"实时指数数据可通过 ak.stock_zh_index_daily() 获取。\n"
    )
