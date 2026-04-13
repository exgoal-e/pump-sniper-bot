def report():
    global last_report_day

    now = datetime.now()

    if last_report_day == now.day:
        return

    if now.hour == 23:

        wins = sum(1 for x in trade_history if x > 0)
        total = len(trade_history)

        winrate = (wins/total*100) if total > 0 else 0
        pnl_total = sum(trade_history)*100

        coins = coin_analysis()

        top = coins[:3]
        worst = coins[-3:]

        top_text = "\n".join([f"{c} → %{round(w*100,1)}" for c,w in top])
        worst_text = "\n".join([f"{c} → %{round(w*100,1)}" for c,w in worst])

        ai_text = ai_report_comment(winrate)

        send(f"""
📊 GÜNLÜK RAPOR

Tarandı: {scan_count}
Sinyal: {signal_count}
Trade: {trade_count}

Winrate: %{round(winrate,2)}
PnL: %{round(pnl_total,2)}

🔥 En iyi coinler:
{top_text}

⚠️ En kötü coinler:
{worst_text}

🧠 AI Yorum:
{ai_text}
""")

        last_report_day = now.day
