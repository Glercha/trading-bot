"""
Konfiguration für den Trading Bot.
Alle Werte werden aus .env geladen oder nutzen sichere Defaults.
"""

import os


class Config:
    """Zentrale Konfiguration — alle Werte aus Umgebungsvariablen."""

    def __init__(self):
        # ─── Binance API ──────────────────────────────────────────────────
        self.API_KEY = os.getenv("BINANCE_API_KEY", "cyBNLnyzQUdUebPtLFywhjZmc2t7YmPzuU5U1LS2scbokkmyKTz0gU8QX67aUP8w")
        self.API_SECRET = os.getenv("BINANCE_API_SECRET", "f8KIPVjgpMDemWE6VNHlJFeM4lh2djpNa6ipLNU75Njs1xtR1TedYlRoPz1YyAQx")
        self.USE_TESTNET = os.getenv("USE_TESTNET", "true").lower() == "true"

        # Binance Futures Endpoints
        self.BASE_URL = (
            "https://testnet.binancefuture.com"
            if self.USE_TESTNET
            else "https://fapi.binance.com"
        )

        # ─── Webhook Security ────────────────────────────────────────────
        self.WEBHOOK_PASSPHRASE = os.getenv("WEBHOOK_PASSPHRASE", "changeme123")
        self.PORT = int(os.getenv("PORT", 3000))

        # ─── Trading Defaults ─────────────────────────────────────────────
        self.DEFAULT_SYMBOL = os.getenv("DEFAULT_SYMBOL", "BTCUSDT")
        self.DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", 20))
        self.MARGIN_TYPE = os.getenv("MARGIN_TYPE", "CROSSED")  # CROSSED oder ISOLATED

        # ─── Risikomanagement ─────────────────────────────────────────────
        self.RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", 2.0))      # % des Kontos
        self.MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", 6.0))      # % Tagesverlust
        self.MAX_DAILY_TRADES = int(os.getenv("MAX_DAILY_TRADES", 5))
        self.MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", 3))
        self.MIN_BALANCE_USDT = float(os.getenv("MIN_BALANCE_USDT", 50.0)) # Minimum Balance

    def validate(self):
        """Prüft ob alle kritischen Werte gesetzt sind."""
        errors = []
        if not self.API_KEY:
            errors.append("BINANCE_API_KEY nicht gesetzt")
        if not self.API_SECRET:
            errors.append("BINANCE_API_SECRET nicht gesetzt")
        if self.WEBHOOK_PASSPHRASE == "changeme123":
            errors.append("WEBHOOK_PASSPHRASE noch auf Default — bitte ändern!")
        if self.DEFAULT_LEVERAGE > 50:
            errors.append(f"Leverage {self.DEFAULT_LEVERAGE}x ist extrem riskant")
        return errors
