# 📈 株式スクリーニングツール

引け後に翌営業日の監視候補銘柄を自動抽出する、個人用の半自動売買補助ツール。

> **免責事項**: 本ツールは情報提供のみを目的としています。投資判断はすべて自己責任で行ってください。

---

## 目的

- 完全自動発注はしない
- **「見る価値のある銘柄を絞る」** ことが主目的
- 引け後に実行 → 翌朝の判断材料を出す

---

## 機能一覧

| 機能 | 説明 |
|---|---|
| スクリーニング | 設定条件に基づいてTOPIX銘柄をフィルタリング |
| トレードプラン | エントリー候補・損切り・利確・注文サイズを自動計算 |
| スコアリング | 複数条件の重み付きスコアで候補をランキング |
| 通知 | コンソール / CSV / Discord webhook |
| 履歴管理 | 通知結果をCSVに記録し、後から勝率・損益を検証 |
| Webアプリ | Streamlit製のブラウザUI（スマホからも使用可） |

---

## スクリーニング条件

### 買い候補条件（全条件を満たす銘柄のみ通過）

| # | 条件 | 設定値 |
|---|---|---|
| 1 | 25日移動平均線が上向き | MA25の5日前比がプラス |
| 2 | 株価が25日移動平均線より上 | Close > MA25 |
| 3 | 直近5営業日以内に高値更新あり | 過去30日高値を更新 |
| 4 | 当日出来高が20日平均より多い | 出来高倍率 ≥ 1.2倍 |
| 5 | 株価が低位株でない | 株価 ≥ 300円 |
| 6 | 出来高が薄すぎない | 1日出来高 ≥ 100,000株 |

### 見送り警告（条件通過後に警告表示）

| 警告 | 条件 |
|---|---|
| ギャップアップ | 寄り付きが前日終値比 +5%超 |
| 上髭警告 | 上髭比率 50%以上 |
| 出来高の質 | 出来高2倍以上 かつ 値幅1%未満 |
| 過熱感 | MA25乖離率 +15%以上 |

---

## トレードプラン計算

### 損切り（config.STOP_MODE = "both" が標準）

```
固定損切り  = エントリー価格 × (1 - 損切り幅%)
スウィング  = 直近10日安値 × 0.99
→ 保守的な方（高い方）を採用
```

### 利確

```
固定利確 = エントリー価格 × (1 + 利確幅%)
RR利確   = エントリー価格 + (エントリー - 損切り) × RR倍率
```

### 注文サイズ

```
許容損失額   = 総資金 × リスク%
1株損失      = エントリー価格 - 損切り価格
注文株数     = 許容損失額 ÷ 1株損失（100株単位に切り捨て）
```

**例：**
```
総資金      500,000円
許容損失    1.0% → 5,000円
1株損失     50円
注文株数    100株
投資額      エントリー価格 × 100株
```

---

## スコアリング

| 条件 | 点数 |
|---|---|
| MA25上に位置 | 20点 |
| MA25上向き | 20点 |
| 直近5日高値更新 | 25点 |
| 出来高急増 | 20点 |
| 高値から3%以内の軽い押し | 15点 |
| **合計最高点** | **100点** |

---

## ファイル構成

```
Investor/
├── app.py              # Streamlit Webアプリ
├── main.py             # CLIエントリーポイント
├── config.py           # 全設定（資金・条件・通知）
├── data_fetcher.py     # yfinanceでOHLCV取得
├── screener.py         # スクリーニングロジック
├── calculator.py       # 損切り・利確・注文サイズ計算
├── notifier.py         # コンソール/CSV/Discord出力
├── history.py          # 履歴CSV管理
├── fetch_universe.py   # TOPIX銘柄リスト取得
├── requirements.txt
└── data/
    ├── watchlist.txt   # スクリーニング対象銘柄リスト
    ├── history.csv     # 通知履歴（自動生成）
    └── output/         # CSVレポート出力先
```

---

## セットアップ

### 必要環境
- Python 3.11 以上
- インターネット接続（yfinance・JPXデータ取得用）

### インストール

```bash
git clone https://github.com/<あなたのユーザー名>/investor.git
cd investor
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### TOPIX銘柄リストの取得

```bash
python fetch_universe.py --top 500   # 時価総額上位500銘柄
python fetch_universe.py --prime     # プライム市場全銘柄
python fetch_universe.py             # TOPIX全銘柄
```

### 起動

```bash
# Webアプリ（推奨）
streamlit run app.py

# CLI
python main.py

# 履歴統計の確認
python main.py --stats
```

---

## 設定変更

`config.py` を編集することで動作を変更できます。

```python
TOTAL_CAPITAL       = 500_000   # 総資金（円）
RISK_PERCENT        = 1.0       # 許容損失（%）
STOP_LOSS_PERCENT   = 4.0       # 損切り幅（%）
TAKE_PROFIT_PERCENT = 8.0       # 利確幅（%）
VOLUME_RATIO_MIN    = 1.2       # 最低出来高倍率
MIN_PRICE           = 300       # 最低株価（円）
MAX_CANDIDATES      = 10        # 最大候補数
```

### Discord通知の設定

`.env.example` を `.env` にコピーして Webhook URL を設定：

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxxx/yyyy
```

`config.py` で `OUTPUT_DISCORD = True` に変更。

---

## 使い方（毎日のルーティン）

```
15:30 引け後
  ↓
python fetch_universe.py --top 500  # 月1回程度でOK
  ↓
streamlit run app.py  または  python main.py
  ↓
候補銘柄を確認
  ↓
翌朝、エントリー候補価格帯で寄り付きを監視
  ↓
自分で判断してから発注（ツールは自動発注しない）
  ↓
結果を history.csv に記録（手動）
```

---

## 履歴管理

`data/history.csv` に以下を記録します。
トレード後に手動で追記することで勝率・損益を追跡できます。

| 列 | 記録タイミング |
|---|---|
| 通知日・銘柄・抽出理由 | 自動記録 |
| 実際に入ったか | 翌朝判断後に手動入力 |
| 勝ち / 負け | 決済後に手動入力 |
| 損益（円） | 決済後に手動入力 |

---

## 使用ライブラリ

| ライブラリ | 用途 |
|---|---|
| yfinance | 株価・出来高データ取得 |
| pandas | データ処理・指標計算 |
| numpy | 数値計算 |
| streamlit | WebアプリUI |
| requests | JPXデータ取得・Discord通知 |
| tabulate | CLI表示整形 |
| openpyxl | Excel読み込み |

---

## データソース

- 株価データ: [Yahoo Finance](https://finance.yahoo.com/)（yfinance経由・無料）
- TOPIX構成銘柄: [日本取引所グループ（JPX）](https://www.jpx.co.jp/markets/indices/topix/)（無料・毎月更新）

---

## 今後の拡張予定

- [ ] 決算カレンダー連携（決算直前銘柄の自動除外）
- [ ] チャート画像生成（mplfinance）
- [ ] 地合い判断（TOPIX・日経平均のトレンド自動判定）
- [ ] 米国株対応の強化
- [ ] バックテスト機能

---

*個人学習・研究用途のツールです。投資は自己責任で。*
