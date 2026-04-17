"""
fetch_universe.py — TOPIX構成銘柄をJPXから取得してwatchlist.txtに保存する

使い方:
    python fetch_universe.py           # TOPIX全銘柄を取得
    python fetch_universe.py --top 500 # 時価総額上位500銘柄のみ
    python fetch_universe.py --prime   # プライム市場のみ
"""

import argparse
import os
import io
import requests
import pandas as pd


# JPXが公開しているTOPIX構成銘柄ウエイトCSV（毎月更新）
# 確認先: https://www.jpx.co.jp/markets/indices/topix/
JPX_TOPIX_URL = (
    "https://www.jpx.co.jp/automation/markets/indices/topix/files/topixweight_j.csv"
)

WATCHLIST_PATH = "data/watchlist.txt"


def fetch_topix_from_jpx(top_n: int = None, prime_only: bool = False) -> list[dict]:
    """
    JPXのCSVファイルからTOPIX構成銘柄ウエイトを取得する。
    Returns: [{"code": "7203", "name": "トヨタ自動車", "weight": 4.5}, ...]
    """
    print(f"[INFO] JPXからTOPIX構成銘柄を取得中...")
    print(f"       URL: {JPX_TOPIX_URL}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    resp = requests.get(JPX_TOPIX_URL, headers=headers, timeout=30)
    resp.raise_for_status()

    # JPXのCSVはShift-JISエンコード
    content = resp.content.decode("shift_jis", errors="replace")
    df = pd.read_csv(io.StringIO(content), header=0)
    df.columns = [str(c).strip() for c in df.columns]

    print(f"[DEBUG] 列名: {list(df.columns)}")

    # ─── 列名の正規化 ─────────────────────────────────────
    col_map = {}
    for col in df.columns:
        c = str(col)
        if "コード" in c or "code" in c.lower():
            col_map["code"] = col
        elif "銘柄" in c or "name" in c.lower() or "会社" in c:
            col_map["name"] = col
        elif "比率" in c or "weight" in c.lower() or "構成" in c:
            col_map["weight"] = col
        elif "市場" in c or "market" in c.lower() or "区分" in c:
            col_map["market"] = col

    if "code" not in col_map:
        raise ValueError(f"銘柄コード列が見つかりません。列名: {list(df.columns)}")

    # ─── データ抽出 ────────────────────────────────────────
    records = []
    for _, row in df.iterrows():
        try:
            code = str(int(float(str(row[col_map["code"]]).replace(",", "")))).zfill(4)
        except (ValueError, TypeError):
            continue

        if not (code.isdigit() and 1000 <= int(code) <= 9999):
            continue

        name = str(row.get(col_map.get("name", ""), "")).strip()
        weight = 0.0
        try:
            weight = float(str(row.get(col_map.get("weight", ""), 0)).replace(",", ""))
        except (ValueError, TypeError):
            pass

        market = str(row.get(col_map.get("market", ""), "")).strip()

        records.append({
            "code"   : code,
            "name"   : name,
            "weight" : weight,
            "market" : market,
        })

    if not records:
        raise ValueError("銘柄データが取得できませんでした")

    # 時価総額ウェイト降順でソート
    records.sort(key=lambda x: x["weight"], reverse=True)

    # ─── フィルター ────────────────────────────────────────
    if prime_only:
        records = [r for r in records if "プライム" in r["market"]]
        print(f"[INFO] プライム市場フィルター後: {len(records)}銘柄")

    if top_n:
        records = records[:top_n]
        print(f"[INFO] 上位{top_n}銘柄に絞り込み")

    return records


def save_watchlist(records: list[dict], path: str = WATCHLIST_PATH) -> None:
    """取得した銘柄リストをwatchlist.txtに保存する"""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write("# TOPIX構成銘柄リスト（fetch_universe.py で自動生成）\n")
        f.write(f"# 取得銘柄数: {len(records)}銘柄\n")
        f.write("# コード  # 銘柄名（ウェイト順）\n")
        f.write("#\n")
        for r in records:
            name_comment = f"  # {r['name']}" if r["name"] else ""
            f.write(f"{r['code']}{name_comment}\n")

    print(f"[INFO] watchlist.txt を更新しました: {len(records)}銘柄 → {path}")


def main():
    parser = argparse.ArgumentParser(description="TOPIX構成銘柄をwatchlist.txtに保存")
    parser.add_argument("--top",   type=int,  default=None, help="時価総額上位N銘柄のみ")
    parser.add_argument("--prime", action="store_true",     help="プライム市場のみ")
    args = parser.parse_args()

    try:
        records = fetch_topix_from_jpx(top_n=args.top, prime_only=args.prime)
        print(f"[INFO] 取得完了: {len(records)}銘柄")
        save_watchlist(records)
        print("\n次のステップ: python main.py でスクリーニングを実行")

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] JPXへの接続に失敗しました: {e}")
        print("        ネットワーク接続を確認するか、URLを手動で確認してください")
        print(f"        URL: {JPX_TOPIX_URL}")
        raise SystemExit(1)
    except Exception as e:
        print(f"[ERROR] {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
