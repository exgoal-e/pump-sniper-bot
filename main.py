from binance.client import Client
import pandas as pd
import time, os, requests
from datetime import datetime

# ========= CONFIG =========
MODE = "PAPER"

CONFIG = {
    "RISK": 0.01,
    "vol_mult": 2.0,
    "trail": 0.01
}

DAILY_LOSS_LIMIT = -0.05

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("BINANCE_KEY")
API_SECRET = os.getenv("BINANCE_SECRET")

client = Client(API_KEY, API_SECRET)

positions = {}
pattern_db = {}
trade_history = []
trade_log = []

daily_pnl = 0

scan_count = 0
signal_count = 0
trade_count = 0

last_report_day = None

# ========= TELEGRAM =========
def send(msg):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  json={"chat_id": CHAT_ID, "text": msg})

# ========= DATA =========
def get_symbols():
    info = client.futures_exchange_info()
    return [s['symbol'] for s in info['symbols'] if s['quoteAsset']=="USDT"]

def get_klines(symbol, tf):
    k = client.futures_klines(symbol=symbol, interval=tf, limit=100)
    df = pd.DataFrame(k)
    df.columns = ["t","o","h","l","c","v","_","_","_","_","_","_"]
    df[["o","h","l","c","v"]] = df[["o","h","l","c","v"]].astype(float)
    return df

# ========= ORDERBOOK =========
def orderbook(symbol):
    ob = client.futures_order_book(symbol=symbol, limit=20)
    bids = sum(float(x[1]) for x in ob["bids"])
    asks = sum(float(x[1]) for x in ob["asks"])
    return bids/asks if asks else 1

# ========= EXPECTED TIME =========
def expected_time(df):
    momentum = abs(df["c"].iloc[-1] - df["c"].iloc[-2])
    vol = df["v"].iloc[-1]
    avg = df["v"].rolling(20).mean().iloc[-1]

    if vol > avg * 2.5 and momentum > 0:
        return "10–30 dk"
    elif vol > avg * 1.5:
        return "30–60 dk"
    return "1–2 saat"

# ========= DYNAMIC TP =========
def dynamic_tp(df):
    momentum = df["c"].iloc[-1] - df["c"].iloc[-2]
    vol = df["v"].iloc[-1]
    avg = df["v"].rolling(20).mean().iloc[-1]

    if vol > avg * 3:
        return 0.04
    elif momentum > 0:
        return 0.02
    return 0.01

# ========= PATTERN FILTER =========
def pattern_allowed(key):
    if key not in pattern_db:
        return True

    data = pattern_db[key]
    if data["trades"] < 10:
        return True

    winrate = data["win"] / data["trades"]
    return winrate >= 0.65

# ========= ANALYZE =========
def analyze(symbol):
    global signal_count

    df5 = get_klines(symbol, "5m")
    df1h = get_klines(symbol, "1h")

    price = df5["c"].iloc[-1]

    trend5 = price > df5["c"].rolling(50).mean().iloc[-1]
    trend1h = price > df1h["c"].rolling(50).mean().iloc[-1]

    if trend5 != trend1h:
        return None

    ob = orderbook(symbol)

    vol = df5["v"].iloc[-1]
    vol_avg = df5["v"].rolling(20).mean().iloc[-1]
    momentum = df5["c"].iloc[-1] - df5["c"].iloc[-2]

    volSpike = vol > vol_avg * CONFIG["vol_mult"]
    obStrong = ob > 1.2 if trend5 else ob < 0.8

    score = 0
    if volSpike: score += 2
    if momentum != 0: score += 1
    if obStrong: score += 1

    if score < 3:
        return None

    key = f"{volSpike}_{momentum>0}_{obStrong}_{trend5}"

    if not pattern_allowed(key):
        return None

    signal_count += 1

    return ("LONG" if trend5 else "SHORT"), score, ob, key, df5

# ========= OPEN =========
def open_trade(symbol, side, score, ob, key, df):
    global trade_count

    price = df["c"].iloc[-1]
    tp = dynamic_tp(df)
    exp_time = expected_time(df)

    positions[symbol] = {
        "side": side,
        "entry": price,
        "peak": price,
        "tp": tp,
        "tp_hit": False,
        "pattern": key
    }

    trade_count += 1

    confidence = min(90, score * 20)

    send(f"""
🚀 {side} {symbol}

💰 Entry: {round(price,5)}
📊 Size: %1 risk  
⚡ Lev: 3x  

━━━━━━━━━━━━━━━
🎯 TP Zone:  
→ TP1: {round(price*(1+tp),5)}  
→ TP2: RUNNER 🔥  
━━━━━━━━━━━━━━━

📊 Market Insight:
• Orderbook: {round(ob,2)}x  
• Momentum: {"Bullish" if side=="LONG" else "Bearish"}  

🧠 AI Confidence: {confidence}%  

⏱ Beklenen süre: {exp_time}  

📉 Trailing: Active  
🛑 SL: Dynamic  

🔗 Chart:
https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}
""")

# ========= MANAGE =========
def manage(symbol):
    global daily_pnl

    pos = positions[symbol]
    df = get_klines(symbol, "5m")
    price = df["c"].iloc[-1]

    entry = pos["entry"]
    pnl = (price-entry)/entry if pos["side"]=="LONG" else (entry-price)/entry

    if price > pos["peak"]:
        pos["peak"] = price

    if not pos["tp_hit"] and pnl > pos["tp"]:
        pos["tp_hit"] = True
        send(f"💰 TP HIT {symbol} %{round(pnl*100,2)}")

    if price < pos["peak"] * (1-CONFIG["trail"]):
        send(f"""
❌ TRAILING EXIT {symbol}

PnL: %{round(pnl*100,2)}
""")

        key = pos["pattern"]

        if key not in pattern_db:
            pattern_db[key] = {"win":0,"loss":0,"trades":0}

        if pnl > 0:
            pattern_db[key]["win"] += 1
        else:
            pattern_db[key]["loss"] += 1

        pattern_db[key]["trades"] += 1

        trade_history.append(pnl)
        trade_log.append({"symbol":symbol,"pnl":pnl})

        daily_pnl += pnl
        del positions[symbol]

# ========= BEST COINS =========
def best_coins():
    coin_perf = {}

    for t in trade_log:
        sym = t["symbol"]
        if sym not in coin_perf:
            coin_perf[sym] = {"win":0,"total":0}

        if t["pnl"] > 0:
            coin_perf[sym]["win"] += 1

        coin_perf[sym]["total"] += 1

    result = []
    for c,v in coin_perf.items():
        if v["total"] > 5:
            wr = v["win"]/v["total"]
            result.append((c,wr))

    result.sort(key=lambda x: x[1], reverse=True)
    return result[:5]

# ========= REPORT =========
def send_report():
    global last_report_day

    now = datetime.now()
    if last_report_day == now.day:
        return

    if now.hour == 23:
        wins = sum(1 for x in trade_history if x>0)
        total = len(trade_history)
        winrate = (wins/total*100) if total>0 else 0

        top = best_coins()
        top_text = "\n".join([f"{c} → %{round(w*100,1)}" for c,w in top])

        send(f"""
📊 GÜNLÜK RAPOR

Tarandı: {scan_count}
Sinyal: {signal_count}
Trade: {trade_count}

Winrate: %{round(winrate,2)}
PnL: %{round(daily_pnl*100,2)}

🔥 En iyi coinler:
{top_text}
""")

        last_report_day = now.day

# ========= MAIN =========
def run():
    global scan_count

    if daily_pnl <= DAILY_LOSS_LIMIT:
        send("🛑 BOT DURDU")
        return

    for sym in get_symbols()[:200]:
        scan_count += 1

        try:
            res = analyze(sym)
            if not res:
                continue

            signal, s, ob, key, df = res

            if sym not in positions:
                open_trade(sym, signal, s, ob, key, df)

            if sym in positions:
                manage(sym)

        except:
            continue

    send_report()

while True:
    run()
    time.sleep(60)
