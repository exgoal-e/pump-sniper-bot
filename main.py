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
trade_history = []
daily_pnl = 0

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

# ========= ANALYZE =========
def analyze(symbol):
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

    score = 0
    if vol > vol_avg * CONFIG["vol_mult"]: score += 2
    if momentum > 0: score += 1
    if ob > 1.2: score += 1

    if score < 3:
        return None

    return ("LONG" if trend5 else "SHORT"), score, ob

# ========= TP LOGIC =========
def dynamic_tp(df):
    momentum = df["c"].iloc[-1] - df["c"].iloc[-2]
    vol = df["v"].iloc[-1]
    avg = df["v"].rolling(20).mean().iloc[-1]

    if vol > avg * 3:
        return 0.04
    elif momentum > 0:
        return 0.02
    return 0.01

# ========= OPEN =========
def open_trade(symbol, side, score, ob):
    df = get_klines(symbol, "5m")
    price = df["c"].iloc[-1]
    tp = dynamic_tp(df)

    positions[symbol] = {
        "side": side,
        "entry": price,
        "peak": price,
        "tp": tp,
        "tp_hit": False
    }

    send(f"""
🚀 {side} {symbol}

Entry: {round(price,4)}
Lev: 3x

TP: %{tp*100}
Orderbook: {round(ob,2)}x

Runner aktif 🔥
Trailing aktif
""")

# ========= MANAGE =========
def manage(symbol):
    global daily_pnl

    pos = positions[symbol]
    df = get_klines(symbol, "5m")
    price = df["c"].iloc[-1]

    entry = pos["entry"]
    pnl = (price-entry)/entry if pos["side"]=="LONG" else (entry-price)/entry

    # peak
    if price > pos["peak"]:
        pos["peak"] = price

    # TP
    if not pos["tp_hit"] and pnl > pos["tp"]:
        pos["tp_hit"] = True
        send(f"💰 TP HIT {symbol} %{round(pnl*100,2)}")

    # trailing
    if price < pos["peak"] * (1-CONFIG["trail"]):
        send(f"""
❌ TRAILING EXIT {symbol}

PnL: %{round(pnl*100,2)}
""")
        daily_pnl += pnl
        trade_history.append(pnl)
        del positions[symbol]

# ========= AI =========
def optimize():
    if len(trade_history) < 20:
        return

    winrate = sum(1 for x in trade_history if x>0)/len(trade_history)

    if winrate < 0.5:
        CONFIG["vol_mult"] += 0.2
    elif winrate > 0.65:
        CONFIG["vol_mult"] -= 0.1

    send(f"🧠 AI UPDATE Winrate: %{round(winrate*100,2)}")

# ========= MAIN =========
def run():
    global daily_pnl

    if daily_pnl <= DAILY_LOSS_LIMIT:
        send("🛑 BOT DURDU")
        return

    for sym in get_symbols()[:200]:
        try:
            res = analyze(sym)
            if not res:
                continue

            signal, s, ob = res

            if sym not in positions:
                open_trade(sym, signal, s, ob)

            if sym in positions:
                manage(sym)

        except:
            continue

    optimize()

while True:
    run()
    time.sleep(60)
