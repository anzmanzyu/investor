"""
history.py — 通知履歴の保存・更新・検証
スクリーニング結果を CSV に記録し、後から実績を振り返る。
"""

import os
import csv
from datetime import date
from typing import Optional
import config


HISTORY_FIELDS = [
    "通知日",
    "銘柄コード",
    "銘柄名",
    "現在値",
    "エントリー候補",
    "損切り候補",
    "利確候補",
    "注文株数",
    "抽出理由",
    "見送り注意点",
    # 以下はあとで手動入力する列
    "実際に入ったか",   # はい / いいえ / 見送り
    "実際のエントリー価格",
    "実際のエグジット価格",
    "勝負",             # 勝ち / 負け / 未決済 / 見送り
    "損益(円)",
    "見送り理由",
    "メモ",
    "通知後5日値動き%",
]


def _ensure_file() -> None:
    """履歴CSVが存在しない場合にヘッダー行だけ作成する"""
    os.makedirs(os.path.dirname(config.HISTORY_CSV), exist_ok=True)
    if not os.path.exists(config.HISTORY_CSV):
        with open(config.HISTORY_CSV, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
            writer.writeheader()
        print(f"[History] 履歴ファイルを新規作成: {config.HISTORY_CSV}")


def save_history(candidates: list[dict], run_date: str = None) -> None:
    """
    スクリーニング結果を履歴 CSV に追記する。
    実際の結果（勝負・損益など）は後から手動入力する。
    """
    _ensure_file()
    run_date = run_date or date.today().strftime("%Y-%m-%d")

    with open(config.HISTORY_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        for c in candidates:
            plan = c["plan"]
            writer.writerow({
                "通知日"          : run_date,
                "銘柄コード"      : c["symbol"],
                "銘柄名"          : c["name"],
                "現在値"          : c["close"],
                "エントリー候補"  : plan["entry"],
                "損切り候補"      : plan["stop"],
                "利確候補"        : plan["tp_fixed"],
                "注文株数"        : plan["shares"],
                "抽出理由"        : " / ".join(c["reasons"]),
                "見送り注意点"    : " / ".join(c["warnings"]) if c["warnings"] else "",
                # 以下は空欄のまま。後から手動入力する
                "実際に入ったか"      : "",
                "実際のエントリー価格": "",
                "実際のエグジット価格": "",
                "勝負"                : "",
                "損益(円)"            : "",
                "見送り理由"          : "",
                "メモ"                : "",
                "通知後5日値動き%"    : "",
            })

    print(f"[History] {len(candidates)}件を履歴に追記しました: {config.HISTORY_CSV}")


def print_stats() -> None:
    """
    履歴 CSV の簡易統計を表示する。
    """
    _ensure_file()
    try:
        with open(config.HISTORY_CSV, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except Exception as e:
        print(f"[History] 読み込みエラー: {e}")
        return

    if not rows:
        print("[History] 履歴データがありません")
        return

    total   = len(rows)
    entered = [r for r in rows if r.get("実際に入ったか") == "はい"]
    wins    = [r for r in entered if r.get("勝負") == "勝ち"]
    losses  = [r for r in entered if r.get("勝負") == "負け"]

    pnl_list = []
    for r in entered:
        try:
            pnl_list.append(float(r["損益(円)"]))
        except (ValueError, KeyError):
            pass

    total_pnl  = sum(pnl_list)
    win_rate   = len(wins) / len(entered) * 100 if entered else 0

    print("\n─── 履歴統計 ─────────────────────────────────")
    print(f"  通知件数          : {total}件")
    print(f"  実際に入った件数  : {len(entered)}件")
    print(f"  勝ち              : {len(wins)}件")
    print(f"  負け              : {len(losses)}件")
    print(f"  勝率              : {win_rate:.1f}%")
    print(f"  累計損益          : {total_pnl:+,.0f}円")
    print("──────────────────────────────────────────────\n")
