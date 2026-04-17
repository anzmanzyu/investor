"""
backtest.py — 過去期間のスクリーニング結果シミュレーション

使い方:
    python backtest.py                          # デフォルト: 2026-03-01〜2026-03-31
    python backtest.py --start 2026-01-01 --end 2026-03-31
    python backtest.py --symbols 7203 6758 9984 # 特定銘柄のみ

前提:
    - 引け後スクリーニング → 翌営業日の始値でエントリー
    - 損切りまたは利確に達したら決済（最大MAX_HOLD_DAYS日保有）
    - 同日複数通過時はスコア上位MAX_ENTRIES_PER_DAY銘柄のみエントリー
"""

import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import warnings
warnings.filterwarnings("ignore")

import config
import data_fetcher
from data_fetcher import compute_indicators
import screener
import calculator

# ─── バックテスト設定 ─────────────────────────────────────
MAX_HOLD_DAYS       = 10    # 最大保有日数 ← 5→10
MAX_ENTRIES_PER_DAY = 2     # 1日あたり最大エントリー数 ← 3→2
SLIPPAGE_PCT        = 0.1   # スリッページ（%）始値から少し不利な価格で入る想定

# ─── 日本の祝日（簡易版・2026年3月）─────────────────────
# yfinanceのデータに取引日が入っているので実際には不要だが参考まで
JP_HOLIDAYS_2026 = [
    "2026-03-20",  # 春分の日
]


def get_trading_days(df: pd.DataFrame, start: str, end: str) -> list:
    """DataFrameのインデックスから指定期間の取引日リストを返す"""
    idx = pd.to_datetime(df.index)
    mask = (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))
    return [d.strftime("%Y-%m-%d") for d in idx[mask]]


def run_screener_asof(symbol: str, full_df: pd.DataFrame, asof_date: str, info: dict):
    """
    指定日時点のデータのみを使ってスクリーニングを実行する。
    （未来のデータを使わないようにする）
    """
    cutoff = pd.Timestamp(asof_date)
    df_slice = full_df[full_df.index <= cutoff].copy()

    if len(df_slice) < 30:
        return None

    df_ind = compute_indicators(df_slice)
    return screener.screen(symbol, df_ind, info)


def simulate_trade(full_df: pd.DataFrame, entry_date: str,
                   entry_price: float, stop: float, tp: float) -> dict:
    """
    エントリー日以降のデータで損切り・利確・期間切れを判定して損益を返す。

    Returns:
        {
            "exit_date": str,
            "exit_price": float,
            "exit_reason": str,  # "TP" / "SL" / "TIMEOUT"
            "pnl_per_share": float,
            "pnl_pct": float,
        }
    """
    cutoff = pd.Timestamp(entry_date)
    future = full_df[full_df.index > cutoff].head(MAX_HOLD_DAYS)

    if future.empty:
        return None

    for dt, row in future.iterrows():
        low  = float(row["Low"])
        high = float(row["High"])
        close = float(row["Close"])

        # 損切り判定（その日の安値が損切り価格を割った）
        if low <= stop:
            exit_price = stop
            exit_reason = "SL（損切り）"
            pnl = exit_price - entry_price
            return {
                "exit_date"    : dt.strftime("%Y-%m-%d"),
                "exit_price"   : exit_price,
                "exit_reason"  : exit_reason,
                "pnl_per_share": round(pnl, 1),
                "pnl_pct"      : round(pnl / entry_price * 100, 2),
            }

        # 利確判定（その日の高値が利確価格を超えた）
        if high >= tp:
            exit_price = tp
            exit_reason = "TP（利確）"
            pnl = exit_price - entry_price
            return {
                "exit_date"    : dt.strftime("%Y-%m-%d"),
                "exit_price"   : exit_price,
                "exit_reason"  : exit_reason,
                "pnl_per_share": round(pnl, 1),
                "pnl_pct"      : round(pnl / entry_price * 100, 2),
            }

    # 期間切れ → 最終日の終値で決済
    last_row   = future.iloc[-1]
    exit_price = float(last_row["Close"])
    exit_date  = future.index[-1].strftime("%Y-%m-%d")
    pnl        = exit_price - entry_price
    return {
        "exit_date"    : exit_date,
        "exit_price"   : exit_price,
        "exit_reason"  : f"期間切れ({MAX_HOLD_DAYS}日)",
        "pnl_per_share": round(pnl, 1),
        "pnl_pct"      : round(pnl / entry_price * 100, 2),
    }


def run_backtest(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    """メインのバックテスト実行"""

    from market_filter import fetch_market_data_range, is_market_ok

    print(f"\n{'='*60}")
    print(f"  バックテスト開始（地合いフィルターON）")
    print(f"  期間: {start} 〜 {end}")
    print(f"  対象銘柄数: {len(symbols)}")
    print(f"  総資金: {config.TOTAL_CAPITAL:,}円  許容損失: {config.RISK_PERCENT}%")
    print(f"{'='*60}\n")

    # ─── TOPIXデータを取得（地合い判定用）──────────────────
    print(f"[INFO] TOPIXデータ取得中...")
    market_df = fetch_market_data_range(start, end)
    if market_df is None:
        print("[WARN] TOPIXデータ取得失敗。地合いフィルターをスキップします。")
    else:
        print(f"[INFO] TOPIXデータ取得完了\n")

    # ─── 全銘柄のデータを一括取得（期間を少し広めに取る）─────
    fetch_start = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
    fetch_end   = (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=10)).strftime("%Y-%m-%d")

    print(f"[INFO] データ取得中（{fetch_start} 〜 {fetch_end}）...")
    all_data = {}
    all_info = {}
    for i, sym in enumerate(symbols, 1):
        ticker = data_fetcher._build_ticker(sym)
        try:
            import yfinance as yf
            df = yf.download(ticker, start=fetch_start, end=fetch_end,
                             auto_adjust=True, progress=False)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.dropna(subset=["Close"])
                if len(df) >= 30:
                    all_data[sym] = df
                    all_info[sym] = data_fetcher.fetch_info(sym)
        except Exception:
            pass
        if i % 50 == 0:
            print(f"  {i}/{len(symbols)} 取得完了...")

    print(f"[INFO] データ取得完了: {len(all_data)}銘柄\n")

    # ─── 取引日リストを取得（代表銘柄のインデックスから）──────
    rep_df = next(iter(all_data.values()))
    trading_days = get_trading_days(rep_df, start, end)
    print(f"[INFO] 取引日数: {len(trading_days)}日\n")

    # ─── 日次スクリーニング → トレードシミュレーション ─────
    all_trades   = []
    capital      = config.TOTAL_CAPITAL
    equity_curve = [{"date": start, "equity": capital}]
    skipped_days = 0

    for screen_date in trading_days:
        # ── 地合いフィルター ─────────────────────────────────
        if market_df is not None:
            ok, reason = is_market_ok(asof_date=screen_date, market_df=market_df)
            if not ok:
                skipped_days += 1
                continue  # 地合いNGの日はエントリーしない

        # この日にスクリーニングを実行（引け後想定）
        day_results = []
        for sym, full_df in all_data.items():
            result = run_screener_asof(sym, full_df, screen_date, all_info.get(sym, {}))
            if result:
                day_results.append(result)

        if not day_results:
            continue

        # スコア上位N銘柄のみ
        day_results.sort(key=lambda r: r["score"], reverse=True)
        day_results = day_results[:MAX_ENTRIES_PER_DAY]

        # 翌日のデータでエントリー
        screen_dt = pd.Timestamp(screen_date)

        for result in day_results:
            sym     = result["symbol"]
            full_df = all_data[sym]
            future  = full_df[full_df.index > screen_dt]

            if future.empty:
                continue

            # 翌日始値でエントリー（スリッページ考慮）
            next_row    = future.iloc[0]
            entry_date  = future.index[0].strftime("%Y-%m-%d")
            raw_entry   = float(next_row["Open"])
            entry_price = round(raw_entry * (1 + SLIPPAGE_PCT / 100), 1)

            # 損切り・利確を計算
            stop_pct = config.STOP_LOSS_PERCENT / 100
            tp_pct   = config.TAKE_PROFIT_PERCENT / 100
            stop     = round(entry_price * (1 - stop_pct), 1)
            tp       = round(entry_price * (1 + tp_pct), 1)

            # 注文サイズ計算
            pos = calculator.calc_position_size(entry_price, stop)
            shares = pos["shares_rounded"]
            if shares == 0:
                continue

            # トレードシミュレーション
            trade_result = simulate_trade(full_df, entry_date, entry_price, stop, tp)
            if trade_result is None:
                continue

            pnl_total = trade_result["pnl_per_share"] * shares
            capital  += pnl_total

            trade_record = {
                "スクリーニング日"  : screen_date,
                "エントリー日"      : entry_date,
                "銘柄コード"        : sym,
                "銘柄名"            : result["name"],
                "スコア"            : result["score"],
                "エントリー価格"    : entry_price,
                "損切り価格"        : stop,
                "利確価格"          : tp,
                "株数"              : shares,
                "決済日"            : trade_result["exit_date"],
                "決済価格"          : trade_result["exit_price"],
                "決済理由"          : trade_result["exit_reason"],
                "1株損益"           : trade_result["pnl_per_share"],
                "損益率%"           : trade_result["pnl_pct"],
                "損益合計"          : round(pnl_total, 0),
                "残高"              : round(capital, 0),
            }
            all_trades.append(trade_record)
            equity_curve.append({"date": entry_date, "equity": round(capital, 0)})

    print(f"\n[INFO] 地合いNGでスキップした日数: {skipped_days}日 / {len(trading_days)}日")
    return pd.DataFrame(all_trades), pd.DataFrame(equity_curve)


def print_summary(df: pd.DataFrame, initial_capital: float):
    """バックテスト結果のサマリーを表示"""
    if df.empty:
        print("\n[結果] トレード0件。条件を満たす銘柄がありませんでした。")
        return

    total_trades = len(df)
    wins   = df[df["損益合計"] > 0]
    losses = df[df["損益合計"] <= 0]
    win_rate = len(wins) / total_trades * 100

    total_pnl    = df["損益合計"].sum()
    avg_win      = wins["損益合計"].mean()   if not wins.empty   else 0
    avg_loss     = losses["損益合計"].mean() if not losses.empty else 0
    profit_factor = abs(wins["損益合計"].sum() / losses["損益合計"].sum()) if not losses.empty else float("inf")
    final_capital = initial_capital + total_pnl
    return_pct    = total_pnl / initial_capital * 100

    print(f"\n{'='*60}")
    print(f"  バックテスト結果サマリー")
    print(f"{'='*60}")
    print(f"  総トレード数    : {total_trades}件")
    print(f"  勝ち           : {len(wins)}件")
    print(f"  負け           : {len(losses)}件")
    print(f"  勝率           : {win_rate:.1f}%")
    print(f"{'─'*60}")
    print(f"  平均利益       : +{avg_win:,.0f}円/トレード")
    print(f"  平均損失       : {avg_loss:,.0f}円/トレード")
    print(f"  プロフィットF  : {profit_factor:.2f}")
    print(f"{'─'*60}")
    print(f"  初期資金       : {initial_capital:,.0f}円")
    print(f"  最終資金       : {final_capital:,.0f}円")
    print(f"  総損益         : {total_pnl:+,.0f}円")
    print(f"  リターン       : {return_pct:+.2f}%")
    print(f"{'='*60}")

    print(f"\n─── 決済理由別内訳 ───────────────────────────")
    for reason, group in df.groupby("決済理由"):
        avg = group["損益合計"].mean()
        print(f"  {reason:15s}: {len(group):3d}件  平均損益 {avg:+,.0f}円")

    print(f"\n─── 銘柄別損益ランキング（上位10） ───────────")
    by_symbol = df.groupby(["銘柄コード", "銘柄名"])["損益合計"].sum().sort_values(ascending=False)
    for (code, name), pnl in by_symbol.head(10).items():
        print(f"  {code} {name[:12]:12s}: {pnl:+,.0f}円")

    print(f"\n─── トレード一覧 ──────────────────────────────")
    display_cols = ["エントリー日", "銘柄コード", "銘柄名", "エントリー価格",
                    "決済日", "決済理由", "損益率%", "損益合計"]
    print(df[display_cols].to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description="バックテスト")
    parser.add_argument("--start",   default="2026-03-01", help="開始日 YYYY-MM-DD")
    parser.add_argument("--end",     default="2026-03-31", help="終了日 YYYY-MM-DD")
    parser.add_argument("--symbols", nargs="*",            help="対象銘柄コード（省略時はwatchlist.txt）")
    parser.add_argument("--top",     type=int, default=50, help="watchlistから上位N銘柄のみ使用（速度優先）")
    args = parser.parse_args()

    symbols = args.symbols or data_fetcher.load_watchlist()[:args.top]
    initial = config.TOTAL_CAPITAL

    trades_df, equity_df = run_backtest(symbols, args.start, args.end)
    print_summary(trades_df, initial)

    # CSV保存
    import os
    os.makedirs("data/output", exist_ok=True)
    out_path = f"data/output/backtest_{args.start}_{args.end}.csv"
    trades_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n[保存] {out_path}")


if __name__ == "__main__":
    main()
