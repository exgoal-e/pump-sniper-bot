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
    "max_positions": 3,
    "daily_dd": -0.03,
    "scan_limit": 100,
    "tf": "5m",
    "sleep": 30
}

LIVE = False

# ========= ENV =========
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("BINANCE_KEY")
API_SECRET = os.getenv("BINANCE_SECRET")

client = Client(API_KEY, API_SECRET)

# ========= STATE =========
positions = {}
trade_history = []
daily_pnl = 0

# ========= ML =========
model = RandomForestClassifier(n_estimators=50)
X_data, y_data = [], []

# ========= TELEGRAM =========
def send(msg):
    try:
        if not TOKEN or not CHAT_ID:
            return
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg}
        )
    except Exception as e:
        print("TG ERR:", e)

# ========= BINANCE DATA =========
def symbols():
    try:
        data = client.futures_exchange_info()['symbols']
        return [s['symbol'] for s in data if s['quoteAsset'] == "USDT"]
    except Exception as e:
        print("SYMBOL ERR:", e)
        return []

def klines(sym):
    try:
        k = client.futures_klines(symbol=sym, interval=CONFIG["tf"], limit=100)
        df = pd.DataFrame(k)
        df.columns = ["t","o","h","l","c","v","_","_","_","_","_","_"]
        df[["o","h","l","c","v"]] = df[["o","h","l","c","v"]].astype(float)
        return df
    except:
        return None

# ========= FEATURES =========
def features(df):
    try:
        price = df["c"].iloc[-1]
        ma = df["c"].rolling(20).mean().iloc[-1]
        vol = df["v"].iloc[-1]
        avg = df["v"].rolling(20).mean().iloc[-1]
        mom = df["c"].iloc[-1] - df["c"].iloc[-2]

        ma = ma if not np.isnan(ma) else price
        avg = avg if not np.isnan(avg) and avg != 0 else 1

        return [
            price / ma if ma != 0 else 1,
            vol / avg,
            mom
        ]
    except:
        return None

# ========= ML =========
def train():
    try:
        if len(X_data) > 50:
            model.fit(X_data, y_data)
    except:
        pass

def predict(x):
    try:
        if len(X_data) < 50:
            return 0.5
        return model.predict_proba([x])[0][1]
    except:
        return 0.5

# ========= RISK =========
def can_trade():
    if len(positions) >= CONFIG["max_positions"]:
        return False
    if daily_pnl < CONFIG["daily_dd"]:
        return False
    return True

# ========= ORDER =========
def order(sym, side, qty):
    if not LIVE:
        return
    try:
        client.futures_create_order(
            symbol=sym,
            side="BUY" if side == "LONG" else "SELL",
            type="MARKET",
            quantity=qty
        )
    except Exception as e:
        print("ORDER ERR:", e)

# ========= TRADE =========
def open_trade(sym, side, price, f, score):
    if not can_trade():
        return

    sl = price * (0.99 if side == "LONG" else 1.01)
    risk = abs(price - sl)
    tp = price + risk * CONFIG["RR"] if side == "LONG" else price - risk * CONFIG["RR"]

    qty = 10

    order(sym, side, qty)

    positions[sym] = {
        "side": side,
        "entry": price,
        "sl": sl,
        "tp": tp,
        "features": f
    }

    send(f"""🚀 {sym} {side}
Entry: {price}
TP: {tp}
SL: {sl}
Score: {round(score*100,2)}%""")

# ========= CLOSE =========
def close_trade(sym, pnl):
    global daily_pnl

    trade_history.append(pnl)
    daily_pnl += pnl

    pos = positions[sym]
    X_data.append(pos["features"])
    y_data.append(1 if pnl > 0 else 0)

    train()

    send(f"❌ CLOSE {sym} PnL %{round(pnl*100,2)}")

    del positions[sym]

# ========= MANAGE =========
def manage(sym):
    try:
        pos = positions[sym]
        df = klines(sym)
        if df is None:
            return

        price = df["c"].iloc[-1]
        entry = pos["entry"]

        pnl = (price - entry) / entry if pos["side"] == "LONG" else (entry - price) / entry

        if abs(pnl) > 0.01:
            close_trade(sym, pnl)

    except Exception as e:
        print("MANAGE ERR:", e)

# ========= ANALYZE =========
def analyze(sym):
    df = klines(sym)
    if df is None or len(df) < 30:
        return

    f = features(df)
    if f is None:
        return

    score = predict(f)

    if score < 0.6:
        return

    side = "LONG" if f[2] > 0 else "SHORT"
    price = df["c"].iloc[-1]

    if sym not in positions:
        open_trade(sym, side, price, f, score)
    else:
        manage(sym)

# ========= RUN =========
def run():
    syms = symbols()[:CONFIG["scan_limit"]]

    for s in syms:
        try:
            analyze(s)
        except Exception as e:
            print("RUN ERR:", e)

# ========= MAIN LOOP =========
def main():
    print("🚀 BOT STARTED")

    send("🚀 Bot Started")

    while True:
        try:
            run()
            time.sleep(CONFIG["sleep"])
        except Exception as e:
            print("LOOP ERR:", e)
            time.sleep(5)

# ========= ENTRY =========
if __name__ == "__main__":
    main()
