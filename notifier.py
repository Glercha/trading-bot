"""
Telegram Notifier
Sendet Bot-Benachrichtigungen an Telegram.
"""

import logging
import requests

log = logging.getLogger("TradingBot")


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, enabled: bool = True):
        self.token = (token or "").strip()
        self.chat_id = str(chat_id or "").strip()
        self.enabled = enabled and bool(self.token) and bool(self.chat_id)

        if self.enabled:
            self.base_url = f"https://api.telegram.org/bot{self.token}"
        else:
            self.base_url = None
            log.warning("Telegram Notifier deaktiviert: TOKEN oder CHAT_ID fehlt")

    def send(self, message: str) -> bool:
        """Sendet eine Telegram Nachricht."""
        if not self.enabled:
            log.debug("Telegram deaktiviert, Nachricht wird nicht gesendet")
            return False

        try:
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                },
                timeout=10
            )

            data = resp.json()

            if resp.status_code != 200 or not data.get("ok", False):
                log.error(f"Telegram Fehler: {data}")
                return False

            return True

        except Exception as e:
            log.error(f"Telegram Sendefehler: {e}")
            return False

    def send_startup(self, symbol: str, testnet: bool):
        env = "TESTNET" if testnet else "LIVE"
        msg = (
            f"🤖 <b>Trading Bot gestartet</b>\n"
            f"Symbol: <code>{symbol}</code>\n"
            f"Umgebung: <b>{env}</b>"
        )
        self.send(msg)

    def send_trade_executed(self, signal: str, ticker: str, quantity: float,
                            price: float, leverage: int, sl=None, tp=None):
        msg = (
            f"🚀 <b>{signal} Order ausgeführt</b>\n"
            f"Symbol: <code>{ticker}</code>\n"
            f"Qty: <code>{quantity:.6f}</code>\n"
            f"Entry: <code>{price}</code>\n"
            f"Leverage: <code>{leverage}x</code>\n"
            f"SL: <code>{sl if sl else '-'}</code>\n"
            f"TP: <code>{tp if tp else '-'}</code>"
        )
        self.send(msg)

    def send_position_closed(self, ticker: str):
        msg = (
            f"🔴 <b>Position geschlossen</b>\n"
            f"Symbol: <code>{ticker}</code>"
        )
        self.send(msg)

    def send_rejected(self, ticker: str, reason: str):
        msg = (
            f"🛡️ <b>Trade abgelehnt</b>\n"
            f"Symbol: <code>{ticker}</code>\n"
            f"Grund: {reason}"
        )
        self.send(msg)

    def send_error(self, error_text: str):
        msg = (
            f"❌ <b>Bot Fehler</b>\n"
            f"<code>{error_text}</code>"
        )
        self.send(msg)

    def send_sl_set(self, ticker: str, sl: float):
        msg = (
            f"🛑 <b>Stop-Loss gesetzt</b>\n"
            f"Symbol: <code>{ticker}</code>\n"
            f"SL: <code>{sl}</code>"
        )
        self.send(msg)

    def send_tp_set(self, ticker: str, tp: float):
        msg = (
            f"🎯 <b>Take-Profit gesetzt</b>\n"
            f"Symbol: <code>{ticker}</code>\n"
            f"TP: <code>{tp}</code>"
        )
        self.send(msg)
