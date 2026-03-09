"""
Trading Bot — Webhook Server
Empfängt TradingView Alerts via Webhook und führt Trades auf Binance Futures aus.

Architektur:
    TradingView (Pine Script Alert)
        → Webhook (JSON POST)
            → Dieser Server (Flask)
                → Validierung & Risikomanagement
                    → Binance Futures API
"""

import os
import json
import logging
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from dotenv import load_dotenv

from config import Config
from binance_client import BinanceClient
from risk_manager import RiskManager

# ─── Setup ────────────────────────────────────────────────────────────────────
# load_dotenv nur lokal nutzen, nicht auf Render
import os
if os.path.exists(".env"):
    load_dotenv()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("TradingBot")

# Debug — nach dem Logger!
log.info(f"API Key geladen: '{config.API_KEY[:8]}...' (Länge: {len(config.API_KEY)})")
log.info(f"Direct env: '{os.environ.get('BINANCE_API_KEY', 'NOT FOUND')[:8]}...'")


# Flask App
app = Flask(__name__)

# Binance Client & Risk Manager
binance = BinanceClient(config)
risk_mgr = RiskManager(config)

# ─── Webhook Endpoint ─────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Empfängt TradingView Webhook Alerts.
    
    Erwartetes JSON Format:
    {
        "passphrase": "dein_geheimes_passwort",
        "signal": "LONG" oder "SHORT" oder "CLOSE",
        "ticker": "BTCUSDT",
        "price": 87000.0,
        "sl": 86500.0,          # optional
        "tp": 88500.0,          # optional
        "leverage": 20,         # optional (Default aus Config)
        "risk_pct": 2.0,        # optional (Default aus Config)
        "timeframe": "15"       # optional (Info only)
    }
    """
    try:
        # ─── 1. Parse Request ─────────────────────────────────────────────
        data = request.get_json(force=True)
        if not data:
            log.warning("Leerer Request empfangen")
            return jsonify({"error": "empty request"}), 400

        log.info(f"📨 Webhook empfangen: {json.dumps(data, indent=2)}")

        # ─── 2. Authentifizierung ─────────────────────────────────────────
        passphrase = data.get("passphrase", "")
        if passphrase != config.WEBHOOK_PASSPHRASE:
            log.warning(f"⛔ Ungültige Passphrase: {passphrase}")
            return jsonify({"error": "unauthorized"}), 401

        # ─── 3. Signal validieren ─────────────────────────────────────────
        signal = data.get("signal", "").upper()
        ticker = data.get("ticker", config.DEFAULT_SYMBOL).upper()
        
        if signal not in ["LONG", "SHORT", "CLOSE"]:
            log.warning(f"⚠️ Unbekanntes Signal: {signal}")
            return jsonify({"error": f"unknown signal: {signal}"}), 400

        # ─── 4. CLOSE Signal ──────────────────────────────────────────────
        if signal == "CLOSE":
            result = binance.close_position(ticker)
            log.info(f"🔴 Position geschlossen: {ticker}")
            return jsonify({"status": "closed", "result": result}), 200

        # ─── 5. Trade-Parameter extrahieren ───────────────────────────────
        price = float(data.get("price", 0))
        sl = float(data.get("sl", 0)) if data.get("sl") else None
        tp = float(data.get("tp", 0)) if data.get("tp") else None
        leverage = int(data.get("leverage", config.DEFAULT_LEVERAGE))
        risk_pct = float(data.get("risk_pct", config.RISK_PER_TRADE))

        # ─── 6. Risikomanagement prüfen ───────────────────────────────────
        risk_check = risk_mgr.check_trade(
            signal=signal,
            price=price,
            sl=sl,
            leverage=leverage,
            risk_pct=risk_pct
        )

        if not risk_check["allowed"]:
            log.warning(f"🛡️ Trade abgelehnt: {risk_check['reason']}")
            return jsonify({
                "status": "rejected",
                "reason": risk_check["reason"]
            }), 200

        # ─── 7. Position Sizing ───────────────────────────────────────────
        balance = binance.get_balance()
        quantity = risk_mgr.calculate_position_size(
            balance=balance,
            price=price,
            sl=sl,
            leverage=leverage,
            risk_pct=risk_pct,
            ticker=ticker
        )

        if quantity <= 0:
            log.warning("⚠️ Position Size = 0, Trade übersprungen")
            return jsonify({"status": "skipped", "reason": "quantity zero"}), 200

        # ─── 8. Bestehende Position schliessen ────────────────────────────
        current_pos = binance.get_position(ticker)
        if current_pos and current_pos["size"] != 0:
            opposite = (current_pos["side"] == "LONG" and signal == "SHORT") or \
                       (current_pos["side"] == "SHORT" and signal == "LONG")
            if opposite:
                log.info(f"🔄 Gegenposition erkannt → schliesse {current_pos['side']}")
                binance.close_position(ticker)

        # ─── 9. Leverage setzen ───────────────────────────────────────────
        binance.set_leverage(ticker, leverage)

        # ─── 10. Order ausführen ──────────────────────────────────────────
        side = "BUY" if signal == "LONG" else "SELL"

        order_result = binance.place_market_order(
            symbol=ticker,
            side=side,
            quantity=quantity
        )

        log.info(f"✅ {signal} Order ausgeführt: {ticker} | Qty: {quantity} | Leverage: {leverage}x")

        # ─── 11. Stop-Loss setzen ─────────────────────────────────────────
        sl_result = None
        if sl and sl > 0:
            sl_side = "SELL" if signal == "LONG" else "BUY"
            sl_result = binance.place_stop_loss(
                symbol=ticker,
                side=sl_side,
                quantity=quantity,
                stop_price=sl
            )
            log.info(f"🛑 Stop-Loss gesetzt: {sl}")

        # ─── 12. Take-Profit setzen ──────────────────────────────────────
        tp_result = None
        if tp and tp > 0:
            tp_side = "SELL" if signal == "LONG" else "BUY"
            tp_result = binance.place_take_profit(
                symbol=ticker,
                side=tp_side,
                quantity=quantity,
                take_profit_price=tp
            )
            log.info(f"🎯 Take-Profit gesetzt: {tp}")

        # ─── 13. Trade loggen ─────────────────────────────────────────────
        risk_mgr.log_trade(
            signal=signal,
            ticker=ticker,
            quantity=quantity,
            price=price,
            sl=sl,
            tp=tp,
            leverage=leverage
        )

        return jsonify({
            "status": "executed",
            "signal": signal,
            "ticker": ticker,
            "quantity": quantity,
            "leverage": leverage,
            "sl": sl,
            "tp": tp,
            "order": order_result,
            "sl_order": sl_result,
            "tp_order": tp_result
        }), 200

    except Exception as e:
        log.error(f"❌ Fehler: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint für Monitoring."""
    try:
        balance = binance.get_balance()
        positions = binance.get_open_positions()
        daily_stats = risk_mgr.get_daily_stats()

        return jsonify({
            "status": "online",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "balance_usdt": balance,
            "open_positions": len(positions),
            "positions": positions,
            "daily_stats": daily_stats
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "name": "TradingView → Binance Futures Bot",
        "version": "1.0.0",
        "endpoints": {
            "/webhook": "POST — TradingView Alert empfangen",
            "/health": "GET — Status & Balance prüfen"
        }
    })


# ─── Start ────────────────────────────────────────────────────────────────────

# ─── Start ────────────────────────────────────────────────────────────────────

# Diese Zeilen laufen IMMER (auch unter gunicorn)
log.info("🚀 Trading Bot gestartet")
log.info(f"   Symbol: {config.DEFAULT_SYMBOL}")
log.info(f"   Testnet: {config.USE_TESTNET}")

