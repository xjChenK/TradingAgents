# TradingAgents 运行原理与流程

## 概述

TradingAgents 是一个基于 **多智能体 LLM** 的金融交易框架，模拟真实交易公司的运作模式。通过部署专门的 LLM 驱动智能体：基本面分析师、情绪分析师、技术分析师、交易员、风险管理团队等，协同评估市场状况并给出交易决策。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      TradingAgentsGraph                         │
│                         (主协调器)                               │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  Analyst Team │    │Research Team  │    │ Risk/Portfolio│
│  (分析师团队)   │───▶│ (研究团队)     │───▶│ (风险管理)    │
└───────────────┘    └───────────────┘    └───────────────┘
```

## 完整工作流程

```
                                    ┌─────────────────┐
                                    │      START      │
                                    └────────┬────────┘
                                             │
                                             ▼
                         ┌──────────────────────────────────┐
                         │      Analyst Team (顺序执行)      │
                         │  ┌─────────────────────────────┐ │
                         │  │ Market Analyst → Tools      │ │
                         │  │ Social Analyst → Tools      │ │
                         │  │ News Analyst → Tools        │ │
                         │  │ Fundamentals Analyst → Tools│ │
                         │  └─────────────────────────────┘ │
                         └──────────────┬───────────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────────┐
                         │    Research Debate (多轮辩论)      │
                         │                                   │
                         │  Bull Researcher ←→ Bear Researcher│
                         │         ↕ (最多 max_debate_rounds)│
                         │       Research Manager             │
                         └──────────────┬────────────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────────┐
                         │         Trader Agent              │
                         │     (整合分析，生成投资计划)        │
                         └──────────────┬────────────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────────┐
                         │      Risk Debate (风险辩论)       │
                         │                                   │
                         │  Aggressive ↔ Conservative ↔ Neutral│
                         │         ↕ (最多 max_risk_discuss_rounds)│
                         └──────────────┬────────────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────────┐
                         │       Portfolio Manager           │
                         │    (审核投资计划，做出最终决策)      │
                         └──────────────┬────────────────────┘
                                        │
                                        ▼
                                    ┌────────┐
                                    │  END   │
                                    └────────┘
```

## 各模块详解

### 1. 分析师团队 (Analyst Team)

并行/顺序收集不同维度的市场数据：

| 分析师 | 职责 | 使用工具 |
|--------|------|----------|
| Market Analyst | 技术分析 (MACD, RSI 等指标) | `get_stock_data`, `get_indicators` |
| Social Analyst | 社交媒体情绪分析 | `get_news` |
| News Analyst | 全球新闻与宏观事件 | `get_news`, `get_global_news`, `get_insider_transactions` |
| Fundamentals Analyst | 财务数据分析 | `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement` |

### 2. 研究辩论 (Research Debate)

- **Bull Researcher** (看涨) 和 **Bear Researcher** (看跌) 进行多轮辩论
- 由 **Research Manager** (使用 deep_thinking_llm) 裁决
- 辩论轮数由 `max_debate_rounds` 控制

### 3. 交易决策 (Trader)

- **Trader Agent** 整合所有分析报告
- 生成初步 **投资计划** (Investment Plan)

### 4. 风险辩论 (Risk Debate)

三种风险观点的辩论：
- **Aggressive Analyst** (激进)
- **Conservative Analyst** (保守)
- **Neutral Analyst** (中性)

### 5. 投资组合经理 (Portfolio Manager)

- 审核投资计划
- 结合历史记忆 (`TradingMemoryLog`) 做出**最终交易决策**
- 决策会被记录用于后续反思学习

## 数据流

1. 用户输入：股票代码 (如 `NVDA`) 和交易日期 (如 `2026-01-15`)
2. 分析师阶段：各分析师调用数据工具获取市场数据
3. 研究辩论：多轮辩论形成投资建议
4. 交易阶段：交易员制定具体交易方案
5. 风险辩论：风险分析师评估方案的潜在风险
6. 最终决策：组合经理综合所有信息做出最终交易决定

## 报告输出

CLI 执行完成后会生成完整的本地分析报告，保存位置：

```
~/.tradingagents/logs/<TICKER>/<DATE>/
├── reports/                          ← Markdown 格式分节报告
│   ├── market_report.md
│   ├── sentiment_report.md
│   ├── news_report.md
│   ├── fundamentals_report.md
│   ├── investment_plan.md
│   ├── trader_investment_plan.md
│   └── final_trade_decision.md
└── TradingAgentsStrategy_logs/
    └── full_states_log_<DATE>.json   ← 完整状态 JSON
```

## 关键特性

| 特性 | 说明 |
|------|------|
| **Checkpoint/恢复** | 支持断点续传，崩溃后可从上次成功步骤恢复 |
| **记忆日志** | 每次决策记录到 `~/.tradingagents/memory/trading_memory.md` |
| **反思机制** | 下次运行时获取上次结果，生成反思总结 |
| **多数据源** | 支持 yfinance、Alpha Vantage、akshare 等 |
| **多 LLM 支持** | OpenAI GPT、Google Gemini、Claude、DeepSeek、Qwen 等 |
| **多语言输出** | 支持配置输出语言 (默认中文) |

## 使用方式

### CLI 方式
```bash
tradingagents
```

### Python API 方式
```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

## 配置文件

关键配置项 (`tradingagents/default_config.py`)：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `llm_provider` | `openai` | LLM 提供商 |
| `deep_think_llm` | `MiniMax-M2.7-highspeed` | 深度思考模型 |
| `quick_think_llm` | `MiniMax-M2.7-highspeed` | 快速思考模型 |
| `output_language` | `Chinese` | 输出语言 |
| `max_debate_rounds` | `1` | 研究辩论轮数 |
| `max_risk_discuss_rounds` | `1` | 风险辩论轮数 |
| `checkpoint_enabled` | `False` | 是否启用断点续传 |

## 技术栈

- **LangGraph**: 多智能体工作流编排
- **LangChain**: LLM 接口封装
- **yfinance / akshare / Alpha Vantage**: 金融数据源
- **SQLite**: Checkpoint 持久化
