"""
dividend_manager.py — 高配当株ポートフォリオ管理（改良⑩）

保有銘柄の登録・表示・削除と、配当スケジュール・財務健全性の取得を担当する。
保存先: data/dividend_portfolio.csv
"""

import os
import csv
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import date, datetime, timedelta
from typing import Optional
import config

DIVIDEND_CSV = "data/dividend_portfolio.csv"

FIELDS = [
    "id",
    "銘柄コード",
    "銘柄名",
    "保有数",
    "取得単価",
    "セクター",
    "登録日",
]


# ─── ファイル管理 ─────────────────────────────────────────

def _ensure_file():
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(DIVIDEND_CSV):
        with open(DIVIDEND_CSV, "w", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def load_portfolio() -> pd.DataFrame:
    _ensure_file()
    try:
        df = pd.read_csv(DIVIDEND_CSV, encoding="utf-8-sig")
        return df if not df.empty else pd.DataFrame(columns=FIELDS)
    except Exception:
        return pd.DataFrame(columns=FIELDS)


def save_portfolio(df: pd.DataFrame):
    _ensure_file()
    df.to_csv(DIVIDEND_CSV, index=False, encoding="utf-8-sig")


# ─── 銘柄の追加・削除 ────────────────────────────────────

def add_stock(symbol: str, name: str, shares: int, cost_price: float,
              sector: str = "その他") -> int:
    """保有銘柄を追加して ID を返す"""
    df = load_portfolio()
    new_id = int(df["id"].max()) + 1 if not df.empty and "id" in df.columns else 1
    row = {
        "id"      : new_id,
        "銘柄コード": symbol,
        "銘柄名"  : name,
        "保有数"  : shares,
        "取得単価": cost_price,
        "セクター": sector,
        "登録日"  : date.today().strftime("%Y-%m-%d"),
    }
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_portfolio(df)
    return new_id


def remove_stock(stock_id: int) -> bool:
    """ID で保有銘柄を削除する"""
    df = load_portfolio()
    if df.empty:
        return False
    new_df = df[df["id"] != stock_id]
    if len(new_df) == len(df):
        return False
    save_portfolio(new_df)
    return True


# ─── 価格・配当データ取得 ────────────────────────────────

def _build_ticker(symbol: str) -> str:
    if config.MARKET == "JP" and not symbol.endswith(".T"):
        return f"{symbol}.T"
    return symbol


def _get_current_price(symbol: str) -> Optional[float]:
    ticker = _build_ticker(symbol)
    try:
        df = yf.download(ticker, period="5d", auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        return float(df["Close"].iloc[-1]) if not df.empty else None
    except Exception:
        return None


def _get_annual_dividend(symbol: str) -> Optional[float]:
    """年間1株配当を取得する。取得できない場合は None を返す。"""
    ticker = _build_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        info = t.info
        div = info.get("trailingAnnualDividendRate") or info.get("dividendRate")
        if div and float(div) > 0:
            return float(div)
        # dividends から直近1年合計で算出
        divs = t.dividends
        if divs is not None and not divs.empty:
            one_year_ago = pd.Timestamp.now() - pd.DateOffset(years=1)
            recent = divs[divs.index >= one_year_ago]
            if not recent.empty:
                return float(recent.sum())
        return None
    except Exception:
        return None


# ─── ポートフォリオ一覧（現在値付き）─────────────────────

def get_portfolio_with_prices() -> list[dict]:
    """保有銘柄に現在値・評価額・損益・利回りを付けて返す"""
    df = load_portfolio()
    if df.empty:
        return []

    results = []
    for _, row in df.iterrows():
        sym    = str(row["銘柄コード"])
        cost   = float(row["取得単価"])
        shares = int(row["保有数"])

        current    = _get_current_price(sym)
        annual_div = _get_annual_dividend(sym)

        if current is None:
            current_val  = cost
            price_status = "⚠️ 取得失敗"
        else:
            current_val  = current
            price_status = "✅"

        eval_amount    = current_val * shares
        cost_amount    = cost * shares
        unrealized     = eval_amount - cost_amount
        unrealized_pct = unrealized / cost_amount * 100 if cost_amount > 0 else 0

        current_yield = (annual_div / current_val * 100) if (annual_div and current_val > 0) else None
        cost_yield    = (annual_div / cost * 100)        if (annual_div and cost > 0)        else None
        annual_income = (annual_div * shares)             if annual_div else None

        results.append({
            "id"         : int(row["id"]),
            "銘柄コード" : sym,
            "銘柄名"     : row["銘柄名"],
            "保有数"     : shares,
            "取得単価"   : cost,
            "セクター"   : row.get("セクター", ""),
            "現在値"     : round(current_val, 0),
            "評価額"     : round(eval_amount, 0),
            "含み損益"   : round(unrealized, 0),
            "含み損益%"  : round(unrealized_pct, 2),
            "現在利回り" : round(current_yield, 2) if current_yield else None,
            "取得利回り" : round(cost_yield,    2) if cost_yield    else None,
            "年間配当額" : round(annual_income,  0) if annual_income else None,
            "状態"       : price_status,
        })

    return results


# ─── 配当スケジュール ─────────────────────────────────────

def get_dividend_schedule(symbol: str) -> dict:
    """
    権利確定日・権利落ち日・権利付き最終日・カウントダウンを返す。
    yfinance で取得できない場合は「要手動確認」を返す。
    """
    ticker = _build_ticker(symbol)
    _base = {
        "権利落ち日"      : "要手動確認",
        "権利確定日"      : "要手動確認",
        "権利付き最終日"  : "要手動確認",
        "配当月"          : "不明",
        "カウントダウン"  : None,
        "カウントダウン状態": "unknown",
    }

    try:
        t    = yf.Ticker(ticker)
        info = t.info

        ex_div_raw = info.get("exDividendDate")
        if not ex_div_raw:
            return _base

        # Unix timestamp or string
        if isinstance(ex_div_raw, (int, float)):
            ex_date = datetime.fromtimestamp(ex_div_raw).date()
        else:
            ex_date = pd.Timestamp(ex_div_raw).date()

        # 権利付き最終日 = 権利落ち日の前営業日（簡易: 暦日-1日）
        last_buy = ex_date - timedelta(days=1)
        # 権利確定日 = 権利落ち日の翌営業日（簡易: 暦日+1日）
        record   = ex_date + timedelta(days=1)

        today              = date.today()
        days_to_last_buy   = (last_buy - today).days

        if days_to_last_buy < 0:
            status    = "権利落ち済み"
            countdown = None
        else:
            countdown = days_to_last_buy
            if days_to_last_buy <= 7:
                status = "danger"
            elif days_to_last_buy <= 30:
                status = "warning"
            else:
                status = "ok"

        return {
            "権利落ち日"      : ex_date.strftime("%Y-%m-%d"),
            "権利確定日"      : record.strftime("%Y-%m-%d"),
            "権利付き最終日"  : last_buy.strftime("%Y-%m-%d"),
            "配当月"          : ex_date.strftime("%Y年%m月"),
            "カウントダウン"  : countdown,
            "カウントダウン状態": status,
        }
    except Exception:
        return _base


# ─── 権利落ち後分析 ───────────────────────────────────────

def get_historical_analysis(symbol: str) -> dict:
    """
    過去3年の権利落ち後の実績を分析する。
    - 権利落ち日の実際の下落額・下落率
    - 前日終値水準への回復日数
    - 平均回復日数
    """
    ticker = _build_ticker(symbol)
    try:
        t    = yf.Ticker(ticker)
        divs = t.dividends

        if divs is None or divs.empty:
            return {"error": "配当データなし（手動確認推奨）"}

        three_years_ago = pd.Timestamp.now() - pd.DateOffset(years=3)
        recent_divs     = divs[divs.index >= three_years_ago]

        if recent_divs.empty:
            return {"error": "直近3年の配当データなし（手動確認推奨）"}

        # 株価履歴（4年分）
        hist = yf.download(ticker, period="4y", auto_adjust=True, progress=False)
        if hist is None or hist.empty:
            return {"error": "株価データ取得失敗"}
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        hist = hist.dropna(subset=["Close"])

        # 最新の1株配当
        latest_div = float(recent_divs.iloc[-1]) if not recent_divs.empty else None

        records = []
        for ex_date_ts, div_amount in recent_divs.items():
            ex_ts = pd.Timestamp(ex_date_ts)
            pre   = hist[hist.index < ex_ts].tail(1)
            post  = hist[hist.index >= ex_ts].head(1)

            if pre.empty or post.empty:
                continue

            prev_close    = float(pre["Close"].iloc[0])
            ex_day_close  = float(post["Close"].iloc[0])
            drop          = ex_day_close - prev_close
            drop_pct      = drop / prev_close * 100 if prev_close > 0 else 0

            # 権利落ち後に前日終値水準まで回復した日数
            after_ex      = hist[hist.index >= ex_ts]
            recovery_days: object = "未回復"
            for i, (_, r) in enumerate(after_ex.iterrows()):
                if float(r["Close"]) >= prev_close:
                    recovery_days = i
                    break

            records.append({
                "権利落ち日"      : ex_ts.strftime("%Y-%m-%d"),
                "配当額"          : round(float(div_amount), 2),
                "前日終値"        : round(prev_close, 0),
                "権利落ち日終値"  : round(ex_day_close, 0),
                "実際下落額"      : round(drop, 0),
                "実際下落率%"     : round(drop_pct, 2),
                "回復日数"        : recovery_days,
            })

        numeric_recoveries = [r["回復日数"] for r in records if isinstance(r["回復日数"], int)]
        avg_recovery = round(sum(numeric_recoveries) / len(numeric_recoveries), 1) if numeric_recoveries else None

        return {
            "records"          : records,
            "latest_div"       : latest_div,
            "avg_recovery_days": avg_recovery,
        }
    except Exception as e:
        return {"error": f"分析エラー: {str(e)[:80]}"}


# ─── 財務健全性チェック ───────────────────────────────────

def get_financial_health(symbol: str) -> dict:
    """
    配当性向・自己資本比率・増減配トレンドを返す。
    yfinance の精度が低い場合は「データなし」を返す。
    """
    ticker = _build_ticker(symbol)
    try:
        t    = yf.Ticker(ticker)
        info = t.info

        # 配当性向（0.5 → 50%）
        payout_ratio = info.get("payoutRatio")
        if payout_ratio is not None:
            try:
                payout_ratio = float(payout_ratio) * 100
            except Exception:
                payout_ratio = None

        # 自己資本比率
        equity_ratio = None
        try:
            bs = t.balance_sheet
            if bs is not None and not bs.empty:
                equity_keys = [
                    "Total Stockholder Equity",
                    "Stockholders Equity",
                    "Total Equity Gross Minority Interest",
                ]
                asset_keys  = ["Total Assets"]
                eq = None
                ta = None
                for k in equity_keys:
                    if k in bs.index:
                        eq = float(bs.loc[k].iloc[0])
                        break
                for k in asset_keys:
                    if k in bs.index:
                        ta = float(bs.loc[k].iloc[0])
                        break
                if eq is not None and ta and ta > 0:
                    equity_ratio = round(eq / ta * 100, 1)
        except Exception:
            pass

        # 配当推移（直近3年）
        div_trend        = "データなし"
        div_trend_status = "unknown"
        try:
            divs = t.dividends
            if divs is not None and not divs.empty:
                three_years_ago = pd.Timestamp.now() - pd.DateOffset(years=3)
                recent = divs[divs.index >= three_years_ago]
                if len(recent) >= 2:
                    annual = recent.groupby(recent.index.year).sum()
                    if len(annual) >= 2:
                        years = sorted(annual.index)
                        trend = [float(annual[y]) for y in years[-3:] if y in annual]
                        if len(trend) >= 2:
                            if all(trend[i] <= trend[i + 1] for i in range(len(trend) - 1)):
                                if len(trend) >= 3:
                                    div_trend        = "✅ 3年連続増配"
                                    div_trend_status = "good"
                                else:
                                    div_trend        = "✅ 増配傾向"
                                    div_trend_status = "good"
                            elif trend[-1] < trend[-2]:
                                div_trend        = "⚠️ 直近1年で減配あり"
                                div_trend_status = "warning"
                            else:
                                div_trend        = "横ばい"
                                div_trend_status = "neutral"
        except Exception:
            pass

        return {
            "payout_ratio"    : payout_ratio,
            "equity_ratio"    : equity_ratio,
            "div_trend"       : div_trend,
            "div_trend_status": div_trend_status,
        }
    except Exception:
        return {
            "payout_ratio"    : None,
            "equity_ratio"    : None,
            "div_trend"       : "データなし",
            "div_trend_status": "unknown",
        }
