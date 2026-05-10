#!/usr/bin/env python3
"""
AkShare Financial Data Fetcher (Standalone CLI)
获取个股财务数据：净利润、自由现金流、总股本、有息负债、现金等
使用同花顺(THS)数据源，更稳定可靠

Usage:
    python stock_financial_data.py --code 000001 --name 平安银行
    python stock_financial_data.py --code 600519 --name 贵州茅台 --optional
"""

import argparse
import json
from datetime import datetime

try:
    import akshare as ak
    import pandas as pd
except ImportError:
    print("请先安装 akshare 和 pandas: pip install akshare pandas")
    exit(1)


def get_financial_data(stock_code: str, stock_name: str, include_optional: bool = False) -> dict:
    """
    获取个股财务数据

    Args:
        stock_code: 股票代码 (e.g., "000001", "600519")
        stock_name: 股票名称
        include_optional: 是否包含辅助数据
    """
    result = {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "report_date": datetime.now().strftime("%Y-%m-%d"),
        "required_data": {},
        "optional_data": {},
        "errors": [],
    }

    # 1. 获取净利润 (Net Income) 和基本财务指标
    print(f"正在获取 {stock_name}({stock_code}) 的财务数据...")
    financial_data = get_financial_abstract(stock_code)
    if financial_data:
        result["required_data"]["net_income"] = financial_data.get("net_income")
        print(f"  净利润: {financial_data.get('net_income')}")
    else:
        result["errors"].append("净利润获取失败")

    # 2. 获取总股本 (Total Shares)
    print(f"正在获取总股本...")
    total_shares = get_total_shares(stock_code)
    result["required_data"]["total_shares"] = total_shares
    print(f"  总股本: {total_shares}")

    # 3. 获取现金及等价物 (Cash and Equivalents)
    cash = get_cash_and_equivalents(stock_code)
    result["required_data"]["cash_and_equivalents"] = cash
    print(f"  现金及等价物: {cash}")

    # 4. 获取有息负债 (Interest-bearing Debt)
    print(f"正在获取有息负债...")
    debt_info = get_interest_bearing_debt(stock_code)
    result["required_data"]["interest_bearing_debt"] = debt_info["total"]
    result["required_data"]["_debt_detail"] = debt_info["detail"]
    print(f"  有息负债: {debt_info['total']}")

    # 5. 计算自由现金流 (FCF)
    print(f"正在计算自由现金流...")
    fcf = calculate_fcf(stock_code)
    result["required_data"]["free_cash_flow"] = fcf
    print(f"  自由现金流: {fcf}")

    # 6. 可选数据
    if include_optional:
        print(f"正在获取辅助数据...")
        get_optional_data(stock_code, result, financial_data)

    print(f"\n数据获取完成!")
    return result


def get_financial_abstract(stock_code: str) -> dict:
    """获取财务摘要数据 (同花顺)"""
    result = {}

    try:
        df = ak.stock_financial_abstract_ths(symbol=stock_code)
        if df is None or df.empty:
            return result

        # 数据按日期升序排列，取最后一行获取最新数据
        latest = df.iloc[-1]
        print(f"    报告期: {latest.get('报告期')}")

        # 净利润 - 尝试多个列名
        net_income = latest.get("净利润")
        if net_income is not None:
            result["net_income"] = parse_number(net_income)

        # 营业总收入
        revenue = latest.get("营业总收入")
        if revenue is not None:
            result["revenue"] = parse_number(revenue)

        # 销售净利率
        net_margin = latest.get("销售净利率")
        if net_margin is not None:
            result["net_margin"] = parse_number(net_margin)

        # 销售毛利率
        gross_margin = latest.get("销售毛利率")
        if gross_margin is not None:
            result["gross_margin"] = parse_number(gross_margin)

        # 资产负债率
        debt_ratio = latest.get("资产负债率")
        if debt_ratio is not None:
            result["debt_ratio"] = parse_number(debt_ratio)

        # 每股经营现金流
        op_cf_per_share = latest.get("每股经营现金流")
        if op_cf_per_share is not None:
            result["op_cf_per_share"] = parse_number(op_cf_per_share)

    except Exception as e:
        print(f"    财务摘要获取失败: {e}")

    return result


def get_total_shares(stock_code: str) -> float:
    """获取总股本"""
    try:
        df = ak.stock_share_change_cninfo(symbol=stock_code)
        if df is None or df.empty:
            return None

        # 找总股本列
        if "总股本" in df.columns:
            for i in range(len(df)):
                val = df.iloc[i]["总股本"]
                if val is not None and not pd.isna(val):
                    return float(val)

    except Exception as e:
        print(f"    总股本获取失败: {e}")

    return None


def get_cash_and_equivalents(stock_code: str) -> float:
    """获取现金及现金等价物"""
    try:
        df = ak.stock_financial_debt_ths(symbol=stock_code)
        if df is None or df.empty:
            return None

        # 取最新数据
        latest = df.iloc[-1]

        # 货币资金 = 现金
        cash = latest.get("货币资金")
        if cash is not None:
            return parse_number(cash)

    except Exception as e:
        print(f"    现金获取失败: {e}")

    return None


def get_interest_bearing_debt(stock_code: str) -> dict:
    """
    获取有息负债
    有息负债 = 短期借款 + 长期借款 + 应付债券 + 一年内到期的非流动负债
    """
    result = {"total": None, "detail": {}}

    try:
        df = ak.stock_financial_debt_ths(symbol=stock_code)
        if df is None or df.empty:
            return result

        # 取最新数据
        latest = df.iloc[-1]

        short_term_loan = parse_number(latest.get("短期借款")) or 0
        long_term_loan = parse_number(latest.get("长期借款")) or 0
        bonds_payable = parse_number(latest.get("应付债券")) or 0
        non_current_due = parse_number(latest.get("一年内到期的非流动负债")) or 0

        total = short_term_loan + long_term_loan + bonds_payable + non_current_due

        result["detail"] = {
            "short_term_loan": short_term_loan,
            "long_term_loan": long_term_loan,
            "bonds_payable": bonds_payable,
            "non_current_liabilities_due": non_current_due,
        }
        result["total"] = round(total, 2)

    except Exception as e:
        print(f"    有息负债获取失败: {e}")

    return result


def calculate_fcf(stock_code: str) -> float:
    """
    计算自由现金流 (Free Cash Flow)
    FCF = 净利润 + 折旧摊销 - 资本支出 - 营运资本变动
    """
    try:
        cash_df = ak.stock_financial_cash_ths(symbol=stock_code)
        if cash_df is None or cash_df.empty:
            return None

        latest = cash_df.iloc[0]

        # 净利润
        net_income = parse_number(latest.get("净利润")) or 0

        # 折旧摊销
        depreciation = parse_number(latest.get("固定资产折旧、油气资产折耗、生产性生物资产折旧")) or 0
        amortization = parse_number(latest.get("无形资产摊销")) or 0
        long_term_deferred = parse_number(latest.get("长期待摊费用摊销")) or 0
        da = depreciation + amortization + long_term_deferred

        # 资本支出
        capex = parse_number(latest.get("购建固定资产、无形资产和其他长期资产支付的现金")) or 0

        # 营运资本变动 (间接法)
        # 存货的减少 + 经营性应收项目的减少 + 经营性应付项目的增加
        inventory_decrease = parse_number(latest.get("存货的减少")) or 0
        operating_receivable_decrease = parse_number(latest.get("经营性应收项目的减少")) or 0
        operating_payable_increase = parse_number(latest.get("经营性应付项目的增加")) or 0
        working_capital_change = inventory_decrease + operating_receivable_decrease + operating_payable_increase

        fcf = net_income + da - capex + working_capital_change
        return round(fcf, 2)

    except Exception as e:
        print(f"    计算FCF失败: {e}")
        return None


def get_optional_data(stock_code: str, result: dict, financial_data: dict):
    """获取辅助数据"""
    try:
        # 营业收入
        if "revenue" in financial_data:
            result["optional_data"]["revenue"] = financial_data["revenue"]
            print(f"  营业收入: {financial_data['revenue']}")

        # 毛利率
        if "gross_margin" in financial_data:
            result["optional_data"]["gross_margin"] = financial_data["gross_margin"]
            print(f"  毛利率: {financial_data['gross_margin']}%")

        # 净利率
        if "net_margin" in financial_data:
            result["optional_data"]["net_margin"] = financial_data["net_margin"]
            print(f"  净利率: {financial_data['net_margin']}%")

        # 资产负债率
        if "debt_ratio" in financial_data:
            result["optional_data"]["debt_to_asset_ratio"] = financial_data["debt_ratio"]
            print(f"  资产负债率: {financial_data['debt_ratio']}%")

        # 经营现金流
        try:
            cash_df = ak.stock_financial_cash_ths(symbol=stock_code)
            if cash_df is not None and not cash_df.empty:
                # 取最新数据
                operating_cf = cash_df.iloc[-1].get("经营活动产生的现金流量净额")
                if operating_cf is not None:
                    result["optional_data"]["operating_cash_flow"] = parse_number(operating_cf)
                    print(f"  经营现金流: {result['optional_data']['operating_cash_flow']}")
        except Exception as e:
            print(f"    经营现金流获取失败: {e}")

    except Exception as e:
        print(f"获取辅助数据失败: {e}")


def parse_number(val) -> float:
    """解析数字字符串 (如 '1.47亿' -> 147000000)"""
    if val is None:
        return None

    if isinstance(val, (int, float)):
        return float(val)

    val_str = str(val).strip()

    # 处理 False 或无效值
    if val_str.upper() == "FALSE" or val_str == "":
        return None

    try:
        # 亿
        if "亿" in val_str:
            return float(val_str.replace("亿", "").replace(",", "")) * 1e8
        # 万
        elif "万" in val_str:
            return float(val_str.replace("万", "").replace(",", "")) * 1e4
        # 百分比
        elif "%" in val_str:
            return float(val_str.replace("%", "").replace(",", ""))
        else:
            # 尝试直接转换
            return float(val_str.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def main():
    parser = argparse.ArgumentParser(description="获取个股财务数据")
    parser.add_argument("--code", required=True, help="股票代码 (如: 000001, 600519)")
    parser.add_argument("--name", required=True, help="股票名称 (如: 平安银行)")
    parser.add_argument("--optional", action="store_true", help="包含辅助数据")
    parser.add_argument("--json", action="store_true", help="输出JSON格式")

    args = parser.parse_args()

    result = get_financial_data(args.code, args.name, args.optional)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print("\n" + "=" * 60)
        print(f"股票: {result['stock_name']} ({result['stock_code']})")
        print("=" * 60)
        print("\n【必填数据】")
        for key, value in result["required_data"].items():
            if not key.startswith("_"):
                print(f"  {key}: {value}")

        if result["optional_data"]:
            print("\n【辅助数据】")
            for key, value in result["optional_data"].items():
                print(f"  {key}: {value}")

        if result.get("errors"):
            print("\n【错误信息】")
            for err in result["errors"]:
                print(f"  - {err}")


if __name__ == "__main__":
    main()