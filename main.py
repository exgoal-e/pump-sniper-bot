from binance.client import Client
import pandas as pd
import time, os, requests
from datetime import datetime, UTC
import time, os, requests

# ========= CONFIG =========
CONFIG = {
    "RISK": 0.01,
    "RR": 2,
    "trail": 0.01,
    "vol_mult": 2.2,
    "max_open_trades": 5,
    "debug": True,
    "range_mode": False,
}

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("BINANCE_KEY")
API_SECRET = os.getenv("BINANCE_SECRET")

client = Client(API_KEY, API_SECRET)

positions = {}

POSITIONS_FILE = "positions.json"
STATS_FILE = "stats.json"

# ========= STATS =========
scan_count = 0
signal_count = 0
trade_count = 0
daily_pnl = 0

coin_stats = {}
pattern_stats = {"LONG": [], "SHORT": []}
hour_stats = {}
mode_stats = {"TREND": [], "RANGE": []}

debug_stats = {
    "MACD_fail": 0,
    "VOL_fail": 0,
    "BREAK_fail": 0,
    "STRONG_fail": 0
}

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

# ========= SAVE / LOAD =========
def save_positions():
    try:
        with open(POSITIONS_FILE, "w") as f:
            json.dump(positions, f)
    except:
        pass

def load_positions():
    global positions

    try:
        with open(POSITIONS_FILE, "r") as f:
            positions = json.load(f)
    except:
        positions = {}

def save_stats():
    data = {
        "scan_count": scan_count,
        "signal_count": signal_count,
        "trade_count": trade_count,
        "daily_pnl": daily_pnl,
        "coin_stats": coin_stats,
        "pattern_stats": pattern_stats,
        "hour_stats": hour_stats,
        "mode_stats": mode_stats,
        "last_report_day": last_report_day
    }

    try:
        with open(STATS_FILE, "w") as f:
            json.dump(data, f)
    except:
        pass

def load_stats():
    global scan_count, signal_count, trade_count
    global daily_pnl, coin_stats
    global pattern_stats, hour_stats
    global mode_stats, last_report_day

    try:
        with open(STATS_FILE, "r") as f:
            data = json.load(f)

            scan_count = data.get("scan_count", 0)
            signal_count = data.get("signal_count", 0)
            trade_count = data.get("trade_count", 0)
            daily_pnl = data.get("daily_pnl", 0)

            coin_stats = data.get("coin_stats", {})
            pattern_stats = data.get("pattern_stats", {"LONG": [], "SHORT": []})
            hour_stats = data.get("hour_stats", {})
            mode_stats = data.get("mode_stats", {"TREND": [], "RANGE": []})

            last_report_day = data.get("last_report_day", None)

    except:
        pass
        
# ========= INDICATORS =========
def macd(df):
    ema12 = df["c"].ewm(span=12).mean()
    ema26 = df["c"].ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9).mean()
    return macd_line, signal

def rsi(df, period=14):
    delta = df["c"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

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
    global signal_count, debug_stats

    df = klines(sym, "5m")
    if df is None or len(df) < 50:
        return None

    price = df["c"].iloc[-1]
    ma = df["c"].rolling(50).mean().iloc[-1]
    if pd.isna(ma):
        return None

    macd_line, signal_line = macd(df)
    if len(macd_line) < 2:
        return None

    macd_cross = macd_line.iloc[-2] < signal_line.iloc[-2] and macd_line.iloc[-1] > signal_line.iloc[-1]

    vol = df["v"].iloc[-1]
    avg = df["v"].rolling(20).mean().iloc[-1]
    if avg == 0 or pd.isna(avg):
        return None

    volSpike = vol > avg * CONFIG["vol_mult"]

    recent_high = df["h"].rolling(20).max().iloc[-2]
    recent_low = df["l"].rolling(20).min().iloc[-2]

    breakout = price > recent_high * 1.002  # erken giriş

    body = abs(df["c"].iloc[-1] - df["o"].iloc[-1])
    rng = df["h"].iloc[-1] - df["l"].iloc[-1]
    if rng == 0:
        return None

    strong = body > rng * 0.5

    # DEBUG
    if CONFIG["debug"]:
        if not macd_cross: debug_stats["MACD_fail"] += 1
        if not volSpike: debug_stats["VOL_fail"] += 1
        if not breakout: debug_stats["BREAK_fail"] += 1
        if not strong: debug_stats["STRONG_fail"] += 1

    # AI optimize
    if CONFIG["debug"]:
        if debug_stats["VOL_fail"] > 600:
            CONFIG["vol_mult"] = max(1.5, CONFIG["vol_mult"] - 0.1)
            debug_stats["VOL_fail"] = 0
            send(f"🤖 AI Optimize → VOL {CONFIG['vol_mult']}")

    # TREND
    if macd_cross and volSpike and breakout and price > ma:
        signal_count += 1
        return "LONG", df, "TREND"

    # RANGE
    if CONFIG["range_mode"]:

        # trend varsa range yok
        if price > ma:
            return None

        r = rsi(df)
        if r is None or len(r) < 2:
            return None

        near_low = price <= recent_low * 1.01
        near_high = price >= recent_high * 0.99

        bullish = df["c"].iloc[-1] > df["o"].iloc[-1] and df["c"].iloc[-2] > df["o"].iloc[-2]
        bearish = df["c"].iloc[-1] < df["o"].iloc[-1] and df["c"].iloc[-2] < df["o"].iloc[-2]

        if near_low and r.iloc[-1] < 30 and bullish:
            signal_count += 1
            return "LONG", df, "RANGE"

        if near_high and r.iloc[-1] > 70 and bearish:
            signal_count += 1
            return "SHORT", df, "RANGE"

    return None

# ========= OPEN =========
def open_trade(sym, side, df, mode):
    global trade_count, hour_stats

    if len(positions) >= CONFIG["max_open_trades"]:
        return

    price = df["c"].iloc[-1]
    sl = df["l"].iloc[-2] if side == "LONG" else df["h"].iloc[-2]

    risk = abs(price - sl)
    if risk == 0:
        return

    tp1 = price + risk * 0.5 if side == "LONG" else price - risk * 0.5
    tp2 = price + risk * 0.8 if side == "LONG" else price - risk * 0.8

    positions[sym] = {
        "side": side,
        "entry": price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp1_hit": False,
        "tp2_hit": False,
        "peak": price,
        "mode": mode
    }

    trade_count += 1
    hour = datetime.now(UTC).hour
    hour_stats[hour] = hour_stats.get(hour, 0) + 1

    send(f"""
🚀 {side} {sym} ({mode})

💰 Entry: {round(price,4)}

━━━━━━━━━━━━━━━
🎯 TP LEVELS
→ TP1: {round(tp1,4)} (%50)
→ TP2: {round(tp2,4)} (%30)
→ Runner: ACTIVE 🔥
━━━━━━━━━━━━━━━

📉 Trailing: TP2 sonrası aktif
🛑 SL: {round(sl,4)}
""")

# ========= MANAGE =========
def manage(sym):
    global daily_pnl, coin_stats, pattern_stats, mode_stats

    pos = positions[sym]

    df = klines(sym, "5m")
    if df is None:
        return

    price = df["c"].iloc[-1]

    pnl = (price - pos["entry"]) / pos["entry"] if pos["side"]=="LONG" else (pos["entry"] - price) / pos["entry"]

    # ========= TP1 =========
    if not pos["tp1_hit"]:
        if (pos["side"]=="LONG" and price >= pos["tp1"]) or (pos["side"]=="SHORT" and price <= pos["tp1"]):

            pos["tp1_hit"] = True

            # SL -> ENTRY
            pos["sl"] = pos["entry"]

            send(f"💰 TP1 {sym} → SL moved to ENTRY")
            save_positions()

    # ========= TP2 =========
    if not pos["tp2_hit"]:
        if (pos["side"]=="LONG" and price >= pos["tp2"]) or (pos["side"]=="SHORT" and price <= pos["tp2"]):

            pos["tp2_hit"] = True

            # SL -> TP1
            pos["sl"] = pos["tp1"]

            send(f"💰 TP2 {sym} → SL moved to TP1")
            save_positions()

    # ========= STOP LOSS =========
    if (pos["side"]=="LONG" and price <= pos["sl"]) or (pos["side"]=="SHORT" and price >= pos["sl"]):

        daily_pnl += pnl

        coin_stats.setdefault(sym, []).append(pnl)
        pattern_stats[pos["side"]].append(pnl)
        mode_stats[pos["mode"]].append(pnl)

        send(f"🛑 SL HIT {sym} | PnL %{round(pnl*100,2)}")

        del positions[sym]
        save_positions()
        save_stats()
        return

    # ========= TRAILING =========
    if pos["tp2_hit"]:

        if price > pos["peak"]:
            pos["peak"] = price

        if price < pos["peak"] * (1 - CONFIG["trail"]):

            daily_pnl += pnl

            coin_stats.setdefault(sym, []).append(pnl)
            pattern_stats[pos["side"]].append(pnl)
            mode_stats[pos["mode"]].append(pnl)

            send(f"❌ TRAILING EXIT {sym} %{round(pnl*100,2)}")

            del positions[sym]
            save_positions()
            save_stats()

# ========= REPORT =========
def send_daily_report():
    global last_report_day

    now = datetime.now(UTC)

    if not (now.hour == 23 and now.minute < 10):
        return

    if last_report_day == now.day:
        return

    last_report_day = now.day

    total = sum(len(v) for v in coin_stats.values()) or 1
    wins = sum(sum(1 for x in v if x > 0) for v in coin_stats.values())
    winrate = wins / total * 100

    best = sorted(coin_stats.items(), key=lambda x: sum(x[1])/len(x[1]) if x[1] else 0, reverse=True)[:3]
    best_text = "\n".join([f"{c} → %{round(sum(v)/len(v)*100,1)}" for c,v in best if v])

    best_hour = max(hour_stats, key=hour_stats.get) if hour_stats else "N/A"

    mode_text = ""
    for m, data in mode_stats.items():
        if data:
            wr = sum(1 for x in data if x>0)/len(data)*100
            avg = sum(data)/len(data)*100
            mode_text += f"{m} → Winrate: %{round(wr,1)} | PnL: %{round(avg,2)}\n"

    open_text = ""
    if positions:
        open_text += f"\n📊 AÇIK POZİSYONLAR ({len(positions)})\n"
        for sym, pos in positions.items():
            try:
                df = klines(sym, "5m")
                if df is None:
                    continue
                price = df["c"].iloc[-1]
                pnl = (price - pos["entry"]) / pos["entry"] if pos["side"]=="LONG" else (pos["entry"] - price) / pos["entry"]

                tp_status = ""
                if pos["tp1_hit"]: tp_status += "TP1✅ "
                if pos["tp2_hit"]: tp_status += "TP2✅ "

                open_text += f"{sym} → %{round(pnl*100,2)} {tp_status}\n"
            except:
                continue
                except:
            continue

    save_positions()
    save_stats()
    else:
        open_text = "\n📊 Açık pozisyon yok"

    send(f"""
save_positions()
save_stats()
📊 GÜNLÜK RAPOR

Tarandı: {scan_count}
Sinyal: {signal_count}
Trade: {trade_count}

Winrate: %{round(winrate,2)}
PnL: %{round(daily_pnl*100,2)}

🔥 En iyi coinler:
{best_text}

⏱ En iyi saat:
{best_hour}:00

🧠 MODE ANALİZ
{mode_text}
{open_text}
""")

# ========= MAIN =========
def run():
    global scan_count

    for sym in symbols()[:100]:
        scan_count += 1

        try:
            res = analyze(sym)
            if not res:
                continue

            side, df, mode = res

            if sym not in positions:
                open_trade(sym, side, df, mode)

            if sym in positions:
                manage(sym)

        except:
            continue

load_positions()
load_stats()

while True:
    run()
    send_daily_report()
    time.sleep(60)
