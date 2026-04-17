"""
main.py — 株式スクリーニングツール エントリーポイント

使い方:
    python main.py              # 通常実行（スクリーニング + 通知）
    python main.py --stats      # 履歴統計を表示
    python main.py --market US  # 米国株でスクリーニング（一時的に設定を上書き）
    python main.py --capital 1000000  # 総資金を変更して計算
"""

import argparse
import sys
from datetime import date

# ── .env が存在すれば読み込む（Discord Webhook URL など）──────
try:
    from dotenv import load_dotenv
    load_dotenv()
    import os
    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    if webhook:
        import config
        config.DISCORD_WEBHOOK_URL = webhook
except ImportError:
    pass

import config
import data_fetcher
import screener
import calculator
import notifier
import history


def parse_args():
    parser = argparse.ArgumentParser(description="株式スクリーニングツール")
    parser.add_argument("--stats",   action="store_true", help="履歴統計を表示して終了")
    parser.add_argument("--market",  type=str, help="対象市場を上書き (JP / US)")
    parser.add_argument("--capital", type=float, help="総資金を上書き（円）")
    parser.add_argument("--risk",    type=float, help="許容損失率を上書き(%%)")
    parser.add_argument("--no-save", action="store_true", help="履歴保存をスキップ")
    return parser.parse_args()


def main():
    args = parse_args()

    # ─── 引数で設定を上書き ─────────────────────────────
    if args.market:
        config.MARKET = args.market.upper()
    if args.capital:
        config.TOTAL_CAPITAL = args.capital
    if args.risk:
        config.RISK_PERCENT = args.risk

    # ─── 履歴統計のみ表示して終了 ─────────────────────────
    if args.stats:
        history.print_stats()
        return

    # ─── スクリーニング開始 ────────────────────────────
    run_date = date.today().strftime("%Y-%m-%d")
    print(f"\n{'='*60}")
    print(f"  株式スクリーニング開始  {run_date}")
    print(f"  市場: {config.MARKET}  総資金: {config.TOTAL_CAPITAL:,}円  許容損失: {config.RISK_PERCENT}%")
    print(f"{'='*60}\n")

    # 銘柄リスト読み込み
    symbols = data_fetcher.load_watchlist()
    print(f"[INFO] 対象銘柄数: {len(symbols)}銘柄\n")

    # スクリーニング実行
    raw_results = screener.run_screening(
        symbols,
        fetch_fn=data_fetcher.fetch_ohlcv,
        info_fn=data_fetcher.fetch_info,
    )

    if not raw_results:
        print("\n[結果] 本日は条件を満たす候補銘柄がありませんでした。")
        return

    # ─── トレードプランを計算して結果に追加 ──────────────
    candidates = []
    for r in raw_results:
        plan = calculator.build_trade_plan(r)
        r["plan"] = plan
        candidates.append(r)

    # ─── 出力 ────────────────────────────────────────
    if config.OUTPUT_CONSOLE:
        notifier.print_summary_table(candidates)
        notifier.print_report(candidates, run_date)

    if config.OUTPUT_CSV:
        notifier.save_csv(candidates, run_date)

    if config.OUTPUT_DISCORD:
        notifier.send_discord(candidates, run_date)

    # ─── 履歴保存 ─────────────────────────────────────
    if not args.no_save:
        history.save_history(candidates, run_date)

    print(f"\n[完了] {len(candidates)}銘柄を抽出しました。")
    print(f"       ※ 投資判断は必ず自己責任で行ってください。\n")


if __name__ == "__main__":
    main()
