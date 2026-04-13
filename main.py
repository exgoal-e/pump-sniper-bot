# ========= IMPORT =========
from binance.client import Client
import pandas as pd
import numpy as np
import time, os, requests
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier

# ========= CONFIG =========
CONFIG = {
    "RISK": 0.01,
    "RR": 2,
    "trail": 0.01,
    "vol_mult": 2,
    "max_positions": 3,
    "daily_dd": -0.03
}

LIVE = False  # 🔴 TRUE yapınca gerçek trade açar

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("BINANCE_KEY")
API_SECRET = os.getenv("BINANCE_SECRET")

client = Client(API_KEY, API_SECRET)

positions = {}
trade_history = []
daily_pnl = 0

# ========= ML MODEL =========
model = RandomForestClassifier(n_estimators=50)

X_data = []
y_data = []

def train_model():
    if len(X_data) > 50:
        model.fit(X_data, y_data)

def predict(features):
    if len(X_data) < 50:
        return 0.5
    return model.predict_proba([features])[0][1]

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

# ========= ORDER =========
def open_order(sym, side, qty):
    if not LIVE:
        return

    try:
        client.futures_create_order(
            symbol=sym,
            side="BUY" if side=="LONG" else "SELL",
            type="MARKET",
            quantity=qty
        )
    except:
        pass

# ========= ANALYZE =========
def analyze(sym):
    df = klines(sym, "5m")

    price = df["c"].iloc[-1]
    ma = df["c"].rolling(20).mean().iloc[-1]

    vol = df["v"].iloc[-1]
    avg = df["v"].rolling(20).mean().iloc[-1]

    momentum = df["c"].iloc[-1] - df["c"].iloc[-2]

    features = [
        price/ma,
        vol/avg,
        momentum
    ]

    ml_score = predict(features)

    if ml_score < 0.6:
        return None

    side = "LONG" if momentum > 0 else "SHORT"

    return side, price, features, ml_score

# ========= PORTFOLIO =========
def can_trade():
    global daily_pnl

    if len(positions) >= CONFIG["max_positions"]:
        return False

    if daily_pnl < CONFIG["daily_dd"]:
        return False

    return True

# ========= OPEN =========
def open_trade(sym, side, price, features, score):
    global positions

    if not can_trade():
        return

    sl = price * (0.99 if side=="LONG" else 1.01)
    risk = abs(price - sl)
    tp = price + risk*CONFIG["RR"] if side=="LONG" else price - risk*CONFIG["RR"]

    qty = 10  # sabit (istersen dinamik yaparız)

    open_order(sym, side, qty)

    positions[sym] = {
        "side": side,
        "entry": price,
        "sl": sl,
        "tp": tp,
        "features": features
    }

    send(f"""
🚀 {side} {sym}

Entry: {round(price,4)}
TP: {round(tp,4)}
SL: {round(sl,4)}

🧠 ML Score: {round(score*100,1)}%
""")

# ========= MANAGE =========
def manage(sym):
    global daily_pnl

    pos = positions[sym]
    price = klines(sym, "5m")["c"].iloc[-1]

    entry = pos["entry"]

    pnl = (price-entry)/entry if pos["side"]=="LONG" else (entry-price)/entry

    if pnl > 0.01 or pnl < -0.01:
        trade_history.append(pnl)
        daily_pnl += pnl

        # ML öğrenme
        X_data.append(pos["features"])
        y_data.append(1 if pnl > 0 else 0)

        train_model()

        send(f"❌ CLOSE {sym} PnL %{round(pnl*100,2)}")

        del positions[sym]

# ========= MAIN =========
def run():
    for sym in symbols()[:100]:

        try:
            res = analyze(sym)

            if not res:
                continue

            side, price, features, score = res

            if sym not in positions:
                open_trade(sym, side, price, features, score)

            if sym in positions:
                manage(sym)

        except:
            continue

while True:
    run()
    time.sleep(60)
