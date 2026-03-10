"""
Risk Manager — Schützt dein Konto.

Implementiert:
- Position Sizing basierend auf Risiko %
- Max Tagesverlust (Bot stoppt)
- Max Trades pro Tag
- Max aufeinanderfolgende Verluste
- Minimum Balance Check
- Trade-Logging
"""

import json
import logging
from datetime import datetime, timezone, date
from pathlib import Path

log = logging.getLogger("TradingBot")


class RiskManager:
    """Risikomanagement für den Trading Bot."""

    def __init__(self, config):
        self.config = config

        # Tägliche Statistiken (reset bei neuem Tag)
        self._today = date.today()
        self._trades_today = 0
        self._daily_pnl = 0.0
        self._consecutive_losses = 0
        self._start_balance = None

        # Trade History File
        self.history_file = Path("trade_history.json")
        self._load_history()

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def normalize_ticker(self, ticker: str) -> str:
        """
        Normalisiert externe Ticker in ein konsistentes Format.
        Das ist hier vor allem für Logs/History nützlich.

        Beispiele:
        BTCUSDT.P   -> BTCUSDT
        ETHUSDT.P   -> ETHUSDT
        BTC/USDT    -> BTCUSDT
        btcusdt     -> BTCUSDT
        BTCUSDTPERP -> BTCUSDT
        """
        if not ticker:
            return "UNKNOWN"

        s = str(ticker).upper().strip()
        s = s.replace("/", "").replace(":", "").replace("-", "")

        for suffix in [".P", "PERP"]:
            if s.endswith(suffix):
                s = s[:-len(suffix)]

        return s

    # ─── Daily Reset ──────────────────────────────────────────────────────────

    def _check_new_day(self):
        """Reset tägliche Zähler wenn neuer Tag."""
        today = date.today()
        if today != self._today:
            log.info("📅 Neuer Tag: Reset tägliche Statistiken")
            self._today = today
            self._trades_today = 0
            self._daily_pnl = 0.0
            self._consecutive_losses = 0
            self._start_balance = None

    # ─── Trade Check ──────────────────────────────────────────────────────────

    def check_trade(self, signal: str, price: float, sl: float = None,
                    leverage: int = 20, risk_pct: float = 2.0) -> dict:
        """
        Prüft ob ein Trade erlaubt ist.

        Returns:
            {"allowed": True/False, "reason": "..."}
        """
        self._check_new_day()

        # Grundvalidierung
        if signal not in ["LONG", "SHORT", "CLOSE"]:
            return {
                "allowed": False,
                "reason": f"Ungültiges Signal: {signal}"
            }

        if signal in ["LONG", "SHORT"]:
            if price is None or price <= 0:
                return {
                    "allowed": False,
                    "reason": f"Ungültiger Price: {price}"
                }

            if leverage <= 0:
                return {
                    "allowed": False,
                    "reason": f"Ungültiger Leverage: {leverage}"
                }

            if risk_pct <= 0:
                return {
                    "allowed": False,
                    "reason": f"Ungültiges Risiko pro Trade: {risk_pct}%"
                }

        # 1. Max Trades pro Tag
        if self._trades_today >= self.config.MAX_DAILY_TRADES:
            return {
                "allowed": False,
                "reason": f"Max Trades/Tag erreicht ({self.config.MAX_DAILY_TRADES})"
            }

        # 2. Max aufeinanderfolgende Verluste
        if self._consecutive_losses >= self.config.MAX_CONSECUTIVE_LOSSES:
            return {
                "allowed": False,
                "reason": f"Max Verluste hintereinander erreicht ({self.config.MAX_CONSECUTIVE_LOSSES}) — Bot pausiert"
            }

        # 3. Max Tagesverlust
        if self._start_balance and self._start_balance > 0:
            daily_loss_pct = (self._daily_pnl / self._start_balance) * 100
            if daily_loss_pct <= -self.config.MAX_DAILY_LOSS:
                return {
                    "allowed": False,
                    "reason": f"Max Tagesverlust erreicht ({daily_loss_pct:.1f}% / {self.config.MAX_DAILY_LOSS}%)"
                }

        # 4. Stop-Loss Validierung
        if sl and sl > 0 and price > 0:
            if signal == "LONG" and sl >= price:
                return {
                    "allowed": False,
                    "reason": f"SL ({sl}) muss unter Entry ({price}) für LONG sein"
                }
            if signal == "SHORT" and sl <= price:
                return {
                    "allowed": False,
                    "reason": f"SL ({sl}) muss über Entry ({price}) für SHORT sein"
                }

            # SL-Distanz vs Liquidation Check
            sl_dist_pct = abs(price - sl) / price * 100
            liquidation_pct = 100 / leverage * 0.9  # 90% der Liquidation als Grenze

            if sl_dist_pct > liquidation_pct:
                return {
                    "allowed": False,
                    "reason": f"SL-Distanz ({sl_dist_pct:.1f}%) zu gross für {leverage}x Hebel (Liquidation bei ~{100/leverage:.1f}%)"
                }

        # 5. Risiko pro Trade Check
        if risk_pct > 5.0:
            return {
                "allowed": False,
                "reason": f"Risiko pro Trade ({risk_pct}%) zu hoch — Max 5%"
            }

        return {"allowed": True, "reason": "OK"}

    # ─── Position Sizing ──────────────────────────────────────────────────────

    def calculate_position_size(self, balance: float, price: float,
                                sl: float = None, leverage: int = 20,
                                risk_pct: float = 2.0, ticker: str = "BTCUSDT") -> float:
        """
        Berechnet die Position Size basierend auf Risiko.

        Formel:
            Risk Amount = Balance * (risk_pct / 100)
            SL Distance = |price - sl|
            Position Size = Risk Amount / SL Distance

        Falls kein SL:
            Position Size = (Balance * risk_pct / 100) / price * leverage
        """
        self._check_new_day()
        ticker = self.normalize_ticker(ticker)

        if self._start_balance is None:
            self._start_balance = balance

        # Grundvalidierung
        if balance <= 0:
            log.warning(f"⚠️ Ungültige Balance: {balance}")
            return 0.0

        if price <= 0:
            log.warning(f"⚠️ Ungültiger Price für Position Sizing: {price}")
            return 0.0

        if leverage <= 0:
            log.warning(f"⚠️ Ungültiger Leverage für Position Sizing: {leverage}")
            return 0.0

        if risk_pct <= 0:
            log.warning(f"⚠️ Ungültiges Risiko % für Position Sizing: {risk_pct}")
            return 0.0

        # Minimum Balance Check
        if balance < self.config.MIN_BALANCE_USDT:
            log.warning(
                f"⚠️ Balance ({balance} USDT) unter Minimum ({self.config.MIN_BALANCE_USDT} USDT)"
            )
            return 0.0

        risk_amount = balance * (risk_pct / 100)

        if sl and sl > 0:
            sl_distance = abs(price - sl)
            if sl_distance == 0:
                log.warning("SL-Distanz = 0, kann Position Size nicht berechnen")
                return 0.0

            # Position Size so berechnen, dass Verlust bei SL = risk_amount
            quantity = risk_amount / sl_distance
        else:
            # Ohne SL: einfache Berechnung basierend auf Risiko %
            quantity = (risk_amount * leverage) / price

        if quantity <= 0:
            log.warning(f"⚠️ Berechnete Quantity ungültig: {quantity}")
            return 0.0

        log.info(
            f"📐 Position Sizing: Balance={balance:.2f} USDT | "
            f"Risk={risk_pct}% ({risk_amount:.2f} USDT) | "
            f"Qty={quantity:.6f} {ticker}"
        )

        return quantity

    # ─── Trade Logging ────────────────────────────────────────────────────────

    def log_trade(self, signal: str, ticker: str, quantity: float,
                  price: float, sl: float = None, tp: float = None,
                  leverage: int = 20):
        """Loggt einen ausgeführten Trade."""
        self._check_new_day()
        self._trades_today += 1

        ticker = self.normalize_ticker(ticker)

        trade = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signal": signal,
            "ticker": ticker,
            "quantity": quantity,
            "price": price,
            "sl": sl,
            "tp": tp,
            "leverage": leverage,
            "trade_number_today": self._trades_today
        }

        # An History anhängen
        self.history.append(trade)
        self._save_history()

        log.info(
            f"📝 Trade #{self._trades_today} heute: "
            f"{signal} {quantity} {ticker} @ {price} | "
            f"SL: {sl} | TP: {tp} | Leverage: {leverage}x"
        )

    def record_trade_result(self, pnl: float):
        """Zeichnet das Ergebnis eines geschlossenen Trades auf."""
        self._check_new_day()
        self._daily_pnl += pnl

        if pnl < 0:
            self._consecutive_losses += 1
            log.info(f"📉 Verlust: {pnl:.2f} USDT | Serie: {self._consecutive_losses}")
        else:
            self._consecutive_losses = 0
            log.info(f"📈 Gewinn: {pnl:.2f} USDT")

    # ─── Statistics ───────────────────────────────────────────────────────────

    def get_daily_stats(self) -> dict:
        """Gibt tägliche Statistiken zurück."""
        self._check_new_day()
        return {
            "date": str(self._today),
            "trades_today": self._trades_today,
            "max_trades": self.config.MAX_DAILY_TRADES,
            "daily_pnl": round(self._daily_pnl, 2),
            "max_daily_loss": self.config.MAX_DAILY_LOSS,
            "consecutive_losses": self._consecutive_losses,
            "max_consecutive": self.config.MAX_CONSECUTIVE_LOSSES,
            "bot_status": "ACTIVE" if self._is_active() else "PAUSED"
        }

    def _is_active(self) -> bool:
        """Prüft ob der Bot aktiv handeln darf."""
        if self._trades_today >= self.config.MAX_DAILY_TRADES:
            return False
        if self._consecutive_losses >= self.config.MAX_CONSECUTIVE_LOSSES:
            return False
        if self._start_balance and self._start_balance > 0:
            daily_loss_pct = (self._daily_pnl / self._start_balance) * 100
            if daily_loss_pct <= -self.config.MAX_DAILY_LOSS:
                return False
        return True

    # ─── History Persistence ──────────────────────────────────────────────────

    def _load_history(self):
        """Lädt Trade History aus Datei."""
        if self.history_file.exists():
            try:
                content = self.history_file.read_text(encoding="utf-8").strip()
                self.history = json.loads(content) if content else []
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"⚠️ Konnte Trade History nicht laden: {e}")
                self.history = []
        else:
            self.history = []

    def _save_history(self):
        """Speichert Trade History in Datei."""
        try:
            self.history_file.write_text(
                json.dumps(self.history, indent=2, default=str),
                encoding="utf-8"
            )
        except OSError as e:
            log.error(f"❌ Konnte Trade History nicht speichern: {e}")
