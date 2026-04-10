import requests
import pandas as pd
import numpy as np
import time

TOKEN = "TELEGRAM_BOT_TOKEN"
CHAT_ID = "CHAT_ID"

sent_cache = {}

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

    df["o"] = df["o"].astype(float)
    df["h"] = df["h"].astype(float)
    df["l"] = df["l"].astype(float)
    df["c"] = df["c"].astype(float)
    df["v"] = df["v"].astype(float)

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

# ================= SMART MONEY (YENİ) =================
def smart_money(df):
    # hacim artışı + mum gücü
    vol = df["v"].iloc[-1]
    vol_prev = df["v"].iloc[-2]

    body = abs(df["c"].iloc[-1] - df["o"].iloc[-1])
    spread = df["h"].iloc[-1] - df["l"].iloc[-1]

    strong_candle = body > spread * 0.6
    vol_increase = vol > vol_prev * 1.3

    return strong_candle and vol_increase

# ================= ERKEN SİNYAL (YENİ) =================
def early_breakout(df):
    highest = df["h"].rolling(20).max()

    # klasik breakout değil → yaklaşma
    near_break = df["c"].iloc[-1] > highest.iloc[-2] * 0.995

    # momentum artıyor mu?
    momentum_build = df["c"].iloc[-1] > df["c"].iloc[-2]

    return near_break and momentum_build

# ================= ANALYZE =================
def analyze(symbol):
    df = get_klines(symbol)
    df1h = get_klines(symbol, "1h")

    df["ma"] = df["c"].rolling(50).mean()
    df["vol_avg"] = df["v"].rolling(20).mean()
    df["hist"] = macd(df)
    df["rsi"] = rsi(df)

    # ===== BASE (DEĞİŞMEDİ) =====
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

    # ===== YENİ GÜÇLENDİRME =====
    smart = smart_money(df)
    early = early_breakout(df)

    # ===== FINAL =====
    longSignal = (
        volSpike and
        (breakout or early) and
        trendUp and
        macdBull and
        rsiLong and
        noFake and
        htfBull and
        smart
    )

    shortSignal = (
        volSpike and
        (breakdown) and
        trendDown and
        macdBear and
        rsiShort and
        noFake and
        htfBear and
        smart
    )

    if longSignal or shortSignal:
        price = df["c"].iloc[-1]

        if longSignal:
            sl = price * 0.99
            tp = price * 1.025
            direction = "🚀 LONG"
        else:
            sl = price * 1.01
            tp = price * 0.975
            direction = "🔻 SHORT"

        # SCORE (upgrade)
        score = 0
        if volSpike: score += 20
        if breakout: score += 20
        if early: score += 10
        if macdBull or macdBear: score += 15
        if smart: score += 20
        if htfBull or htfBear: score += 15

        return {
            "symbol": symbol,
            "score": score,
            "msg": f"""
{direction} SNIPER

Coin: {symbol}
Fiyat: {price:.6f}

SL: {sl:.6f}
TP: {tp:.6f}

Score: {score}/100
            """
        }

    return None

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

# LOOP
while True:
    run()
    time.sleep(60)
