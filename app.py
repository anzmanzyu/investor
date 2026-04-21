"""
app.py — Streamlit Webアプリ版 株式スクリーニングツール

起動方法:
    streamlit run app.py

ブラウザで http://localhost:8501 が自動で開く
スマホからは http://<PCのIPアドレス>:8501 でアクセス可能
"""

import io
import threading
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st
import pandas as pd

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
from config_manager import load_settings, save_settings


def _sn(symbol: str, name: str) -> str:
    """銘柄表示用ヘルパー: '7203:トヨタ自動車' 形式に統一する"""
    return f"{symbol}:{name}"


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
        h1 { font-size: 1.4rem !important; }
        h2 { font-size: 1.2rem !important; }
        h3 { font-size: 1.0rem !important; }

        [data-testid="column"] {
            width: 100% !important;
            flex: 1 1 100% !important;
            min-width: 100% !important;
        }

        [data-testid="stMetricValue"] { font-size: 1.1rem !important; }
        [data-testid="stMetricLabel"] { font-size: 0.75rem !important; }

        .stButton > button {
            height: 3rem !important;
            font-size: 1rem !important;
        }

        [data-testid="stSidebar"] { min-width: 0 !important; }

        .stTabs [data-baseweb="tab"] {
            font-size: 0.75rem !important;
            padding: 6px 8px !important;
        }

        [data-testid="stDataFrame"] { overflow-x: auto !important; }
    }
</style>
""", unsafe_allow_html=True)


# ─── サイドバー（設定パネル）────────────────────────────────
def render_sidebar() -> dict:
    st.sidebar.title("⚙️ 設定")
    st.sidebar.caption("最初はそのままでOKです。慣れてきたら少しずつ調整してみましょう。")
    st.sidebar.markdown("---")

    # 保存済み設定を読み込む（改良⑥）
    saved = load_settings()

    # ── STEP 1: 資金 ────────────────────────────────────────
    st.sidebar.markdown("### 💰 STEP 1｜用意する資金")
    capital = st.sidebar.number_input(
        "株に使う金額（円）",
        value=int(saved["capital"]),
        step=100_000, min_value=10_000, format="%d",
    )

    st.sidebar.markdown("---")

    # ── STEP 2: 1回の損失上限 ──────────────────────────────
    st.sidebar.markdown("### 🛡️ STEP 2｜1回でいくらまで損していい？")
    st.sidebar.caption("「これ以上損したら売る」金額のルールです。小さいほど安全です。")

    default_risk_yen = int(capital * saved["risk"] / 100)
    risk_options     = [1000, 2000, 3000, 5000, 10000, 15000, 20000]
    # 保存値が選択肢にない場合は最近傍に丸める
    if default_risk_yen not in risk_options:
        default_risk_yen = min(risk_options, key=lambda x: abs(x - default_risk_yen))

    risk_yen = st.sidebar.select_slider(
        "1回の最大損失額",
        options=risk_options,
        value=default_risk_yen,
        format_func=lambda x: f"{x:,}円"
    )
    risk = risk_yen / capital * 100

    st.sidebar.success(f"💡 総資金 {capital:,}円 の **{risk:.1f}%** が上限")
    st.sidebar.caption("一般的には総資金の0.5〜1%が安全な目安です。")

    st.sidebar.markdown("---")

    # ── STEP 3: 売るタイミング ──────────────────────────────
    st.sidebar.markdown("### 📉📈 STEP 3｜売るタイミング")

    col_s, col_t = st.sidebar.columns(2)
    with col_s:
        st.markdown("**🔴 損切り**\n\n下がったら売る")
        stop_pct = st.select_slider(
            "下落幅",
            options=[2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 10.0],
            value=float(saved["stop_pct"]),
            format_func=lambda x: f"-{x}%",
            key="stop_slider"
        )
    with col_t:
        st.markdown("**🟢 利確**\n\n上がったら売る")
        tp_pct = st.select_slider(
            "上昇幅",
            options=[4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0, 15.0, 20.0],
            value=float(saved["tp_pct"]),
            format_func=lambda x: f"+{x}%",
            key="tp_slider"
        )

    # 具体例を表示
    example_price = 1000
    stop_ex = int(example_price * (1 - stop_pct / 100))
    tp_ex   = int(example_price * (1 + tp_pct   / 100))
    rr      = tp_pct / stop_pct

    st.sidebar.markdown(f"""
**📌 例：1,000円の株を買った場合**
- 🔴 {stop_ex}円 を下回ったら売る（損切り）
- 🟢 {tp_ex}円 を超えたら売る（利確）
- 利益は損失の **{rr:.1f}倍** を狙う設定
""")

    if rr < 1.5:
        st.sidebar.warning("⚠️ 利確幅が損切り幅に近すぎます。利確を広げるか損切りを狭めましょう。")

    st.sidebar.markdown("---")

    # ── 詳細設定（折りたたみ）──────────────────────────────
    with st.sidebar.expander("🔧 詳細設定（上級者向け）"):
        st.caption("通常はそのままでOKです。")

        market_raw = st.radio(
            "対象市場",
            ["🇯🇵 日本株", "🇺🇸 米国株"],
            index=0 if saved["market"] == "JP" else 1,
        )
        vol_ratio_min = st.slider(
            "出来高の急増倍率（普段より何倍以上か）",
            1.0, 3.0, float(saved["vol_ratio_min"]), step=0.1,
            help="普段より多く売買されている銘柄だけを表示します。1.5倍＝普段の1.5倍以上。"
        )
        min_price = st.number_input(
            "最低株価（円以下は除外）",
            value=int(saved["min_price"]), step=100, min_value=0,
            help="あまりにも安い株は値動きが荒いため除外します。"
        )
        max_candidates = st.slider(
            "表示する候補数",
            3, 20, int(saved["max_candidates"]),
            help="スコアが高い順に表示する銘柄数。"
        )

        # ── 売買代金フィルター（改良⑤）──────────────────────
        st.markdown("---")
        st.markdown("**📊 売買代金フィルター**")
        st.caption("1日あたりの売買代金が少ない銘柄は流動性が低いため除外します。")

        def _fmt_turnover(x: int) -> str:
            if x >= 100_000_000:
                return f"{x // 100_000_000}億円"
            return f"{x // 10_000:,}万円"

        turnover_options = [50_000_000, 100_000_000, 200_000_000, 500_000_000]
        saved_turnover   = int(saved.get("min_turnover", config.MIN_TURNOVER))
        if saved_turnover not in turnover_options:
            saved_turnover = min(turnover_options, key=lambda x: abs(x - saved_turnover))

        min_turnover = st.select_slider(
            "最低売買代金",
            options=turnover_options,
            value=saved_turnover,
            format_func=_fmt_turnover,
        )

        # ── 取引単位（改良⑨）────────────────────────────────
        st.markdown("---")
        st.markdown("**📦 取引単位**")
        lot_index   = 0 if int(saved.get("lot_size", 100)) == 100 else 1
        lot_label   = st.radio(
            "注文単位",
            ["通常株（100株単位）", "ミニ株（1株単位）"],
            index=lot_index,
        )
        lot_size = 100 if "100株" in lot_label else 1
        if lot_size == 1:
            st.caption(
                "かぶミニ®は指値・逆指値不可。損切りは手動対応が必要です。"
                "バックテスト結果との乖離が生じる可能性があります。"
            )

    st.sidebar.markdown("---")
    st.sidebar.caption("💡 設定を変えたら「スクリーニング実行」を押し直してください。")

    return {
        "capital"       : capital,
        "risk"          : risk,
        "vol_ratio_min" : vol_ratio_min,
        "min_price"     : min_price,
        "max_candidates": max_candidates,
        "stop_pct"      : stop_pct,
        "tp_pct"        : tp_pct,
        "market"        : "JP" if "日本" in market_raw else "US",
        "min_turnover"  : min_turnover,
        "lot_size"      : lot_size,
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
    config.MIN_TURNOVER        = cfg["min_turnover"]
    config.LOT_SIZE            = cfg["lot_size"]


# ─── チャート表示（改良①）───────────────────────────────────
def render_chart(symbol: str):
    """mplfinance でローソク足チャート（直近60日 + MA25 + 出来高）を表示する"""
    try:
        import mplfinance as mpf
        import matplotlib.pyplot as plt
    except ImportError:
        st.caption("チャート表示には mplfinance が必要です（pip install mplfinance）")
        return

    df = data_fetcher.fetch_ohlcv_cached(
        symbol,
        force_refresh=st.session_state.get("force_refresh", False)
    )
    if df is None or len(df) < 30:
        st.caption("チャートデータ取得失敗")
        return

    df_chart = df.tail(60).copy()
    df_chart.index = pd.DatetimeIndex(df_chart.index)

    # MA25 を addplot に追加
    ma25 = df_chart["Close"].rolling(25).mean()
    add_plots = [
        mpf.make_addplot(ma25, color="orange", width=1.5, label="MA25"),
    ]

    try:
        fig, _ = mpf.plot(
            df_chart,
            type="candle",
            volume=True,
            addplot=add_plots,
            style="yahoo",
            returnfig=True,
            figsize=(9, 4),
            title=f"{symbol}  直近{len(df_chart)}日",
            tight_layout=True,
        )
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
        buf.seek(0)
        st.image(buf, use_container_width=True)
        plt.close(fig)
    except Exception as e:
        st.caption(f"チャート生成失敗: {e}")


# ─── スクリーニング実行（進捗バー付き）──────────────────────
def run_screening_with_progress(symbols: list[str], force_refresh: bool = False) -> list[dict]:
    from data_fetcher import compute_indicators

    results    = []
    total      = len(symbols)
    done_count = [0]
    lock       = threading.Lock()

    progress_bar = st.progress(0, text=f"0 / {total} 銘柄チェック中...")
    status_text  = st.empty()

    def process_one(sym):
        # 改良③: fetch_ohlcv_cached を使用
        df_raw = data_fetcher.fetch_ohlcv_cached(sym, force_refresh=force_refresh)
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
                    status_text.success(f"✅ 通過: {_sn(sym, result['name'])}  スコア:{result['score']}")
            except Exception:
                pass

    progress_bar.empty()
    status_text.empty()

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[: config.MAX_CANDIDATES]


# ─── 候補カード表示（改良①チャート追加）─────────────────────
def render_candidate_card(rank: int, c: dict):
    plan = c["plan"]

    score       = c["score"]
    score_color = "score-high" if score >= 80 else ("score-mid" if score >= 60 else "score-low")

    with st.expander(
        f"#{rank}  {_sn(c['symbol'], c['name'])}  "
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
            help=f"総資金の{config.RISK_PERCENT}%以内の損失になるよう計算した株数です。"
        )

        st.markdown("---")

        # ── ローソク足チャート（改良①）──────────────────────
        with st.spinner("チャート読み込み中..."):
            render_chart(c["symbol"])

        st.markdown("---")

        # ── テクニカル情報 + 資金計算 ────────────────────────
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
                "📝 ポジションに追加する",
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
                st.success(f"✅ {_sn(c['symbol'], c['name'])} をポートフォリオに追加しました！ → 💼ポートフォリオタブで確認できます")
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
            "銘柄"        : _sn(c["symbol"], c["name"]),
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

    def color_score(val):
        if val >= 80: return "color: #00c853"
        if val >= 60: return "color: #ffab00"
        return "color: #ff5252"

    st.dataframe(
        df.style.map(color_score, subset=["スコア"]),
        use_container_width=True,
        hide_index=True,
    )

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

        entered = df[df["実際に入ったか"] == "はい"]
        wins    = entered[entered["勝負"] == "勝ち"]
        losses  = entered[entered["勝負"] == "負け"]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("通知件数",     len(df))
        c2.metric("実際に入った", len(entered))
        c3.metric("勝ち / 負け",  f"{len(wins)} / {len(losses)}")

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


# ─── 高配当株タブ（改良⑩）──────────────────────────────────
def render_dividend_tab():
    import dividend_manager as dm

    st.subheader("💰 高配当株ポートフォリオ")
    st.caption(
        "配当収入を目的とした長期保有銘柄を管理します。"
        "yfinanceの日本株配当データは精度が低い場合があるため、"
        "取得できない場合は「データなし（手動確認推奨）」と表示します。"
    )

    # ── ポートフォリオ一覧（現在値自動取得）────────────────
    with st.spinner("現在値取得中..."):
        holdings = dm.get_portfolio_with_prices()

    if holdings:
        # 年間配当合計（大きく表示）
        total_income  = sum(h["年間配当額"] or 0 for h in holdings)
        total_cost    = sum(h["取得単価"] * h["保有数"] for h in holdings)
        total_eval    = sum(h["評価額"]               for h in holdings)
        total_unreal  = total_eval - total_cost

        st.markdown(
            f"<h2 style='text-align:center; color:#00c853;'>"
            f"年間配当合計: {total_income:,.0f}円"
            f"</h2>",
            unsafe_allow_html=True,
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("総取得額",  f"{total_cost:,.0f}円")
        c2.metric("総評価額",  f"{total_eval:,.0f}円")
        c3.metric("総含み損益", f"{total_unreal:+,.0f}円",
                  delta=f"{total_unreal/total_cost*100:+.1f}%" if total_cost > 0 else "")

        st.markdown("---")
        st.markdown("### 📌 保有銘柄一覧")

        if st.button("🔄 現在値を更新", key="refresh_div"):
            st.rerun()

        for h in holdings:
            pnl_color = "🟢" if h["含み損益"] >= 0 else "🔴"
            _stock_label = _sn(h["銘柄コード"], h["銘柄名"])
            with st.expander(
                f"{h['状態']}  {_stock_label}  "
                f"含み損益: {pnl_color} {h['含み損益']:+,.0f}円  "
                f"（現在利回り: {h['現在利回り']:.2f}%）" if h["現在利回り"] else
                f"{h['状態']}  {_stock_label}  "
                f"含み損益: {pnl_color} {h['含み損益']:+,.0f}円",
                expanded=False,
            ):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("取得単価",   f"{h['取得単価']:,.0f}円")
                c2.metric("現在値",     f"{h['現在値']:,.0f}円",
                          delta=f"{h['含み損益%']:+.1f}%")
                c3.metric("現在利回り", f"{h['現在利回り']:.2f}%" if h["現在利回り"] else "データなし")
                c4.metric("取得利回り", f"{h['取得利回り']:.2f}%" if h["取得利回り"] else "データなし")

                st.markdown(
                    f"**保有数**: {h['保有数']:,}株　"
                    f"**評価額**: {h['評価額']:,.0f}円　"
                    f"**年間配当**: {h['年間配当額']:,.0f}円" if h["年間配当額"] else
                    f"**保有数**: {h['保有数']:,}株　"
                    f"**評価額**: {h['評価額']:,.0f}円　"
                    f"**年間配当**: データなし（手動確認推奨）"
                )
                st.caption(f"セクター: {h['セクター']}")

                # ── 権利スケジュール ──────────────────────────
                st.markdown("**📅 権利スケジュール**")
                sched = dm.get_dividend_schedule(h["銘柄コード"])
                s1, s2, s3 = st.columns(3)
                s1.markdown(f"**権利付き最終日**: {sched['権利付き最終日']}")
                s2.markdown(f"**権利落ち日**: {sched['権利落ち日']}")
                s3.markdown(f"**権利確定日**: {sched['権利確定日']}")

                cd = sched["カウントダウン"]
                cd_status = sched["カウントダウン状態"]
                if cd_status == "権利落ち済み":
                    st.markdown("<span style='color:gray'>権利落ち済み</span>", unsafe_allow_html=True)
                elif cd_status == "danger":
                    st.markdown(f"<span style='color:red'>⚠️ 権利付き最終日まで残り **{cd}日**</span>", unsafe_allow_html=True)
                elif cd_status == "warning":
                    st.markdown(f"<span style='color:orange'>📆 権利付き最終日まで残り **{cd}日**</span>", unsafe_allow_html=True)
                elif cd_status == "ok":
                    st.markdown(f"📆 権利付き最終日まで残り **{cd}日**")

                # ── 財務健全性チェック ────────────────────────
                with st.expander("📊 財務健全性・配当トレンド"):
                    health = dm.get_financial_health(h["銘柄コード"])

                    # 配当性向
                    pr = health["payout_ratio"]
                    if pr is None:
                        st.markdown("**配当性向**: データなし（手動確認推奨）")
                    elif pr > 100:
                        st.markdown(f"**配当性向**: 🔴 {pr:.1f}%（要注意：減配リスク）")
                    elif pr > 70:
                        st.markdown(f"**配当性向**: ⚠️ {pr:.1f}%（高め）")
                    else:
                        st.markdown(f"**配当性向**: ✅ {pr:.1f}%")

                    # 自己資本比率
                    er = health["equity_ratio"]
                    if er is None:
                        st.markdown("**自己資本比率**: データなし")
                    elif er < 30:
                        st.markdown(f"**自己資本比率**: ⚠️ {er:.1f}%（低め）")
                    else:
                        st.markdown(f"**自己資本比率**: ✅ {er:.1f}%")

                    # 配当トレンド
                    dt_status = health["div_trend_status"]
                    dt_text   = health["div_trend"]
                    if dt_status == "good":
                        st.markdown(f"**配当トレンド**: ✅ {dt_text}")
                    elif dt_status == "warning":
                        st.markdown(f"**配当トレンド**: ⚠️ {dt_text}")
                    else:
                        st.markdown(f"**配当トレンド**: {dt_text}")

                # ── 権利落ち後分析 ────────────────────────────
                with st.expander("📉 権利落ち後の過去分析"):
                    analysis = dm.get_historical_analysis(h["銘柄コード"])
                    if "error" in analysis:
                        st.caption(f"データなし（手動確認推奨）: {analysis['error']}")
                    else:
                        if analysis.get("latest_div"):
                            st.markdown(f"**理論権利落ち下落額（税引前）**: {analysis['latest_div']:.2f}円/株")
                        if analysis.get("avg_recovery_days") is not None:
                            st.markdown(f"**平均回復日数**: {analysis['avg_recovery_days']}日")
                        else:
                            st.markdown("**平均回復日数**: データ不足")

                        records = analysis.get("records", [])
                        if records:
                            df_rec = pd.DataFrame(records)
                            st.dataframe(df_rec, use_container_width=True, hide_index=True)

                # ── 削除ボタン ────────────────────────────────
                if st.button(f"🗑 {h['銘柄名']}を削除", key=f"del_div_{h['id']}"):
                    dm.remove_stock(h["id"])
                    st.success(f"{_sn(h['銘柄コード'], h['銘柄名'])}を削除しました")
                    st.rerun()
    else:
        st.info("高配当株がまだ登録されていません。下のフォームから追加してください。")

    st.markdown("---")

    # ── 新規銘柄追加フォーム ────────────────────────────────
    st.markdown("### ➕ 保有銘柄を追加")
    with st.form("add_dividend_stock"):
        col_a, col_b, col_c = st.columns(3)
        new_sym  = col_a.text_input("銘柄コード（例: 9434）")
        new_name = col_b.text_input("銘柄名（例: ソフトバンク）")
        new_sect = col_c.selectbox("セクター", ["ディフェンシブ", "景気敏感", "その他"])

        col_d, col_e = st.columns(2)
        new_shares = col_d.number_input("保有数（株）", min_value=1, step=1, value=100)
        new_cost   = col_e.number_input("取得単価（円）", min_value=1.0, step=1.0, value=1000.0)

        if st.form_submit_button("📝 追加する", type="primary"):
            if not new_sym or not new_name or new_cost <= 0:
                st.error("銘柄コード・銘柄名・取得単価を入力してください")
            else:
                dm.add_stock(new_sym, new_name, int(new_shares), new_cost, new_sect)
                st.success(f"✅ {_sn(new_sym, new_name)} を追加しました")
                st.rerun()


# ─── メイン ──────────────────────────────────────────────────
def main():
    st.title("📈 株式スクリーニングツール")
    st.caption("毎日の引け後（15:30以降）に実行 → 翌日チェックすべき銘柄を自動で絞り込みます")
    st.warning(
        "⚠️ **免責事項**：本ツールは個人学習・情報整理を目的としたものです。"
        "表示される情報は投資の推奨・助言ではありません。"
        "投資判断はご自身の責任で行ってください。"
        "株式投資には元本割れのリスクがあります。"
    )

    # サイドバーから設定を取得・適用
    cfg = render_sidebar()
    apply_settings(cfg)

    # タブ（改良⑩で高配当株タブを追加）
    tab_screen, tab_portfolio, tab_backtest, tab_history, tab_dividend, tab_help = st.tabs([
        "🔍 スクリーニング", "💼 ポートフォリオ", "📊 バックテスト",
        "📚 履歴", "💰 高配当株", "❓ 使い方"
    ])

    # ─── セッション状態の初期化 ──────────────────────────
    if "candidates"     not in st.session_state:
        st.session_state["candidates"]     = []
    if "screen_date"    not in st.session_state:
        st.session_state["screen_date"]    = ""
    if "market_status"  not in st.session_state:
        st.session_state["market_status"]  = None
    if "force_refresh"  not in st.session_state:
        st.session_state["force_refresh"]  = False
    if "ad_ratio"       not in st.session_state:
        st.session_state["ad_ratio"]       = None

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

        # ── 騰落レシオ表示（改良④）──────────────────────
        if st.session_state["ad_ratio"] is not None:
            adr = st.session_state["ad_ratio"]
            if adr >= 120:
                st.markdown(
                    f"<span style='color:orange'>🌡️ 騰落レシオ: <b>{adr}</b>　過熱注意</span>",
                    unsafe_allow_html=True,
                )
            elif adr <= 75:
                st.markdown(
                    f"<span style='color:#1976d2'>🌡️ 騰落レシオ: <b>{adr}</b>　売られすぎ</span>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<span style='color:gray'>🌡️ 騰落レシオ: <b>{adr}</b>　中立</span>",
                    unsafe_allow_html=True,
                )
            # 上昇トレンドかつ過熱のときは追加警告
            if mkt["ok"] and adr >= 120:
                st.warning("地合いは上昇中ですが過熱感があります。慎重にエントリーしてください。")

        st.markdown(f"""
**対象市場**: {cfg['market']}
**総資金**: {cfg['capital']:,}円
**1回の最大損失**: {cfg['capital'] * cfg['risk'] / 100:,.0f}円
""")

        # ── 実行ボタン（通常 + キャッシュ更新）──────────────
        col_run, col_refresh, col_clear = st.columns([3, 2, 1])
        with col_run:
            run_button = st.button("▶ スクリーニング実行", type="primary", use_container_width=True)
        with col_refresh:
            refresh_button = st.button(
                "🔄 キャッシュ更新して実行",
                use_container_width=True,
                help="保存済みキャッシュを無視して全銘柄のデータを最新取得します。時間がかかります。"
            )
        with col_clear:
            if st.button("🗑 クリア", use_container_width=True):
                st.session_state["candidates"]    = []
                st.session_state["screen_date"]   = ""
                st.session_state["market_status"] = None
                st.session_state["force_refresh"] = False
                st.session_state["ad_ratio"]      = None
                st.rerun()

        st.caption("引け後（15:30以降）に実行するのが最適です。")

        # キャッシュ更新ボタン → force_refresh を立てて通常実行に合流
        force_refresh = False
        if refresh_button:
            st.session_state["force_refresh"] = True
            force_refresh = True

        do_run = run_button or refresh_button

        if do_run:
            # 設定を保存（改良⑥）
            save_settings(cfg)

            symbols = data_fetcher.load_watchlist()
            st.markdown(f"**対象銘柄数: {len(symbols)}銘柄**")

            raw_results = run_screening_with_progress(
                symbols,
                force_refresh=st.session_state.get("force_refresh", False)
            )
            st.session_state["force_refresh"] = False   # リセット

            # 騰落レシオを計算（改良④）
            with st.spinner("騰落レシオ計算中..."):
                from market_filter import get_advance_decline_ratio
                st.session_state["ad_ratio"] = get_advance_decline_ratio(symbols)

            if not raw_results:
                st.warning(
                    "本日は条件を満たす候補銘柄がありませんでした。\n\n"
                    "考えられる原因:\n"
                    "- 相場全体が下降トレンド（候補0件 = 見送りサイン）\n"
                    "- watchlist.txtの銘柄数が少ない\n"
                    "- スクリーニング条件が厳しすぎる（左サイドバーで調整）"
                )
            else:
                candidates = []
                for r in raw_results:
                    r["plan"] = calculator.build_trade_plan(r)
                    candidates.append(r)

                run_date = date.today().strftime("%Y-%m-%d")
                st.session_state["candidates"]  = candidates
                st.session_state["screen_date"] = run_date

                history_module.save_history(candidates, run_date)
                st.rerun()

        # ── 結果表示（セッションから読み込む）──────────────
        candidates = st.session_state["candidates"]
        run_date   = st.session_state["screen_date"]

        if candidates:
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

        summary = pf_module.get_summary()
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("総トレード数", f"{summary['total']}件")
        c2.metric("保有中",       f"{summary['open']}件")
        c3.metric("決済済み",     f"{summary['closed']}件")
        c4.metric("確定損益",     f"{summary['realized_pnl']:+,.0f}円")
        c5.metric("勝/負",        f"{summary['win']}勝 {summary['lose']}敗")

        st.markdown("---")
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
                    f"{pos['状態']}  {_sn(pos['銘柄コード'], pos['銘柄名'])}  "
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
                            st.success(f"{_sn(pos['銘柄コード'], pos['銘柄名'])} を決済しました")
                            st.rerun()

        st.markdown("---")
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
                max_loss       = loss_per_share * new_shares
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
                    st.success(f"✅ {_sn(new_symbol, new_name)} を追加しました")
                    st.rerun()

        st.markdown("---")
        st.markdown("### 📋 決済済みポジション")
        df_all    = pf_module.load_positions()
        closed_df = df_all[df_all["ステータス"] == "closed"]
        if closed_df.empty:
            st.info("決済済みのポジションはまだありません。")
        else:
            disp = closed_df[[
                "エントリー日", "銘柄コード", "銘柄名",
                "エントリー価格", "決済日", "決済価格", "決済理由", "確定損益"
            ]].copy()
            disp["銘柄"] = disp.apply(
                lambda r: _sn(str(r["銘柄コード"]), str(r["銘柄名"])), axis=1
            )
            disp = disp[["エントリー日", "銘柄", "エントリー価格", "決済日", "決済価格", "決済理由", "確定損益"]]
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

        st.info("⏱ 銘柄数×期間に応じて数分〜数十分かかります。実行中はタブを切り替えないでください。")
        bt_button = st.button("▶ バックテスト実行", type="secondary", use_container_width=True)

        if bt_button:
            from backtest import run_backtest, print_summary
            from market_filter import fetch_market_data_range

            symbols   = data_fetcher.load_watchlist()[:bt_top]
            start_str = bt_start.strftime("%Y-%m-%d")
            end_str   = bt_end.strftime("%Y-%m-%d")

            with st.spinner(f"{len(symbols)}銘柄 × {start_str}〜{end_str} でシミュレーション中..."):
                trades_df, equity_df = run_backtest(symbols, start_str, end_str)

            if trades_df.empty:
                st.warning("期間内にトレードがありませんでした。条件を変えて再実行してください。")
            else:
                total    = len(trades_df)
                wins     = (trades_df["損益合計"] > 0).sum()
                losses   = (trades_df["損益合計"] <= 0).sum()
                win_rate = wins / total * 100
                total_pnl = trades_df["損益合計"].sum()
                init_cap  = config.TOTAL_CAPITAL
                ret_pct   = total_pnl / init_cap * 100
                avg_win   = trades_df[trades_df["損益合計"] > 0]["損益合計"].mean() if wins > 0 else 0
                avg_loss  = trades_df[trades_df["損益合計"] <= 0]["損益合計"].mean() if losses > 0 else 0
                pf = abs(
                    trades_df[trades_df["損益合計"] > 0]["損益合計"].sum() /
                    trades_df[trades_df["損益合計"] <= 0]["損益合計"].sum()
                ) if losses > 0 else 999

                st.markdown("### 📋 結果サマリー")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("総トレード数", f"{total}件")
                c2.metric("勝率",         f"{win_rate:.1f}%")
                c3.metric("プロフィットF", f"{pf:.2f}")
                c4.metric("総損益",       f"{total_pnl:+,.0f}円", delta=f"{ret_pct:+.1f}%")

                c5, c6, c7, c8 = st.columns(4)
                c5.metric("初期資金",   f"{init_cap:,.0f}円")
                c6.metric("最終資金",   f"{init_cap + total_pnl:,.0f}円")
                c7.metric("平均利益",   f"+{avg_win:,.0f}円")
                c8.metric("平均損失",   f"{avg_loss:,.0f}円")

                st.markdown("### 🔖 決済理由の内訳")
                reason_df = trades_df.groupby("決済理由").agg(
                    件数=("損益合計", "count"),
                    平均損益=("損益合計", "mean"),
                    合計損益=("損益合計", "sum"),
                ).reset_index()
                reason_df["平均損益"] = reason_df["平均損益"].map(lambda x: f"{x:+,.0f}円")
                reason_df["合計損益"] = reason_df["合計損益"].map(lambda x: f"{x:+,.0f}円")
                st.dataframe(reason_df, use_container_width=True, hide_index=True)

                st.markdown("### 🏆 銘柄別損益ランキング")
                sym_df = (
                    trades_df.groupby(["銘柄コード", "銘柄名"])["損益合計"]
                    .sum().reset_index()
                    .sort_values("損益合計", ascending=False)
                )
                sym_df["銘柄"] = sym_df.apply(
                    lambda r: _sn(str(r["銘柄コード"]), str(r["銘柄名"])), axis=1
                )
                sym_df = sym_df[["銘柄", "損益合計"]]
                sym_df["損益合計"] = sym_df["損益合計"].map(lambda x: f"{x:+,.0f}円")
                st.dataframe(sym_df.head(15), use_container_width=True, hide_index=True)

                st.markdown("### 📄 全トレード一覧")
                display = trades_df[[
                    "エントリー日", "銘柄コード", "銘柄名",
                    "エントリー価格", "決済日", "決済理由", "損益率%", "損益合計"
                ]].copy()
                display["銘柄"] = display.apply(
                    lambda r: _sn(str(r["銘柄コード"]), str(r["銘柄名"])), axis=1
                )
                display = display[[
                    "エントリー日", "銘柄", "エントリー価格",
                    "決済日", "決済理由", "損益率%", "損益合計"
                ]]
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

    # ─── 高配当株タブ ────────────────────────────────────
    with tab_dividend:
        render_dividend_tab()

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
- 決済後の記録が自動で history.csv に書き込まれる

**手順**: スクリーニング結果 →「📝 ポジションに追加する」ボタン → 💼ポートフォリオタブで確認

---

### 💰 高配当株タブの使い方

長期保有を目的とした配当目当ての銘柄を管理できます：
- 年間配当合計が一目でわかる
- 配当性向・自己資本比率で減配リスクをチェック
- 権利落ち日のカウントダウンを表示

---

### 📚 用語集

| 用語 | 意味 |
|---|---|
| **スクリーニング** | 大量の株の中から条件に合う銘柄だけを絞り込むこと |
| **損切り（ロスカット）** | 損失が一定以上になったら売って損失を確定すること |
| **利確（利益確定）** | 値上がりしたところで売って利益を受け取ること |
| **出来高** | その日に売買された株の数 |
| **売買代金** | 終値 × 出来高。1億円以上が流動性の目安 |
| **MA25（25日移動平均線）** | 過去25日間の株価の平均 |
| **騰落レシオ** | 値上がり銘柄 ÷ 値下がり銘柄 × 100。120超で過熱、75以下で売られすぎ |
| **地合い** | 相場全体の雰囲気 |
| **かぶミニ®** | 楽天証券の1株単位取引サービス。ミニ株設定で対応可能 |

---

> ⚠️ **注意**: このツールは情報提供のみが目的です。表示された情報は投資の推奨ではありません。投資判断はご自身の責任で行ってください。
""")


if __name__ == "__main__":
    main()
