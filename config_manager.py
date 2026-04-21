"""
config_manager.py — ユーザー設定の永続化（改良⑥）

サイドバーの設定をブラウザを閉じても保持する。
保存先: data/user_settings.json

使い方:
    from config_manager import load_settings, save_settings

    settings = load_settings()           # 起動時に読み込み
    save_settings(cfg)                   # 実行ボタン押下時に保存
"""

import os
import json
import config

SETTINGS_PATH = "data/user_settings.json"

# config.py の現在値をデフォルトとして使う
def _defaults() -> dict:
    return {
        "capital"       : config.TOTAL_CAPITAL,
        "risk"          : config.RISK_PERCENT,
        "vol_ratio_min" : config.VOLUME_RATIO_MIN,
        "min_price"     : config.MIN_PRICE,
        "max_candidates": config.MAX_CANDIDATES,
        "stop_pct"      : config.STOP_LOSS_PERCENT,
        "tp_pct"        : config.TAKE_PROFIT_PERCENT,
        "market"        : config.MARKET,
        "min_turnover"  : config.MIN_TURNOVER,
        "lot_size"      : config.LOT_SIZE,
    }


def load_settings() -> dict:
    """
    保存済み設定を読み込む。
    ファイルがなければ config.py のデフォルト値を返す。
    保存済みの値で不足しているキーはデフォルト値で補完する。
    """
    defaults = _defaults()
    if not os.path.exists(SETTINGS_PATH):
        return defaults

    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        # デフォルト値をベースに保存値で上書き（新規キーにはデフォルト値を使う）
        result = defaults.copy()
        result.update({k: v for k, v in saved.items() if k in defaults})
        return result
    except Exception as e:
        print(f"[ConfigManager] 設定読み込みエラー: {e}")
        return defaults


def save_settings(cfg: dict) -> None:
    """
    設定を JSON ファイルに書き出す。
    data/ ディレクトリが存在しない場合は自動作成する。
    """
    os.makedirs("data", exist_ok=True)
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ConfigManager] 設定保存エラー: {e}")
