"""
data_fetcher.py — yfinance を使った株価データ取得
日本株: ticker に ".T" を付ける（例: "7203.T" = トヨタ）
米国株: ticker そのまま（例: "AAPL"）
"""

import os
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, datetime
from typing import Optional
import config


def _build_ticker(symbol: str) -> str:
    """市場設定に応じて yfinance 用 ticker を構築する"""
    if config.MARKET == "JP" and not symbol.endswith(".T"):
        return f"{symbol}.T"
    return symbol


def fetch_ohlcv(symbol: str, period: str = "3mo") -> Optional[pd.DataFrame]:
    """
    指定銘柄のOHLCVを取得して返す。
    失敗した場合は None を返す。

    Returns:
        DataFrame with columns: Open, High, Low, Close, Volume
        Index: DatetimeIndex (ascending)
    """
    ticker = _build_ticker(symbol)
    try:
        df = yf.download(
            ticker,
            period=period,
            auto_adjust=True,
            progress=False,
        )
        if df is None or df.empty:
            return None

        # MultiIndex列をフラット化: ('Close','7203.T') → 'Close'
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 当日の未確定データ（CloseがNaN）を除去
        df = df.dropna(subset=["Close"])

        if len(df) < 30:
            return None

        df.sort_index(inplace=True)
        return df
    except Exception as e:
        print(f"  [WARN] {symbol} データ取得失敗: {e}")
        return None


def fetch_ohlcv_cached(symbol: str, period: str = "3mo", force_refresh: bool = False) -> Optional[pd.DataFrame]:
    """
    OHLCVをparquetキャッシュから取得する（改良③）。
    当日中のキャッシュが有効な場合は再利用し、なければfetch_ohlcvで取得して保存する。

    Args:
        symbol       : 銘柄コード
        period       : 取得期間（キャッシュミス時のみ使用）
        force_refresh: True の場合はキャッシュを無視して再取得

    Returns:
        OHLCV DataFrame または None
    """
    cache_dir  = "data/cache"
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{symbol}.parquet")
    today      = date.today()

    # キャッシュが当日中かつ force_refresh=False なら再利用
    if not force_refresh and os.path.exists(cache_path):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(cache_path)).date()
            if mtime == today:
                df = pd.read_parquet(cache_path)
                if df is not None and not df.empty:
                    return df
        except Exception:
            pass  # キャッシュ読み込み失敗 → 再取得へ

    # 新規取得してキャッシュに保存
    df = fetch_ohlcv(symbol, period)
    if df is not None:
        try:
            df.to_parquet(cache_path)
        except Exception as e:
            print(f"  [WARN] {symbol} キャッシュ保存失敗: {e}")
    return df


def validate_ohlcv(df: pd.DataFrame, symbol: str) -> list[str]:
    """
    OHLCVデータの品質チェックを行い、問題点のリストを返す（改良②）。
    screener.screen() の warnings リストにマージして使用する。

    チェック項目:
        1. 直近データが3日以上（5暦日）古い
        2. 出来高ゼロの日が3日以上ある
        3. Close の NaN 比率が 5% 超
    """
    warnings_list: list[str] = []
    if df is None or df.empty:
        return warnings_list

    # 1. 最終データ日付チェック
    try:
        last_date = df.index[-1].date() if hasattr(df.index[-1], "date") else df.index[-1]
        staleness = (date.today() - last_date).days
        if staleness >= 5:
            warnings_list.append(f"データが{staleness}日前（{last_date}）と古い可能性があります")
    except Exception:
        pass

    # 2. 出来高ゼロ日数チェック
    try:
        zero_vol_days = int((df["Volume"] == 0).sum())
        if zero_vol_days >= 3:
            warnings_list.append(f"出来高ゼロの日が{zero_vol_days}日あります（流動性に注意）")
    except Exception:
        pass

    # 3. Close の NaN 比率チェック
    try:
        nan_ratio = df["Close"].isna().sum() / len(df)
        if nan_ratio > 0.05:
            warnings_list.append(f"価格データの{nan_ratio*100:.1f}%が欠損しています")
    except Exception:
        pass

    return warnings_list


def fetch_info(symbol: str) -> dict:
    """
    銘柄の基本情報（名前、業種など）を取得する。
    取得できない場合は空辞書を返す。
    """
    ticker = _build_ticker(symbol)
    try:
        info = yf.Ticker(ticker).info
        return {
            "name"    : info.get("longName") or info.get("shortName") or symbol,
            "sector"  : info.get("sector", ""),
            "industry": info.get("industry", ""),
            "currency": info.get("currency", "JPY"),
        }
    except Exception:
        return {"name": symbol, "sector": "", "industry": "", "currency": "JPY"}


def load_watchlist(path: str = None) -> list[str]:
    """
    watchlist.txt からティッカーリストを読み込む。
    # で始まる行はコメントとして無視。
    空ファイルの場合はサンプル銘柄を返す。
    """
    filepath = path or config.WATCHLIST
    try:
        with open(filepath, encoding="utf-8") as f:
            symbols = []
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                code = line.split("#")[0].strip()  # インラインコメントを除去
                if code:
                    symbols.append(code)
        if symbols:
            return symbols
    except FileNotFoundError:
        pass

    # watchlist が存在しない / 空の場合のサンプル銘柄（日本株）
    print("[INFO] watchlist.txt が見つからないためサンプル銘柄を使用します")
    return [
        "7203",  # トヨタ自動車
        "6758",  # ソニーグループ
        "9984",  # ソフトバンクグループ
        "6861",  # キーエンス
        "4063",  # 信越化学工業
        "7974",  # 任天堂
        "6367",  # ダイキン工業
        "8035",  # 東京エレクトロン
        "2413",  # エムスリー
        "4519",  # 中外製薬
        "6954",  # ファナック
        "9433",  # KDDI
        "4661",  # オリエンタルランド
        "6501",  # 日立製作所
        "7741",  # HOYA
    ]


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    スクリーニングに必要なテクニカル指標を計算して列に追加する。
    """
    df = df.copy()

    # 移動平均
    df["ma25"] = df["Close"].rolling(config.MA_SHORT).mean()
    df["ma75"] = df["Close"].rolling(config.MA_LONG).mean()

    # MA25 の向き（5日前との差）
    df["ma25_slope"] = df["ma25"] - df["ma25"].shift(5)

    # 出来高の移動平均
    df["vol_ma20"] = df["Volume"].rolling(config.VOLUME_MA).mean()

    # 出来高倍率（当日 / 20日平均）
    df["vol_ratio"] = df["Volume"] / df["vol_ma20"]

    # 直近N日の高値
    df["rolling_high"] = df["High"].rolling(config.LOOKBACK_DAYS).max()

    # 5日以内に高値更新があったか（当日の高値が直近高値と一致）
    lookback = config.LOOKBACK_DAYS
    df["prev_high"] = df["High"].shift(lookback).rolling(lookback * 2).max()

    # 当日の高値が過去30日間の高値と同水準なら更新フラグ
    df["high_30d"] = df["High"].rolling(30).max()
    df["new_high_5d"] = df["High"] >= df["high_30d"].shift(1)

    # 高値からの押し率（%）
    df["pullback_pct"] = (df["High"].rolling(lookback).max() - df["Close"]) / df["High"].rolling(lookback).max() * 100

    # 上髭の長さ（（High-Close）/レンジ）
    df["wick_ratio"] = np.where(
        (df["High"] - df["Low"]) > 0,
        (df["High"] - df["Close"]) / (df["High"] - df["Low"]),
        0,
    )

    # ギャップアップ率（当日始値 vs 前日終値）
    df["gap_pct"] = (df["Open"] - df["Close"].shift(1)) / df["Close"].shift(1) * 100

    return df
