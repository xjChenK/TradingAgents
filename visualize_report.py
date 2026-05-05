"""Streamlit app for visualizing TradingAgents analysis reports."""

import streamlit as st
from pathlib import Path
from datetime import datetime
import plotly.graph_objects as go
import re


st.set_page_config(
    page_title="TradingAgents 可视化报告",
    page_icon="📈",
    layout="wide"
)


def find_reports_dir() -> Path:
    """Find the reports directory."""
    return Path(__file__).parent / "reports"


def get_available_reports() -> list:
    """Get list of available reports."""
    reports_dir = find_reports_dir()
    if not reports_dir.exists():
        return []

    reports = []
    for d in reports_dir.iterdir():
        if d.is_dir() and "_20" in d.name:
            # Parse ticker from directory name like "603019_20260505_172545"
            parts = d.name.split("_")
            if len(parts) >= 3:
                ticker = parts[0]
                date = parts[1]
                reports.append({
                    "ticker": ticker,
                    "date": date,
                    "path": d
                })

    return sorted(reports, key=lambda x: x["date"], reverse=True)


def load_report_data(report_path: Path) -> dict:
    """Load report data from markdown files."""
    data = {
        "company_of_interest": "",
        "trade_date": "",
        "market_report": "",
        "sentiment_report": "",
        "news_report": "",
        "fundamentals_report": "",
        "investment_plan": "",
        "trader_investment_plan": "",
        "bull_history": "",
        "bear_history": "",
        "aggressive_history": "",
        "conservative_history": "",
        "neutral_history": "",
        "final_trade_decision": "",
        "complete_report": ""
    }

    # Parse directory name for ticker and date
    parts = report_path.name.split("_")
    if len(parts) >= 3:
        data["company_of_interest"] = parts[0]
        data["trade_date"] = parts[1]

    # Load complete report
    complete_report_file = report_path / "complete_report.md"
    if complete_report_file.exists():
        data["complete_report"] = complete_report_file.read_text(encoding="utf-8")
        # Parse header
        if "Generated:" in data["complete_report"]:
            gen_match = re.search(r"Generated:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", data["complete_report"])
            if gen_match:
                data["trade_date"] = gen_match.group(1).split(" ")[0]

    # Load analyst reports
    analysts_dir = report_path / "1_analysts"
    if analysts_dir.exists():
        for report_file in analysts_dir.iterdir():
            content = report_file.read_text(encoding="utf-8")
            if report_file.name == "market.md":
                data["market_report"] = content
            elif report_file.name == "sentiment.md":
                data["sentiment_report"] = content
            elif report_file.name == "news.md":
                data["news_report"] = content
            elif report_file.name == "fundamentals.md":
                data["fundamentals_report"] = content

    # Load research reports
    research_dir = report_path / "2_research"
    if research_dir.exists():
        for report_file in research_dir.iterdir():
            content = report_file.read_text(encoding="utf-8")
            if report_file.name == "bull.md":
                data["bull_history"] = content
            elif report_file.name == "bear.md":
                data["bear_history"] = content
            elif report_file.name == "manager.md":
                data["investment_plan"] = content

    # Load trading reports
    trading_dir = report_path / "3_trading"
    if trading_dir.exists():
        trader_file = trading_dir / "trader.md"
        if trader_file.exists():
            data["trader_investment_plan"] = trader_file.read_text(encoding="utf-8")

    # Load risk reports
    risk_dir = report_path / "4_risk"
    if risk_dir.exists():
        for report_file in risk_dir.iterdir():
            content = report_file.read_text(encoding="utf-8")
            if report_file.name == "aggressive.md":
                data["aggressive_history"] = content
            elif report_file.name == "conservative.md":
                data["conservative_history"] = content
            elif report_file.name == "neutral.md":
                data["neutral_history"] = content

    # Load portfolio decision
    portfolio_dir = report_path / "5_portfolio"
    if portfolio_dir.exists():
        decision_file = portfolio_dir / "decision.md"
        if decision_file.exists():
            data["final_trade_decision"] = decision_file.read_text(encoding="utf-8")

    return data


def parse_decision_signal(decision_text: str) -> dict:
    """Parse trading decision to extract signal."""
    signal = {"action": "Hold", "confidence": "Medium", "summary": ""}

    if not decision_text:
        return signal

    text_lower = decision_text.lower()

    if "buy" in text_lower or "做多" in text_lower or "买入" in text_lower or "买" in text_lower:
        signal["action"] = "Buy"
    elif "sell" in text_lower or "做空" in text_lower or "卖出" in text_lower or "卖" in text_lower:
        signal["action"] = "Sell"
    elif "hold" in text_lower or "持有" in text_lower or "观望" in text_lower:
        signal["action"] = "Hold"

    if "strong" in text_lower or "强烈" in text_lower:
        signal["confidence"] = "High"
    elif "cautious" in text_lower or "谨慎" in text_lower or "保守" in text_lower:
        signal["confidence"] = "Low"

    return signal


def extract_key_metrics(market_report: str) -> dict:
    """Extract key metrics from market report text."""
    metrics = {
        "trend": "Unknown",
        "rsi": None,
        "macd": None,
        "support": None,
        "resistance": None,
        "signal": "Neutral"
    }

    if not market_report:
        return metrics

    # Extract RSI
    rsi_match = re.search(r'RSI[^\d]*(\d+\.?\d*)', market_report)
    if not rsi_match:
        rsi_match = re.search(r'RS[II]+[^\d]*(\d+\.?\d*)', market_report)
    if rsi_match:
        metrics["rsi"] = float(rsi_match.group(1))

    # Extract MACD
    macd_match = re.search(r'MACD[^\d]*(-?\d+\.?\d*)', market_report)
    if not macd_match:
        macd_match = re.search(r'MACD[^\d]*(-?\d+\.?\d*)', market_report)
    if macd_match:
        metrics["macd"] = float(macd_match.group(1))

    # Extract support
    support_match = re.search(r'支撑.*?(\d+\.?\d*)', market_report)
    if not support_match:
        support_match = re.search(r'支撑位[^\d]*(\d+\.?\d*)', market_report)
    if support_match:
        metrics["support"] = float(support_match.group(1))

    # Extract resistance
    resistance_match = re.search(r'阻力.*?(\d+\.?\d*)', market_report)
    if not resistance_match:
        resistance_match = re.search(r'阻力位[^\d]*(\d+\.?\d*)', market_report)
    if resistance_match:
        metrics["resistance"] = float(resistance_match.group(1))

    # Determine trend
    if "看多" in market_report or "买入" in market_report or "buy" in market_report.lower():
        metrics["signal"] = "Bullish"
    elif "看空" in market_report or "卖出" in market_report or "sell" in market_report.lower():
        metrics["signal"] = "Bearish"

    return metrics


def create_gauge_chart(value: float, title: str, min_val: int = 0, max_val: int = 100) -> go.Figure:
    """Create a gauge chart for metrics like RSI."""
    if value is None:
        value = 50

    if value < 30:
        color = "#28a745"  # green - oversold
    elif value > 70:
        color = "#dc3545"  # red - overbought
    else:
        color = "#ffc107"  # yellow - neutral

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        domain={'x': [0, 1], 'y': [0, 1]},
        gauge={
            'axis': {'range': [min_val, max_val], 'tickwidth': 1},
            'bar': {'color': color},
            'bgcolor': "lightgray",
            'borderwidth': 2,
            'bordercolor': "gray",
            'steps': [
                {'range': [min_val, 30], 'color': 'lightgreen'},
                {'range': [30, 70], 'color': 'lightyellow'},
                {'range': [70, max_val], 'color': 'lightcoral'}
            ],
        },
        title={'text': title}
    ))

    fig.update_layout(
        height=200,
        margin=dict(l=20, r=20, t=40, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12)
    )

    return fig


def main():
    st.title("📈 TradingAgents 可视化分析报告")

    # Sidebar for report selection
    st.sidebar.title("报告选择")

    # Get available reports
    reports = get_available_reports()

    if not reports:
        st.warning("未找到分析报告，请先运行 TradingAgents 生成报告。")
        return

    # Create options for selectbox
    options = [f"{r['ticker']} - {r['date']}" for r in reports]
    selected_option = st.sidebar.selectbox(
        "选择报告",
        options=options
    )

    # Get selected report
    selected_idx = options.index(selected_option)
    selected_report = reports[selected_idx]
    report_path = selected_report["path"]

    # Load data
    data = load_report_data(report_path)

    # Display header info
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("股票代码", data.get("company_of_interest", "N/A"))
    with col2:
        st.metric("分析日期", data.get("trade_date", "N/A"))
    with col3:
        signal = parse_decision_signal(data.get("final_trade_decision", ""))
        st.metric("交易信号", signal["action"], delta=signal["confidence"])

    st.markdown("---")

    # Key Metrics Section
    st.subheader("📊 技术指标")

    metrics = extract_key_metrics(data.get("market_report", ""))

    metric_cols = st.columns(4)

    with metric_cols[0]:
        fig = create_gauge_chart(metrics.get("rsi") if metrics.get("rsi") else 50, "RSI 相对强弱指数")
        st.plotly_chart(fig, use_container_width=True)

    with metric_cols[1]:
        macd_value = metrics.get("macd")
        if macd_value is not None:
            # Normalize MACD to 0-100 range (assuming range -5 to 5)
            normalized_macd = max(0, min(100, (macd_value + 5) * 10))
        else:
            normalized_macd = 50
        fig = create_gauge_chart(normalized_macd, "MACD 动量指标")
        st.plotly_chart(fig, use_container_width=True)

    with metric_cols[2]:
        st.markdown("#### 技术信号")
        st.markdown(f"**{metrics.get('signal', 'N/A')}**")
        if metrics.get("support"):
            st.markdown(f"支撑位: **{metrics['support']:.2f}**")
        if metrics.get("resistance"):
            st.markdown(f"阻力位: **{metrics['resistance']:.2f}**")

    with metric_cols[3]:
        st.markdown("#### 交易决策")
        st.markdown(f"**{signal['action']}** ({signal['confidence']} Confidence)")

    st.markdown("---")

    # Report Sections
    st.subheader("📝 分析报告详情")

    report_tabs = st.tabs([
        "市场分析",
        "情绪分析",
        "新闻分析",
        "基本面分析",
        "投资辩论",
        "交易决策"
    ])

    with report_tabs[0]:
        st.markdown(data.get("market_report", "无数据"))

    with report_tabs[1]:
        st.markdown(data.get("sentiment_report", "无数据"))

    with report_tabs[2]:
        st.markdown(data.get("news_report", "无数据"))

    with report_tabs[3]:
        st.markdown(data.get("fundamentals_report", "无数据"))

    with report_tabs[4]:
        st.markdown("### 📈 投资辩论")
        st.markdown("**看多方观点:**")
        st.markdown(data.get("bull_history", "无数据"))
        st.markdown("---")
        st.markdown("**看空方观点:**")
        st.markdown(data.get("bear_history", "无数据"))
        st.markdown("---")
        st.markdown("**研究经理决策:**")
        st.markdown(data.get("investment_plan", "无数据"))

    with report_tabs[5]:
        st.markdown("### 💼 交易员提案")
        st.markdown(data.get("trader_investment_plan", "无数据"))
        st.markdown("---")
        st.markdown("### ⚖️ 风险辩论")
        st.markdown("**激进观点:**")
        st.markdown(data.get("aggressive_history", "无数据"))
        st.markdown("---")
        st.markdown("**保守观点:**")
        st.markdown(data.get("conservative_history", "无数据"))
        st.markdown("---")
        st.markdown("**中性观点:**")
        st.markdown(data.get("neutral_history", "无数据"))
        st.markdown("---")
        st.markdown("### 🎯 最终交易决策")
        st.markdown(data.get("final_trade_decision", "无数据"))

    # Footer
    st.markdown("---")
    st.caption(f"TradingAgents 可视化报告 | 数据来源: {report_path}")


if __name__ == "__main__":
    main()
