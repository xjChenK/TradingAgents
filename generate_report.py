"""Generate beautiful HTML/PDF reports from TradingAgents markdown reports."""

import markdown
from pathlib import Path
from datetime import datetime
import re


# CSS template for beautiful report with tabbed interface
REPORT_CSS = """
@font-face {
    font-family: 'Noto Sans SC';
    font-style: normal;
    font-weight: 400;
    src: local('Noto Sans SC'), local('NotoSansSC-Regular');
}

@font-face {
    font-family: 'Noto Sans SC';
    font-style: normal;
    font-weight: 700;
    src: local('Noto Sans SC Bold'), local('NotoSansSC-Bold');
}

:root {
    --primary-color: #1a73e8;
    --secondary-color: #f8f9fa;
    --text-color: #333;
    --accent-green: #28a745;
    --accent-red: #dc3545;
    --accent-yellow: #ffc107;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: 'Noto Sans SC', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: var(--text-color);
    line-height: 1.6;
    max-width: 1000px;
    margin: 0 auto;
    padding: 20px;
    background: #f5f5f5;
}

.header {
    text-align: center;
    background: white;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 20px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.header h1 { color: var(--primary-color); font-size: 1.8em; margin-bottom: 8px; }
.header .meta { color: #666; font-size: 0.85em; }

.signal-box {
    display: inline-block;
    padding: 8px 20px;
    border-radius: 20px;
    font-weight: bold;
    font-size: 1em;
    margin: 10px 0;
}
.signal-buy { background: var(--accent-green); color: white; }
.signal-sell { background: var(--accent-red); color: white; }
.signal-hold { background: var(--accent-yellow); color: #333; }

.metrics-bar {
    display: flex;
    justify-content: center;
    gap: 12px;
    flex-wrap: wrap;
    margin: 12px 0;
}
.metric-badge {
    background: var(--primary-color);
    color: white;
    padding: 6px 14px;
    border-radius: 16px;
    font-size: 0.8em;
}
.metric-badge .value { font-weight: bold; }

/* Tab Navigation */
.tab-nav {
    display: flex;
    gap: 4px;
    background: white;
    padding: 8px;
    border-radius: 12px 12px 0 0;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    overflow-x: auto;
}
.tab-btn {
    flex: 1;
    min-width: 90px;
    padding: 10px 12px;
    border: none;
    background: var(--secondary-color);
    color: #666;
    font-size: 0.85em;
    font-weight: 500;
    cursor: pointer;
    border-radius: 6px;
    transition: all 0.3s ease;
    white-space: nowrap;
}
.tab-btn:hover { background: #e0e0e0; }
.tab-btn.active { background: var(--primary-color); color: white; }

/* Tab Content */
.tab-content-wrapper {
    background: white;
    border-radius: 0 0 12px 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    min-height: 400px;
}
.tab-content { display: none; padding: 20px; }
.tab-content.active { display: block; }
.tab-content h2 { color: var(--primary-color); font-size: 1.2em; border-bottom: 2px solid var(--primary-color); padding-bottom: 8px; margin-bottom: 15px; }
.tab-content h3 { color: #555; font-size: 1em; margin: 15px 0 8px 0; padding-left: 8px; border-left: 3px solid var(--primary-color); }
.tab-content p { margin: 8px 0; }
.tab-content table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 0.9em; }
.tab-content th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #ddd; }
.tab-content th { background: var(--primary-color); color: white; }
.tab-content tr:nth-child(even) { background: var(--secondary-color); }
.tab-content blockquote { border-left: 3px solid var(--primary-color); margin: 10px 0; padding: 8px 12px; background: #f0f7ff; }

.footer { text-align: center; margin-top: 20px; padding: 12px; color: #888; font-size: 0.75em; }
.bullish { color: var(--accent-green); font-weight: bold; }
.bearish { color: var(--accent-red); font-weight: bold; }

@media (max-width: 600px) {
    .tab-nav { flex-wrap: wrap; }
    .tab-btn { min-width: 70px; font-size: 0.75em; padding: 8px 6px; }
    .metrics-bar { gap: 6px; }
    .metric-badge { padding: 5px 8px; font-size: 0.7em; }
}
"""

JAVASCRIPT_TAB = """
<script>
function openTab(evt, tabName) {
    var i, content, buttons;
    content = document.getElementsByClassName("tab-content");
    for (i = 0; i < content.length; i++) {
        content[i].classList.remove("active");
    }
    buttons = document.getElementsByClassName("tab-btn");
    for (i = 0; i < buttons.length; i++) {
        buttons[i].classList.remove("active");
    }
    document.getElementById(tabName).classList.add("active");
    evt.currentTarget.classList.add("active");
}
</script>
"""


def parse_decision_signal(decision_text: str) -> dict:
    """Parse trading decision to extract signal."""
    signal = {"action": "Hold", "confidence": "Medium", "signal_class": "signal-hold"}

    if not decision_text:
        return signal

    text_lower = decision_text.lower()

    if "buy" in text_lower or "做多" in text_lower or "买入" in text_lower or "买" in text_lower:
        signal["action"] = "买入 (Buy)"
        signal["signal_class"] = "signal-buy"
    elif "sell" in text_lower or "做空" in text_lower or "卖出" in text_lower or "卖" in text_lower:
        signal["action"] = "卖出 (Sell)"
        signal["signal_class"] = "signal-sell"
    elif "hold" in text_lower or "持有" in text_lower or "观望" in text_lower:
        signal["action"] = "观望 (Hold)"
        signal["signal_class"] = "signal-hold"

    if "strong" in text_lower or "强烈" in text_lower:
        signal["confidence"] = "高"
    elif "cautious" in text_lower or "谨慎" in text_lower or "保守" in text_lower:
        signal["confidence"] = "低"

    return signal


def extract_key_metrics(market_report: str) -> dict:
    """Extract key metrics from market report text."""
    metrics = {"rsi": None, "macd": None, "support": None, "resistance": None, "signal": "中性"}

    if not market_report:
        return metrics

    # Extract RSI
    rsi_match = re.search(r'RSI[^\d]*(\d+\.?\d*)', market_report)
    if rsi_match:
        metrics["rsi"] = float(rsi_match.group(1))

    # Extract MACD
    macd_match = re.search(r'MACD[^\d]*(-?\d+\.?\d*)', market_report)
    if macd_match:
        metrics["macd"] = float(macd_match.group(1))

    # Extract support
    support_match = re.search(r'支撑.*?(\d+\.?\d*)', market_report)
    if support_match:
        metrics["support"] = float(support_match.group(1))

    # Extract resistance
    resistance_match = re.search(r'阻力.*?(\d+\.?\d*)', market_report)
    if resistance_match:
        metrics["resistance"] = float(resistance_match.group(1))

    # Determine trend
    if "看多" in market_report or "买入" in market_report or "buy" in market_report.lower():
        metrics["signal"] = "看多"
    elif "看空" in market_report or "卖出" in market_report or "sell" in market_report.lower():
        metrics["signal"] = "看空"

    return metrics


def load_report_data(report_path: Path) -> dict:
    """Load report data from markdown files."""
    data = {
        "company_of_interest": "",
        "trade_date": "",
        "market_report": "",
        "sentiment_report": "",
        "news_report": "",
        "fundamentals_report": "",
        "bull_history": "",
        "bear_history": "",
        "investment_plan": "",
        "trader_investment_plan": "",
        "aggressive_history": "",
        "conservative_history": "",
        "neutral_history": "",
        "final_trade_decision": "",
    }

    # Parse directory name
    parts = report_path.name.split("_")
    if len(parts) >= 3:
        data["company_of_interest"] = parts[0]
        data["trade_date"] = parts[1]

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


def convert_markdown(md, text):
    md.reset()
    return md.convert(text)


def generate_html_report(data: dict, output_path: Path):
    """Generate beautiful HTML report with tabbed interface from data."""

    signal = parse_decision_signal(data.get("final_trade_decision", ""))
    metrics = extract_key_metrics(data.get("market_report", ""))

    md = markdown.Markdown(extensions=['tables', 'fenced_code', 'toc'])

    # Convert markdown sections
    market_html = convert_markdown(md, data.get('market_report', '无数据'))
    sentiment_html = convert_markdown(md, data.get('sentiment_report', '无数据'))
    news_html = convert_markdown(md, data.get('news_report', '无数据'))
    fundamentals_html = convert_markdown(md, data.get('fundamentals_report', '无数据'))
    bull_html = convert_markdown(md, data.get('bull_history', '无数据'))
    bear_html = convert_markdown(md, data.get('bear_history', '无数据'))
    investment_plan_html = convert_markdown(md, data.get('investment_plan', '无数据'))
    trader_html = convert_markdown(md, data.get('trader_investment_plan', '无数据'))
    aggressive_html = convert_markdown(md, data.get('aggressive_history', '无数据'))
    conservative_html = convert_markdown(md, data.get('conservative_history', '无数据'))
    neutral_html = convert_markdown(md, data.get('neutral_history', '无数据'))
    decision_html = convert_markdown(md, data.get('final_trade_decision', '无数据'))

    rsi_val = f"{metrics.get('rsi', 'N/A'):.2f}" if metrics.get('rsi') else 'N/A'
    macd_val = f"{metrics.get('macd', 'N/A'):.2f}" if metrics.get('macd') else 'N/A'
    support_val = f"{metrics.get('support', 'N/A'):.2f}" if metrics.get('support') else 'N/A'
    resistance_val = f"{metrics.get('resistance', 'N/A'):.2f}" if metrics.get('resistance') else 'N/A'

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TradingAgents 分析报告 - {data.get('company_of_interest', 'N/A')}</title>
    <style>{REPORT_CSS}</style>
</head>
<body>
    <div class="header">
        <h1>📈 TradingAgents 分析报告</h1>
        <div class="meta">
            <strong>股票代码:</strong> {data.get('company_of_interest', 'N/A')} |
            <strong>分析日期:</strong> {data.get('trade_date', 'N/A')} |
            <strong>生成时间:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
        <div class="signal-box {signal['signal_class']}">
            交易信号: {signal['action']} (置信度: {signal['confidence']})
        </div>
        <div class="metrics-bar">
            <div class="metric-badge">RSI: <span class="value">{rsi_val}</span></div>
            <div class="metric-badge">MACD: <span class="value">{macd_val}</span></div>
            <div class="metric-badge">技术信号: <span class="value">{metrics.get('signal', 'N/A')}</span></div>
            <div class="metric-badge">支撑: <span class="value">{support_val}</span></div>
            <div class="metric-badge">阻力: <span class="value">{resistance_val}</span></div>
        </div>
    </div>

    <div class="tab-nav">
        <button class="tab-btn active" onclick="openTab(event, 'tab-market')">📊 市场分析</button>
        <button class="tab-btn" onclick="openTab(event, 'tab-sentiment')">💬 情绪分析</button>
        <button class="tab-btn" onclick="openTab(event, 'tab-news')">📰 新闻分析</button>
        <button class="tab-btn" onclick="openTab(event, 'tab-fundamentals')">📈 基本面</button>
        <button class="tab-btn" onclick="openTab(event, 'tab-debate')">🔄 投资辩论</button>
        <button class="tab-btn" onclick="openTab(event, 'tab-trading')">💼 交易决策</button>
        <button class="tab-btn" onclick="openTab(event, 'tab-risk')">⚖️ 风险辩论</button>
        <button class="tab-btn" onclick="openTab(event, 'tab-decision')">🎯 最终决策</button>
    </div>

    <div class="tab-content-wrapper">
        <div id="tab-market" class="tab-content active">
            <h2>📊 市场技术分析</h2>
            {market_html}
        </div>

        <div id="tab-sentiment" class="tab-content">
            <h2>💬 情绪分析</h2>
            {sentiment_html}
        </div>

        <div id="tab-news" class="tab-content">
            <h2>📰 新闻分析</h2>
            {news_html}
        </div>

        <div id="tab-fundamentals" class="tab-content">
            <h2>📈 基本面分析</h2>
            {fundamentals_html}
        </div>

        <div id="tab-debate" class="tab-content">
            <h2>🔄 投资辩论</h2>
            <h3>看多方观点</h3>
            {bull_html}
            <h3>看空方观点</h3>
            {bear_html}
            <h3>研究经理决策</h3>
            {investment_plan_html}
        </div>

        <div id="tab-trading" class="tab-content">
            <h2>💼 交易决策</h2>
            <h3>交易员提案</h3>
            {trader_html}
        </div>

        <div id="tab-risk" class="tab-content">
            <h2>⚖️ 风险辩论</h2>
            <h3>激进观点</h3>
            {aggressive_html}
            <h3>保守观点</h3>
            {conservative_html}
            <h3>中性观点</h3>
            {neutral_html}
        </div>

        <div id="tab-decision" class="tab-content">
            <h2>🎯 最终交易决策</h2>
            {decision_html}
        </div>
    </div>

    <div class="footer">
        <p>由 TradingAgents 多智能体框架生成 | 仅供参考，不构成投资建议</p>
    </div>
    {JAVASCRIPT_TAB}
</body>
</html>"""

    output_path.write_text(html_content, encoding="utf-8")
    return output_path


def generate_pdf_from_html(html_path: Path, pdf_path: Path):
    """Convert HTML to PDF using WeasyPrint."""
    from weasyprint import HTML
    HTML(filename=str(html_path)).write_pdf(str(pdf_path))
    return pdf_path


def main():
    import sys

    # Find report
    reports_dir = Path(__file__).parent / "reports"

    if not reports_dir.exists():
        print("❌ reports 目录不存在")
        return

    # Get latest report
    reports = []
    for d in reports_dir.iterdir():
        if d.is_dir() and "_20" in d.name:
            reports.append(d)

    if not reports:
        print("❌ 未找到任何报告")
        return

    # Sort by date part of report name (format: STOCKCODE_YYYYMMDD_HHMMSS)
    latest_report = max(reports, key=lambda x: x.name.split("_")[1] if len(x.name.split("_")) >= 2 else x.name)
    print(f"📂 使用报告: {latest_report.name}")

    # Load data
    data = load_report_data(latest_report)

    # Generate HTML
    html_output = latest_report / "report.html"
    generate_html_report(data, html_output)
    print(f"✅ HTML 报告已生成: {html_output}")

    # Generate PDF
    try:
        pdf_output = latest_report / "report.pdf"
        generate_pdf_from_html(html_output, pdf_output)
        print(f"✅ PDF 报告已生成: {pdf_output}")
    except Exception as e:
        print(f"⚠️ PDF 生成失败: {e}")
        print("   请确保已安装 WeasyPrint 依赖 (可能需要额外系统库)")


if __name__ == "__main__":
    main()
