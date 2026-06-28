"""Sentiment analyst — multi-source sentiment analysis for a target ticker.

Designed for the A-share (China) market. Pre-fetches three complementary
data sources before the LLM is invoked and injects them into the prompt
as structured blocks:

  1. News headlines        — Yahoo Finance / AKShare (东方财富) news
  2. Fear & Greed Index      — China MM Fear & Greed Index (market sentiment)
  3. Xueqiu/雪球 discussions — A-share stock discussion community data

The agent does not use tool-calling; the data is in the prompt from
turn 0. Output uses the structured-output pattern (json_schema for
OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic), falling
back to free-text generation for providers that lack native support, so
the sentiment header (band + score + confidence) is deterministic across
runs and providers instead of free-form per-model prose.

See: https://github.com/TauricResearch/TradingAgents/issues/557
See: https://github.com/TauricResearch/TradingAgents/issues/796
"""

from datetime import datetime, timedelta

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.schemas import SentimentReport, render_sentiment_report
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_news,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.dataflows.fear_greed import fetch_fear_greed_index
from tradingagents.dataflows.xueqiu import fetch_xueqiu_posts


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def create_sentiment_analyst(llm):
    """Create a sentiment analyst node for the trading graph.

    Pre-fetches news + Fear & Greed Index + Xueqiu community data, injects
    them into the prompt as structured blocks, and produces a deterministic
    sentiment report via structured output (with a free-text fallback for
    providers that do not support it).
    """
    structured_llm = bind_structured(llm, SentimentReport, "Sentiment Analyst")

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _seven_days_back(end_date)
        instrument_context = get_instrument_context_from_state(state)

        # Pre-fetch all three sources. Each fetcher degrades gracefully and
        # returns a string (no exceptions surface from here), so the LLM
        # always sees something — either real data or a clear placeholder.
        news_block = get_news.func(ticker, start_date, end_date)
        fear_greed_block = fetch_fear_greed_index(ticker, end_date)
        xueqiu_block = fetch_xueqiu_posts(ticker)

        system_message = _build_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            fear_greed_block=fear_greed_block,
            xueqiu_block=xueqiu_block,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " Today's date is {current_date}; treat it as 'now' for all analysis and tool-call date ranges. {instrument_context}"
                    "\n{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        # Format the template into a concrete message list so the structured
        # and free-text paths receive the same input. No bind_tools — the
        # data is already in the prompt.
        formatted_messages = prompt.format_messages(messages=state["messages"])

        report_text = invoke_structured_or_freetext(
            structured_llm,
            llm,
            formatted_messages,
            render_sentiment_report,
            "Sentiment Analyst",
        )

        return {
            "messages": [AIMessage(content=report_text)],
            "sentiment_report": report_text,
        }

    return sentiment_analyst_node


def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    fear_greed_block: str,
    xueqiu_block: str,
) -> str:
    """Assemble the sentiment-analyst system message with structured data blocks."""
    return f"""You are a financial market sentiment analyst specializing in the China A-share market. Your task is to produce a comprehensive sentiment report for {ticker} covering the period from {start_date} to {end_date}, drawing on three complementary data sources that have already been collected for you.

## Data sources (pre-fetched, in this prompt)

### News headlines — Yahoo Finance / AKShare, past 7 days
Institutional framing. Fact-driven, slower-moving signal.

<start_of_news>
{news_block}
<end_of_news>

### China MM Fear & Greed Index — macro-level market sentiment
A market-wide sentiment gauge on a 0 (Extreme Fear) to 100 (Extreme Greed) scale. When combined with per-stock data, it tells you whether the stock's sentiment is in sync with or diverging from the broader market.

<start_of_fear_greed>
{fear_greed_block}
<end_of_fear_greed>

### Xueqiu/雪球 community discussion data — A-share stock discussion sentiment
The largest investor community in China (20M+ users). Sentiment metrics include composite score, user attention index, participation willingness, and institutional participation. When available, raw discussion post content is included.

<start_of_xueqiu>
{xueqiu_block}
<end_of_xueqiu>

## How to analyze this data (best practices for China A-share market)

1. **Read the Fear & Greed Index as a market-level sentiment anchor.** A reading above 70 indicates Greed (potential over-extension); below 30 indicates Fear (potential capitulation). Divergence between the index and individual stock sentiment is itself a signal.

2. **Use the Xueqiu/雪球 composite score (0-100) as a per-stock sentiment baseline.** Scores consistently above 70 are bullish; below 30 are bearish; 30-70 is neutral. Pair this with the user attention index — high attention + high score = consensus bullish; high attention + low score = negative sentiment concentration.

3. **Look for cross-source divergences.** If news framing is bearish but the Fear & Greed Index shows Greed, or if the composite score is bullish but participation willingness is falling — these mismatches are themselves actionable signals.

4. **Weight the Fear & Greed Index differently based on stock characteristics.** Large-cap blue chips (e.g. 贵州茅台, 招商银行) track the market index more closely; small/mid-cap stocks may diverge significantly. Note when the stock's individual sentiment moves against the market tide.

5. **Distinguish event-driven news from sentiment drift.** A company earnings announcement (news block) is an event; a change in the composite score or user attention index over several days reflects sentiment drift. Both matter but differently.

6. **Identify recurring narrative themes.** What concerns or catalysts keep appearing across news and community data? That's the dominant narrative driving current sentiment.

7. **Be honest about data limits.** If the Fear & Greed Index returned a placeholder or Xueqiu data is unavailable, the sentiment read is less robust — flag this explicitly in the `confidence` field and the narrative.

8. **Remember the A-share market context.** Retail investors dominate (80%+ of trading volume), so community sentiment metrics matter more than in US/developed markets. However, retail sentiment can be contrarian — extreme consensus often marks turning points.

9. **Identify catalysts and risks** that emerge across sources — news of policy changes, industry regulation, economic data releases, earnings, product launches, etc.

10. **Past sentiment is not predictive.** Frame your conclusions as signal for the trader to weigh alongside fundamentals and technicals, not as a price call.

## Output fields

Fill the following fields:

- **overall_band**: Exactly one of Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish. Use Mixed when sources point in clearly different directions; Neutral only when all sources are genuinely silent.
- **overall_score**: A number from 0 (maximally bearish) to 10 (maximally bullish); 5 is neutral. Keep it consistent with overall_band.
- **confidence**: low / medium / high, based on data quality and sample size.
- **narrative**: Full source-by-source breakdown, divergences, dominant narrative themes, catalysts and risks, and a markdown summary table of key sentiment signals (direction, source, supporting evidence).

{get_language_instruction()}"""


# ---------------------------------------------------------------------------
# Backwards-compatibility shim
# ---------------------------------------------------------------------------
def create_social_media_analyst(llm):
    """Deprecated alias for :func:`create_sentiment_analyst`.

    Kept so existing code that imports ``create_social_media_analyst``
    continues to work.

    .. deprecated::
        Import :func:`create_sentiment_analyst` directly instead.
    """
    import warnings
    warnings.warn(
        "create_social_media_analyst is deprecated and will be removed in a "
        "future version. Use create_sentiment_analyst instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_sentiment_analyst(llm)
