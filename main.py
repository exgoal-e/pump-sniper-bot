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
    "max_pos_usdt": 50,
    "min_pos_usdt": 5,
    "scale_trigger": 0.01,
    "max_scale": 1,
    "max_open_trades": 5,
    "min_conf": 60
}

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("BINANCE_KEY")
API_SECRET = os.getenv("BINANCE_SECRET")

client = Client(API_KEY, API_SECRET)

positions = {}

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
    df = klines(sym, "5m")
    if df is None:
        return None

    price = df["c"].iloc[-1]
    ma = df["c"].rolling(50).mean().iloc[-1]
    if pd.isna(ma):
        return None

    # 💣 LONG ONLY
    side = "LONG" if price > ma else None
    if side is None:
        return None

    macd_line, signal_line = macd(df)
    macd_cross = macd_line.iloc[-2] < signal_line.iloc[-2] and macd_line.iloc[-1] > signal_line.iloc[-1]

    vol = df["v"].iloc[-1]
    avg = df["v"].rolling(20).mean().iloc[-1]
    if avg == 0 or pd.isna(avg):
        return None

    volSpike = vol > avg * CONFIG["vol_mult"]

    # breakout + fake filter
    recent_high = df["h"].rolling(20).max().iloc[-2]
    breakout = price > recent_high

    body = abs(df["c"].iloc[-1] - df["o"].iloc[-1])
    candle_range = df["h"].iloc[-1] - df["l"].iloc[-1]
    strong_candle = body > candle_range * 0.6

    if not (macd_cross and volSpike and breakout and strong_candle):
        return None

    confidence = 80
    return side, df, confidence

# ========= OPEN =========
def open_trade(sym, side, df, confidence):
    if len(positions) >= CONFIG["max_open_trades"]:
        return

    price = df["c"].iloc[-1]
    sl = df["l"].iloc[-2]

    risk = abs(price - sl)

    tp1 = price + risk*0.5
    tp2 = price + risk*0.8
    tp3 = price + risk*1.3

    positions[sym] = {
        "side": side,
        "entry": price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "tp1_hit": False,
        "tp2_hit": False,
        "peak": price,
        "scale": 0
    }

    send(f"""
🚀 LONG {sym} (SNIPER)

💰 Entry: {round(price,4)}
🎯 Confidence: {confidence}

TP1: {round(tp1,4)}
TP2: {round(tp2,4)}
TP3: {round(tp3,4)}

SL: {round(sl,4)}
""")

# ========= MANAGE =========
def manage(sym):
    pos = positions[sym]
    df = klines(sym, "5m")
    if df is None:
        return

    price = df["c"].iloc[-1]
    pnl = (price - pos["entry"]) / pos["entry"]

    if not pos["tp1_hit"] and price >= pos["tp1"]:
        pos["tp1_hit"] = True
        send(f"💰 TP1 {sym}")

    # scale sadece tp1 sonrası
    if pos["tp1_hit"] and pnl > CONFIG["scale_trigger"] and pos["scale"] < CONFIG["max_scale"]:
        pos["scale"] += 1
        send(f"➕ SCALE {sym}")

    # trailing
    if price > pos["peak"]:
        pos["peak"] = price

    if price < pos["peak"]*(1-CONFIG["trail"]):
        send(f"❌ EXIT {sym} %{round(pnl*100,2)}")
        del positions[sym]

# ========= MAIN =========
def run():
    for sym in symbols()[:100]:
        try:
            res = analyze(sym)
            if not res:
                continue

            side, df, conf = res

            if sym not in positions:
                open_trade(sym, side, df, conf)

            if sym in positions:
                manage(sym)

        except:
            continue

while True:
    run()
    time.sleep(60)
