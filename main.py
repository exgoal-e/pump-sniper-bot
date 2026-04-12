from binance.client import Client
import pandas as pd
import time, os, requests
from datetime import datetime

# ========= CONFIG =========
MODE = "PAPER"   # PAPER / LIVE

CONFIG = {
    "RISK": 0.01,
    "vol_mult": 2.0,
    "tp1": 0.01,
    "tp2": 0.02,
    "trail": 0.01
}

MAX_POS = 3
DAILY_LOSS_LIMIT = -0.03

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("BINANCE_KEY")
API_SECRET = os.getenv("BINANCE_SECRET")

client = Client(API_KEY, API_SECRET)

positions = {}
daily_pnl = 0
pattern_db = {}
trade_count = 0

# ========= TELEGRAM =========
def send(msg):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  json={"chat_id": CHAT_ID, "text": msg})

# ========= DATA =========
def get_symbols():
    info = client.futures_exchange_info()
    return [s['symbol'] for s in info['symbols'] if s['quoteAsset'] == 'USDT']

def get_klines(symbol):
    k = client.futures_klines(symbol=symbol, interval="5m", limit=100)
    df = pd.DataFrame(k)
    df.columns = ["t","o","h","l","c","v","_","_","_","_","_","_"]
    df[["o","h","l","c","v"]] = df[["o","h","l","c","v"]].astype(float)
    return df

# ========= SCORE =========
def score(df):
    vol = df["v"].iloc[-1]
    vol_avg = df["v"].rolling(20).mean().iloc[-1]
    momentum = df["c"].iloc[-1] - df["c"].iloc[-2]

    s = 0
    if vol > vol_avg * CONFIG["vol_mult"]: s += 2
    if momentum > 0: s += 1
    if df["c"].iloc[-1] > df["c"].rolling(50).mean().iloc[-1]: s += 1

    return s, vol > vol_avg, momentum > 0

# ========= ANALYZE =========
def analyze(symbol):
    df = get_klines(symbol)
    s, volSpike, momentum = score(df)

    if s < 3:
        return None

    trendUp = df["c"].iloc[-1] > df["c"].rolling(50).mean().iloc[-1]
    key = f"{volSpike}_{momentum}_{trendUp}"

    if key in pattern_db and pattern_db[key]["trades"] > 5:
        winrate = pattern_db[key]["win"] / pattern_db[key]["trades"]
        if winrate < 0.4:
            return None

    return ("LONG" if trendUp else "SHORT"), s, key

# ========= BALANCE =========
def get_balance():
    if MODE == "PAPER":
        return 1000
    b = client.futures_account_balance()
    for x in b:
        if x["asset"] == "USDT":
            return float(x["balance"])

# ========= SIZE =========
def calc_qty(price):
    bal = get_balance()
    risk_amt = bal * CONFIG["RISK"]
    sl = price * 0.01
    return round(risk_amt / sl, 3)

# ========= OPEN =========
def open_trade(symbol, side, score_val, key):
    df = get_klines(symbol)
    price = df["c"].iloc[-1]
    qty = calc_qty(price)

    if MODE == "LIVE":
        order_side = "BUY" if side=="LONG" else "SELL"
        client.futures_create_order(symbol=symbol, side=order_side,
                                    type="MARKET", quantity=qty)

    positions[symbol] = {
        "side": side,
        "entry": price,
        "qty": qty,
        "tp1": False,
        "added": False,
        "peak": price,
        "pattern": key
    }

    send(f"""
🚀 {side} {symbol}

Entry: {round(price,5)}
Score: {score_val}

TP1: {round(price*(1+CONFIG["tp1"]),5)}
TP2: {round(price*(1+CONFIG["tp2"]),5)}

Trailing: ON
📊 https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}
""")

# ========= CLOSE =========
def close(symbol, price):
    global daily_pnl, trade_count

    pos = positions[symbol]
    entry = pos["entry"]

    pnl = (price-entry)/entry if pos["side"]=="LONG" else (entry-price)/entry
    daily_pnl += pnl
    trade_count += 1

    key = pos["pattern"]
    if key not in pattern_db:
        pattern_db[key] = {"win":0,"loss":0,"trades":0}

    if pnl > 0:
        pattern_db[key]["win"] += 1
    else:
        pattern_db[key]["loss"] += 1

    pattern_db[key]["trades"] += 1

    if MODE == "LIVE":
        side = "SELL" if pos["side"]=="LONG" else "BUY"
        client.futures_create_order(symbol=symbol, side=side,
                                    type="MARKET", quantity=pos["qty"])

    send(f"""
❌ CLOSE {symbol}

PnL: %{round(pnl*100,2)}
Günlük: %{round(daily_pnl*100,2)}
""")

    del positions[symbol]

# ========= MANAGE =========
def manage(symbol):
    pos = positions[symbol]
    df = get_klines(symbol)
    price = df["c"].iloc[-1]

    entry = pos["entry"]
    side = pos["side"]

    pnl = (price-entry)/entry if side=="LONG" else (entry-price)/entry

    # peak
    if side=="LONG" and price > pos["peak"]:
        pos["peak"] = price
    elif side=="SHORT" and price < pos["peak"]:
        pos["peak"] = price

    # scale-in
    if not pos["added"] and pnl < -0.005:
        pos["added"] = True
        send(f"📥 SCALE-IN {symbol}")

    # TP1
    if not pos["tp1"] and pnl > CONFIG["tp1"]:
        pos["tp1"] = True
        send(f"💰 TP1 {symbol} %{round(pnl*100,2)}")

    # trailing
    if side=="LONG":
        if price < pos["peak"] * (1-CONFIG["trail"]):
            send(f"❌ TRAILING EXIT {symbol}")
            close(symbol, price)
    else:
        if price > pos["peak"] * (1+CONFIG["trail"]):
            send(f"❌ TRAILING EXIT {symbol}")
            close(symbol, price)

# ========= AI OPTIMIZER =========
def optimize():
    if trade_count < 20:
        return

    wins = sum(v["win"] for v in pattern_db.values())
    total = sum(v["trades"] for v in pattern_db.values())

    if total == 0:
        return

    winrate = wins / total

    msg = f"\n🧠 AI OPTIMIZATION\nWinrate: %{round(winrate*100,2)}\n"

    if winrate < 0.5:
        CONFIG["vol_mult"] += 0.2
        CONFIG["tp1"] -= 0.002
        CONFIG["trail"] -= 0.001
        msg += "❌ Daha sıkı filtre\n"

    elif winrate > 0.65:
        CONFIG["vol_mult"] -= 0.1
        CONFIG["tp1"] += 0.002
        CONFIG["trail"] += 0.001
        msg += "🔥 Daha agresif\n"

    msg += f"""
Vol: {CONFIG["vol_mult"]}
TP1: {CONFIG["tp1"]}
Trail: {CONFIG["trail"]}
"""

    send(msg)

# ========= FILTER =========
def allowed_hour():
    return datetime.now().hour not in [3,4]

# ========= KILL SWITCH =========
def kill_switch():
    if daily_pnl <= DAILY_LOSS_LIMIT:
        send("🛑 BOT DURDU")
        return True
    return False

# ========= MAIN =========
def run():
    if kill_switch():
        return

    symbols = get_symbols()[:200]

    for sym in symbols:
        try:
            if not allowed_hour():
                continue

            result = analyze(sym)
            if not result:
                continue

            signal, s, key = result

            if sym not in positions:
                open_trade(sym, signal, s, key)

            if sym in positions:
                manage(sym)

        except:
            continue

    optimize()

while True:
    run()
    time.sleep(60)
