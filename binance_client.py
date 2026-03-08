"""
Binance Futures API Client.
Handhabt alle Kommunikation mit der Binance Futures API.
"""

import time
import hmac
import hashlib
import logging
import requests
from urllib.parse import urlencode

log = logging.getLogger("TradingBot")


class BinanceClient:
    """Binance Futures API Wrapper."""

    def __init__(self, config):
        self.config = config
        self.base_url = config.BASE_URL
        self.api_key = config.API_KEY
        self.api_secret = config.API_SECRET
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key
        })

    # ─── Signierung ───────────────────────────────────────────────────────────

    def _sign(self, params: dict) -> dict:
        """Signiert Request-Parameter mit HMAC-SHA256."""
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params

    def _request(self, method: str, path: str, params: dict = None, signed: bool = True) -> dict:
        """Führt einen API Request aus."""
        url = f"{self.base_url}{path}"
        params = params or {}

        if signed:
            params = self._sign(params)

        try:
            if method == "GET":
                resp = self.session.get(url, params=params, timeout=10)
            elif method == "POST":
                resp = self.session.post(url, params=params, timeout=10)
            elif method == "DELETE":
                resp = self.session.delete(url, params=params, timeout=10)
            else:
                raise ValueError(f"Unbekannte Methode: {method}")

            data = resp.json()

            if resp.status_code != 200:
                error_msg = data.get("msg", "Unknown error")
                error_code = data.get("code", "N/A")
                log.error(f"Binance API Error [{error_code}]: {error_msg}")
                raise Exception(f"Binance API Error [{error_code}]: {error_msg}")

            return data

        except requests.exceptions.Timeout:
            log.error("Binance API Timeout")
            raise
        except requests.exceptions.ConnectionError:
            log.error("Binance API Verbindungsfehler")
            raise

    # ─── Account Info ─────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        """Holt die verfügbare USDT Balance."""
        data = self._request("GET", "/fapi/v2/balance")
        for asset in data:
            if asset["asset"] == "USDT":
                return float(asset["availableBalance"])
        return 0.0

    def get_account_info(self) -> dict:
        """Holt Account-Informationen."""
        return self._request("GET", "/fapi/v2/account")

    # ─── Position Info ────────────────────────────────────────────────────────

    def get_position(self, symbol: str) -> dict | None:
        """Holt aktuelle Position für ein Symbol."""
        data = self._request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
        for pos in data:
            if pos["symbol"] == symbol:
                size = float(pos["positionAmt"])
                if size != 0:
                    return {
                        "symbol": symbol,
                        "side": "LONG" if size > 0 else "SHORT",
                        "size": abs(size),
                        "entry_price": float(pos["entryPrice"]),
                        "unrealized_pnl": float(pos["unRealizedProfit"]),
                        "leverage": int(pos["leverage"]),
                        "margin_type": pos["marginType"]
                    }
        return None

    def get_open_positions(self) -> list:
        """Holt alle offenen Positionen."""
        data = self._request("GET", "/fapi/v2/positionRisk")
        positions = []
        for pos in data:
            size = float(pos["positionAmt"])
            if size != 0:
                positions.append({
                    "symbol": pos["symbol"],
                    "side": "LONG" if size > 0 else "SHORT",
                    "size": abs(size),
                    "entry_price": float(pos["entryPrice"]),
                    "pnl": float(pos["unRealizedProfit"])
                })
        return positions

    # ─── Leverage & Margin ────────────────────────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int):
        """Setzt den Leverage für ein Symbol."""
        try:
            return self._request("POST", "/fapi/v1/leverage", {
                "symbol": symbol,
                "leverage": leverage
            })
        except Exception as e:
            # Ignoriere "no need to change" Fehler
            if "No need to change" in str(e):
                log.debug(f"Leverage bereits auf {leverage}x")
            else:
                raise

    def set_margin_type(self, symbol: str, margin_type: str = "CROSSED"):
        """Setzt den Margin-Typ (CROSSED oder ISOLATED)."""
        try:
            return self._request("POST", "/fapi/v1/marginType", {
                "symbol": symbol,
                "marginType": margin_type
            })
        except Exception as e:
            if "No need to change" in str(e):
                log.debug(f"Margin-Typ bereits {margin_type}")
            else:
                raise

    # ─── Symbol Info ──────────────────────────────────────────────────────────

    def get_symbol_info(self, symbol: str) -> dict:
        """Holt Handelsinformationen für ein Symbol (Tick Size, Lot Size etc.)."""
        data = self._request("GET", "/fapi/v1/exchangeInfo", signed=False)
        for s in data["symbols"]:
            if s["symbol"] == symbol:
                info = {"symbol": symbol}
                for f in s["filters"]:
                    if f["filterType"] == "PRICE_FILTER":
                        info["tick_size"] = float(f["tickSize"])
                    elif f["filterType"] == "LOT_SIZE":
                        info["step_size"] = float(f["stepSize"])
                        info["min_qty"] = float(f["minQty"])
                    elif f["filterType"] == "MIN_NOTIONAL":
                        info["min_notional"] = float(f.get("notional", 5))
                info["quantity_precision"] = s["quantityPrecision"]
                info["price_precision"] = s["pricePrecision"]
                return info
        raise Exception(f"Symbol {symbol} nicht gefunden")

    def round_quantity(self, symbol: str, quantity: float) -> float:
        """Rundet die Quantity auf die erlaubte Precision."""
        info = self.get_symbol_info(symbol)
        precision = info["quantity_precision"]
        step = info["step_size"]
        quantity = round(quantity - (quantity % step), precision)
        return max(quantity, info["min_qty"])

    def round_price(self, symbol: str, price: float) -> float:
        """Rundet den Preis auf die erlaubte Precision."""
        info = self.get_symbol_info(symbol)
        precision = info["price_precision"]
        return round(price, precision)

    # ─── Orders ───────────────────────────────────────────────────────────────

    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        """Platziert eine Market Order."""
        quantity = self.round_quantity(symbol, quantity)
        log.info(f"📤 Market Order: {side} {quantity} {symbol}")

        return self._request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity
        })

    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> dict:
        """Platziert eine Limit Order."""
        quantity = self.round_quantity(symbol, quantity)
        price = self.round_price(symbol, price)

        return self._request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "quantity": quantity,
            "price": price,
            "timeInForce": "GTC"
        })

    def place_stop_loss(self, symbol: str, side: str, quantity: float, stop_price: float) -> dict:
        """Platziert eine Stop-Market Order (Stop-Loss)."""
        quantity = self.round_quantity(symbol, quantity)
        stop_price = self.round_price(symbol, stop_price)
        log.info(f"📤 Stop-Loss: {side} {quantity} {symbol} @ {stop_price}")

        return self._request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": side,
            "type": "STOP_MARKET",
            "quantity": quantity,
            "stopPrice": stop_price,
            "closePosition": "false",
            "workingType": "MARK_PRICE"
        })

    def place_take_profit(self, symbol: str, side: str, quantity: float, take_profit_price: float) -> dict:
        """Platziert eine Take-Profit-Market Order."""
        quantity = self.round_quantity(symbol, quantity)
        take_profit_price = self.round_price(symbol, take_profit_price)
        log.info(f"📤 Take-Profit: {side} {quantity} {symbol} @ {take_profit_price}")

        return self._request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": side,
            "type": "TAKE_PROFIT_MARKET",
            "quantity": quantity,
            "stopPrice": take_profit_price,
            "closePosition": "false",
            "workingType": "MARK_PRICE"
        })

    # ─── Position Management ──────────────────────────────────────────────────

    def close_position(self, symbol: str) -> dict | None:
        """Schliesst alle offenen Positionen für ein Symbol."""
        pos = self.get_position(symbol)
        if not pos:
            log.info(f"Keine offene Position für {symbol}")
            return None

        # Alle offenen Orders für dieses Symbol canceln
        self.cancel_all_orders(symbol)

        # Position schliessen mit Market Order
        close_side = "SELL" if pos["side"] == "LONG" else "BUY"
        result = self.place_market_order(symbol, close_side, pos["size"])
        log.info(f"🔴 Position geschlossen: {pos['side']} {pos['size']} {symbol}")
        return result

    def cancel_all_orders(self, symbol: str) -> dict:
        """Cancelt alle offenen Orders für ein Symbol."""
        try:
            return self._request("DELETE", "/fapi/v1/allOpenOrders", {
                "symbol": symbol
            })
        except Exception as e:
            log.warning(f"Cancel Orders Fehler (möglicherweise keine offenen): {e}")
            return {}

    # ─── Preis Info ───────────────────────────────────────────────────────────

    def get_mark_price(self, symbol: str) -> float:
        """Holt den aktuellen Mark Price."""
        data = self._request("GET", "/fapi/v1/premiumIndex",
                             {"symbol": symbol}, signed=False)
        return float(data["markPrice"])
