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


# ─── CSS（スマホ対応・レスポンシブ）────────────────────────
st.markdown("""
<style>
    /* 共通 */
    .pass-badge  { color: #00c853; font-weight: bold; }
    .warn-badge  { color: #ffab00; font-weight: bold; }
    .score-high  { color: #00c853; }
    .score-mid   { color: #ffab00; }
    .score-low   { color: #ff5252; }
    .stProgress > div > div { background: #00c853; }

    /* スマホ対応（画面幅600px以下） */
    @media (max-width: 600px) {
        /* タイトルを小さく */
        h1 { font-size: 1.4rem !important; }
        h2 { font-size: 1.2rem !important; }
        h3 { font-size: 1.0rem !important; }

        /* カラムを縦積みに */
        [data-testid="column"] {
            width: 100% !important;
            flex: 1 1 100% !important;
            min-width: 100% !important;
        }

        /* メトリクスを小さく */
        [data-testid="stMetricValue"] {
            font-size: 1.1rem !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.75rem !important;
        }

        /* ボタンを大きく（タップしやすく） */
        .stButton > button {
            height: 3rem !important;
            font-size: 1rem !important;
        }

        /* サイドバーを非表示にしてメインを広く */
        [data-testid="stSidebar"] {
            min-width: 0 !important;
        }

        /* タブ文字を小さく */
        .stTabs [data-baseweb="tab"] {
            font-size: 0.75rem !important;
            padding: 6px 8px !important;
        }

        /* テーブルをスクロール可能に */
        [data-testid="stDataFrame"] {
            overflow-x: auto !important;
        }
    }
</style>
""", unsafe_allow_html=True)


# ─── サイドバー（設定パネル）────────────────────────────────
def render_sidebar() -> dict:
    st.sidebar.title("⚙️ 設定")
    st.sidebar.caption("ここを変えると計算結果が変わります。最初はそのままでOKです。")

    # ── 資金管理 ───────────────────────────────────────────
    st.sidebar.subheader("💰 資金管理")
    st.sidebar.caption("「何円持っていて、1回いくらまで損していいか」を設定します。")

    capital = st.sidebar.number_input(
        "総資金（円）",
        value=config.TOTAL_CAPITAL,
        step=100_000, min_value=10_000, format="%d",
        help="株に使える資金の合計。これをもとに「何株買えるか」を自動計算します。"
    )
    risk = st.sidebar.slider(
        "1回の許容損失（総資金の何%まで損していいか）",
        0.5, 2.0, config.RISK_PERCENT, step=0.1,
        help=(
            "1回のトレードで最大いくら損してもいいかの割合です。\n"
            f"例：総資金{capital:,}円 × 1% = {capital*0.01:,.0f}円まで\n"
            "0.5〜1%が安全な目安です。欲張って大きくしないことが大切。"
        )
    )
    st.sidebar.info(f"👉 1回の最大損失額：**{capital * risk / 100:,.0f}円**")

    # ── 損切り・利確 ────────────────────────────────────────
    st.sidebar.subheader("🎯 損切り・利確の目安")
    st.sidebar.caption("損切り＝「これ以上損したら諦める価格」、利確＝「ここで利益を受け取る価格」です。")

    stop_pct = st.sidebar.slider(
        "損切り幅（買値から何%下がったら売るか）",
        2.0, 10.0, config.STOP_LOSS_PERCENT, step=0.5,
        help=(
            "例：3%に設定 → 1,000円で買ったら970円で損切り\n"
            "小さいほど損失を抑えられますが、少しの値動きで売れてしまいます。\n"
            "3〜5%が一般的な目安です。"
        )
    )
    tp_pct = st.sidebar.slider(
        "利確幅（買値から何%上がったら売るか）",
        4.0, 20.0, config.TAKE_PROFIT_PERCENT, step=0.5,
        help=(
            "例：5%に設定 → 1,000円で買ったら1,050円で利確\n"
            "損切り幅の2倍以上が理想です（リスクより利益を大きく）。"
        )
    )
    st.sidebar.caption(f"損切り{stop_pct}% → 利確{tp_pct}%（利益が損失の{tp_pct/stop_pct:.1f}倍）")

    # ── スクリーニング条件 ──────────────────────────────────
    st.sidebar.subheader("🔍 銘柄の絞り込み条件")
    st.sidebar.caption("どんな銘柄を候補に出すかの基準です。厳しくすると候補が減ります。")

    vol_ratio_min = st.sidebar.slider(
        "出来高の急増倍率（普段より何倍以上売買されているか）",
        1.0, 3.0, config.VOLUME_RATIO_MIN, step=0.1,
        help=(
            "出来高＝その日に売買された株の数。\n"
            "普段より多く売買されている銘柄は注目されているサインです。\n"
            "1.5倍 → 普段の1.5倍以上売買された銘柄のみ表示。"
        )
    )
    min_price = st.sidebar.number_input(
        "最低株価（円）",
        value=config.MIN_PRICE, step=100, min_value=0,
        help=(
            "これより安い株は候補から除外します。\n"
            "あまりにも安い株（低位株）は値動きが荒く扱いにくいためです。"
        )
    )
    max_candidates = st.sidebar.slider(
        "表示する候補の最大数",
        3, 20, config.MAX_CANDIDATES,
        help="スコアが高い順に、この数だけ候補を表示します。"
    )

    # ── 対象市場 ────────────────────────────────────────────
    st.sidebar.subheader("🌍 対象市場")
    market = st.sidebar.radio(
        "どちらの株を対象にしますか？",
        ["🇯🇵 JP（日本株）", "🇺🇸 US（米国株）"],
        index=0 if config.MARKET == "JP" else 1,
        help="日本株は東証（東京証券取引所）の銘柄、米国株はNYSEやNASDAQの銘柄が対象です。"
    )

    st.sidebar.markdown("---")
    st.sidebar.caption("💡 設定を変えたらスクリーニングを再実行してください。")

    return {
        "capital"       : capital,
        "risk"          : risk,
        "vol_ratio_min" : vol_ratio_min,
        "min_price"     : min_price,
        "max_candidates": max_candidates,
        "stop_pct"      : stop_pct,
        "tp_pct"        : tp_pct,
        "market"        : "JP" if "JP" in market else "US",
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
        col1.metric(
            "🎯 買う価格の目安",
            f"{plan['entry']:,.0f}円",
            help="翌朝この価格帯で動きを見てから判断しましょう。必ずしもこの価格で買わなくてOKです。"
        )
        col2.metric(
            "🛑 損切り価格（ここを割ったら売る）",
            f"{plan['stop']:,.0f}円",
            delta=f"買値より -{plan['loss_per_share']:.0f}円/株",
            delta_color="inverse",
            help="この価格を終値で下回ったら損失を確定して売ります。必ず事前に決めておきましょう。"
        )
        col3.metric(
            "✅ 利確価格（ここで利益を受け取る）",
            f"{plan['tp_fixed']:,.0f}円",
            help=f"買値より+{config.TAKE_PROFIT_PERCENT}%上がったら利益確定の目安です。"
        )
        col4.metric(
            "📦 推奨株数",
            f"{plan['shares']:,}株",
            help=f"総資金の{config.RISK_PERCENT}%以内の損失になるよう計算した株数です。これより多く買うとリスクが高くなります。"
        )

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

        st.markdown("**✅ この銘柄が選ばれた理由**")
        for r in c["reasons"]:
            st.markdown(f"- {r}")

        if c["warnings"]:
            st.markdown("**⚠️ 注意点（これがあれば慎重に）**")
            for w in c["warnings"]:
                st.warning(f"⚠️ {w}")

        if plan["pos_note"]:
            st.error(plan["pos_note"])

        # ── ポジション追加ボタン ──────────────────────────
        st.markdown("---")
        col_btn, col_msg = st.columns([2, 3])
        with col_btn:
            if st.button(
                f"📝 ポジションに追加する",
                key=f"add_pos_{c['symbol']}_{rank}",
                type="primary",
                use_container_width=True,
            ):
                import portfolio as pf_module
                pf_module.add_position(
                    entry_date  = date.today().strftime("%Y-%m-%d"),
                    symbol      = c["symbol"],
                    name        = c["name"],
                    entry_price = plan["entry"],
                    shares      = plan["shares"],
                    stop        = plan["stop"],
                    tp          = plan["tp_fixed"],
                    memo        = f"スコア{c['score']}点 / " + c["reasons"][0] if c["reasons"] else "",
                )
                st.success(f"✅ {c['name']} をポートフォリオに追加しました！ → 💼ポートフォリオタブで確認できます")
        with col_msg:
            if c["warnings"]:
                st.caption(f"⚠️ 注意: {c['warnings'][0]}")


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
    st.caption("毎日の引け後（15:30以降）に実行 → 翌日チェックすべき銘柄を自動で絞り込みます")

    # サイドバーから設定を取得・適用
    cfg = render_sidebar()
    apply_settings(cfg)

    # タブ
    tab_screen, tab_portfolio, tab_backtest, tab_history, tab_help = st.tabs([
        "🔍 スクリーニング", "💼 ポートフォリオ", "📊 バックテスト", "📚 履歴", "❓ 使い方"
    ])

    # ─── セッション状態の初期化 ──────────────────────────
    if "candidates" not in st.session_state:
        st.session_state["candidates"] = []
    if "screen_date" not in st.session_state:
        st.session_state["screen_date"] = ""
    if "market_status" not in st.session_state:
        st.session_state["market_status"] = None

    # ─── スクリーニングタブ ──────────────────────────────
    with tab_screen:

        # 地合いステータス（キャッシュして再取得を減らす）
        if st.session_state["market_status"] is None:
            with st.spinner("地合い確認中..."):
                from market_filter import get_market_status
                st.session_state["market_status"] = get_market_status()
        mkt = st.session_state["market_status"]

        # 地合い表示
        if mkt["ok"]:
            st.success(f"🟢 今日の相場は上昇トレンド中 → スクリーニング実行OK\n{mkt['message']}")
        else:
            st.error(
                f"🔴 今日の相場は下降トレンド中 → 本日は見送りを推奨します\n"
                f"{mkt['message']}\n\n"
                "※ 下落相場では良い銘柄でも値下がりしやすいため、エントリーを控えるのが無難です。"
            )

        st.markdown(f"""
**対象市場**: {cfg['market']}
**総資金**: {cfg['capital']:,}円
**1回の最大損失**: {cfg['capital'] * cfg['risk'] / 100:,.0f}円
""")

        col_run, col_clear = st.columns([3, 1])
        with col_run:
            run_button = st.button("▶ スクリーニング実行", type="primary", use_container_width=True)
        with col_clear:
            if st.button("🗑 結果をクリア", use_container_width=True):
                st.session_state["candidates"] = []
                st.session_state["screen_date"] = ""
                st.session_state["market_status"] = None
                st.rerun()

        st.caption("引け後（15:30以降）に実行するのが最適です。")

        if run_button:
            symbols = data_fetcher.load_watchlist()
            st.markdown(f"**対象銘柄数: {len(symbols)}銘柄**")

            raw_results = run_screening_with_progress(symbols)

            if not raw_results:
                st.warning(
                    "本日は条件を満たす候補銘柄がありませんでした。\n\n"
                    "考えられる原因:\n"
                    "- 相場全体が下降トレンド（候補0件 = 見送りサイン）\n"
                    "- watchlist.txtの銘柄数が少ない\n"
                    "- スクリーニング条件が厳しすぎる（左サイドバーで調整）"
                )
            else:
                # トレードプランを計算してセッションに保存
                candidates = []
                for r in raw_results:
                    r["plan"] = calculator.build_trade_plan(r)
                    candidates.append(r)

                run_date = date.today().strftime("%Y-%m-%d")
                st.session_state["candidates"]  = candidates
                st.session_state["screen_date"] = run_date

                # 履歴保存
                history_module.save_history(candidates, run_date)

        # ── 結果表示（セッションから読み込む）──────────────
        candidates = st.session_state["candidates"]
        run_date   = st.session_state["screen_date"]

        if candidates:
            # 結果表示
            st.success(f"✅ {len(candidates)}銘柄が条件を通過しました")
            st.markdown("---")

            st.subheader("📋 サマリー")
            render_summary_table(candidates)

            st.markdown("---")
            st.subheader("📄 詳細")
            for rank, c in enumerate(candidates, 1):
                render_candidate_card(rank, c)

    # ─── ポートフォリオタブ ───────────────────────────────
    with tab_portfolio:
        import portfolio as pf_module

        st.subheader("💼 ポートフォリオ（リアルタイム損益）")
        st.caption("実際にエントリーしたポジションを記録して損益をリアルタイム表示します。")

        # ── サマリー ─────────────────────────────────────
        summary = pf_module.get_summary()
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("総トレード数", f"{summary['total']}件")
        c2.metric("保有中", f"{summary['open']}件")
        c3.metric("決済済み", f"{summary['closed']}件")
        c4.metric("確定損益", f"{summary['realized_pnl']:+,.0f}円")
        c5.metric("勝/負", f"{summary['win']}勝 {summary['lose']}敗")

        st.markdown("---")

        # ── オープンポジション ────────────────────────────
        st.markdown("### 📌 保有中ポジション（現在値自動更新）")

        if st.button("🔄 現在値を更新", key="refresh_pf"):
            st.rerun()

        with st.spinner("現在値取得中..."):
            open_positions = pf_module.get_open_positions_with_pnl()

        if not open_positions:
            st.info("保有中のポジションはありません。下のフォームから追加してください。")
        else:
            for pos in open_positions:
                pnl_color = "🟢" if pos["未実現損益"] >= 0 else "🔴"
                with st.expander(
                    f"{pos['状態']}  {pos['銘柄コード']} {pos['銘柄名']}  "
                    f"損益: {pnl_color} {pos['未実現損益']:+,.0f}円（{pos['損益率']:+.1f}%）",
                    expanded=True
                ):
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("エントリー価格", f"{pos['エントリー価格']:,.0f}円")
                    col2.metric("現在値", f"{pos['現在値']:,.0f}円",
                                delta=f"{pos['損益率']:+.1f}%")
                    col3.metric("損切りまで",
                                f"{pos['現在値'] - pos['損切り価格']:+,.0f}円")
                    col4.metric("利確まで",
                                f"{pos['利確価格'] - pos['現在値']:+,.0f}円")

                    st.markdown(
                        f"**株数**: {pos['株数']:,}株　"
                        f"**未実現損益**: {pos['未実現損益']:+,.0f}円　"
                        f"**エントリー日**: {pos['エントリー日']}"
                    )
                    if pos["メモ"]:
                        st.caption(f"メモ: {pos['メモ']}")

                    # 決済ボタン
                    with st.form(key=f"close_{pos['id']}"):
                        st.markdown("**決済する**")
                        exit_col1, exit_col2, exit_col3 = st.columns(3)
                        exit_price  = exit_col1.number_input(
                            "決済価格", value=float(pos["現在値"]), step=1.0, key=f"ep_{pos['id']}")
                        exit_reason = exit_col2.selectbox(
                            "決済理由",
                            ["利確", "損切り", "手動決済", "その他"],
                            key=f"er_{pos['id']}"
                        )
                        exit_date = exit_col3.date_input(
                            "決済日", value=date.today(), key=f"ed_{pos['id']}")
                        if st.form_submit_button("✅ 決済を記録"):
                            pf_module.close_position(
                                pos["id"], exit_price, exit_reason,
                                exit_date.strftime("%Y-%m-%d")
                            )
                            st.success(f"{pos['銘柄名']} を決済しました")
                            st.rerun()

        st.markdown("---")

        # ── 新規ポジション追加フォーム ────────────────────
        st.markdown("### ➕ 新規ポジションを追加")
        with st.form("add_position"):
            col_a, col_b, col_c = st.columns(3)
            new_date   = col_a.date_input("エントリー日", value=date.today())
            new_symbol = col_b.text_input("銘柄コード（例: 7203）")
            new_name   = col_c.text_input("銘柄名（例: トヨタ）")

            col_d, col_e, col_f = st.columns(3)
            new_entry  = col_d.number_input("エントリー価格（円）", min_value=1.0, step=1.0)
            new_shares = col_e.number_input("株数", min_value=1, step=100)
            new_memo   = col_f.text_input("メモ（任意）")

            col_g, col_h = st.columns(2)
            new_stop = col_g.number_input(
                "損切り価格（円）",
                value=round(new_entry * (1 - config.STOP_LOSS_PERCENT / 100), 0),
                step=1.0
            )
            new_tp = col_h.number_input(
                "利確価格（円）",
                value=round(new_entry * (1 + config.TAKE_PROFIT_PERCENT / 100), 0),
                step=1.0
            )

            if new_entry > 0:
                loss_per_share = new_entry - new_stop
                max_loss = loss_per_share * new_shares
                st.caption(
                    f"最大損失: {max_loss:,.0f}円　"
                    f"（損失率: {max_loss / config.TOTAL_CAPITAL * 100:.1f}%）"
                )

            submitted = st.form_submit_button("📝 追加する", type="primary")
            if submitted:
                if not new_symbol or not new_name or new_entry <= 0:
                    st.error("銘柄コード・銘柄名・エントリー価格を入力してください")
                else:
                    pf_module.add_position(
                        new_date.strftime("%Y-%m-%d"),
                        new_symbol, new_name,
                        new_entry, int(new_shares),
                        new_stop, new_tp, new_memo
                    )
                    st.success(f"✅ {new_name} を追加しました")
                    st.rerun()

        # ── 決済済みポジション ────────────────────────────
        st.markdown("---")
        st.markdown("### 📋 決済済みポジション")
        df_all = pf_module.load_positions()
        closed_df = df_all[df_all["ステータス"] == "closed"]
        if closed_df.empty:
            st.info("決済済みのポジションはまだありません。")
        else:
            disp = closed_df[[
                "エントリー日", "銘柄コード", "銘柄名",
                "エントリー価格", "決済日", "決済価格", "決済理由", "確定損益"
            ]].copy()
            disp["確定損益"] = pd.to_numeric(disp["確定損益"], errors="coerce")

            def color_pnl2(val):
                try:
                    return "color: #00c853" if float(val) > 0 else "color: #ff5252"
                except Exception:
                    return ""

            st.dataframe(
                disp.style.map(color_pnl2, subset=["確定損益"]),
                use_container_width=True, hide_index=True
            )

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
## 📖 このツールの使い方

### 🕒 毎日の流れ（5分でできます）

1. **株式市場が閉まった後（15:30以降）** にこのページを開く
2. 画面上部の **🟢/🔴 相場状況** を確認する
   - 🟢 なら → 「スクリーニング実行」ボタンを押す
   - 🔴 なら → 今日は見送り（下落相場では買わない方が安全）
3. 候補銘柄が表示されたら内容を確認する
4. 翌朝、気になった銘柄の値動きをチェックして自分で判断する

---

### 📊 結果の見方（初心者向け）

| 表示 | 意味 | 使い方 |
|---|---|---|
| **買う価格の目安** | 翌日この価格帯で動きを見る | 必ずしもこの価格で買わなくていい |
| **損切り価格** | ここを下回ったら売る | 買ったら必ずこの価格を覚えておく |
| **利確価格** | ここで利益を受け取る目安 | 欲張らずにここで売るのが大切 |
| **推奨株数** | 買っていい最大の株数 | これ以上買うとリスクが高くなる |
| **スコア** | 条件の合致度（100点満点） | 高いほど条件が揃っている |

---

### ⚠️ 注意点が出た銘柄は慎重に

| 注意点 | 意味 |
|---|---|
| ギャップアップ〇%超 | 寄り付きから大きく上がりすぎ。追いかけて買うと高値づかみになりやすい |
| 上髭が長い | 一度上がったのに売られた。勢いが弱い可能性がある |
| 出来高急増+値幅狭い | 売買は増えているのに価格が動いていない。不自然な売買の可能性 |
| MA25から〇%乖離 | 平均値から離れすぎ。反落しやすいタイミングの可能性 |

---

### 💼 ポートフォリオタブの使い方

実際に買った銘柄を記録すると：
- 現在の損益をリアルタイムで確認できる
- いくら損切り・利確まであるかが一目でわかる
- 決済後の記録が自動で残る

**手順**: スクリーニング結果 →「📝 ポジションに追加する」ボタン → 💼ポートフォリオタブで確認

---

### 📚 用語集

| 用語 | 意味 |
|---|---|
| **スクリーニング** | 大量の株の中から条件に合う銘柄だけを絞り込むこと |
| **損切り（ロスカット）** | 損失が一定以上になったら売って損失を確定すること。これをしないと大損につながる |
| **利確（利益確定）** | 値上がりしたところで売って利益を受け取ること |
| **出来高** | その日に売買された株の数。多いほど注目されている |
| **MA25（25日移動平均線）** | 過去25日間の株価の平均。これより上にいると上昇トレンドの目安 |
| **地合い** | 相場全体の雰囲気。地合いが悪いと良い銘柄でも下がりやすい |
| **エントリー** | 株を買うこと |
| **ポジション** | 現在保有している株のこと |

---

> ⚠️ **注意**: このツールは情報提供のみが目的です。表示された情報は投資の推奨ではありません。投資判断はご自身の責任で行ってください。
""")


if __name__ == "__main__":
    main()
