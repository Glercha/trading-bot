"""
Konfigurationsklasse für den Trading Bot.
Lädt alle wichtigen Werte aus Environment Variablen.
"""

import os


class Config:
    def __init__(self):
        # ─── Binance ────────────────────────────────────────────────────────
        self.API_KEY = os.getenv("BINANCE_API_KEY", "cyBNLnyzQUdUebPtLFywhjZmc2t7YmPzuU5U1LS2scbokkmyKTz0gU8QX67aUP8w")
        self.API_SECRET = os.getenv("BINANCE_API_SECRET", "f8KIPVjgpMDemWE6VNHlJFeM4lh2djpNa6ipLNU75Njs1xtR1TedYlRoPz1YyAQx")
        self.USE_TESTNET = os.getenv("USE_TESTNET", "false").lower() == "true"

        if self.USE_TESTNET:
            self.BASE_URL = "https://testnet.binancefuture.com"
        else:
            self.BASE_URL = "https://fapi.binance.com"

        # ─── Webhook ────────────────────────────────────────────────────────
        self.WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE", "ajsdljdsaojoOASJojdasj129")

        # ─── Defaults ───────────────────────────────────────────────────────
        self.DEFAULT_SYMBOL = os.getenv("DEFAULT_SYMBOL", "BTCUSDT")
        self.DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "20"))
        self.RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "2.0"))

        # ─── Risk Management ────────────────────────────────────────────────
        self.MAX_DAILY_TRADES = int(os.getenv("MAX_DAILY_TRADES", "10"))
        self.MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "5.0"))
        self.MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3"))
        self.MIN_BALANCE_USDT = float(os.getenv("MIN_BALANCE_USDT", "50"))

        # ─── Telegram ───────────────────────────────────────────────────────
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8735205351:AAGeEXe1BPgSmNFYqt9uEq0kPX3Uc4F2LyA")
        self.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1747500351")
        self.TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "true").lower() == "true"

        # ─── Optional ───────────────────────────────────────────────────────
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
