"""
Binance Futures API Client.
Handhabt alle Kommunikation mit der Binance Futures API.
"""

import time
import hmac
import hashlib
import logging
import requests
import re
from urllib.parse import urlencode

log = logging.getLogger("TradingBot")


class BinanceClient:
    """Binance Futures API Wrapper."""

    def __init__(self, config):
        self.config = config
        self.base_url = config.BASE_URL.rstrip("/")
        self.api_key = config.API_KEY
        self.api_secret = config.API_SECRET
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key
        })

        self._exchange_info_cache = None
        self._exchange_info_cache_ts = 0
        self._exchange_info_ttl = 300  # 5 Minuten Cache

    # ─── Symbol Normalisierung / Validierung ────────────────────────────────

    def normalize_symbol(self, symbol: str) -> str:
        """
        Normalisiert Symbole aus TradingView/externen Quellen
        in gültige Binance Futures Symbole.

        Beispiele:
        BTCUSDT.P           -> BTCUSDT
        ETHUSDT.P           -> ETHUSDT
        BTC/USDT            -> BTCUSDT
        btcusdt             -> BTCUSDT
        BTCUSDTPERP         -> BTCUSDT
        BINANCE:BTCUSDT.P   -> BTCUSDT
        """
        if not symbol:
            raise ValueError("Leeres Symbol erhalten")

        s = str(symbol).upper().strip()

        # TradingView Exchange Prefix entfernen
        # Beispiel: BINANCE:BTCUSDT.P -> BTCUSDT.P
        if ":" in s:
            s = s.split(":")[-1]

        # Trennzeichen entfernen
        s = s.replace("/", "").replace("-", "").replace("_", "")

        # Bekannte Suffixe entfernen
        for suffix in ["USDTPERP", "PERP", ".P"]:
            if s.endswith(suffix):
                s = s[:-len(suffix)]

        # Alles außer A-Z / 0-9 entfernen
        s = re.sub(r"[^A-Z0-9]", "", s)

        if not s:
            raise ValueError(f"Ungültiges Symbol nach Normalisierung: {symbol}")

        return s

    def _get_exchange_info(self, force_refresh: bool = False) -> dict:
        """Lädt ExchangeInfo mit kleinem Cache."""
        now = time.time()
        if (
            not force_refresh
            and self._exchange_info_cache is not None
            and (now - self._exchange_info_cache_ts) < self._exchange_info_ttl
        ):
            return self._exchange_info_cache

        data = self._request("GET", "/fapi/v1/exchangeInfo", signed=False)
        self._exchange_info_cache = data
        self._exchange_info_cache_ts = now
        return data

    def get_valid_symbols(self, force_refresh: bool = False) -> set:
        """Gibt alle aktuell gültigen Futures-Symbole zurück."""
        data = self._get_exchange_info(force_refresh=force_refresh)
        valid = set()

        for s in data.get("symbols", []):
            if s.get("status") == "TRADING" and s.get("symbol"):
                valid.add(s["symbol"].upper())

        return valid

    def validate_symbol(self, symbol: str) -> str:
        """
        Normalisiert und validiert ein Symbol gegen Binance Futures.
        """
        raw_symbol = symbol
        normalized = self.normalize_symbol(symbol)
        valid_symbols = self.get_valid_symbols()

        if normalized in valid_symbols:
            if raw_symbol != normalized:
                log.info(f"🔄 Symbol normalisiert: {raw_symbol} -> {normalized}")
            return normalized

        # Cache erneut laden falls veraltet
        valid_symbols = self.get_valid_symbols(force_refresh=True)
        if normalized in valid_symbols:
            if raw_symbol != normalized:
                log.info(f"🔄 Symbol normalisiert: {raw_symbol} -> {normalized}")
            return normalized

        raise ValueError(
            f"Ungültiges Futures-Symbol: raw='{raw_symbol}' normalized='{normalized}'"
        )

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
        symbol = self.validate_symbol(symbol)
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
        symbol = self.validate_symbol(symbol)

        try:
            return self._request("POST", "/fapi/v1/leverage", {
                "symbol": symbol,
                "leverage": leverage
            })
        except Exception as e:
            if "No need to change" in str(e):
                log.debug(f"Leverage bereits auf {leverage}x")
            else:
                raise

    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED"):
        """Setzt den Margin-Typ (CROSSED oder ISOLATED)."""
        symbol = self.validate_symbol(symbol)

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
        symbol = self.validate_symbol(symbol)
        data = self._get_exchange_info()

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
        symbol = self.validate_symbol(symbol)
        info = self.get_symbol_info(symbol)
        precision = info["quantity_precision"]
        step = info["step_size"]
        quantity = round(quantity - (quantity % step), precision)
        return max(quantity, info["min_qty"])

    def round_price(self, symbol: str, price: float) -> float:
        """Rundet den Preis auf die erlaubte Precision."""
        symbol = self.validate_symbol(symbol)
        info = self.get_symbol_info(symbol)
        precision = info["price_precision"]
        return round(price, precision)

    # ─── Orders ───────────────────────────────────────────────────────────────

    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        """Platziert eine Market Order."""
        raw_symbol = symbol
        symbol = self.validate_symbol(symbol)
        quantity = self.round_quantity(symbol, quantity)

        log.info(f"📤 Market Order: raw={raw_symbol} normalized={symbol} side={side} qty={quantity}")

        return self._request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": quantity
        })

    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> dict:
        """Platziert eine Limit Order."""
        raw_symbol = symbol
        symbol = self.validate_symbol(symbol)
        quantity = self.round_quantity(symbol, quantity)
        price = self.round_price(symbol, price)

        log.info(f"📤 Limit Order: raw={raw_symbol} normalized={symbol} side={side} qty={quantity} price={price}")

        return self._request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": side.upper(),
            "type": "LIMIT",
            "quantity": quantity,
            "price": price,
            "timeInForce": "GTC"
        })

    def place_stop_loss(self, symbol: str, side: str, quantity: float, stop_price: float) -> dict:
        """Platziert eine Stop-Market Order (Stop-Loss)."""
        raw_symbol = symbol
        symbol = self.validate_symbol(symbol)
        quantity = self.round_quantity(symbol, quantity)
        stop_price = self.round_price(symbol, stop_price)

        log.info(f"📤 Stop-Loss: raw={raw_symbol} normalized={symbol} side={side} qty={quantity} stop={stop_price}")

        return self._request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": side.upper(),
            "type": "STOP_MARKET",
            "quantity": quantity,
            "stopPrice": stop_price,
            "closePosition": "false",
            "workingType": "MARK_PRICE"
        })

    def place_take_profit(self, symbol: str, side: str, quantity: float, take_profit_price: float) -> dict:
        """Platziert eine Take-Profit-Market Order."""
        raw_symbol = symbol
        symbol = self.validate_symbol(symbol)
        quantity = self.round_quantity(symbol, quantity)
        take_profit_price = self.round_price(symbol, take_profit_price)

        log.info(f"📤 Take-Profit: raw={raw_symbol} normalized={symbol} side={side} qty={quantity} tp={take_profit_price}")

        return self._request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": side.upper(),
            "type": "TAKE_PROFIT_MARKET",
            "quantity": quantity,
            "stopPrice": take_profit_price,
            "closePosition": "false",
            "workingType": "MARK_PRICE"
        })

    # ─── Position Management ──────────────────────────────────────────────────

    def close_position(self, symbol: str) -> dict | None:
        """Schliesst alle offenen Positionen für ein Symbol."""
        symbol = self.validate_symbol(symbol)

        pos = self.get_position(symbol)
        if not pos:
            log.info(f"Keine offene Position für {symbol}")
            return None

        self.cancel_all_orders(symbol)

        close_side = "SELL" if pos["side"] == "LONG" else "BUY"
        result = self.place_market_order(symbol, close_side, pos["size"])
        log.info(f"🔴 Position geschlossen: {pos['side']} {pos['size']} {symbol}")
        return result

    def cancel_all_orders(self, symbol: str) -> dict:
        """Cancelt alle offenen Orders für ein Symbol."""
        symbol = self.validate_symbol(symbol)

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
        symbol = self.validate_symbol(symbol)

        data = self._request(
            "GET",
            "/fapi/v1/premiumIndex",
            {"symbol": symbol},
            signed=False
        )
        return float(data["markPrice"])
