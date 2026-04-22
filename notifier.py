"""
notifier.py — 通知・出力機能
コンソール表示 / CSV出力 / Discord webhook に対応。
"""

import os
import csv
import json
import requests
from datetime import date, datetime
from tabulate import tabulate
import config


# ─── コンソール出力 ────────────────────────────────────
def print_report(candidates: list[dict], run_date: str = None) -> None:
    """候補銘柄をコンソールに表示する"""
    run_date = run_date or date.today().strftime("%Y-%m-%d")

    print("\n" + "=" * 70)
    print(f"  翌営業日 監視候補リスト  {run_date} 引け後スクリーニング結果")
    print("=" * 70)
    print(f"  総資金: {config.TOTAL_CAPITAL:,}円  |  許容損失: {config.RISK_PERCENT}%  |  候補数: {len(candidates)}銘柄\n")

    for rank, c in enumerate(candidates, 1):
        plan = c["plan"]
        print(f"─── [{rank}位] {c['symbol']} {c['name']}  スコア:{c['score']}点 ───")
        print(f"  現在値   : {c['close']:,.0f} 円  (MA25: {c['ma25']:,.0f}円  乖離: +{c['pct_vs_ma25']:.1f}%)")
        print(f"  出来高倍率: {c['vol_ratio']:.1f}倍 (20日平均比)")
        print(f"  高値更新  : {'あり ✓' if c['new_high_5d'] else 'なし'}")
        print(f"  高値押し  : {c['pullback_pct']:.1f}%")
        print()
        print(f"  ▶ エントリー候補  : {plan['entry']:,.0f} 円")
        print(f"  ▶ 損切り候補      : {plan['stop']:,.0f} 円  ({plan['sl_detail']})")
        print(f"  ▶ 利確候補        : {plan['tp_fixed']:,.0f}円(固定) / {plan['tp_rr']:,.0f}円(RR{config.RISK_REWARD_RATIO})")
        print(f"  ▶ 注文サイズ      : {plan['shares']:,}株  (投資額: {plan['investment']:,.0f}円  |  最大損失: {plan['max_loss']:,.0f}円)")
        if plan["pos_note"]:
            print(f"  ⚠ {plan['pos_note']}")
        print()
        print(f"  【抽出理由】")
        for r in c["reasons"]:
            print(f"    ✓ {r}")
        if c["warnings"]:
            print(f"  【見送り注意点】")
            for w in c["warnings"]:
                print(f"    ⚠ {w}")
        print()

    print("=" * 70)
    print("  ※ 本ツールは情報提供のみ。投資判断は必ず自己責任で行ってください。")
    print("=" * 70 + "\n")


# ─── サマリーテーブル出力 ───────────────────────────────
def print_summary_table(candidates: list[dict]) -> None:
    """候補銘柄のサマリーをテーブル形式で出力する"""
    headers = [
        "順位", "コード", "銘柄名", "現在値", "スコア",
        "エントリー", "損切り", "利確(固定)", "株数", "主な理由"
    ]
    rows = []
    for rank, c in enumerate(candidates, 1):
        plan = c["plan"]
        rows.append([
            rank,
            c["symbol"],
            c["name"][:10],
            f"{c['close']:,.0f}",
            c["score"],
            f"{plan['entry']:,.0f}",
            f"{plan['stop']:,.0f}",
            f"{plan['tp_fixed']:,.0f}",
            f"{plan['shares']:,}株",
            c["reasons"][0] if c["reasons"] else "",
        ])
    print(tabulate(rows, headers=headers, tablefmt="rounded_outline"))


# ─── CSV 出力 ────────────────────────────────────────────
def save_csv(candidates: list[dict], run_date: str = None) -> str:
    """候補銘柄を CSV ファイルに保存する。ファイルパスを返す。"""
    run_date = run_date or date.today().strftime("%Y-%m-%d")
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(config.OUTPUT_DIR, f"candidates_{run_date}.csv")

    fieldnames = [
        "日付", "コード", "銘柄名", "現在値", "MA25", "MA25乖離%",
        "出来高倍率", "高値更新", "押し%", "スコア",
        "エントリー候補", "損切り候補", "利確固定", "利確RR",
        "注文株数", "投資額", "最大損失", "損切り詳細",
        "抽出理由", "見送り注意点"
    ]

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in candidates:
            plan = c["plan"]
            writer.writerow({
                "日付"        : run_date,
                "コード"      : c["symbol"],
                "銘柄名"      : c["name"],
                "現在値"      : c["close"],
                "MA25"        : round(c["ma25"], 1),
                "MA25乖離%"   : round(c["pct_vs_ma25"], 1),
                "出来高倍率"  : round(c["vol_ratio"], 2),
                "高値更新"    : "あり" if c["new_high_5d"] else "なし",
                "押し%"       : round(c["pullback_pct"], 1),
                "スコア"      : c["score"],
                "エントリー候補": plan["entry"],
                "損切り候補"  : plan["stop"],
                "利確固定"    : plan["tp_fixed"],
                "利確RR"      : plan["tp_rr"],
                "注文株数"    : plan["shares"],
                "投資額"      : plan["investment"],
                "最大損失"    : plan["max_loss"],
                "損切り詳細"  : plan["sl_detail"],
                "抽出理由"    : " / ".join(c["reasons"]),
                "見送り注意点": " / ".join(c["warnings"]) if c["warnings"] else "",
            })

    print(f"[CSV] 保存完了: {filepath}")
    return filepath


# ─── Discord 通知 ──────────────────────────────────────
def send_discord(candidates: list[dict], run_date: str = None) -> bool:
    """Discord Webhook に通知を送る。成功したら True を返す。"""
    if not config.DISCORD_WEBHOOK_URL:
        print("[Discord] Webhook URL が未設定のためスキップ")
        return False

    run_date = run_date or date.today().strftime("%Y-%m-%d")

    # 日付を「4月22日（火）」形式に変換
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    dt = datetime.strptime(run_date, "%Y-%m-%d")
    date_jp = f"{dt.month}月{dt.day}日（{weekdays[dt.weekday()]}）"

    lines = [
        f"━" * 28,
        f"📅  **{date_jp}　引け後スクリーニング**",
        f"━" * 28,
        f"📈 **株式スクリーニング結果**",
        f"🎯 候補: {len(candidates)}銘柄",
        "━" * 28,
    ]

    for rank, c in enumerate(candidates, 1):
        plan  = c["plan"]
        medal = ["🥇", "🥈", "🥉"][rank - 1] if rank <= 3 else f"#{rank}"
        high  = "✅ あり" if c["new_high_5d"] else "❌ なし"

        # 選出理由
        reasons_str = "\n".join(f"  ・{r}" for r in c["reasons"])

        # 注意点
        warn_lines = ""
        if c["warnings"]:
            warn_lines = "\n⚠️ **注意点**\n" + "\n".join(f"  ・{w}" for w in c["warnings"])

        lines.append(
            f"\n{medal} **{c['symbol']}:{c['name']}**　スコア: {c['score']}点\n"
            f"\n📊 **テクニカル**\n"
            f"  現在値: {c['close']:,.0f}円（MA25比 +{c['pct_vs_ma25']:.1f}%）\n"
            f"  出来高: {c['vol_ratio']:.1f}倍（20日平均比）｜高値更新: {high}\n"
            f"\n💹 **トレードプラン**\n"
            f"  🎯 エントリー : {plan['entry']:,.0f}円\n"
            f"  🛑 損切り     : {plan['stop']:,.0f}円（-{config.STOP_LOSS_PERCENT}%）\n"
            f"  ✅ 利確目標   : {plan['tp_fixed']:,.0f}円（+{config.TAKE_PROFIT_PERCENT}%）\n"
            f"\n✅ **選出理由**\n{reasons_str}"
            + warn_lines
            + f"\n{'━' * 28}"
        )

    message = "\n".join(lines)

    # Discord の文字数制限 (2000文字) に対応して分割送信
    chunks = _split_message(message, 1900)
    for chunk in chunks:
        try:
            resp = requests.post(
                config.DISCORD_WEBHOOK_URL,
                json={"content": chunk},
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as e:
            print(f"[Discord] 送信エラー: {e}")
            return False

    print("[Discord] 通知送信完了")
    return True


def _split_message(text: str, limit: int) -> list[str]:
    """テキストを limit 文字以内に分割する"""
    lines  = text.split("\n")
    chunks = []
    current = []
    length  = 0
    for line in lines:
        if length + len(line) + 1 > limit:
            chunks.append("\n".join(current))
            current = []
            length  = 0
        current.append(line)
        length += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks
