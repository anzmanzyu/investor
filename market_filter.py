"""
market_filter.py — 地合い（市場環境）フィルター

TOPIXまたは日経225を使って相場全体のトレンドを判定する。
地合いが悪い日はスクリーニング結果があってもエントリーしない。

判定条件（全て満たす場合のみ「地合いOK」）:
  1. TOPIX終値 > MA25
  2. MA25が上向き（5日前比でプラス）
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Optional

# ─── 設定 ──────────────────────────────────────────────
# TOPIXのyfinanceティッカー
# ^TPX が使えない場合は 1306.T（TOPIX連動ETF）を使う
MARKET_TICKERS = ["^TPX", "1306.T"]

# 地合い判定に使う移動平均期間
MARKET_MA_SHORT = 25
MARKET_MA_LONG  = 75

# キャッシュ（同じセッション内で再取得しないよう）
_cache: dict = {}


def fetch_market_data(period: str = "6mo") -> Optional[pd.DataFrame]:
    """TOPIXのデータを取得する。失敗したら代替ティッカーを試す。"""
    for ticker in MARKET_TICKERS:
        try:
            df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
            if df is None or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=["Close"])
            if len(df) >= 30:
                return df
        except Exception:
            continue
    return None


def fetch_market_data_range(start: str, end: str) -> Optional[pd.DataFrame]:
    """指定期間のTOPIXデータを取得する（バックテスト用）"""
    # MA計算のために開始日より90日前から取得
    fetch_start = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
    fetch_end   = (datetime.strptime(end,   "%Y-%m-%d") + timedelta(days=10)).strftime("%Y-%m-%d")

    for ticker in MARKET_TICKERS:
        try:
            df = yf.download(ticker, start=fetch_start, end=fetch_end,
                             auto_adjust=True, progress=False)
            if df is None or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=["Close"])
            if len(df) >= 30:
                # 指標を計算
                df["ma25"] = df["Close"].rolling(MARKET_MA_SHORT).mean()
                df["ma75"] = df["Close"].rolling(MARKET_MA_LONG).mean()
                df["ma25_slope"] = df["ma25"] - df["ma25"].shift(5)
                return df
        except Exception:
            continue
    return None


def is_market_ok(asof_date: str = None, market_df: pd.DataFrame = None) -> tuple[bool, str]:
    """
    指定日時点の地合いを判定する。

    Args:
        asof_date  : 判定日（YYYY-MM-DD）。Noneなら最新データを使う
        market_df  : 事前取得済みのTOPIXデータ（バックテスト用）

    Returns:
        (OK: bool, 理由: str)
    """
    # データ取得
    if market_df is not None:
        df = market_df
    else:
        df = fetch_market_data()

    if df is None or df.empty:
        # データ取得失敗時はフィルターをスキップ（通過扱い）
        return True, "地合いデータ取得失敗（スキップ）"

    # 指標計算（market_dfが渡された場合はすでに計算済み）
    if "ma25" not in df.columns:
        df = df.copy()
        df["ma25"]       = df["Close"].rolling(MARKET_MA_SHORT).mean()
        df["ma75"]       = df["Close"].rolling(MARKET_MA_LONG).mean()
        df["ma25_slope"] = df["ma25"] - df["ma25"].shift(5)

    # 指定日以前のデータに絞る
    if asof_date:
        cutoff = pd.Timestamp(asof_date)
        df = df[df.index <= cutoff]

    if df.empty or len(df) < MARKET_MA_SHORT:
        return True, "地合いデータ不足（スキップ）"

    latest     = df.iloc[-1]
    close      = float(latest["Close"])
    ma25       = float(latest["ma25"])      if not pd.isna(latest["ma25"])      else 0
    ma25_slope = float(latest["ma25_slope"]) if not pd.isna(latest["ma25_slope"]) else 0
    ma75       = float(latest["ma75"])      if "ma75" in df.columns and not pd.isna(latest["ma75"]) else 0

    reasons = []

    # 条件1: 終値 > MA25
    if ma25 > 0 and close < ma25:
        reasons.append(f"TOPIX({close:.0f}) < MA25({ma25:.0f})")

    # 条件2: MA25が上向き
    if ma25_slope < 0:
        reasons.append(f"MA25下向き(slope:{ma25_slope:.1f})")

    if reasons:
        return False, "地合いNG: " + " / ".join(reasons)

    pct = (close - ma25) / ma25 * 100 if ma25 > 0 else 0
    return True, f"地合いOK: TOPIX {close:.0f}(MA25比+{pct:.1f}%)"


def get_market_status() -> dict:
    """現在の地合い情報をまとめて返す（Webアプリ表示用）"""
    df = fetch_market_data()
    if df is None:
        return {"ok": True, "message": "データ取得失敗", "close": 0, "ma25": 0, "pct": 0}

    if "ma25" not in df.columns:
        df["ma25"]       = df["Close"].rolling(MARKET_MA_SHORT).mean()
        df["ma25_slope"] = df["ma25"] - df["ma25"].shift(5)

    latest     = df.iloc[-1]
    close      = float(latest["Close"])
    ma25       = float(latest["ma25"])       if not pd.isna(latest["ma25"])       else 0
    ma25_slope = float(latest["ma25_slope"]) if not pd.isna(latest["ma25_slope"]) else 0
    pct        = (close - ma25) / ma25 * 100 if ma25 > 0 else 0

    ok, message = is_market_ok(market_df=df)

    return {
        "ok"       : ok,
        "message"  : message,
        "close"    : close,
        "ma25"     : ma25,
        "ma25_slope": ma25_slope,
        "pct"      : pct,
        "date"     : df.index[-1].strftime("%Y-%m-%d"),
    }
