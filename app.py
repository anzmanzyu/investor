"""
app.py — Streamlit Webアプリ版 株式スクリーニングツール

起動方法:
    streamlit run app.py

ブラウザで http://localhost:8501 が自動で開く
スマホからは http://<PCのIPアドレス>:8501 でアクセス可能
"""

import streamlit as st
import pandas as pd
import threading
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ページ設定（一番最初に呼ぶ必要がある）
st.set_page_config(
    page_title="株式スクリーニング",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

import config
import data_fetcher
import screener
import calculator
import history as history_module


# ─── CSS（スマホ対応・ダークテーマ調整）────────────────────
st.markdown("""
<style>
    .metric-card {
        background: #1e2130;
        border-radius: 8px;
        padding: 12px 16px;
        margin: 4px 0;
    }
    .pass-badge  { color: #00c853; font-weight: bold; }
    .warn-badge  { color: #ffab00; font-weight: bold; }
    .score-high  { color: #00c853; }
    .score-mid   { color: #ffab00; }
    .score-low   { color: #ff5252; }
    .stProgress > div > div { background: #00c853; }
</style>
""", unsafe_allow_html=True)


# ─── サイドバー（設定パネル）────────────────────────────────
def render_sidebar() -> dict:
    st.sidebar.title("⚙️ 設定")

    st.sidebar.subheader("💰 資金管理")
    capital = st.sidebar.number_input(
        "総資金（円）", value=config.TOTAL_CAPITAL,
        step=100_000, min_value=10_000, format="%d"
    )
    risk = st.sidebar.slider(
        "1トレード許容損失（%）", 0.5, 2.0, config.RISK_PERCENT, step=0.1
    )

    st.sidebar.subheader("📊 スクリーニング条件")
    vol_ratio_min = st.sidebar.slider(
        "最低出来高倍率（20日平均比）", 1.0, 3.0, config.VOLUME_RATIO_MIN, step=0.1
    )
    min_price = st.sidebar.number_input(
        "最低株価（円）", value=config.MIN_PRICE, step=100, min_value=0
    )
    max_candidates = st.sidebar.slider(
        "最大候補数", 3, 20, config.MAX_CANDIDATES
    )

    st.sidebar.subheader("🎯 損切り・利確")
    stop_pct = st.sidebar.slider("損切り幅（%）", 2.0, 10.0, config.STOP_LOSS_PERCENT, step=0.5)
    tp_pct   = st.sidebar.slider("利確幅（%）",   4.0, 20.0, config.TAKE_PROFIT_PERCENT, step=0.5)

    st.sidebar.subheader("🌍 対象市場")
    market = st.sidebar.radio("市場", ["JP（日本株）", "US（米国株）"],
                               index=0 if config.MARKET == "JP" else 1)

    return {
        "capital"       : capital,
        "risk"          : risk,
        "vol_ratio_min" : vol_ratio_min,
        "min_price"     : min_price,
        "max_candidates": max_candidates,
        "stop_pct"      : stop_pct,
        "tp_pct"        : tp_pct,
        "market"        : "JP" if market.startswith("JP") else "US",
    }


# ─── 設定を一時的に上書きする ───────────────────────────────
def apply_settings(cfg: dict):
    config.TOTAL_CAPITAL       = cfg["capital"]
    config.RISK_PERCENT        = cfg["risk"]
    config.VOLUME_RATIO_MIN    = cfg["vol_ratio_min"]
    config.MIN_PRICE           = cfg["min_price"]
    config.MAX_CANDIDATES      = cfg["max_candidates"]
    config.STOP_LOSS_PERCENT   = cfg["stop_pct"]
    config.TAKE_PROFIT_PERCENT = cfg["tp_pct"]
    config.MARKET              = cfg["market"]


# ─── スクリーニング実行（進捗バー付き）──────────────────────
def run_screening_with_progress(symbols: list[str]) -> list[dict]:
    from data_fetcher import compute_indicators

    results = []
    total   = len(symbols)
    done_count = [0]
    lock = threading.Lock()

    progress_bar  = st.progress(0, text=f"0 / {total} 銘柄チェック中...")
    status_text   = st.empty()

    def process_one(sym):
        df_raw = data_fetcher.fetch_ohlcv(sym)
        if df_raw is None:
            return None
        df   = compute_indicators(df_raw)
        info = data_fetcher.fetch_info(sym)
        return screener.screen(sym, df, info)

    workers = min(10, max(1, total // 50 + 1))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            sym = futures[future]
            with lock:
                done_count[0] += 1
                done = done_count[0]

            pct = done / total
            progress_bar.progress(pct, text=f"{done} / {total} 銘柄チェック中...")

            try:
                result = future.result()
                if result:
                    with lock:
                        results.append(result)
                    status_text.success(f"✅ 通過: {sym} {result['name']}  スコア:{result['score']}")
            except Exception:
                pass

    progress_bar.empty()
    status_text.empty()

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[: config.MAX_CANDIDATES]


# ─── 候補カード表示 ──────────────────────────────────────────
def render_candidate_card(rank: int, c: dict):
    plan = c["plan"]

    score = c["score"]
    score_color = "score-high" if score >= 80 else ("score-mid" if score >= 60 else "score-low")

    with st.expander(
        f"#{rank}  {c['symbol']} {c['name']}  "
        f"｜ 現在値: {c['close']:,.0f}円  "
        f"｜ スコア: {score}点",
        expanded=(rank <= 3),
    ):
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("エントリー候補", f"{plan['entry']:,.0f}円")
        col2.metric("損切り候補",     f"{plan['stop']:,.0f}円",
                    delta=f"-{plan['loss_per_share']:.0f}円/株", delta_color="inverse")
        col3.metric("利確候補（固定）", f"{plan['tp_fixed']:,.0f}円")
        col4.metric("注文サイズ",      f"{plan['shares']:,}株")

        st.markdown("---")
        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("**📌 テクニカル情報**")
            st.markdown(f"""
| 項目 | 値 |
|---|---|
| MA25 | {c['ma25']:,.0f}円（乖離 +{c['pct_vs_ma25']:.1f}%）|
| 出来高倍率 | {c['vol_ratio']:.1f}倍（20日平均比）|
| 直近高値更新 | {'✅ あり' if c['new_high_5d'] else '❌ なし'}|
| 高値からの押し | {c['pullback_pct']:.1f}%|
""")

        with col_b:
            st.markdown("**💰 資金計算**")
            st.markdown(f"""
| 項目 | 値 |
|---|---|
| 投資額 | {plan['investment']:,.0f}円 |
| 最大損失 | {plan['max_loss']:,.0f}円 |
| 利確RR{config.RISK_REWARD_RATIO} | {plan['tp_rr']:,.0f}円 |
| 損切り詳細 | {plan['sl_detail']}|
""")

        st.markdown("**✅ 抽出理由**")
        for r in c["reasons"]:
            st.markdown(f"- {r}")

        if c["warnings"]:
            st.markdown("**⚠️ 見送り注意点**")
            for w in c["warnings"]:
                st.warning(w)

        if plan["pos_note"]:
            st.error(plan["pos_note"])


# ─── サマリーテーブル表示 ────────────────────────────────────
def render_summary_table(candidates: list[dict]):
    rows = []
    for rank, c in enumerate(candidates, 1):
        plan = c["plan"]
        rows.append({
            "順位"        : rank,
            "コード"      : c["symbol"],
            "銘柄名"      : c["name"],
            "現在値"      : c["close"],
            "スコア"      : c["score"],
            "エントリー"  : plan["entry"],
            "損切り"      : plan["stop"],
            "利確（固定）": plan["tp_fixed"],
            "株数"        : plan["shares"],
            "出来高倍率"  : round(c["vol_ratio"], 1),
            "注意点"      : "⚠ あり" if c["warnings"] else "—",
        })

    df = pd.DataFrame(rows)

    # スコアで色分け
    def color_score(val):
        if val >= 80: return "color: #00c853"
        if val >= 60: return "color: #ffab00"
        return "color: #ff5252"

    st.dataframe(
        df.style.map(color_score, subset=["スコア"]),
        use_container_width=True,
        hide_index=True,
    )

    # CSVダウンロードボタン
    csv = df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        label="📥 CSVダウンロード",
        data=csv.encode("utf-8-sig"),
        file_name=f"candidates_{date.today()}.csv",
        mime="text/csv",
    )


# ─── 履歴タブ ────────────────────────────────────────────────
def render_history_tab():
    st.subheader("📚 通知履歴")
    try:
        df = pd.read_csv(config.HISTORY_CSV, encoding="utf-8-sig")
        if df.empty:
            st.info("履歴がまだありません")
            return

        # 簡易統計
        entered = df[df["実際に入ったか"] == "はい"]
        wins    = entered[entered["勝負"] == "勝ち"]
        losses  = entered[entered["勝負"] == "負け"]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("通知件数",   len(df))
        c2.metric("実際に入った", len(entered))
        c3.metric("勝ち / 負け", f"{len(wins)} / {len(losses)}")

        win_rate = len(wins) / len(entered) * 100 if len(entered) > 0 else 0
        c4.metric("勝率", f"{win_rate:.1f}%")

        pnl_vals = pd.to_numeric(df["損益(円)"], errors="coerce").dropna()
        if not pnl_vals.empty:
            st.metric("累計損益", f"{pnl_vals.sum():+,.0f}円")

        st.markdown("---")
        st.markdown("**履歴一覧**（CSVを直接編集して実績を記録できます）")
        st.dataframe(df, use_container_width=True, hide_index=True)

        csv = df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button("📥 履歴CSVをダウンロード", csv.encode("utf-8-sig"),
                           f"history_{date.today()}.csv", "text/csv")

    except FileNotFoundError:
        st.info("履歴ファイルがまだありません。スクリーニングを実行すると自動生成されます。")


# ─── メイン ──────────────────────────────────────────────────
def main():
    st.title("📈 株式スクリーニングツール")
    st.caption(f"引け後スクリーニング ｜ 翌営業日の監視候補を抽出")

    # サイドバーから設定を取得・適用
    cfg = render_sidebar()
    apply_settings(cfg)

    # タブ
    tab_screen, tab_backtest, tab_history, tab_help = st.tabs(["🔍 スクリーニング", "📊 バックテスト", "📚 履歴", "❓ 使い方"])

    # ─── スクリーニングタブ ──────────────────────────────
    with tab_screen:
        col_run, col_info = st.columns([2, 3])

        with col_run:
            st.markdown(f"""
**対象市場**: {cfg['market']}
**総資金**: {cfg['capital']:,}円
**許容損失**: {cfg['risk']}%（最大損失 {cfg['capital'] * cfg['risk'] / 100:,.0f}円/トレード）
""")
            run_button = st.button("▶ スクリーニング実行", type="primary", use_container_width=True)

        with col_info:
            # 地合いステータス表示
            with st.spinner("地合い確認中..."):
                from market_filter import get_market_status
                mkt = get_market_status()
            if mkt["ok"]:
                st.success(f"🟢 {mkt['message']}")
            else:
                st.error(f"🔴 {mkt['message']}  ← 本日は見送り推奨")
            st.caption("引け後（15:30以降）に実行するのが最適です。")

        if run_button:
            symbols = data_fetcher.load_watchlist()
            st.markdown(f"**対象銘柄数: {len(symbols)}銘柄**")

            with st.spinner("データ取得中..."):
                raw_results = run_screening_with_progress(symbols)

            if not raw_results:
                st.warning(
                    "本日は条件を満たす候補銘柄がありませんでした。\n\n"
                    "考えられる原因:\n"
                    "- 相場全体が下降トレンド（候補0件 = 見送りサイン）\n"
                    "- watchlist.txtの銘柄数が少ない\n"
                    "- スクリーニング条件が厳しすぎる（左サイドバーで調整）"
                )
                return

            # トレードプランを計算
            candidates = []
            for r in raw_results:
                r["plan"] = calculator.build_trade_plan(r)
                candidates.append(r)

            # 履歴保存
            run_date = date.today().strftime("%Y-%m-%d")
            history_module.save_history(candidates, run_date)

            # 結果表示
            st.success(f"✅ {len(candidates)}銘柄が条件を通過しました")
            st.markdown("---")

            st.subheader("📋 サマリー")
            render_summary_table(candidates)

            st.markdown("---")
            st.subheader("📄 詳細")
            for rank, c in enumerate(candidates, 1):
                render_candidate_card(rank, c)

    # ─── バックテストタブ ─────────────────────────────────
    with tab_backtest:
        st.subheader("📊 バックテスト（過去シミュレーション）")
        st.caption("「もし実際に入っていたら」の損益をシミュレーションします。結果はあくまで参考値です。")

        col_s, col_e, col_n = st.columns(3)
        with col_s:
            bt_start = st.date_input("開始日", value=pd.Timestamp("2025-01-01"))
        with col_e:
            bt_end   = st.date_input("終了日",  value=pd.Timestamp("2025-12-31"))
        with col_n:
            bt_top   = st.slider("対象銘柄数（watchlist上位）", 20, 200, 50, step=10)

        st.info(f"⏱ 銘柄数×期間に応じて数分〜数十分かかります。実行中はタブを切り替えないでください。")
        bt_button = st.button("▶ バックテスト実行", type="secondary", use_container_width=True)

        if bt_button:
            from backtest import run_backtest, print_summary
            from market_filter import fetch_market_data_range

            symbols = data_fetcher.load_watchlist()[:bt_top]
            start_str = bt_start.strftime("%Y-%m-%d")
            end_str   = bt_end.strftime("%Y-%m-%d")

            with st.spinner(f"{len(symbols)}銘柄 × {start_str}〜{end_str} でシミュレーション中..."):
                trades_df, equity_df = run_backtest(symbols, start_str, end_str)

            if trades_df.empty:
                st.warning("期間内にトレードがありませんでした。条件を変えて再実行してください。")
            else:
                total   = len(trades_df)
                wins    = (trades_df["損益合計"] > 0).sum()
                losses  = (trades_df["損益合計"] <= 0).sum()
                win_rate = wins / total * 100
                total_pnl = trades_df["損益合計"].sum()
                init_cap  = config.TOTAL_CAPITAL
                ret_pct   = total_pnl / init_cap * 100
                avg_win   = trades_df[trades_df["損益合計"] > 0]["損益合計"].mean() if wins > 0 else 0
                avg_loss  = trades_df[trades_df["損益合計"] <= 0]["損益合計"].mean() if losses > 0 else 0
                pf = abs(trades_df[trades_df["損益合計"] > 0]["損益合計"].sum() /
                         trades_df[trades_df["損益合計"] <= 0]["損益合計"].sum()) if losses > 0 else 999

                # ── サマリー指標 ──────────────────────────────
                st.markdown("### 📋 結果サマリー")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("総トレード数", f"{total}件")
                c2.metric("勝率", f"{win_rate:.1f}%")
                c3.metric("プロフィットF", f"{pf:.2f}")
                c4.metric("総損益", f"{total_pnl:+,.0f}円", delta=f"{ret_pct:+.1f}%")

                c5, c6, c7, c8 = st.columns(4)
                c5.metric("初期資金", f"{init_cap:,.0f}円")
                c6.metric("最終資金", f"{init_cap + total_pnl:,.0f}円")
                c7.metric("平均利益", f"+{avg_win:,.0f}円")
                c8.metric("平均損失", f"{avg_loss:,.0f}円")

                # ── 決済理由 ──────────────────────────────────
                st.markdown("### 🔖 決済理由の内訳")
                reason_df = trades_df.groupby("決済理由").agg(
                    件数=("損益合計", "count"),
                    平均損益=("損益合計", "mean"),
                    合計損益=("損益合計", "sum"),
                ).reset_index()
                reason_df["平均損益"] = reason_df["平均損益"].map(lambda x: f"{x:+,.0f}円")
                reason_df["合計損益"] = reason_df["合計損益"].map(lambda x: f"{x:+,.0f}円")
                st.dataframe(reason_df, use_container_width=True, hide_index=True)

                # ── 銘柄別損益 ────────────────────────────────
                st.markdown("### 🏆 銘柄別損益ランキング")
                sym_df = (
                    trades_df.groupby(["銘柄コード", "銘柄名"])["損益合計"]
                    .sum()
                    .reset_index()
                    .sort_values("損益合計", ascending=False)
                )
                sym_df["損益合計"] = sym_df["損益合計"].map(lambda x: f"{x:+,.0f}円")
                st.dataframe(sym_df.head(15), use_container_width=True, hide_index=True)

                # ── トレード一覧 ──────────────────────────────
                st.markdown("### 📄 全トレード一覧")
                display = trades_df[[
                    "エントリー日", "銘柄コード", "銘柄名",
                    "エントリー価格", "決済日", "決済理由", "損益率%", "損益合計"
                ]].copy()
                display["損益合計"] = display["損益合計"].map(lambda x: f"{x:+,.0f}円")

                def color_pnl(val):
                    try:
                        v = float(str(val).replace(",", "").replace("円", "").replace("+", ""))
                        return "color: #00c853" if v > 0 else "color: #ff5252"
                    except Exception:
                        return ""

                st.dataframe(
                    display.style.map(color_pnl, subset=["損益合計"]),
                    use_container_width=True, hide_index=True
                )

                # ── CSVダウンロード ───────────────────────────
                csv = trades_df.to_csv(index=False, encoding="utf-8-sig")
                st.download_button(
                    "📥 バックテスト結果をCSVダウンロード",
                    csv.encode("utf-8-sig"),
                    f"backtest_{start_str}_{end_str}.csv",
                    "text/csv"
                )

                st.warning("⚠️ バックテストは過去データによる参考値です。将来の利益を保証するものではありません。")

    # ─── 履歴タブ ────────────────────────────────────────
    with tab_history:
        render_history_tab()

    # ─── 使い方タブ ─────────────────────────────────────
    with tab_help:
        st.markdown("""
## 使い方

### 毎日の手順
1. **引け後（15:30以降）** にこのページを開く
2. 左サイドバーで **総資金** と **許容損失%** を確認
3. **「スクリーニング実行」** ボタンを押す
4. 候補銘柄の **エントリー候補・損切り・利確** を確認
5. 翌朝、**候補価格帯** で寄り付きを監視して自分で判断

### 結果の読み方
| 項目 | 説明 |
|---|---|
| エントリー候補 | 翌朝この価格帯で監視。寄り付き後に動きを確認してから判断 |
| 損切り候補 | ここを終値で割ったら即撤退。必ず事前に決めておく |
| 利確候補（固定） | 固定+8%での利確目安 |
| 利確（RR2） | 損切り幅×2のリスクリワードでの利確目安 |
| 注文株数 | 許容損失内に収まる最大株数（100株単位） |

### 見送り判断
⚠️マークの注意点が出たら慎重に。特に：
- **ギャップアップ5%超** → 追いかけ買いはリスク大
- **上髭が長い** → 当日売り圧力が強い
- **地合いが悪い** → watchlistの大半が候補ゼロの日は見送り推奨

### スマホからのアクセス
PCとスマホが同じWi-Fiに繋がっていれば、
スマホのブラウザで `http://<PCのIPアドレス>:8501` にアクセスできます。

### watchlist.txtの編集
`data/watchlist.txt` に証券コードを1行1銘柄で追加するだけで対象銘柄を増やせます。
```
7203   # トヨタ
6758   # ソニー
```
""")


if __name__ == "__main__":
    main()
