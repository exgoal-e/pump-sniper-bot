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
signal_count = 0
trade_count = 0
daily_pnl = 0

coin_stats = {}
pattern_stats = {"LONG": [], "SHORT": []}
hour_stats = {}

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
    global signal_count

    df = klines(sym, "5m")
    if df is None:
        return None

    price = df["c"].iloc[-1]
    ma = df["c"].rolling(50).mean().iloc[-1]
    if pd.isna(ma):
        return None

    if price < ma:
        return None

    macd_line, signal_line = macd(df)
    macd_cross = macd_line.iloc[-2] < signal_line.iloc[-2] and macd_line.iloc[-1] > signal_line.iloc[-1]

    vol = df["v"].iloc[-1]
    avg = df["v"].rolling(20).mean().iloc[-1]
    if avg == 0:
        return None

    volSpike = vol > avg * CONFIG["vol_mult"]

    recent_high = df["h"].rolling(20).max().iloc[-2]
    breakout = price > recent_high

    body = abs(df["c"].iloc[-1] - df["o"].iloc[-1])
    rng = df["h"].iloc[-1] - df["l"].iloc[-1]
    strong = body > rng * 0.6

    if not (macd_cross and volSpike and breakout and strong):
        return None

    signal_count += 1
    return "LONG", df

# ========= OPEN =========
def open_trade(sym, side, df):
    global trade_count, hour_stats

    if len(positions) >= CONFIG["max_open_trades"]:
        return

    price = df["c"].iloc[-1]
    sl = df["l"].iloc[-2]

    risk = abs(price - sl)

    tp1 = price + risk * 0.5
    tp2 = price + risk * 0.8

    positions[sym] = {
        "entry": price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp1_hit": False,
        "tp2_hit": False,
        "peak": price
    }

    trade_count += 1
    hour = datetime.utcnow().hour
    hour_stats[hour] = hour_stats.get(hour, 0) + 1

    send(f"""
🚀 LONG {sym} (SNIPER)

💰 Entry: {round(price,4)}

━━━━━━━━━━━━━━━
🎯 TP LEVELS
→ TP1: {round(tp1,4)} (%50)
→ TP2: {round(tp2,4)} (%30)
→ Runner: ACTIVE 🔥
━━━━━━━━━━━━━━━

📉 Trailing: Active
🛑 SL: {round(sl,4)}

🔗 Chart:
https://www.tradingview.com/chart/?symbol=BINANCE:{sym}
""")

# ========= MANAGE =========
def manage(sym):
    global daily_pnl, coin_stats, pattern_stats

    pos = positions[sym]
    df = klines(sym, "5m")
    if df is None:
        return

    price = df["c"].iloc[-1]
    pnl = (price - pos["entry"]) / pos["entry"]

    if not pos["tp1_hit"] and price >= pos["tp1"]:
        pos["tp1_hit"] = True
        send(f"💰 TP1 HIT {sym} (%50)")

    if not pos["tp2_hit"] and price >= pos["tp2"]:
        pos["tp2_hit"] = True
        send(f"💰 TP2 HIT {sym} (%30)")

    if price > pos["peak"]:
        pos["peak"] = price

    if price < pos["peak"]*(1-CONFIG["trail"]):
        daily_pnl += pnl

        coin_stats.setdefault(sym, []).append(pnl)
        pattern_stats["LONG"].append(pnl)

        send(f"❌ EXIT {sym} %{round(pnl*100,2)}")
        del positions[sym]

# ========= REPORT =========
from datetime import datetime, UTC

def send_daily_report():
    global last_report_day

    now = datetime.now(UTC)

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

    worst_pattern = min(pattern_stats, key=lambda x: sum(pattern_stats[x])/len(pattern_stats[x]) if pattern_stats[x] else 0)

    best_hour = max(hour_stats, key=hour_stats.get) if hour_stats else "N/A"

    ai = "Stabil"
    if winrate < 45:
        ai = "⚠️ Filtre artır"
    elif winrate > 60:
        ai = "🔥 Güçlü"

    send(f"""
📊 GÜNLÜK RAPOR

Tarandı: {scan_count}
Sinyal: {signal_count}
Trade: {trade_count}

Winrate: %{round(winrate,2)}
PnL: %{round(daily_pnl*100,2)}

🔥 En iyi coinler:
{best_text}

❌ En kötü pattern:
{worst_pattern}

⏱ En iyi saat:
{best_hour}:00

🧠 AI Yorum:
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
