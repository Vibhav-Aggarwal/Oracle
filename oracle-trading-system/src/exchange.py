"""
Exchange Client - Production Grade
"""

import hmac
import hashlib
import time
import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from functools import wraps
import threading

logger = logging.getLogger(__name__)


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


class ExchangeError(Exception):
    pass


class AuthenticationError(ExchangeError):
    pass


class RateLimitError(ExchangeError):
    pass


@dataclass
class Balance:
    asset: str
    available: float
    total: float


@dataclass
class Position:
    symbol: str
    side: str
    size: float
    entry_price: float
    unrealized_pnl: float


class RateLimiter:
    def __init__(self, rps: int = 10):
        self.min_interval = 1.0 / rps
        self.last = 0
        self.lock = threading.Lock()
    
    def wait(self):
        with self.lock:
            elapsed = time.time() - self.last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last = time.time()


class DeltaExchangeClient:
    """Production Delta Exchange API client"""
    
    def __init__(self, api_key: str, api_secret: str, 
                 base_url: str = "https://api.india.delta.exchange",
                 timeout: int = 30):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.rate_limiter = RateLimiter(10)
        self._product_cache = {}
        
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=10))
        logger.info(f"Exchange client initialized: {base_url}")
    
    def _sign(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        ts = str(int(time.time()))
        sig = hmac.new(self.api_secret.encode(), 
                       (method + ts + path + body).encode(), 
                       hashlib.sha256).hexdigest()
        return {"api-key": self.api_key, "timestamp": ts, "signature": sig, "Content-Type": "application/json"}
    
    def _request(self, method: str, path: str, body: Optional[Dict] = None) -> Dict:
        self.rate_limiter.wait()
        url = f"{self.base_url}{path}"
        body_str = json.dumps(body) if body else ""
        headers = self._sign(method, path, body_str)
        
        if method == "GET":
            r = self.session.get(url, headers=headers, timeout=self.timeout)
        elif method == "POST":
            r = self.session.post(url, headers=headers, data=body_str, timeout=self.timeout)
        else:
            r = self.session.delete(url, headers=headers, timeout=self.timeout)
        
        data = r.json()
        if not data.get("success", True):
            err = data.get("error", {}).get("code", "unknown")
            if "auth" in err or "key" in err or "whitelist" in err:
                raise AuthenticationError(err)
            raise ExchangeError(err)
        return data
    
    def get_balances(self) -> List[Balance]:
        data = self._request("GET", "/v2/wallet/balances")
        return [Balance(i.get("asset_symbol",""), float(i.get("available_balance",0)), 
                        float(i.get("balance",0))) for i in data.get("result", [])]
    
    def get_positions(self) -> List[Position]:
        data = self._request("GET", "/v2/positions")
        return [Position(i.get("product_symbol",""), 
                        "long" if float(i.get("size",0)) > 0 else "short",
                        abs(float(i.get("size",0))), float(i.get("entry_price",0)),
                        float(i.get("unrealized_pnl",0))) 
                for i in data.get("result",[]) if float(i.get("size",0)) != 0]
    
    def test_connection(self) -> bool:
        try:
            self.get_balances()
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
