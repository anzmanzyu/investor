"""
calculator.py — 損切り・利確・注文サイズの計算
固定ルールベース。ここを改良すれば精度向上できる。
"""

import pandas as pd
import config


def calc_entry_price(result: dict) -> float:
    """
    エントリー候補価格を計算する。
    基本方針：翌日の寄り値を予測するのは難しいため、
    「現在値（終値）付近 + 少し上」をエントリー候補とする。
    実際の注文は翌日の寄り付き観察後に自分で判断すること。
    """
    close = result["close"]
    # 現在値から +0.5% を候補（ブレイクアウト意識）
    # ※実際はその日の動きを見てから判断する
    return round(close * 1.005, 0)


def calc_stop_loss(result: dict) -> dict:
    """
    損切り候補価格を計算する。
    STOP_MODE に応じて固定% / スウィング安値 / 両方を返す。
    """
    entry = calc_entry_price(result)
    df    = result["df"]

    # 固定%損切り
    fixed_stop = round(entry * (1 - config.STOP_LOSS_PERCENT / 100), 0)

    # スウィング安値損切り（直近5〜10日の安値）
    recent_low = float(df["Low"].tail(10).min())
    swing_stop = round(recent_low * 0.99, 0)   # 安値から少し下

    if config.STOP_MODE == "fixed":
        return {"stop": fixed_stop, "mode": "固定%", "detail": f"-{config.STOP_LOSS_PERCENT}%"}
    elif config.STOP_MODE == "swing":
        return {"stop": swing_stop, "mode": "スウィング安値", "detail": f"直近10日安値({recent_low:.0f}円)割れ"}
    else:   # "both"
        # より保守的（損失が小さくなる＝価格が高い）方を採用
        conservative = max(fixed_stop, swing_stop)
        return {
            "stop"       : conservative,
            "fixed_stop" : fixed_stop,
            "swing_stop" : swing_stop,
            "mode"       : "両方参照",
            "detail"     : f"固定={fixed_stop:.0f}円 / スウィング={swing_stop:.0f}円",
        }


def calc_take_profit(entry: float, stop: float) -> dict:
    """
    利確候補価格を計算する。
    - 固定%利確
    - リスクリワード比率ベース利確
    の2つを返す。
    """
    fixed_tp = round(entry * (1 + config.TAKE_PROFIT_PERCENT / 100), 0)
    risk      = entry - stop
    rr_tp     = round(entry + risk * config.RISK_REWARD_RATIO, 0)

    return {
        "fixed_tp" : fixed_tp,
        "rr_tp"    : rr_tp,
        "detail"   : f"固定+{config.TAKE_PROFIT_PERCENT}%={fixed_tp:.0f}円 / RR{config.RISK_REWARD_RATIO}={rr_tp:.0f}円",
    }


def calc_position_size(entry: float, stop: float) -> dict:
    """
    注文サイズを計算する。

    計算式:
        許容損失額 = 総資金 × リスク%
        1株あたり損失 = エントリー価格 - 損切り価格
        注文株数 = 許容損失額 ÷ 1株あたり損失

    日本株は100株単位が多いため、100株単位に切り捨てる。
    """
    max_loss_amount  = config.TOTAL_CAPITAL * (config.RISK_PERCENT / 100)
    loss_per_share   = entry - stop

    if loss_per_share <= 0:
        return {
            "shares"          : 0,
            "shares_rounded"  : 0,
            "investment"      : 0,
            "max_loss"        : max_loss_amount,
            "loss_per_share"  : 0,
            "note"            : "損切り価格がエントリー以上のため計算不能",
        }

    lot = config.LOT_SIZE  # 注文単位（改良⑨）: 通常100株 / ミニ株1株
    raw_shares     = max_loss_amount / loss_per_share
    rounded_shares = int(raw_shares // lot) * lot   # lot 単位に切り捨て

    # lot 単位に満たない場合は最低 lot 株を確保（ミニ株なら1株単位）
    if rounded_shares == 0:
        if lot == 1:
            rounded_shares = max(1, int(raw_shares))
        else:
            rounded_shares = max(int(raw_shares // 10) * 10, 1)

    investment = rounded_shares * entry

    note = ""
    if investment > config.TOTAL_CAPITAL * 0.3:
        note = "⚠ 投資額が総資金の30%超。分散投資を推奨。"
    if investment > config.TOTAL_CAPITAL:
        note = "⚠ 投資額が総資金を超えています。信用取引になります。"

    return {
        "shares"          : round(raw_shares, 1),
        "shares_rounded"  : rounded_shares,
        "investment"      : round(investment, 0),
        "max_loss"        : round(max_loss_amount, 0),
        "loss_per_share"  : round(loss_per_share, 1),
        "note"            : note,
    }


def build_trade_plan(result: dict) -> dict:
    """
    スクリーニング結果からトレードプランを組み立てる。
    """
    entry   = calc_entry_price(result)
    sl_info = calc_stop_loss(result)
    stop    = sl_info["stop"]
    tp_info = calc_take_profit(entry, stop)
    pos     = calc_position_size(entry, stop)

    return {
        "entry"    : entry,
        "stop"     : stop,
        "tp_fixed" : tp_info["fixed_tp"],
        "tp_rr"    : tp_info["rr_tp"],
        "shares"   : pos["shares_rounded"],
        "investment": pos["investment"],
        "max_loss" : pos["max_loss"],
        "loss_per_share": pos["loss_per_share"],
        "sl_detail": sl_info["detail"],
        "tp_detail": tp_info["detail"],
        "pos_note" : pos["note"],
    }
