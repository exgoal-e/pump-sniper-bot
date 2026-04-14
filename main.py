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
    "whale_size": 10000
}

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("BINANCE_KEY")
API_SECRET = os.getenv("BINANCE_SECRET")

client = Client(API_KEY, API_SECRET)

positions = {}

# ========= TELEGRAM =========
def send(msg):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  json={"chat_id": CHAT_ID, "text": msg})

# ========= DATA =========
def klines(sym, tf):
    k = client.futures_klines(symbol=sym, interval=tf, limit=100)
    df = pd.DataFrame(k)
    df.columns = ["t","o","h","l","c","v","_","_","_","_","_","_"]
    df[["o","h","l","c","v"]] = df[["o","h","l","c","v"]].astype(float)
    return df

def symbols():
    return [s['symbol'] for s in client.futures_exchange_info()['symbols'] if s['quoteAsset']=="USDT"]

# ========= ORDERBOOK =========
def orderbook(sym):
    ob = client.futures_order_book(symbol=sym, limit=50)
    bids = sum(float(x[1]) for x in ob["bids"])
    asks = sum(float(x[1]) for x in ob["asks"])
    ratio = bids/asks if asks else 1
    return ratio, ob

# ========= WHALE =========
def whale(ob):
    big_bids = sum(float(x[1]) for x in ob["bids"] if float(x[1]) > CONFIG["whale_size"])
    big_asks = sum(float(x[1]) for x in ob["asks"] if float(x[1]) > CONFIG["whale_size"])

    if big_bids > big_asks * 1.5:
        return "Bullish"
    elif big_asks > big_bids * 1.5:
        return "Bearish"
    return "Neutral"

# ========= SWEEP =========
def sweep(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    if last["h"] > prev["h"] and last["c"] < last["h"]:
        return "Bearish"
    if last["l"] < prev["l"] and last["c"] > last["l"]:
        return "Bullish"
    return None

# ========= LEVERAGE =========
def calc_lev(conf, vol, whale_dir):
    lev = 2

    if conf > 75: lev += 2
    elif conf > 65: lev += 1

    if whale_dir != "Neutral": lev += 1
    if vol > 0.02: lev -= 1

    return max(2, min(7, lev))

# ========= ANALYZE =========
def analyze(sym):
    df5 = klines(sym, "5m")
    df1h = klines(sym, "1h")
    df4h = klines(sym, "4h")

    price = df5["c"].iloc[-1]

    trend5 = price > df5["c"].rolling(50).mean().iloc[-1]
    trend1 = price > df1h["c"].rolling(50).mean().iloc[-1]
    trend4 = price > df4h["c"].rolling(50).mean().iloc[-1]

    if not (trend5 == trend1 == trend4):
        return None

    side = "LONG" if trend5 else "SHORT"

    ob_ratio, ob = orderbook(sym)

    # ORDERBOOK FIX
    if side == "LONG" and ob_ratio < 1.1:
        return None
    if side == "SHORT" and ob_ratio > 0.9:
        return None

    whale_dir = whale(ob)
    sw = sweep(df5)

    vol = df5["v"].iloc[-1]
    avg = df5["v"].rolling(20).mean().iloc[-1]

    volSpike = vol > avg * CONFIG["vol_mult"]
    momentum = df5["c"].iloc[-1] - df5["c"].iloc[-2]

    score = 0
    if volSpike: score += 2
    if momentum != 0: score += 1
    if whale_dir != "Neutral": score += 1

    if score < 3:
        return None

    volatility = (df5["h"].iloc[-1] - df5["l"].iloc[-1]) / price
    lev = calc_lev(score*20, volatility, whale_dir)

    return side, df5, ob_ratio, whale_dir, sw, lev, score

# ========= OPEN =========
def open_trade(sym, side, df, ob, whale_dir, sw, lev, score):
    price = df["c"].iloc[-1]

    sl = df["l"].iloc[-2] if side=="LONG" else df["h"].iloc[-2]

    risk = abs(price - sl)
    tp1 = price + risk*CONFIG["RR"] if side=="LONG" else price - risk*CONFIG["RR"]

    positions[sym] = {
        "side": side,
        "entry": price,
        "sl": sl,
        "tp1": tp1,
        "tp_hit": False,
        "peak": price
    }

    send(f"""
🚀 {side} {sym}

💰 Entry: {round(price,4)}  
📊 Size: %1 risk  
⚡ Lev: {lev}x  

━━━━━━━━━━━━━━━
🎯 TP Zone:  
→ TP1: {round(tp1,4)}  
→ Runner: OPEN 🔥  
━━━━━━━━━━━━━━━

📊 Market Insight:
• Orderbook: {round(ob,2)}x  
• Whale: {whale_dir} 🐋  
• Sweep: {sw if sw else "None"}  

🧠 AI Confidence: {score*20}%  

⏱ Beklenen süre: 15–45 dk  

📉 Trailing: Active  
🛑 SL: {round(sl,4)}  

🔗 Chart:
https://www.tradingview.com/chart/?symbol=BINANCE:{sym}
""")

# ========= MANAGE =========
def manage(sym):
    pos = positions[sym]
    df = klines(sym, "5m")
    price = df["c"].iloc[-1]

    entry = pos["entry"]
    pnl = (price-entry)/entry if pos["side"]=="LONG" else (entry-price)/entry

    if price > pos["peak"]:
        pos["peak"] = price

    # TP1 partial
    if not pos["tp_hit"]:
        if (pos["side"]=="LONG" and price >= pos["tp1"]) or (pos["side"]=="SHORT" and price <= pos["tp1"]):
            pos["tp_hit"] = True
            send(f"💰 TP1 HIT {sym} (%50 closed)")

    # trailing
    if price < pos["peak"]*(1-CONFIG["trail"]):
        send(f"❌ TRAILING EXIT {sym} PnL %{round(pnl*100,2)}")
        del positions[sym]

# ========= MAIN =========
def run():
    for sym in symbols()[:200]:
        try:
            res = analyze(sym)
            if not res:
                continue

            side, df, ob, whale_dir, sw, lev, score = res

            if sym not in positions:
                open_trade(sym, side, df, ob, whale_dir, sw, lev, score)

            if sym in positions:
                manage(sym)

        except:
            continue

while True:
    run()
    time.sleep(60)
