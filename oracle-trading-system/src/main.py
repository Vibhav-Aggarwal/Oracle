#!/usr/bin/env python3
"""
Oracle Trading Engine - Production Main Entry Point
"""

import signal
import sys
import time
import logging
from typing import Optional, Dict, Any
from datetime import datetime
import threading

from .config import load_config, Config
from .logger import setup_logging, TradeLogger
from .exchange import DeltaExchangeClient
from .strategy import OracleStrategy, Signal
from .risk_manager import RiskManager, RiskAction, Position
from .metrics import init_metrics, TradingMetrics

__version__ = "2.0.0"


class OracleTradingEngine:
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.trade_logger = TradeLogger()
        self.exchange: Optional[DeltaExchangeClient] = None
        self.strategy: Optional[OracleStrategy] = None
        self.risk_manager: Optional[RiskManager] = None
        self.metrics: Optional[TradingMetrics] = None
        self._running = False
        self._healthy = False
        self._last_heartbeat = datetime.utcnow()
        self._trade_count = 0
        self._start_time: Optional[datetime] = None
        self._shutdown_event = threading.Event()
        self._wins = 0
        self._losses = 0
        self._consecutive_losses = 0
        self._peak_balance = 0
        self._total_pnl = 0
        self._daily_pnl = 0

    def _setup_signal_handlers(self) -> None:
        def handler(signum, frame):
            self.logger.info(f"Received signal {signum}, shutting down...")
            self._shutdown_event.set()
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def initialize(self) -> bool:
        self.logger.info("=" * 60)
        self.logger.info(f"Oracle Trading Engine v{__version__}")
        self.logger.info("=" * 60)
        try:
            # Initialize metrics server
            self.logger.info("Initializing metrics server...")
            self.metrics = init_metrics(port=self.config.monitoring.prometheus_port)

            self.logger.info("Initializing exchange client...")
            self.exchange = DeltaExchangeClient(
                api_key=self.config.exchange.api_key,
                api_secret=self.config.exchange.api_secret,
                base_url=self.config.exchange.base_url,
                timeout=self.config.exchange.timeout
            )
            if not self.exchange.test_connection():
                self.logger.error("Exchange connection test failed")
                return False
            balances = self.exchange.get_balances()
            usdt = next((b for b in balances if b.asset == "USDT"), None)
            if usdt:
                self.logger.info(f"Balance: ${usdt.available:.2f} USDT")
                self._peak_balance = usdt.available
                self.metrics.update_balance(usdt.available)
            self.logger.info("Initializing strategy...")
            self.strategy = OracleStrategy(self.config)
            self.logger.info("Initializing risk manager...")
            self.risk_manager = RiskManager(self.config)
            if usdt:
                self.risk_manager.update_equity(usdt.available)
            self._healthy = True
            self.logger.info("Initialization complete!")
            return True
        except Exception as e:
            self.logger.exception(f"Initialization failed: {e}")
            return False

    def _process_signal(self, symbol: str) -> None:
        if not self.strategy or not self.risk_manager:
            return
        start_time = time.time()
        positions = self.risk_manager.get_positions()
        current = positions.get(symbol)
        side = current.side if current else None
        sig = self.strategy.generate_signal(symbol, side)

        # Record signal latency
        latency = time.time() - start_time
        self.metrics.signal_latency.observe(latency)

        if sig.signal == Signal.HOLD:
            return

        # Record signal generation
        self.metrics.record_signal(symbol, sig.signal.value)
        self.trade_logger.log_signal(symbol, sig.signal.value, sig.indicators)

        if sig.signal in [Signal.LONG, Signal.SHORT]:
            self._execute_entry(sig)
        elif sig.signal in [Signal.EXIT_LONG, Signal.EXIT_SHORT]:
            self._execute_exit(symbol, sig)

    def _execute_entry(self, sig) -> None:
        symbol = sig.symbol
        side = "buy" if sig.signal == Signal.LONG else "sell"
        balances = self.exchange.get_balances()
        usdt = next((b for b in balances if b.asset == "USDT"), None)
        if not usdt or usdt.available < 10:
            self.logger.warning("Insufficient balance")
            return
        size = self.strategy.calculate_position_size(usdt.available, sig.price)
        action, reason = self.risk_manager.check_trade_allowed(symbol, size, side)
        if action == RiskAction.BLOCK:
            self.logger.info(f"Trade blocked: {reason}")
            return
        if action == RiskAction.CLOSE_ALL:
            self._close_all_positions("Risk limit exceeded")
            return
        if action == RiskAction.REDUCE_SIZE:
            size = self.risk_manager.get_adjusted_size(size)
        try:
            trade_id = f"oracle_{int(time.time()*1000)}"
            order = self.exchange.place_order(symbol, side, size, "market")
            if order:
                entry = sig.price
                sl = self.strategy.get_stop_loss_price(entry, side)
                tp = self.strategy.get_take_profit_price(entry, side)
                pos = Position(symbol, side, entry, size, datetime.utcnow(), sl, tp, trade_id)
                self.risk_manager.register_position(pos)
                self.trade_logger.log_entry(symbol, side, entry, size, sig.reason, trade_id)
                self._trade_count += 1

                # Update metrics
                positions_count = len(self.risk_manager.get_positions())
                self.metrics.update_positions(positions_count)

                self.logger.info(f"Opened {side.upper()} {symbol} @ {entry:.4f}")
        except Exception as e:
            self.logger.exception(f"Entry failed: {e}")

    def _execute_exit(self, symbol: str, sig) -> None:
        positions = self.risk_manager.get_positions()
        pos = positions.get(symbol)
        if not pos:
            return
        try:
            close_side = "sell" if pos.side == "buy" else "buy"
            order = self.exchange.place_order(symbol, close_side, pos.size, "market")
            if order:
                exit_price = sig.price
                if pos.side == "buy":
                    pnl = (exit_price - pos.entry_price) * pos.size
                else:
                    pnl = (pos.entry_price - exit_price) * pos.size

                # Update trade statistics
                self._total_pnl += pnl
                self._daily_pnl += pnl
                if pnl > 0:
                    self._wins += 1
                    self._consecutive_losses = 0
                else:
                    self._losses += 1
                    self._consecutive_losses += 1

                # Record metrics
                self.metrics.record_trade(symbol, pos.side, pnl)
                win_rate = self._wins / (self._wins + self._losses) if (self._wins + self._losses) > 0 else 0
                self.metrics.update_performance(win_rate, self._consecutive_losses)
                self.metrics.update_pnl(self._daily_pnl, self._total_pnl)

                # Update position count
                self.risk_manager.close_position(symbol, exit_price, pnl, sig.reason)
                positions_count = len(self.risk_manager.get_positions())
                self.metrics.update_positions(positions_count)

                self.trade_logger.log_exit(symbol, pos.trade_id, exit_price, pos.entry_price, pnl, sig.reason)
                self.logger.info(f"Closed {symbol} @ {exit_price:.4f} PnL: {pnl:+.2f}")
        except Exception as e:
            self.logger.exception(f"Exit failed: {e}")

    def _close_all_positions(self, reason: str) -> None:
        for symbol, pos in self.risk_manager.get_positions().items():
            try:
                close_side = "sell" if pos.side == "buy" else "buy"
                self.exchange.place_order(symbol, close_side, pos.size, "market")
                self.logger.warning(f"Closed {symbol}: {reason}")
            except Exception as e:
                self.logger.error(f"Failed close {symbol}: {e}")

    def _main_loop(self) -> None:
        self.logger.info("Starting main loop...")
        symbols = self.config.trading.symbols
        while not self._shutdown_event.is_set():
            try:
                balances = self.exchange.get_balances()
                usdt = next((b for b in balances if b.asset == "USDT"), None)
                if usdt:
                    self.risk_manager.update_equity(usdt.available)

                    # Update metrics
                    self.metrics.update_balance(usdt.available)
                    if usdt.available > self._peak_balance:
                        self._peak_balance = usdt.available

                    # Calculate drawdown from peak
                    if self._peak_balance > 0:
                        drawdown = (self._peak_balance - usdt.available) / self._peak_balance
                        # Track max drawdown separately
                        if not hasattr(self, '_max_drawdown'):
                            self._max_drawdown = 0
                        self._max_drawdown = max(self._max_drawdown, drawdown)
                        self.metrics.update_drawdown(drawdown, self._max_drawdown)

                for symbol in symbols:
                    if self._shutdown_event.is_set():
                        break
                    self._process_signal(symbol)

                # Update health metrics
                uptime = (datetime.utcnow() - self._start_time).total_seconds() if self._start_time else 0
                self.metrics.update_health(self._healthy, uptime)

                self._last_heartbeat = datetime.utcnow()
                self._shutdown_event.wait(60)
            except Exception as e:
                self.logger.exception(f"Loop error: {e}")
                self._healthy = False
                self.metrics.update_health(False, 0)
                time.sleep(10)
                self._healthy = True

    def run(self) -> int:
        self._setup_signal_handlers()
        if not self.initialize():
            return 1
        self._running = True
        self._start_time = datetime.utcnow()
        try:
            self._main_loop()
        except Exception as e:
            self.logger.exception(f"Fatal: {e}")
            return 1
        finally:
            self.shutdown()
        return 0

    def shutdown(self) -> None:
        self.logger.info("Shutting down...")
        self._running = False
        self._healthy = False
        if self.config.trading.close_on_shutdown:
            self._close_all_positions("Shutdown")
        if self._start_time:
            self.logger.info(f"Uptime: {datetime.utcnow() - self._start_time}")
            self.logger.info(f"Trades: {self._trade_count}")
        self.logger.info("Shutdown complete")

    def get_health(self) -> Dict[str, Any]:
        return {
            "healthy": self._healthy,
            "running": self._running,
            "uptime": (datetime.utcnow() - self._start_time).total_seconds() if self._start_time else 0,
            "trades": self._trade_count,
            "version": __version__
        }


def main():
    config = load_config()
    setup_logging(config.logging.log_dir, config.logging.level, config.logging.json_format, True)
    logger = logging.getLogger(__name__)
    engine = OracleTradingEngine(config)
    try:
        sys.exit(engine.run())
    except KeyboardInterrupt:
        logger.info("Interrupted")
        engine.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
