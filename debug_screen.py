"""
debug_screen.py — 各銘柄がどの条件で除外されているか確認する
候補が0件のときに原因を特定するためのデバッグ用スクリプト
"""

import pandas as pd
import data_fetcher
import config

SAMPLE = ["7203", "6758", "9984", "6861", "8035", "7974", "6501"]

print("=" * 60)
print("デバッグ: スクリーニング条件の通過状況")
print("=" * 60)

for sym in SAMPLE:
    print(f"\n── {sym} ──────────────────────────")
    df_raw = data_fetcher.fetch_ohlcv(sym)
    if df_raw is None:
        print("  → データ取得失敗")
        continue

    df = data_fetcher.compute_indicators(df_raw)
    latest = df.iloc[-1]

    close      = float(latest["Close"])
    ma25       = float(latest["ma25"])    if not pd.isna(latest["ma25"])       else 0
    ma25_slope = float(latest["ma25_slope"]) if not pd.isna(latest["ma25_slope"]) else 0
    vol_ratio  = float(latest["vol_ratio"])  if not pd.isna(latest["vol_ratio"])  else 0
    volume     = float(latest["Volume"])
    new_high   = bool(latest["new_high_5d"]) if not pd.isna(latest["new_high_5d"]) else False

    print(f"  現在値      : {close:,.0f}円")
    print(f"  MA25        : {ma25:,.0f}円  (slope: {ma25_slope:+.1f})")
    print(f"  出来高      : {volume:,.0f}株")
    print(f"  出来高倍率  : {vol_ratio:.2f}倍")
    print(f"  高値更新    : {new_high}")

    # 各条件の判定
    checks = {
        f"株価({close:.0f}) > MIN_PRICE({config.MIN_PRICE})"        : close >= config.MIN_PRICE,
        f"出来高({volume:.0f}) > MIN({config.MIN_VOLUME_PER_DAY})"  : volume >= config.MIN_VOLUME_PER_DAY,
        f"株価({close:.0f}) > MA25({ma25:.0f})"                     : close > ma25,
        f"MA25 slope({ma25_slope:+.1f}) > 0"                        : ma25_slope > 0,
        f"出来高倍率({vol_ratio:.2f}) >= {config.VOLUME_RATIO_MIN}" : vol_ratio >= config.VOLUME_RATIO_MIN,
        f"直近5日高値更新"                                           : new_high,
    }

    all_pass = True
    for cond, result in checks.items():
        mark = "✓" if result else "✗ ← ここで除外"
        print(f"  {mark}  {cond}")
        if not result:
            all_pass = False
            break

    if all_pass:
        print("  → 全条件通過！")
