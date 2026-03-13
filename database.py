import sqlite3
import json
import threading
import logging
import time

logger = logging.getLogger("azim-trader.db")
DB_FILE = "azim_trader_state.db"


class StateDatabase:
    def __init__(self):
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.commit()

    def save_state(self, snapshot: dict):
        try:
            with self._lock:
                with sqlite3.connect(DB_FILE) as conn:
                    for key, value in snapshot.items():
                        conn.execute(
                            "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                            (key, json.dumps(value))
                        )
                    conn.commit()
        except Exception as e:
            logger.error(f"DB save error: {e}")

    def load_state(self) -> dict:
        try:
            with sqlite3.connect(DB_FILE) as conn:
                rows = conn.execute("SELECT key, value FROM state").fetchall()
                return {row[0]: json.loads(row[1]) for row in rows}
        except Exception as e:
            logger.error(f"DB load error: {e}")
            return {}

    def start_autosave(self, snapshot_fn, interval=5):
        def _loop():
            while True:
                time.sleep(interval)
                try:
                    self.save_state(snapshot_fn())
                except Exception as e:
                    logger.error(f"Autosave error: {e}")

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
