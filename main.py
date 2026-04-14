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
    "whale_size": 10000,
    "max_pos_usdt": 50,
    "min_pos_usdt": 5
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

# ========= BALANCE =========
def get_balance():
    try:
        bal = client.futures_account_balance()
        for b in bal:
            if b["asset"] == "USDT":
                return float(b["balance"])
    except:
        return 100

# ========= RISK ENGINE =========
def calc_position_size(entry, sl, balance):
    risk_amount = balance * CONFIG["RISK"]
    sl_distance = abs(entry - sl)

    if sl_distance == 0:
        return 0

    size = risk_amount / sl_distance
    pos_usdt = size * entry

    if pos_usdt > CONFIG["max_pos_usdt"]:
        pos_usdt = CONFIG["max_pos_usdt"]

    if pos_usdt < CONFIG["min_pos_usdt"]:
        pos_usdt = CONFIG["min_pos_usdt"]

    qty = pos_usdt / entry
    return round(qty, 3)

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

# ========= ANALYZE (AYNI) =========
def analyze(sym):
    df5 = klines(sym, "5m")
    df1h = klines(sym, "1h")
    df4h = klines(sym, "4h")

    if df5 is None or df1h is None or df4h is None:
        return None

    price = df5["c"].iloc[-1]

    ma5 = df5["c"].rolling(50).mean().iloc[-1]
    ma1 = df1h["c"].rolling(50).mean().iloc[-1]
    ma4 = df4h["c"].rolling(50).mean().iloc[-1]

    if pd.isna(ma5) or pd.isna(ma1) or pd.isna(ma4):
        return None

    trend5 = price > ma5
    trend1 = price > ma1
    trend4 = price > ma4

    if not (trend5 == trend1 == trend4):
        return None

    side = "LONG" if trend5 else "SHORT"

    return side, df5

# ========= OPEN =========
def open_trade(sym, side, df):
    price = df["c"].iloc[-1]
    sl = df["l"].iloc[-2] if side=="LONG" else df["h"].iloc[-2]

    balance = get_balance()
    qty = calc_position_size(price, sl, balance)

    risk = abs(price - sl)
    tp1 = price + risk*CONFIG["RR"] if side=="LONG" else price - risk*CONFIG["RR"]

    positions[sym] = {
        "side": side,
        "entry": price,
        "sl": sl,
        "tp1": tp1,
        "tp_hit": False,
        "peak": price,
        "qty": qty
    }

    send(f"""
🚀 {side} {sym}

💰 Entry: {round(price,4)}
📦 Qty: {qty}

🎯 TP1: {round(tp1,4)}
🛑 SL: {round(sl,4)}
""")

# ========= MANAGE =========
def manage(sym):
    pos = positions[sym]
    df = klines(sym, "5m")
    if df is None:
        return

    price = df["c"].iloc[-1]

    entry = pos["entry"]
    pnl = (price-entry)/entry if pos["side"]=="LONG" else (entry-price)/entry

    # PEAK UPDATE (LONG)
    if pos["side"]=="LONG":
        if price > pos["peak"]:
            pos["peak"] = price

    # PEAK UPDATE (SHORT FIX)
    if pos["side"]=="SHORT":
        if price < pos["peak"]:
            pos["peak"] = price

    # TP1 %50 CLOSE
    if not pos["tp_hit"]:
        if (pos["side"]=="LONG" and price >= pos["tp1"]) or (pos["side"]=="SHORT" and price <= pos["tp1"]):
            pos["tp_hit"] = True
            pos["qty"] *= 0.5  # kalan runner

            send(f"💰 TP1 HIT {sym} (%50 closed)")

    # TRAILING EXIT
    if pos["side"]=="LONG":
        if price < pos["peak"]*(1-CONFIG["trail"]):
            send(f"❌ EXIT {sym} PnL %{round(pnl*100,2)}")
            del positions[sym]

    if pos["side"]=="SHORT":
        if price > pos["peak"]*(1+CONFIG["trail"]):
            send(f"❌ EXIT {sym} PnL %{round(pnl*100,2)}")
            del positions[sym]

# ========= MAIN =========
def run():
    for sym in symbols()[:100]:
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
    time.sleep(60)
