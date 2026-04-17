"""
portfolio.py — 実際のポジション管理
エントリーを記録して現在値から損益をリアルタイム計算する。
"""

import os
import csv
import pandas as pd
import yfinance as yf
from datetime import date, datetime
import config

POSITIONS_CSV = "data/positions.csv"

FIELDS = [
    "id",
    "エントリー日",
    "銘柄コード",
    "銘柄名",
    "エントリー価格",
    "株数",
    "損切り価格",
    "利確価格",
    "ステータス",      # open / closed
    "決済日",
    "決済価格",
    "決済理由",
    "確定損益",
    "メモ",
]


def _ensure_file():
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(POSITIONS_CSV):
        with open(POSITIONS_CSV, "w", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def load_positions() -> pd.DataFrame:
    _ensure_file()
    try:
        df = pd.read_csv(POSITIONS_CSV, encoding="utf-8-sig")
        if df.empty:
            return pd.DataFrame(columns=FIELDS)
        return df
    except Exception:
        return pd.DataFrame(columns=FIELDS)


def save_positions(df: pd.DataFrame):
    _ensure_file()
    df.to_csv(POSITIONS_CSV, index=False, encoding="utf-8-sig")


def add_position(entry_date, symbol, name, entry_price, shares, stop, tp, memo="") -> int:
    """新規ポジションを追加してIDを返す"""
    df = load_positions()
    new_id = int(df["id"].max()) + 1 if not df.empty and "id" in df.columns else 1
    row = {
        "id"            : new_id,
        "エントリー日"  : entry_date,
        "銘柄コード"    : symbol,
        "銘柄名"        : name,
        "エントリー価格": entry_price,
        "株数"          : shares,
        "損切り価格"    : stop,
        "利確価格"      : tp,
        "ステータス"    : "open",
        "決済日"        : "",
        "決済価格"      : "",
        "決済理由"      : "",
        "確定損益"      : "",
        "メモ"          : memo,
    }
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_positions(df)
    return new_id


def close_position(pos_id: int, exit_price: float, exit_reason: str, exit_date: str = None):
    """ポジションを決済する"""
    df = load_positions()
    idx = df[df["id"] == pos_id].index
    if idx.empty:
        return False

    i = idx[0]
    entry_price = float(df.at[i, "エントリー価格"])
    shares      = int(df.at[i, "株数"])
    pnl         = (exit_price - entry_price) * shares

    df.at[i, "ステータス"]  = "closed"
    df.at[i, "決済日"]      = exit_date or date.today().strftime("%Y-%m-%d")
    df.at[i, "決済価格"]    = exit_price
    df.at[i, "決済理由"]    = exit_reason
    df.at[i, "確定損益"]    = round(pnl, 0)
    save_positions(df)
    return True


def get_current_price(symbol: str) -> float | None:
    """yfinanceから現在値（最新終値）を取得"""
    ticker = symbol if symbol.endswith(".T") else f"{symbol}.T" if config.MARKET == "JP" else symbol
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


def get_open_positions_with_pnl() -> list[dict]:
    """オープンポジションに現在値・損益を付けて返す"""
    df = load_positions()
    if df.empty:
        return []

    open_df = df[df["ステータス"] == "open"]
    results = []

    for _, row in open_df.iterrows():
        sym         = str(row["銘柄コード"])
        entry_price = float(row["エントリー価格"])
        shares      = int(row["株数"])
        stop        = float(row["損切り価格"])
        tp          = float(row["利確価格"])

        current = get_current_price(sym)
        if current is None:
            current = entry_price
            status_mark = "⚠️ 取得失敗"
        else:
            if current <= stop:
                status_mark = "🔴 損切りライン割れ"
            elif current >= tp:
                status_mark = "🟢 利確ライン到達"
            else:
                status_mark = "🟡 保有中"

        unrealized_pnl = (current - entry_price) * shares
        pnl_pct        = (current - entry_price) / entry_price * 100

        results.append({
            "id"            : int(row["id"]),
            "エントリー日"  : row["エントリー日"],
            "銘柄コード"    : sym,
            "銘柄名"        : row["銘柄名"],
            "エントリー価格": entry_price,
            "現在値"        : current,
            "株数"          : shares,
            "損切り価格"    : stop,
            "利確価格"      : tp,
            "未実現損益"    : round(unrealized_pnl, 0),
            "損益率"        : round(pnl_pct, 2),
            "状態"          : status_mark,
            "メモ"          : row.get("メモ", ""),
        })

    return results


def get_summary() -> dict:
    """損益サマリーを返す"""
    df = load_positions()
    if df.empty:
        return {"total": 0, "open": 0, "closed": 0, "realized_pnl": 0, "win": 0, "lose": 0}

    closed = df[df["ステータス"] == "closed"]
    pnl_vals = pd.to_numeric(closed["確定損益"], errors="coerce").dropna()

    return {
        "total"       : len(df),
        "open"        : len(df[df["ステータス"] == "open"]),
        "closed"      : len(closed),
        "realized_pnl": pnl_vals.sum(),
        "win"         : int((pnl_vals > 0).sum()),
        "lose"        : int((pnl_vals <= 0).sum()),
    }
