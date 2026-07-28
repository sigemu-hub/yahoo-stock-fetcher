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


EMA_PERIOD_CHOICES = (5, 25, 75, 200)


def parse_ema_periods(value: str) -> list:
    """"5,25,75,200" のようなカンマ区切り文字列をEMA期間のリストに変換する"""
    periods = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        period = int(part)
        if period not in EMA_PERIOD_CHOICES:
            choices = ", ".join(str(p) for p in EMA_PERIOD_CHOICES)
            raise ValueError(f"EMA期間は次の中から指定してください: {choices}（指定値: {period}）")
        periods.append(period)
    if not periods:
        raise ValueError("EMA期間が指定されていません。")
    return sorted(set(periods))


VOL_MA_PERIOD = 20


def fetch_stock(ticker: str, days: int, ema_periods: list = (5, 25, 75, 200)):
    ticker = normalize_ticker(ticker)
    # 土日・祝日に加え、EMAや出来高MAの精度を保つための助走期間分も多めに取得してから直近days件に絞る
    period_days = max(days * 3, max(ema_periods) * 5, days + VOL_MA_PERIOD * 3, 30)
    stock = yf.Ticker(ticker)
    hist = stock.history(period=f"{period_days}d")

    if hist.empty:
        raise ValueError(f"'{ticker}' のデータが見つかりませんでした。銘柄コードを確認してください。")

    # 取引時間中などでまだ確定していない当日分(NaN)は除外する
    hist = hist.dropna(subset=["Close"])

    # 指数平滑移動平均線(EMA)を算出（助走期間を含めた全体で計算してから切り詰める）
    for period in ema_periods:
        hist[f"EMA{period}"] = hist["Close"].ewm(span=period, adjust=False).mean()

    # 出来高の単純移動平均（出来高MA20）を算出
    hist[f"VolMA{VOL_MA_PERIOD}"] = hist["Volume"].rolling(window=VOL_MA_PERIOD, min_periods=1).mean()

    hist = hist.tail(days)
    return ticker, stock, hist


def print_table(ticker: str, stock, hist: "pd.DataFrame", ema_periods: list = (5, 25, 75, 200)):
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

    ema_periods = sorted(ema_periods)
    ema_cols = [f"EMA{p}" for p in ema_periods]
    vol_ma_col = f"VolMA{VOL_MA_PERIOD}"
    vol_ma_header = f"出来高MA{VOL_MA_PERIOD}"

    header = f"{'日付':<12}{'始値':>10}{'高値':>10}{'安値':>10}{'終値':>10}"
    header += "".join(f"{col:>10}" for col in ema_cols)
    header += f"{'出来高':>15}{vol_ma_header:>15}{'出来高比':>10}"
    print(header)
    print("-" * len(header))

    for date, row in hist.iterrows():
        line = (
            f"{date.strftime('%Y-%m-%d'):<12}"
            f"{row['Open']:>10.1f}"
            f"{row['High']:>10.1f}"
            f"{row['Low']:>10.1f}"
            f"{row['Close']:>10.1f}"
        )
        line += "".join(f"{row[col]:>10.1f}" for col in ema_cols)
        vol_ratio = (row["Volume"] / row[vol_ma_col] * 100) if row[vol_ma_col] else 0
        line += f"{int(row['Volume']):>15,}"
        line += f"{int(row[vol_ma_col]):>15,}"
        line += f"{vol_ratio:>9.1f}%"
        print(line)

    print("-" * len(header))

    first_close = hist["Close"].iloc[0]
    last_close = hist["Close"].iloc[-1]
    change = last_close - first_close
    change_pct = (change / first_close) * 100 if first_close else 0
    arrow = "▲" if change > 0 else ("▼" if change < 0 else "→")

    print(f"期間騰落: {arrow} {change:+.1f} ({change_pct:+.2f}%)  通貨: {currency}")

    last_values = [(p, hist[f"EMA{p}"].iloc[-1]) for p in ema_periods]
    order_parts = [f"EMA{last_values[0][0]}"]
    signs = []
    for (_, v1), (p2, v2) in zip(last_values, last_values[1:]):
        if v1 > v2:
            sign = ">"
        elif v1 < v2:
            sign = "<"
        else:
            sign = "="
        signs.append(sign)
        order_parts.append(sign)
        order_parts.append(f"EMA{p2}")
    order_str = " ".join(order_parts)

    if len(ema_periods) >= 2:
        if all(s == ">" for s in signs):
            label = "（短期上位の完全上昇配列）"
        elif all(s == "<" for s in signs):
            label = "（短期下位の完全下降配列）"
        else:
            label = ""
        print(f"EMAトレンド: {order_str}{label}")

    last_volume = hist["Volume"].iloc[-1]
    last_vol_ma = hist[vol_ma_col].iloc[-1]
    last_vol_ratio = (last_volume / last_vol_ma * 100) if last_vol_ma else 0
    if last_vol_ratio > 100:
        vol_note = f"平均(MA{VOL_MA_PERIOD})の{last_vol_ratio:.0f}%（平均より多い）"
    elif last_vol_ratio < 100:
        vol_note = f"平均(MA{VOL_MA_PERIOD})の{last_vol_ratio:.0f}%（平均より少ない）"
    else:
        vol_note = f"平均(MA{VOL_MA_PERIOD})と同水準"
    print(f"出来高: {vol_note}")
    print("=" * len(header))


VRVP_VALUE_AREA_PCT = 0.70


def compute_volume_profile(hist: "pd.DataFrame", bins: int = 10) -> dict:
    """表示期間（Visible Range）の高値・安値レンジを価格帯に分割し、
    各日の出来高を高値〜安値レンジ内で均等分布させて価格帯ごとに積み上げる（VRVP）"""
    price_low = float(hist["Low"].min())
    price_high = float(hist["High"].max())
    if price_high <= price_low:
        price_high = price_low + 1.0

    bin_width = (price_high - price_low) / bins
    edges = [price_low + i * bin_width for i in range(bins + 1)]
    volumes = [0.0] * bins

    for row in hist.itertuples():
        low, high, vol = row.Low, row.High, row.Volume
        day_range = high - low
        if day_range <= 0:
            idx = min(int((low - price_low) / bin_width), bins - 1)
            volumes[idx] += vol
            continue
        for i in range(bins):
            overlap = min(high, edges[i + 1]) - max(low, edges[i])
            if overlap > 0:
                volumes[i] += vol * (overlap / day_range)

    poc_index = max(range(bins), key=lambda i: volumes[i])

    total = sum(volumes)
    va_target = total * VRVP_VALUE_AREA_PCT
    low_idx = high_idx = poc_index
    current = volumes[poc_index]
    while current < va_target and (low_idx > 0 or high_idx < bins - 1):
        vol_below = volumes[low_idx - 1] if low_idx > 0 else -1
        vol_above = volumes[high_idx + 1] if high_idx < bins - 1 else -1
        if vol_above >= vol_below:
            high_idx += 1
            current += volumes[high_idx]
        else:
            low_idx -= 1
            current += volumes[low_idx]

    return {
        "edges": edges,
        "volumes": volumes,
        "poc_index": poc_index,
        "va_low_index": low_idx,
        "va_high_index": high_idx,
    }


def print_volume_profile(hist: "pd.DataFrame", bins: int = 10):
    profile = compute_volume_profile(hist, bins)
    edges = profile["edges"]
    volumes = profile["volumes"]
    poc_index = profile["poc_index"]
    va_low_index = profile["va_low_index"]
    va_high_index = profile["va_high_index"]

    poc_price = (edges[poc_index] + edges[poc_index + 1]) / 2
    va_low_price = edges[va_low_index]
    va_high_price = edges[va_high_index + 1]
    max_vol = max(volumes) if volumes else 0
    bar_width = 30

    print(f"出来高プロファイル（VRVP, 表示期間を{bins}分割）")
    print(f"POC（最多出来高帯）: {poc_price:,.1f}   バリューエリア(70%): {va_low_price:,.1f} 〜 {va_high_price:,.1f}")
    print("-" * 62)

    for i in reversed(range(bins)):
        bin_lo, bin_hi = edges[i], edges[i + 1]
        vol = volumes[i]
        bar_len = int(vol / max_vol * bar_width) if max_vol else 0
        bar = "█" * bar_len
        if i == poc_index:
            marker = " ← POC"
        elif va_low_index <= i <= va_high_index:
            marker = " VA"
        else:
            marker = ""
        print(f"{bin_lo:>9,.1f}-{bin_hi:<9,.1f} {bar:<{bar_width}} {int(vol):>13,}{marker}")

    print("=" * 62)


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
    parser.add_argument(
        "--ema",
        type=str,
        default="5,25,75,200",
        help="表示するEMA期間をカンマ区切りで指定（選択可: 5, 25, 75, 200 / デフォルト: 5,25,75,200）",
    )
    parser.add_argument(
        "--vrvp-bins", type=int, default=10, help="出来高プロファイル(VRVP)の価格帯分割数（デフォルト: 10）"
    )
    parser.add_argument("--no-vrvp", action="store_true", help="出来高プロファイル(VRVP)を表示しない")

    args = parser.parse_args()

    if args.vrvp_bins < 2:
        print("エラー: --vrvp-bins は2以上を指定してください。")
        sys.exit(1)

    try:
        ema_periods = parse_ema_periods(args.ema)
        ticker, stock, hist = fetch_stock(args.ticker, args.days, ema_periods)
    except ValueError as e:
        print(f"エラー: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"データ取得中にエラーが発生しました: {e}")
        sys.exit(1)

    print_table(ticker, stock, hist, ema_periods)

    if not args.no_vrvp:
        print_volume_profile(hist, args.vrvp_bins)

    if args.csv:
        save_csv(ticker, hist)


if __name__ == "__main__":
    main()
