"""yfinanceが実際に返す列名を確認する"""
import yfinance as yf

df = yf.download("7203.T", period="1mo", auto_adjust=True, progress=False)
print("columns:", df.columns.tolist())
print("index type:", type(df.index))
print(df.tail(3))
