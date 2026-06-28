"""Xueqiu (雪球) stock discussion fetcher — A-share social sentiment.

Primary source: Xueqiu (https://xueqiu.com), China's largest stock
discussion community with 20M+ registered users.

The Xueqiu API is behind Alibaba Cloud WAF. This implementation bypasses
the WAF by using DrissionPage (headless Chromium automation) to load the
stock page directly and extract discussion posts from the rendered DOM,
preserving usernames, timestamps, post bodies, and engagement metrics.

Fallback chain (all paths return a string):
  1. DrissionPage → scrape stock page DOM for discussion posts
  2. AKShare community sentiment (综合评分, 参与意愿, 用户关注指数)
  3. Shanghai/Shenzhen composite (market-level fallback)
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_BROWSER_TIMEOUT = 30


def fetch_xueqiu_posts(
    ticker: str,
    limit: int = 20,
    curr_date: str | None = None,
) -> str:
    """Fetch stock discussion posts/sentiment for an A-share ticker.

    Args:
        ticker: Stock symbol. Supports 6-digit codes, with or without
            exchange suffix (e.g. ``600519``, ``002475.SZ``, ``SH600519``).
        limit: Max posts/comments to fetch.
        curr_date: Reference date (yyyy-mm-dd). Defaults to today.

    Returns:
        A formatted plaintext block of discussion data ready for prompt
        injection. Returns a placeholder string when all sources fail.
    """
    if curr_date is None:
        curr_date = datetime.now().strftime("%Y-%m-%d")

    code = _normalize_code(ticker)

    # --- Strategy 1: DrissionPage → scrape Xueqiu stock page DOM ---
    xueqiu_data = _fetch_xueqiu_dom(code, limit)
    if xueqiu_data is not None:
        return xueqiu_data

    # --- Strategy 2: AKShare community sentiment (东方财富) ---
    akshare_data = _fetch_akshare_discussion_sentiment(code)
    if akshare_data is not None:
        return akshare_data

    # --- Strategy 3: Shanghai/Shenzhen composite (market-level fallback) ---
    return _index_fallback(ticker, code, curr_date)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_code(ticker: str) -> str:
    """Reduce various ticker formats to a bare 6-digit A-share code."""
    s = ticker.upper().strip()
    for suffix in (".SS", ".SZ", ".SH", ".BJ"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    # Xueqiu uses SH/SZ prefix format: SH600519, SZ002475
    if s.startswith("SH") or s.startswith("SZ"):
        s = s[2:]
        # But keep the leading 0 for codes like 000001
    # Return the 6-digit code for fallback lookups
    return s if s.isdigit() and len(s) == 6 else ticker


def _exchange_suffix(code: str) -> str:
    """Return the exchange prefix for a 6-digit A-share code (SH or SZ)."""
    if code[:1] in ("6", "9", "5"):
        return "SH"
    return "SZ"


# ---------------------------------------------------------------------------
# Strategy 1: DrissionPage DOM scrape
# ---------------------------------------------------------------------------

_XUEQIU_URL = "https://xueqiu.com/S/{symbol}"

# Cached browser/context so a single analysis run reuses the same Chromium
# instance rather than launching/closing one per call.
_browser_cache: dict = {}

# Logged-in cookies (set via config, env var, or set_xueqiu_cookies()).
# When provided, the scraper authenticates as a real Xueqiu user, which can
# surface more posts and richer engagement data.
_XUEQIU_AUTH_COOKIES: str = ""
_COOKIES_LOADED: bool = False


def _auto_load_cookies():
    """Load Xueqiu cookies from config/env/.env on first use.

    Resolution order (first wins):
      1. ``set_xueqiu_cookies()`` already-called
      2. ``XUEQIU_COOKIES`` env var (via ``.env`` or shell)
      3. ``xueqiu_cookies`` config key
    """
    global _XUEQIU_AUTH_COOKIES, _COOKIES_LOADED
    if _COOKIES_LOADED:
        return
    _COOKIES_LOADED = True

    # Load .env file so XUEQIU_COOKIES works without `cli/main.py`
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    try:
        from tradingagents.dataflows.config import get_config
        cookies = get_config().get("xueqiu_cookies", "").strip()
        if cookies:
            _XUEQIU_AUTH_COOKIES = cookies
            logger.info("Xueqiu: loaded cookies from config (%d chars)", len(cookies))
    except Exception:
        pass


def set_xueqiu_cookies(cookie_string: str):
    """Inject logged-in Xueqiu cookies into the scraper.

    Call this once before running analysis to authenticate as a real user.
    Format: ``"key1=val1; key2=val2; ..."`` (standard cookie string).
    """
    global _XUEQIU_AUTH_COOKIES
    _XUEQIU_AUTH_COOKIES = cookie_string.strip()
    # Reset cached browser so the next call picks up the new cookies
    page = _browser_cache.pop("page", None)
    if page is not None:
        try:
            page.quit()
        except Exception:
            pass
    logger.info("Xueqiu auth cookies set (%d chars)", len(_XUEQIU_AUTH_COOKIES))


def _parse_cookie_string(raw: str) -> list[dict]:
    """Parse a standard cookie string into a list of {name, value, domain} dicts."""
    cookies = []
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            name, value = part.split("=", 1)
            name = name.strip()
            value = value.strip()
            if name:
                cookies.append({"name": name, "value": value, "domain": "xueqiu.com"})
    return cookies


def _extract_uid(cookie_string: str) -> str:
    """Extract user ID from Xueqiu cookie string for logging."""
    for part in cookie_string.split(";"):
        if part.strip().startswith("u="):
            return part.strip()[2:]
    return "?"


def _get_scrape_page():
    """Return a configured DrissionPage ChromiumPage, reusing the cached browser."""
    if "page" in _browser_cache:
        return _browser_cache["page"]

    _auto_load_cookies()

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
    co.set_argument("--lang=zh-CN")

    page = ChromiumPage(co)

    # Prime the session by loading the main page (sets WAF cookies).
    page.get("https://xueqiu.com/", timeout=_BROWSER_TIMEOUT)
    time.sleep(3)

    # Inject logged-in cookies if provided (Xueqiu auth)
    if _XUEQIU_AUTH_COOKIES:
        auth_cookies = _parse_cookie_string(_XUEQIU_AUTH_COOKIES)
        # Set domain to .xueqiu.com for cross-subdomain cookie sharing
        for c in auth_cookies:
            c["domain"] = ".xueqiu.com"
        page.set.cookies(auth_cookies)
        # Reload main page with auth cookies
        page.get("https://xueqiu.com/", timeout=_BROWSER_TIMEOUT)
        time.sleep(2)
        # Verify login
        has_login = page.run_js(
            "return document.cookie.indexOf('xq_is_login=1') >= 0"
        )
        if has_login:
            logger.info("Xueqiu: logged in successfully (user %s)",
                        _extract_uid(_XUEQIU_AUTH_COOKIES))

    _browser_cache["page"] = page
    return page


def _teardown_scrape_page():
    """Close cached browser instance if active."""
    page = _browser_cache.pop("page", None)
    if page is not None:
        try:
            page.quit()
        except Exception:
            pass


def _fetch_xueqiu_dom(code: str, limit: int) -> str | None:
    """Scrape Xueqiu stock page DOM for discussion posts via DrissionPage.

    Loads the stock page (xueqiu.com/S/SH/SZ{code}), waits for JS to
    render discussion content, then extracts <article> elements from the
    DOM. Each article contains username, timestamp, post body, and
    engagement stats.
    """
    if not code.isdigit() or len(code) != 6:
        return None

    symbol = f"{_exchange_suffix(code)}{code}"

    try:
        page = _get_scrape_page()

        # Load the stock page
        stock_url = _XUEQIU_URL.format(symbol=symbol)
        logger.info("Xueqiu: loading %s", stock_url)
        page.get(stock_url, timeout=_BROWSER_TIMEOUT)

        # Wait for discussion content to render
        time.sleep(5)

        # Scroll to trigger lazy-loading of discussion posts
        page.run_js("window.scrollTo(0, document.body.scrollHeight * 0.4)")
        time.sleep(2)

        # Extract discussion posts from <article> elements
        posts = _extract_posts_from_dom(page, limit)

        if not posts:
            return (
                f"<在雪球上未找到关于 {code} 的讨论帖子>\n"
                f"Symbol: {symbol}\n"
                f"URL: {stock_url}\n"
            )

        summary = (
            f"## 雪球社区讨论 — {code} (热帖)\n"
            f"Source: xueqiu.com (雪球投资者社区)\n"
            f"排序: 按热度/互动量降序 · 抓取 {len(posts)} 条 · URL: {stock_url}\n\n"
        )
        return summary + "\n".join(posts)

    except ImportError:
        logger.debug("DrissionPage not installed; skipping DOM scrape")
        return None
    except Exception as exc:
        logger.debug("Xueqiu DOM scrape failed for %s: %s", code, exc)
        return None


def _extract_posts_from_dom(page, limit: int) -> list[str]:
    """Extract and format discussion posts from the Xueqiu stock page DOM.

    Switches to the "热帖" (Hot Posts) tab first so posts are sorted by
    engagement (likes/comments) rather than chronological order. This
    surfaces the highest-quality community discussion.
    """
    # Click the "热帖" (Hot Posts) tab
    clicked = page.run_js("""
        const all = document.querySelectorAll('a, span, button');
        for (const el of all) {
            if (el.innerText?.trim() === '热帖') {
                el.click();
                return true;
            }
        }
        return false;
    """)
    if clicked:
        time.sleep(3)  # wait for hot posts to load

    raw_posts = page.run_js(f"""
        const articles = document.querySelectorAll('article');
        const results = [];
        articles.forEach(a => {{
            const text = a.innerText?.trim() || '';
            if (text.length > 30) {{
                results.push(text.substring(0, 600));
            }}
        }});
        return results.slice(0, {limit});
    """)

    if not raw_posts:
        return []

    formatted: list[str] = []
    for i, raw in enumerate(raw_posts, 1):
        # Clean up: collapse newlines, strip emoji separators
        body = _clean_post_body(raw)
        formatted.append(f"--- 帖子 {i} ---\n{body}")

    return formatted


def _clean_post_body(raw: str) -> str:
    """Clean up raw post text extracted from the DOM.
    
    Preserves: username, timestamp, device info, cashtags, content.
    Removes: excessive whitespace, UI decoration emoji.
    """
    # Collapse runs of separator emoji (, , , etc.) into single markers
    cleaned = re.sub(r"\s*", "[转发] ", raw)
    cleaned = re.sub(r"\s*", "[评论] ", cleaned)
    cleaned = re.sub(r"\s*", "[赞] ", cleaned)
    cleaned = re.sub(r"\s*", "[收藏] ", cleaned)
    cleaned = re.sub(r"", "…", cleaned)

    # Normalize whitespace
    cleaned = re.sub(r"  +", " ", cleaned)
    cleaned = cleaned.strip()

    # First line usually: "username time· 来自platform"
    # Rest is the post content
    return cleaned


# ---------------------------------------------------------------------------
# Strategy 2: AKShare community sentiment (东方财富)
# ---------------------------------------------------------------------------

def _fetch_akshare_discussion_sentiment(code: str) -> str | None:
    """Fetch community discussion sentiment from AKShare (东方财富数据).

    Provides: 综合评分, 参与意愿, 用户关注指数, 机构参与度.
    These are derived from East Money's massive user base — the most
    widely-used stock discussion platform in China.
    """
    try:
        import akshare as ak
        import pandas as pd

        if not code.isdigit() or len(code) != 6:
            return None

        lines: list[str] = [
            f"## 社区讨论情绪 — {code}",
            "Source: 东方财富 (East Money) — 综合评分系统",
            "",
        ]

        # --- Composite score (综合评价历史评分) ---
        try:
            df_score = ak.stock_comment_detail_zhpj_lspf_em(symbol=code)
            if df_score is not None and not df_score.empty:
                latest = df_score.iloc[-1]
                score = latest.get("评分", "N/A")
                score_prev = df_score.iloc[-2].get("评分", "N/A") if len(df_score) > 1 else score
                lines.append("### 综合评分 (Composite Score)")
                lines.append(f"- 最新: {score}")
                try:
                    change = float(score) - float(score_prev)
                    lines.append(f"- 变化: {change:+.2f}")
                except (ValueError, TypeError):
                    pass
                lines.append("")
        except Exception as exc:
            logger.debug("Score fetch failed: %s", exc)

        # --- Participation willingness (参与意愿) ---
        try:
            df_will = ak.stock_comment_detail_scrd_desire_em(symbol=code)
            if df_will is not None and not df_will.empty:
                latest = df_will.iloc[-1]
                lines.append("### 参与意愿 (Participation Willingness)")
                lines.append(f"- 当前: {latest.get('参与意愿', 'N/A')}")
                lines.append(f"- 5日平均: {latest.get('5日平均参与意愿', 'N/A')}")
                change_str = latest.get('参与意愿变化', '')
                lines.append(f"- 变化: {change_str}")
                lines.append("")
        except Exception as exc:
            logger.debug("Desire fetch failed: %s", exc)

        # --- User attention (用户关注指数) ---
        try:
            df_attention = ak.stock_comment_detail_scrd_focus_em(symbol=code)
            if df_attention is not None and not df_attention.empty:
                lines.append("### 用户关注指数 (User Attention)")
                latest = df_attention.iloc[-1]
                lines.append(f"- 当前: {latest.get('用户关注指数', 'N/A')}")
                # Trend
                if len(df_attention) > 1:
                    prev = df_attention.iloc[-2].get("用户关注指数", 0)
                    curr = latest.get("用户关注指数", 0)
                    try:
                        diff = float(curr) - float(prev)
                        direction = "↑ 上升" if diff > 0 else ("↓ 下降" if diff < 0 else "→ 持平")
                        lines.append(f"- 趋势: {direction} ({diff:+.1f})")
                    except (ValueError, TypeError):
                        pass
                lines.append("")
        except Exception as exc:
            logger.debug("Attention fetch failed: %s", exc)

        # --- Institutional participation (机构参与度) ---
        try:
            df_inst = ak.stock_comment_detail_zlkp_jgcyd_em(symbol=code)
            if df_inst is not None and not df_inst.empty:
                latest = df_inst.iloc[-1]
                lines.append("### 机构参与度 (Institutional Participation)")
                lines.append(f"- 当前: {latest.get('机构参与度', 'N/A')}")
                if len(df_inst) > 1:
                    prev = df_inst.iloc[-2].get("机构参与度", 0)
                    curr = latest.get("机构参与度", 0)
                    try:
                        diff = float(curr) - float(prev)
                        lines.append(f"- 变化: {diff:+.2f}")
                    except (ValueError, TypeError):
                        pass
                lines.append("")
        except Exception as exc:
            logger.debug("Institutional participation fetch failed: %s", exc)

        if len(lines) <= 1:
            return None

        return "\n".join(lines)

    except Exception as exc:
        logger.debug("AKShare discussion sentiment failed for %s: %s", code, exc)
        return None


# ---------------------------------------------------------------------------
# Strategy 3: Market-level fallback (Shanghai / Shenzhen)
# ---------------------------------------------------------------------------

def _index_fallback(ticker: str, code: str, curr_date: str) -> str:
    """Return a market-level discussion data fallback."""
    exchange = _exchange_suffix(code)
    index_names = {"SH": "上证指数 (Shanghai Composite)", "SZ": "深证成指 (Shenzhen Composite)"}
    index_name = index_names.get(exchange, "沪深市场 (China A-share Market)")

    return (
        f"<雪球社区和东方财富的 {ticker} 讨论数据暂时不可用>\n\n"
        f"## 市场讨论数据 — {index_name}\n\n"
        f"个股 {ticker} (代码 {code}) 属于{index_name}覆盖范围。\n"
        f"建议手动查阅雪球讨论: https://xueqiu.com/S/{exchange}{code}\n\n"
        f"### 说明\n"
        f"1. 雪球API受阿里云WAF保护，直接HTTP请求无法绕过JavaScript挑战。\n"
        f"2. 东方财富综合评分反映了该股在平台上的社区关注度和情绪。\n"
        f"3. 如需完整的雪球帖子内容，建议通过浏览器访问以上链接。\n"
    )
