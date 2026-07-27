#!/usr/bin/env python3
"""
Yahoo Finance 株価取得ツール

使い方:
    python get_stock.py <銘柄コード> <日数>

例:
    python get_stock.py 9418.T 10      # U-NEXT HOLDINGSの直近10日間
    python get_stock.py AAPL 5         # Appleの直近5日間
    python get_stock.py 9418 10        # 数字のみなら自動で東証(.T)を付与
    python get_stock.py 9418.T 10 --csv   # CSVファイルとしても保存
"""

import sys
import argparse
from datetime import datetime

try:
    import yfinance as yf
    import pandas as pd
except ImportError:
    print("必要なライブラリがインストールされていません。")
    print("次のコマンドを実行してください: pip install -r requirements.txt")
    sys.exit(1)


def normalize_ticker(ticker: str) -> str:
    """数字だけのコードなら東証銘柄とみなして .T を付与する"""
    ticker = ticker.strip().upper()
    if ticker.isdigit():
        return f"{ticker}.T"
    return ticker


def fetch_stock(ticker: str, days: int, ema_short: int = 5, ema_long: int = 25):
    ticker = normalize_ticker(ticker)
    # 土日・祝日に加え、EMAの精度を保つための助走期間分も多めに取得してから直近days件に絞る
    period_days = max(days * 3, ema_long * 5, 30)
    stock = yf.Ticker(ticker)
    hist = stock.history(period=f"{period_days}d")

    if hist.empty:
        raise ValueError(f"'{ticker}' のデータが見つかりませんでした。銘柄コードを確認してください。")

    # 取引時間中などでまだ確定していない当日分(NaN)は除外する
    hist = hist.dropna(subset=["Close"])

    # 指数平滑移動平均線(EMA)を算出（助走期間を含めた全体で計算してから切り詰める）
    hist[f"EMA{ema_short}"] = hist["Close"].ewm(span=ema_short, adjust=False).mean()
    hist[f"EMA{ema_long}"] = hist["Close"].ewm(span=ema_long, adjust=False).mean()

    hist = hist.tail(days)
    return ticker, stock, hist


def print_table(ticker: str, stock, hist: "pd.DataFrame", ema_short: int = 5, ema_long: int = 25):
    info = {}
    try:
        info = stock.info
    except Exception:
        pass

    name = info.get("longName") or info.get("shortName") or ticker
    currency = info.get("currency", "")

    print("=" * 62)
    print(f"銘柄: {name} ({ticker})")
    print("=" * 62)

    ema_short_col = f"EMA{ema_short}"
    ema_long_col = f"EMA{ema_long}"

    header = (
        f"{'日付':<12}{'始値':>10}{'高値':>10}{'安値':>10}{'終値':>10}"
        f"{ema_short_col:>10}{ema_long_col:>10}{'出来高':>15}"
    )
    print(header)
    print("-" * len(header))

    for date, row in hist.iterrows():
        print(
            f"{date.strftime('%Y-%m-%d'):<12}"
            f"{row['Open']:>10.1f}"
            f"{row['High']:>10.1f}"
            f"{row['Low']:>10.1f}"
            f"{row['Close']:>10.1f}"
            f"{row[ema_short_col]:>10.1f}"
            f"{row[ema_long_col]:>10.1f}"
            f"{int(row['Volume']):>15,}"
        )

    print("-" * len(header))

    first_close = hist["Close"].iloc[0]
    last_close = hist["Close"].iloc[-1]
    change = last_close - first_close
    change_pct = (change / first_close) * 100 if first_close else 0
    arrow = "▲" if change > 0 else ("▼" if change < 0 else "→")

    print(f"期間騰落: {arrow} {change:+.1f} ({change_pct:+.2f}%)  通貨: {currency}")

    last_ema_short = hist[ema_short_col].iloc[-1]
    last_ema_long = hist[ema_long_col].iloc[-1]
    if last_ema_short > last_ema_long:
        trend = f"EMA{ema_short} > EMA{ema_long}（短期優勢・上昇基調）"
    elif last_ema_short < last_ema_long:
        trend = f"EMA{ema_short} < EMA{ema_long}（短期劣勢・下降基調）"
    else:
        trend = f"EMA{ema_short} = EMA{ema_long}（拮抗）"
    print(f"EMAトレンド: {trend}")
    print("=" * len(header))


def save_csv(ticker: str, hist: "pd.DataFrame", path: str = None) -> str:
    if path is None:
        safe_ticker = ticker.replace(".", "_")
        path = f"{safe_ticker}_{datetime.now().strftime('%Y%m%d')}.csv"
    hist.to_csv(path, encoding="utf-8-sig")
    print(f"CSVを保存しました: {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description="Yahoo Financeから株価を取得します")
    parser.add_argument("ticker", help="銘柄コード（例: 9418.T, AAPL, 9418）")
    parser.add_argument("days", type=int, nargs="?", default=5, help="取得したい日数（デフォルト: 5日）")
    parser.add_argument("--csv", action="store_true", help="CSVファイルとして保存する")
    parser.add_argument("--ema-short", type=int, default=5, help="短期EMAの期間（デフォルト: 5日）")
    parser.add_argument("--ema-long", type=int, default=25, help="長期EMAの期間（デフォルト: 25日）")

    args = parser.parse_args()

    try:
        ticker, stock, hist = fetch_stock(args.ticker, args.days, args.ema_short, args.ema_long)
    except ValueError as e:
        print(f"エラー: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"データ取得中にエラーが発生しました: {e}")
        sys.exit(1)

    print_table(ticker, stock, hist, args.ema_short, args.ema_long)

    if args.csv:
        save_csv(ticker, hist)


if __name__ == "__main__":
    main()
