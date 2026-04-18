from binance.client import Client
import pandas as pd
import time, os, requests
from datetime import datetime

# ========= CONFIG =========
CONFIG = {
    "RISK": 0.01,
    "RR": 2,
    "trail": 0.01,
    "vol_mult": 2,
    "max_open_trades": 5
}

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("BINANCE_KEY")
API_SECRET = os.getenv("BINANCE_SECRET")

client = Client(API_KEY, API_SECRET)

positions = {}

# ========= STATS =========
scan_count = 0
trade_count = 0
daily_pnl = 0

coin_stats = {}
hour_stats = {}
pattern_stats = {}

last_report_day = None

# ========= TELEGRAM =========
def send(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

# ========= MACD =========
def macd(df):
    ema12 = df["c"].ewm(span=12).mean()
    ema26 = df["c"].ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9).mean()
    return macd_line, signal

# ========= DATA =========
def klines(sym, tf):
    try:
        k = client.futures_klines(symbol=sym, interval=tf, limit=100)
        df = pd.DataFrame(k)
        df.columns = ["t","o","h","l","c","v","_","_","_","_","_","_"]
        df[["o","h","l","c","v"]] = df[["o","h","l","c","v"]].astype(float)
        return df
    except:
        return None

def symbols():
    return [s['symbol'] for s in client.futures_exchange_info()['symbols'] if s['quoteAsset']=="USDT"]

# ========= ANALYZE =========
def analyze(sym):
    df5 = klines(sym, "5m")
    df1h = klines(sym, "1h")

    if df5 is None or df1h is None:
        return None

    price = df5["c"].iloc[-1]
    ma5 = df5["c"].rolling(50).mean().iloc[-1]
    ma1h = df1h["c"].rolling(50).mean().iloc[-1]

    if pd.isna(ma5) or pd.isna(ma1h):
        return None

    # LONG ONLY + MTF
    if not (price > ma5 and price > ma1h):
        return None

    macd_line, signal_line = macd(df5)
    macd_cross = macd_line.iloc[-2] < signal_line.iloc[-2] and macd_line.iloc[-1] > signal_line.iloc[-1]

    vol = df5["v"].iloc[-1]
    avg = df5["v"].rolling(20).mean().iloc[-1]

    if avg == 0:
        return None

    volSpike = vol > avg * CONFIG["vol_mult"]

    recent_high = df5["h"].rolling(20).max().iloc[-2]
    breakout = price > recent_high

    body = abs(df5["c"].iloc[-1] - df5["o"].iloc[-1])
    rng = df5["h"].iloc[-1] - df5["l"].iloc[-1]

    strong = body > rng * 0.6

    if not (macd_cross and volSpike and breakout and strong):
        return None

    return "LONG", df5

# ========= OPEN =========
def open_trade(sym, side, df):
    global trade_count, hour_stats

    if len(positions) >= CONFIG["max_open_trades"]:
        return

    price = df["c"].iloc[-1]
    sl = df["l"].iloc[-2]

    risk = abs(price - sl)

    tp = price + risk * CONFIG["RR"]

    positions[sym] = {
        "entry": price,
        "sl": sl,
        "tp": tp,
        "peak": price
    }

    trade_count += 1
    hour = datetime.utcnow().hour
    hour_stats[hour] = hour_stats.get(hour, 0) + 1

    send(f"🚀 LONG {sym} | Entry: {price} TP: {tp} SL: {sl}")

# ========= MANAGE =========
def manage(sym):
    global daily_pnl, coin_stats

    pos = positions[sym]
    df = klines(sym, "5m")

    if df is None:
        return

    price = df["c"].iloc[-1]

    pnl = (price - pos["entry"]) / pos["entry"]

    if price > pos["peak"]:
        pos["peak"] = price

    if price < pos["peak"]*(1-CONFIG["trail"]):
        daily_pnl += pnl

        coin_stats.setdefault(sym, []).append(pnl)

        send(f"❌ EXIT {sym} %{round(pnl*100,2)}")
        del positions[sym]

# ========= REPORT =========
def send_daily_report():
    global last_report_day

    now = datetime.utcnow()

    if not (now.hour == 23 and now.minute < 10):
        return

    if last_report_day == now.day:
        return

    last_report_day = now.day

    total = sum(len(v) for v in coin_stats.values()) or 1
    wins = sum(sum(1 for x in v if x > 0) for v in coin_stats.values())

    winrate = wins / total * 100

    best = sorted(coin_stats.items(), key=lambda x: sum(x[1])/len(x[1]) if x[1] else 0, reverse=True)[:3]

    best_text = "\n".join([f"{c} → %{round(sum(v)/len(v)*100,1)}" for c,v in best if v])

    best_hour = max(hour_stats, key=hour_stats.get) if hour_stats else "N/A"

    ai = "Stabil"
    if winrate < 45:
        ai = "⚠️ Filtre artır"
    elif winrate > 60:
        ai = "🔥 Güçlü"

    send(f"""
📊 GÜNLÜK RAPOR

Tarandı: {scan_count}
Trade: {trade_count}

Winrate: %{round(winrate,2)}
PnL: %{round(daily_pnl*100,2)}

🔥 En iyi coinler:
{best_text}

⏱ En iyi saat:
{best_hour}

🧠 AI:
{ai}
""")

# ========= MAIN =========
def run():
    global scan_count

    for sym in symbols()[:100]:
        scan_count += 1

        try:
            res = analyze(sym)
            if not res:
                continue

            side, df = res

            if sym not in positions:
                open_trade(sym, side, df)

            if sym in positions:
                manage(sym)

        except:
            continue

while True:
    run()
    send_daily_report()
    time.sleep(60)
