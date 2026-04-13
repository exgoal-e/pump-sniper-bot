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

LIVE = False  # TRUE yaparsan gerçek işlem açar

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("BINANCE_KEY")
API_SECRET = os.getenv("BINANCE_SECRET")

client = Client(API_KEY, API_SECRET)

positions = {}
trade_history = []
daily_pnl = 0

# ========= ML =========
model = RandomForestClassifier(n_estimators=50)
X_data, y_data = [], []

def train_model():
    if len(X_data) > 50:
        try:
            model.fit(X_data, y_data)
        except:
            pass

def predict(features):
    try:
        if len(X_data) < 50:
            return 0.5
        return model.predict_proba([features])[0][1]
    except:
        return 0.5

# ========= TELEGRAM =========
def send(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg}
        )
    except:
        pass

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
    try:
        return [s['symbol'] for s in client.futures_exchange_info()['symbols'] if s['quoteAsset']=="USDT"]
    except:
        return []

# ========= SAFE FEATURE =========
def safe_features(df):
    try:
        price = df["c"].iloc[-1]
        ma = df["c"].rolling(20).mean().iloc[-1]
        vol = df["v"].iloc[-1]
        avg = df["v"].rolling(20).mean().iloc[-1]
        momentum = df["c"].iloc[-1] - df["c"].iloc[-2]

        # SAFE DIVISION
        ma = ma if ma and not pd.isna(ma) else price
        avg = avg if avg and not pd.isna(avg) else vol if vol != 0 else 1

        ratio_price = price / ma if ma != 0 else 1
        ratio_vol = vol / avg if avg != 0 else 1

        # CLEAN
        if np.isnan(ratio_price) or np.isinf(ratio_price):
            ratio_price = 1
        if np.isnan(ratio_vol) or np.isinf(ratio_vol):
            ratio_vol = 1

        return [ratio_price, ratio_vol, momentum]

    except:
        return None

# ========= ANALYZE =========
def analyze(sym):
    df = klines(sym, "5m")
    if df is None or len(df) < 30:
        return None

    features = safe_features(df)
    if features is None:
        return None

    score = predict(features)

    if score < 0.6:
        return None

    momentum = features[2]
    side = "LONG" if momentum > 0 else "SHORT"

    price = df["c"].iloc[-1]

    return side, price, features, score

# ========= PORTFOLIO =========
def can_trade():
    if len(positions) >= CONFIG["max_positions"]:
        return False
    if daily_pnl < CONFIG["daily_dd"]:
        return False
    return True

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

# ========= OPEN =========
def open_trade(sym, side, price, features, score):
    if not can_trade():
        return

    sl = price * (0.99 if side=="LONG" else 1.01)
    risk = abs(price - sl)
    tp = price + risk*CONFIG["RR"] if side=="LONG" else price - risk*CONFIG["RR"]

    qty = 10

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
    df = klines(sym, "5m")
    if df is None:
        return

    price = df["c"].iloc[-1]
    entry = pos["entry"]

    pnl = (price-entry)/entry if pos["side"]=="LONG" else (entry-price)/entry

    if abs(pnl) > 0.01:
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
    syms = symbols()[:100]

    for sym in syms:
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
    try:
        run()
        time.sleep(60)
    except:
        time.sleep(60)
