"""
screener.py — スクリーニングロジック
条件を満たした銘柄を抽出し、スコアと理由・注意点を返す。
条件の追加・変更はここで行う。
"""

import pandas as pd
from typing import Optional
import config


# ─── 型定義 ────────────────────────────────────────────
ScreenResult = dict   # 1銘柄のスクリーニング結果


def screen(symbol: str, df: pd.DataFrame, info: dict) -> Optional[ScreenResult]:
    """
    1銘柄をスクリーニングする。
    条件を満たさない（通過できない）場合は None を返す。
    条件を満たす場合は結果dictを返す。
    """
    if df is None or len(df) < 30:
        return None

    latest = df.iloc[-1]   # 最新足
    prev   = df.iloc[-2]   # 1本前

    close      = float(latest["Close"])
    volume     = float(latest["Volume"])
    vol_ma20   = float(latest["vol_ma20"]) if not pd.isna(latest["vol_ma20"]) else 0
    ma25       = float(latest["ma25"])     if not pd.isna(latest["ma25"])     else 0
    ma25_slope = float(latest["ma25_slope"]) if not pd.isna(latest["ma25_slope"]) else 0
    vol_ratio  = float(latest["vol_ratio"])  if not pd.isna(latest["vol_ratio"])  else 0
    pullback   = float(latest["pullback_pct"]) if not pd.isna(latest["pullback_pct"]) else 999
    gap_pct    = float(latest["gap_pct"])    if not pd.isna(latest["gap_pct"])    else 0
    wick_ratio = float(latest["wick_ratio"]) if not pd.isna(latest["wick_ratio"]) else 0
    new_high   = bool(latest["new_high_5d"]) if not pd.isna(latest["new_high_5d"]) else False

    # ── ハードフィルター（条件未達は即座に除外）─────────────────
    # 1. 低位株除外
    if close < config.MIN_PRICE:
        return None

    # 2. 売買代金フィルター（改良⑤）: 終値 × 出来高 < MIN_TURNOVER は除外
    turnover = close * volume
    if turnover < config.MIN_TURNOVER:
        return None

    # 3. MA25が有効値か
    if ma25 == 0:
        return None

    # 4. 株価が MA25 より上
    if close <= ma25:
        return None

    # 5. MA25 が上向き
    if ma25_slope <= 0:
        return None

    # 6. 出来高倍率フィルター
    if vol_ratio < config.VOLUME_RATIO_MIN:
        return None

    # 7. 直近5日以内に高値更新なし → 除外
    if not new_high:
        return None

    # ── データ品質チェック（改良②）────────────────────────────
    from data_fetcher import validate_ohlcv
    quality_warnings = validate_ohlcv(df, symbol)

    # ── スコア計算 ─────────────────────────────────────────
    score = 0
    reasons = []
    warnings = list(quality_warnings)   # データ品質警告をマージ

    # 条件: MA25 上にいる（ここまで来ていれば確実にTrue）
    score += config.SCORE_WEIGHTS["above_ma25"]
    reasons.append(f"MA25({ma25:.0f}円)上に位置")

    # 条件: MA25 上向き
    score += config.SCORE_WEIGHTS["ma25_upward"]
    reasons.append("MA25上向き")

    # 条件: 5日以内の高値更新
    score += config.SCORE_WEIGHTS["new_high_5d"]
    reasons.append("直近5日以内に高値更新")

    # 条件: 出来高急増
    score += config.SCORE_WEIGHTS["volume_surge"]
    reasons.append(f"出来高{vol_ratio:.1f}倍（20日平均比）")

    # 追加ボーナス: 軽い押しで高値圏維持（0〜3%以内の押し）
    if 0 <= pullback <= 3.0:
        score += config.SCORE_WEIGHTS["pullback_mild"]
        reasons.append(f"高値から{pullback:.1f}%押しで高値圏維持")
    elif pullback <= 6.0:
        reasons.append(f"高値から{pullback:.1f}%押し")

    # MA75との位置関係（参考情報）
    ma75 = float(latest["ma75"]) if not pd.isna(latest["ma75"]) else 0
    if ma75 > 0:
        pct_vs_ma75 = (close - ma75) / ma75 * 100
        reasons.append(f"MA75比+{pct_vs_ma75:.1f}%")

    # ── 見送り警告 ─────────────────────────────────────────
    # ギャップアップ警告
    if gap_pct >= config.MAX_GAP_PERCENT:
        warnings.append(f"本日ギャップアップ{gap_pct:.1f}%（追いかけリスク）")

    # 上髭警告
    if wick_ratio >= 0.5:
        warnings.append(f"上髭比率{wick_ratio:.0%}（無理上げの可能性）")

    # 直近20日の出来高急増後に失速チェック
    if vol_ratio >= 3.0 and wick_ratio >= 0.4:
        warnings.append("出来高急増 + 上髭 → 天井圏の可能性")

    # 出来高の質チェック（量だけ多くて値動きが小さい）
    day_range_pct = (float(latest["High"]) - float(latest["Low"])) / close * 100
    if vol_ratio >= 2.0 and day_range_pct < 1.0:
        warnings.append("出来高急増だが値幅が狭い（仕手・機関整理の可能性）")

    # MA25 との乖離が大きすぎる場合の警告
    pct_vs_ma25 = (close - ma25) / ma25 * 100
    if pct_vs_ma25 >= 15.0:
        warnings.append(f"MA25から{pct_vs_ma25:.1f}%乖離（過熱感）")

    return {
        "symbol"       : symbol,
        "name"         : info.get("name", symbol),
        "close"        : close,
        "ma25"         : ma25,
        "pct_vs_ma25"  : pct_vs_ma25,
        "vol_ratio"    : vol_ratio,
        "new_high_5d"  : new_high,
        "pullback_pct" : pullback,
        "gap_pct"      : gap_pct,
        "wick_ratio"   : wick_ratio,
        "score"        : score,
        "reasons"      : reasons,
        "warnings"     : warnings,
        "df"           : df,   # 後続処理（損切り計算）に使う
    }


def run_screening(symbols: list[str], fetch_fn, info_fn) -> list[ScreenResult]:
    """
    銘柄リストをスクリーニングして結果リストを返す。
    並列処理（ThreadPoolExecutor）で高速化。スコア降順でソート。
    """
    from data_fetcher import compute_indicators
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    results = []
    total   = len(symbols)
    counter = {"done": 0, "passed": 0}
    lock    = threading.Lock()

    def process_one(sym: str):
        df_raw = fetch_fn(sym)
        if df_raw is None:
            return None
        df   = compute_indicators(df_raw)
        info = info_fn(sym)
        return screen(sym, df, info)

    # 並列数: 銘柄数に応じて自動調整（最大10スレッド）
    # yfinance は同時接続数が多すぎるとエラーになるため上限を設ける
    workers = min(10, max(1, total // 50 + 1))
    print(f"[INFO] 並列処理スレッド数: {workers}")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            sym = futures[future]
            with lock:
                counter["done"] += 1
                done = counter["done"]

            try:
                result = future.result()
            except Exception as e:
                print(f"  [{done:>4}/{total}] {sym}: エラー ({e})")
                continue

            if result is None:
                # 除外銘柄は50件ごとにまとめて進捗表示
                if done % 50 == 0 or done == total:
                    with lock:
                        passed = counter["passed"]
                    print(f"  [{done:>4}/{total}] 処理中... 通過: {passed}銘柄")
            else:
                with lock:
                    counter["passed"] += 1
                    passed = counter["passed"]
                print(f"  [{done:>4}/{total}] {sym} 通過！ スコア={result['score']} ({result['name']})")
                results.append(result)

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[: config.MAX_CANDIDATES]
