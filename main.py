from datetime import datetime, timezone
import os
import sqlite3
from typing import Optional
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import requests

app = FastAPI()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DB_FILE = "trading_registry.db"

# ----------------- DATABASE SETUP -----------------


def init_db():
  with sqlite3.connect(DB_FILE) as conn:
    conn.execute("""
            CREATE TABLE IF NOT EXISTS active_levels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT,
                timeframe TEXT,
                level_type TEXT,
                price_high REAL,
                price_low REAL,
                bias TEXT,
                status TEXT DEFAULT 'PENDING',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
    conn.execute("""
            CREATE TABLE IF NOT EXISTS desk_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT,
                event_type TEXT,
                details TEXT,
                verdict TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)


init_db()

# ----------------- NEWS & CALENDAR TOOL -----------------


def check_economic_news_hazard(currency: str = "USD") -> dict:
  url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
  try:
    res = requests.get(url, timeout=5)
    events = res.json()
  except Exception as e:
    return {"status": "CLEAR", "reason": f"Feed unavailable ({e})"}

  now_utc = datetime.now(timezone.utc)
  imminent = []
  for ev in events:
    if (
        ev.get("country") == currency
        and ev.get("impact") == "High"
        and ev.get("date")
    ):
      try:
        ev_time = datetime.fromisoformat(ev["date"]).astimezone(timezone.utc)
        delta = (ev_time - now_utc).total_seconds() / 60
        if -30 <= delta <= 30:
          imminent.append(f"{ev.get('title')} ({int(abs(delta))}m away)")
      except Exception:
        continue

  if imminent:
    return {
        "status": "HAZARDOUS",
        "reason": f"Red-Folder Events near: {', '.join(imminent)}",
    }
  return {"status": "CLEAR", "reason": "No high-impact USD events nearby."}


# ----------------- TELEGRAM DISPATCHER -----------------


def send_telegram(text: str):
  if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("[Telegram] Bot token or Chat ID is missing.")
    return
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  try:
    resp = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
        timeout=8,
    )
    print(f"[Telegram Response] {resp.status_code}: {resp.text}")
  except Exception as e:
    print(f"[Telegram Exception] {e}")


# ----------------- LIVE WEB DASHBOARD -----------------


@app.get("/", response_class=HTMLResponse)
def live_dashboard():
  with sqlite3.connect(DB_FILE) as conn:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, asset, timeframe, level_type, price_high, price_low, bias,"
        " status, created_at FROM active_levels ORDER BY id DESC LIMIT 20"
    )
    levels = cursor.fetchall()
    cursor.execute(
        "SELECT id, asset, event_type, details, verdict, timestamp FROM"
        " desk_logs ORDER BY id DESC LIMIT 10"
    )
    logs = cursor.fetchall()

  rows = ""
  for l in levels:
    color = (
        "#00E676"
        if l[7] == "PENDING"
        else ("#FF5252" if l[7] == "INVALIDATED" else "#FFD600")
    )
    rows += f"""
        <tr>
            <td><b>{l[1]}</b></td>
            <td><span style="background:#2A2E39; padding:2px 6px; border-radius:3px;">{l[2]}</span></td>
            <td>{l[3]}</td>
            <td>{l[5]:.2f} - {l[4]:.2f}</td>
            <td style="color:{'#26a69a' if 'BULL' in l[6] or 'DEMAND' in l[6] else '#ef5350'}; font-weight:600;">{l[6]}</td>
            <td><span style="border:1px solid {color}; color:{color}; padding:2px 6px; border-radius:4px; font-size:11px;">{l[7]}</span></td>
            <td style="color:#787B86; font-size:12px;">{l[8]}</td>
        </tr>
        """

  log_cards = ""
  for log in logs:
    log_cards += f"""
        <div style="background:#1E222D; border-left:4px solid #2962FF; padding:12px; margin-bottom:10px; border-radius:4px;">
            <div style="display:flex; justify-content:space-between; font-size:12px; color:#787B86;">
                <span><b>{log[1]}</b> · {log[2]}</span>
                <span>{log[5]}</span>
            </div>
            <div style="margin:6px 0; color:#D1D4DC; font-size:13px;">{log[3]}</div>
            <pre style="background:#131722; padding:8px; border-radius:4px; color:#00E676; font-size:12px; white-space:pre-wrap; margin:0;">{log[4]}</pre>
        </div>
        """

  return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Trading Desk Monitor</title>
        <meta http-equiv="refresh" content="10">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: -apple-system, sans-serif; background: #131722; color: #D1D4DC; margin: 0; padding: 20px; }}
            .card {{ background: #1E222D; border: 1px solid #2A2E39; border-radius: 8px; padding: 16px; margin-bottom: 20px; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #2A2E39; font-size: 13px; }}
            th {{ color: #787B86; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div style="max-width:1100px; margin:0 auto;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
                <h2 style="margin:0;">Institutional Desk Monitor</h2>
                <span style="color:#787B86; font-size:13px;">● Live Online (Auto-refresh 10s)</span>
            </div>
            <div class="card">
                <h3 style="margin-top:0;">Tracked Levels Registry</h3>
                <div style="overflow-x:auto;">
                    <table>
                        <thead><tr><th>Asset</th><th>TF</th><th>Level Type</th><th>Range</th><th>Expected Bias</th><th>Status</th><th>Logged</th></tr></thead>
                        <tbody>{rows if rows else '<tr><td colspan="7" style="text-align:center; color:#787B86;">Waiting for indicator alerts...</td></tr>'}</tbody>
                    </table>
                </div>
            </div>
            <div class="card">
                <h3 style="margin-top:0;">AI Desk Execution Logs</h3>
                <div>{log_cards if log_cards else '<div style="color:#787B86;">Waiting for confirmation triggers...</div>'}</div>
            </div>
        </div>
    </body>
    </html>
    """


# ----------------- WEBHOOK ENGINE -----------------


class WebhookPayload(BaseModel):
  event: str
  asset: str
  timeframe: Optional[str] = "1H"
  level_type: Optional[str] = "TJL Level"
  price_high: Optional[float] = None
  price_low: Optional[float] = None
  current_price: Optional[float] = None
  bias: Optional[str] = "NEUTRAL"
  notes: Optional[str] = None


@app.post("/webhook")
def handle_event(data: WebhookPayload):
  # 1. NEW LEVEL RECORDING
  if data.event == "NEW_LEVEL":
    with sqlite3.connect(DB_FILE) as conn:
      conn.execute(
          """
                INSERT INTO active_levels (asset, timeframe, level_type, price_high, price_low, bias)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
          (
              data.asset,
              data.timeframe,
              data.level_type,
              data.price_high or 0.0,
              data.price_low or 0.0,
              data.bias,
          ),
      )
    return {"status": "success", "message": "Level recorded in memory"}

  # 2. LEVEL BROKEN (AUTO-CLEANUP)
  elif data.event == "LEVEL_BROKEN":
    curr_p = data.current_price or 0.0
    with sqlite3.connect(DB_FILE) as conn:
      conn.execute(
          """
                UPDATE active_levels 
                SET status = 'INVALIDATED' 
                WHERE asset = ? AND status = 'PENDING'
                AND ((bias LIKE '%DEMAND%' AND price_low > ?) OR (bias LIKE '%SUPPLY%' AND price_high < ?))
            """,
          (data.asset, curr_p, curr_p),
      )
    return {"status": "success", "message": "Levels invalidated"}

  # 3. TRIGGER EVALUATION (CONFIRMATION ENTRY)
  elif data.event == "TRIGGER_CHECK":
    # Step A: Economic Calendar Filter
    news = check_economic_news_hazard(currency="USD")
    if news["status"] == "HAZARDOUS":
      reason = f"REJECTED: News Hazard - {news['reason']}"
      with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "INSERT INTO desk_logs (asset, event_type, details, verdict) VALUES"
            " (?, ?, ?, ?)",
            (data.asset, data.event, f"Price: {data.current_price}", reason),
        )
      return {"status": "rejected", "reason": news["reason"]}

    # Step B: Memory Registry Query
    target_price = data.current_price or 0.0
    with sqlite3.connect(DB_FILE) as conn:
      cur = conn.cursor()
      cur.execute(
          """
                SELECT timeframe, level_type, price_high, price_low, bias, created_at 
                FROM active_levels 
                WHERE asset = ? AND status = 'PENDING' 
                ORDER BY ABS((price_high + price_low)/2 - ?) ASC LIMIT 4
            """,
          (data.asset, target_price),
      )
      nearby = cur.fetchall()

    nearby_summary = (
        "\n".join([
            f"- [{r[0]}] {r[1]}: {r[3]:.2f}-{r[2]:.2f} ({r[4]})"
            for r in nearby
        ])
        if nearby
        else "None"
    )

    # Step C: Prompt Construction
    prompt = f"""
Asset: {data.asset}
Market Price: {data.current_price}
Direction: {data.bias}
Confirmation Notes: {data.notes}

Active Levels in Memory:
{nearby_summary}

Tasks:
1. Verify if price reacted inside an ACTIVE level above. If reacting in empty space, reject it.
2. Ensure {data.bias} matches the higher timeframe level's direction.
3. If valid, output:
   * Setup: {data.asset} ({data.bias})
   * Entry
   * Invalidation (Stop Loss)
   * Target (Strictly >= 1:2.5 Risk-to-Reward)
If invalid, output strictly: "REJECTED: [Brief reason]"
"""

    # Step D: Safe AI Inference
    verdict = ""
    try:
      headers = {
          "Authorization": f"Bearer {GROQ_API_KEY}",
          "Content-Type": "application/json",
      }
      res = requests.post(
          "https://api.groq.com/openai/v1/chat/completions",
          headers=headers,
          json={
              "model": "llama-3.3-70b-specdec",
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.15,
          },
          timeout=15,
      )
      res_json = res.json()
      if "choices" in res_json and len(res_json["choices"]) > 0:
        verdict = res_json["choices"][0]["message"]["content"]
      else:
        err = res_json.get("error", {}).get(
            "message", "Unknown failure response"
        )
        verdict = f"REJECTED: Groq Error - {err}"
    except Exception as e:
      verdict = f"REJECTED: Inference call failed - {str(e)}"

    # Step E: Log into SQLite
    with sqlite3.connect(DB_FILE) as conn:
      conn.execute(
          "INSERT INTO desk_logs (asset, event_type, details, verdict) VALUES"
          " (?, ?, ?, ?)",
          (
              data.asset,
              data.event,
              f"Price: {data.current_price} | {data.notes}",
              verdict,
          ),
      )

    # Step F: Dispatch to Telegram
    if "REJECTED" not in verdict:
      send_telegram(
          f"🎯 TRADE CONFIRMED: {data.asset}\n📍 Price:"
          f" {data.current_price}\n\n{verdict}"
      )

    return {"status": "processed", "verdict": verdict}

  return {"status": "ignored", "message": "Unknown event"}
