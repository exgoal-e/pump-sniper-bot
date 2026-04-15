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
    "min_pos_usdt": 5,
    "scale_trigger": 0.005,
    "max_scale": 2
}

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("BINANCE_KEY")
API_SECRET = os.getenv("BINANCE_SECRET")

client = Client(API_KEY, API_SECRET)

positions = {}

# ========= STATS =========
scan_count = 0
signal_count = 0
trade_count = 0
daily_pnl = 0

coin_stats = {}
hour_stats = {}
pattern_stats = {}

last_report_day = None

# ========= TELEGRAM =========
def send(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg}
        )
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

# ========= POSITION SIZE =========
def calc_qty(entry, sl, balance):
    risk_amount = balance * CONFIG["RISK"]
    sl_dist = abs(entry - sl)
    if sl_dist == 0:
        return 0, 0

    size = risk_amount / sl_dist
    pos_usdt = size * entry

    pos_usdt = max(CONFIG["min_pos_usdt"], min(CONFIG["max_pos_usdt"], pos_usdt))

    return round(pos_usdt / entry, 3), round(pos_usdt,2)

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

# ========= ANALYZE =========
def analyze(sym):
    global signal_count

    df = klines(sym, "5m")
    if df is None:
        return None

    price = df["c"].iloc[-1]
    ma = df["c"].rolling(50).mean().iloc[-1]

    if pd.isna(ma):
        return None

    side = "LONG" if price > ma else "SHORT"

    vol = df["v"].iloc[-1]
    avg = df["v"].rolling(20).mean().iloc[-1]

    if avg == 0 or pd.isna(avg):
        return None

    volSpike = vol > avg * CONFIG["vol_mult"]
    momentum = df["c"].iloc[-1] - df["c"].iloc[-2]

    score = 0
    if volSpike: score += 2
    if momentum != 0: score += 1

    if score < 2:
        return None

    confidence = min(95, score * 30)

    signal_count += 1

    return side, df, confidence

# ========= OPEN =========
def open_trade(sym, side, df, confidence):
    global trade_count, hour_stats

    price = df["c"].iloc[-1]
    sl = df["l"].iloc[-2] if side=="LONG" else df["h"].iloc[-2]

    balance = get_balance()
    qty, pos_usdt = calc_qty(price, sl, balance)

    risk = abs(price - sl)

    tp1 = price + risk*0.5 if side=="LONG" else price - risk*0.5
    tp2 = price + risk*0.8 if side=="LONG" else price - risk*0.8
    tp3 = price + risk*1.3 if side=="LONG" else price - risk*1.3

    rr = round((tp3 - price)/risk,2) if side=="LONG" else round((price - tp3)/risk,2)

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
        "qty": qty,
        "scale": 0
    }

    trade_count += 1

    hour = datetime.utcnow().hour
    hour_stats[hour] = hour_stats.get(hour, 0) + 1

    send(f"""
🚀 {side} {sym} (SNIPER)

💰 Entry: {round(price,4)}
📦 Qty: {qty} (≈ {pos_usdt} USDT)

📊 Risk: {CONFIG["RISK"]*100:.2f}% | Leverage: x5
⚖️ R:R: 1:{rr}
🎯 Confidence: {confidence}/100

──────────────
🎯 TP LEVELS
TP1: {round(tp1,4)} → CLOSE 50%
TP2: {round(tp2,4)} → CLOSE 30%
TP3: {round(tp3,4)} → RUN

🛑 STOP LOSS
SL: {round(sl,4)}

──────────────
🧠 TRADE INFO
Mode: Sniper AI
Strategy: Momentum + Volume
""")

# ========= MANAGE =========
def manage(sym):
    global daily_pnl, coin_stats, pattern_stats

    pos = positions[sym]
    df = klines(sym, "5m")
    if df is None:
        return

    price = df["c"].iloc[-1]
    entry = pos["entry"]

    pnl = (price-entry)/entry if pos["side"]=="LONG" else (entry-price)/entry

    # TP1
    if not pos["tp1_hit"]:
        if (pos["side"]=="LONG" and price >= pos["tp1"]) or (pos["side"]=="SHORT" and price <= pos["tp1"]):
            pos["tp1_hit"] = True
            pos["qty"] *= 0.5
            send(f"💰 TP1 HIT {sym}")

    # TP2
    if pos["tp1_hit"] and not pos["tp2_hit"]:
        if (pos["side"]=="LONG" and price >= pos["tp2"]) or (pos["side"]=="SHORT" and price <= pos["tp2"]):
            pos["tp2_hit"] = True
            pos["qty"] *= 0.7
            send(f"💰 TP2 HIT {sym}")

    # SCALE
    if pnl > CONFIG["scale_trigger"] and pos["scale"] < CONFIG["max_scale"]:
        pos["scale"] += 1
        send(f"➕ SCALE IN {sym}")

    # TRAILING EXIT
    exit_trade = False

    if pos["side"]=="LONG":
        if price > pos["peak"]:
            pos["peak"] = price
        if price < pos["peak"]*(1-CONFIG["trail"]):
            exit_trade = True

    if pos["side"]=="SHORT":
        if price < pos["peak"]:
            pos["peak"] = price
        if price > pos["peak"]*(1+CONFIG["trail"]):
            exit_trade = True

    if exit_trade:
        daily_pnl += pnl

        # coin stats
        if sym not in coin_stats:
            coin_stats[sym] = {"win":0, "total":0}
        coin_stats[sym]["total"] += 1
        if pnl > 0:
            coin_stats[sym]["win"] += 1

        # pattern stats (simple)
        pattern = pos["side"]
        if pattern not in pattern_stats:
            pattern_stats[pattern] = {"win":0, "total":0}
        pattern_stats[pattern]["total"] += 1
        if pnl > 0:
            pattern_stats[pattern]["win"] += 1

        send(f"❌ EXIT {sym} %{round(pnl*100,2)}")
        del positions[sym]

# ========= DAILY REPORT =========
def send_daily_report():
    global last_report_day

    now = datetime.utcnow()

    if now.hour != 23:
        return

    if last_report_day == now.day:
        return

    last_report_day = now.day

    total_trades = sum(v["total"] for v in coin_stats.values()) or 1
    total_wins = sum(v["win"] for v in coin_stats.values())
    winrate = (total_wins / total_trades) * 100

    best = sorted(
        coin_stats.items(),
        key=lambda x: (x[1]["win"]/x[1]["total"]) if x[1]["total"] else 0,
        reverse=True
    )[:3]

    best_text = "\n".join([
        f"{c} → %{round((d['win']/d['total'])*100,1)}"
        for c, d in best if d["total"]
    ]) or "Yok"

    worst = sorted(
        pattern_stats.items(),
        key=lambda x: (x[1]["win"]/x[1]["total"]) if x[1]["total"] else 1
    )[:3]

    worst_text = "\n".join([
        f"{p} → %{round((d['win']/d['total'])*100,1)}"
        for p, d in worst if d["total"]
    ]) or "Yok"

    best_hour = max(hour_stats, key=hour_stats.get) if hour_stats else "N/A"

    ai_comment = "Stabil"
    if winrate > 60:
        ai_comment = "🔥 Sistem güçlü"
    elif winrate < 45:
        ai_comment = "⚠️ Filtre artır"

    send(f"""
📊 GÜNLÜK RAPOR

Tarandı: {scan_count}
Sinyal: {signal_count}
Trade: {trade_count}

Winrate: %{round(winrate,2)}
PnL: %{round(daily_pnl*100,2)}

🔥 En iyi coinler:
{best_text}

❌ En kötü pattern:
{worst_text}

⏱ En iyi saat:
{best_hour}:00

🧠 AI Yorum:
{ai_comment}
""")

# ========= MAIN =========
def run():
    global scan_count

    for sym in symbols()[:80]:
        scan_count += 1

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
    send_daily_report()
    time.sleep(60)
