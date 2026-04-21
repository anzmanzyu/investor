"""
config.py — ツール全体の設定ファイル
ここを編集するだけで動作を変更できる
"""

# ─── 資金管理 ───────────────────────────────────────────
TOTAL_CAPITAL = 500_000          # 総資金（円）
RISK_PERCENT  = 1.0              # 1トレードの許容損失（%）。0.5〜1.0 を推奨

# ─── 損切り・利確 ────────────────────────────────────────
STOP_LOSS_PERCENT   = 3.0        # エントリーからの損切り幅（%）← 4.0→3.0
TAKE_PROFIT_PERCENT = 5.0        # エントリーからの利確幅（%）← 8.0→5.0
RISK_REWARD_RATIO   = 2.0        # リスクリワード倍率（利確 = 損切り幅 × この値）

# 損切り計算方式: "fixed" = 固定%, "swing" = 直近安値, "both" = 両方表示
STOP_MODE = "fixed"              # "both"→"fixed"（損切り幅を統一）

# ─── スクリーニング条件 ─────────────────────────────────
MA_SHORT   = 25    # 短期移動平均（メイン判断）
MA_LONG    = 75    # 長期移動平均（トレンド確認用・参考）
VOLUME_MA  = 20    # 出来高の平均期間（日）
LOOKBACK_DAYS = 5  # 直近高値更新を見る日数

# 除外フィルター
MIN_PRICE           = 300        # この価格以下は低位株として除外（円）
MIN_VOLUME_PER_DAY  = 100_000    # 1日最低出来高（株）。これ以下は流動性不足として除外（参考値）
MIN_TURNOVER        = 100_000_000  # 1日最低売買代金（円）。1億円未満は除外（⑤ 売買代金フィルター）
VOLUME_RATIO_MIN    = 1.5        # 当日出来高 / 20日平均。この値以上のみ通過 ← 1.2→1.5
MAX_GAP_PERCENT     = 5.0        # 寄り付きギャップが何%以上なら警告を出すか

# ─── スコアリング（総合スコアの重み）───────────────────
SCORE_WEIGHTS = {
    "above_ma25"       : 20,   # MA25上にいる
    "ma25_upward"      : 20,   # MA25上向き
    "new_high_5d"      : 25,   # 5日以内に高値更新
    "volume_surge"     : 20,   # 出来高急増
    "pullback_mild"    : 15,   # 高値から -3%以内の軽い押し
}

# ─── 対象市場 ────────────────────────────────────────────
# "JP" = 日本株（yfinance ticker に ".T" を付けて取得）
# "US" = 米国株（ticker そのまま）
MARKET = "JP"

# ─── 通知設定 ─────────────────────────────────────────
OUTPUT_CONSOLE = True             # コンソール出力
OUTPUT_CSV     = True             # CSVファイル出力
OUTPUT_DISCORD = False            # Discord通知（Webhookが必要）

# Discord Webhook URL（OUTPUT_DISCORD=True のときだけ使用）
# 実際のURLは .env ファイルに書くことを推奨
DISCORD_WEBHOOK_URL = ""

# ─── 出力先ディレクトリ ────────────────────────────────
OUTPUT_DIR  = "data/output"      # CSVレポートの保存先
HISTORY_CSV = "data/history.csv" # 履歴ファイルパス
WATCHLIST   = "data/watchlist.txt"  # 銘柄リストのパス

# ─── 最大候補数 ────────────────────────────────────────
MAX_CANDIDATES = 10   # 出力する候補銘柄の最大数

# ─── 注文単位 ────────────────────────────────────────────
# 100 = 通常株（100株単位）
# 1   = ミニ株（かぶミニ® 1株単位）
LOT_SIZE = 100

# ─── 大量銘柄スクリーニング用設定 ──────────────────────
# TOPIX全銘柄（約2000）を対象にする場合の調整値
# fetch_universe.py で watchlist.txt を更新してから main.py を実行する

# 出来高フィルターをやや緩める（小型株が多いため）
# MIN_VOLUME_PER_DAY = 50_000  # 必要なら config.py 側で変更
