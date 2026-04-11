import requests
import pandas as pd
import numpy as np
import time
import os

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

sent_cache = {}
trade_log = []

# ================= TELEGRAM =================
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg})

# ================= DATA =================
def get_symbols():
    url = "https://api.binance.com/api/v3/exchangeInfo"
    data = requests.get(url).json()
    return [s['symbol'] for s in data['symbols'] if s['quoteAsset'] == 'USDT']

def get_klines(symbol, interval="5m", limit=120):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    data = requests.get(url).json()

    df = pd.DataFrame(data)
    df.columns = ["time","o","h","l","c","v","_","_","_","_","_","_"]

    for col in ["o","h","l","c","v"]:
        df[col] = df[col].astype(float)

    return df

# ================= INDICATORS =================
def macd(df):
    exp1 = df["c"].ewm(span=12).mean()
    exp2 = df["c"].ewm(span=26).mean()
    macd_line = exp1 - exp2
    signal = macd_line.ewm(span=9).mean()
    hist = macd_line - signal
    return hist

def rsi(df, period=14):
    delta = df["c"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# ================= SMART MONEY =================
def smart_money(df):
    vol = df["v"].iloc[-1]
    vol_prev = df["v"].iloc[-2]

    body = abs(df["c"].iloc[-1] - df["o"].iloc[-1])
    spread = df["h"].iloc[-1] - df["l"].iloc[-1]

    strong = body > spread * 0.6
    vol_up = vol > vol_prev * 1.3

    return strong and vol_up

# ================= EARLY =================
def early_breakout(df):
    highest = df["h"].rolling(20).max()
    near = df["c"].iloc[-1] > highest.iloc[-2] * 0.995
    momentum = df["c"].iloc[-1] > df["c"].iloc[-2]
    return near and momentum

# ================= ANALYZE =================
def analyze(symbol):
    df = get_klines(symbol)
    df1h = get_klines(symbol, "1h")

    df["ma"] = df["c"].rolling(50).mean()
    df["vol_avg"] = df["v"].rolling(20).mean()
    df["hist"] = macd(df)
    df["rsi"] = rsi(df)

    volSpike = df["v"].iloc[-1] > df["vol_avg"].iloc[-1] * 2

    highest = df["h"].rolling(20).max()
    lowest = df["l"].rolling(20).min()

    breakout = df["c"].iloc[-1] > highest.iloc[-2]
    breakdown = df["c"].iloc[-1] < lowest.iloc[-2]

    trendUp = df["c"].iloc[-1] > df["ma"].iloc[-1]
    trendDown = df["c"].iloc[-1] < df["ma"].iloc[-1]

    macdBull = df["hist"].iloc[-1] > df["hist"].iloc[-2] and df["hist"].iloc[-1] > 0
    macdBear = df["hist"].iloc[-1] < df["hist"].iloc[-2] and df["hist"].iloc[-1] < 0

    rsiLong = df["rsi"].iloc[-1] < 70
    rsiShort = df["rsi"].iloc[-1] > 30

    body = abs(df["c"].iloc[-1] - df["o"].iloc[-1])
    wick = df["h"].iloc[-1] - max(df["o"].iloc[-1], df["c"].iloc[-1])
    noFake = body > wick * 0.7

    # HTF
    ma1h = df1h["c"].rolling(50).mean()
    htfBull = df1h["c"].iloc[-1] > ma1h.iloc[-1]
    htfBear = df1h["c"].iloc[-1] < ma1h.iloc[-1]

    smart = smart_money(df)
    early = early_breakout(df)

    # SCORE
    score = 0
    if volSpike: score += 20
    if breakout or breakdown: score += 20
    if early: score += 10
    if smart: score += 20
    if macdBull or macdBear: score += 15
    if htfBull or htfBear: score += 15

    price = df["c"].iloc[-1]

    # ===== EARLY =====
    if early and not breakout and trendUp and smart:
        msg = f"""
🟡 EARLY SETUP

Coin: {symbol}
Entry: {price:.6f}

Hazırlık aşaması ⚠️
Breakout gelirse pump başlar

Score: {score}/100
"""
        return {"symbol": symbol, "score": score-5, "msg": msg}

    # ===== SNIPER =====
    longSignal = all([volSpike, breakout, trendUp, macdBull, rsiLong, noFake, htfBull, smart])
    shortSignal = all([volSpike, breakdown, trendDown, macdBear, rsiShort, noFake, htfBear, smart])

    if longSignal or shortSignal:

        if longSignal:
            direction = "🚀 LONG"
            sl = price * 0.99
            tp1 = price * 1.01
            tp2 = price * 1.03
        else:
            direction = "🔻 SHORT"
            sl = price * 1.01
            tp1 = price * 0.99
            tp2 = price * 0.97

        # ETA
        if score >= 80:
            eta = "5-15 min"
            speed = "FAST"
        elif score >= 60:
            eta = "15-45 min"
            speed = "MEDIUM"
        else:
            eta = "30-90 min"
            speed = "SLOW"

        # momentum
        if smart and volSpike:
            momentum = "STRONG"
        elif macdBull or macdBear:
            momentum = "NORMAL"
        else:
            momentum = "WEAK"

        msg = f"""
{direction} SNIPER

Coin: {symbol}
Entry: {price:.6f}

TP1: {tp1:.6f}
TP2: {tp2:.6f}

SL: {sl:.6f}

ETA: {eta}
Type: {speed}
Momentum: {momentum}

Score: {score}/100
"""

        # trade log (winrate için)
        trade_log.append({
            "symbol": symbol,
            "entry": price,
            "tp1": tp1,
            "tp2": tp2,
            "sl": sl,
            "time": time.time()
        })

        return {"symbol": symbol, "score": score, "msg": msg}

    return None

# ================= WINRATE =================
def check_results():
    global trade_log
    new_log = []

    for t in trade_log:
        try:
            df = get_klines(t["symbol"])
            high = df["h"].iloc[-1]
            low = df["l"].iloc[-1]

            if high >= t["tp1"]:
                print(f"WIN TP1: {t['symbol']}")
            elif low <= t["sl"]:
                print(f"LOSS: {t['symbol']}")
            else:
                new_log.append(t)
        except:
            new_log.append(t)

    trade_log = new_log

# ================= MAIN =================
def run():
    symbols = get_symbols()
    signals = []

    for sym in symbols:
        try:
            res = analyze(sym)
            if res:
                signals.append(res)
            time.sleep(0.08)
        except:
            continue

    # en iyi 3
    signals = sorted(signals, key=lambda x: x["score"], reverse=True)[:3]

    for s in signals:
        sym = s["symbol"]

        if sym in sent_cache and time.time() - sent_cache[sym] < 1800:
            continue

        send_telegram(s["msg"])
        sent_cache[sym] = time.time()

    check_results()

# LOOP
while True:
    run()
    time.sleep(60)
