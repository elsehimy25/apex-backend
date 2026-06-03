"""
apex_sync.py  —  أضف هذا الملف لمجلد Apex POS
يستبدل دالة _cloud_backup ويرسل البيانات للـ cloud API.

الاستخدام داخل ApexPOS:
    from apex_sync import CloudSync
    self.cloud = CloudSync(self.config, self.db)

    # بعد كل عملية بيع:
    threading.Thread(target=self.cloud.push_after_sale, daemon=True).start()

    # عند بدء التشغيل:
    threading.Thread(target=self.cloud.full_sync, daemon=True).start()
"""

import json, os, threading, time, logging
from datetime import datetime, timedelta
from typing import Optional

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

logger = logging.getLogger("ApexSync")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [SYNC] %(message)s")

# ── configuration ────────────────────────────────────────────────
CLOUD_URL = os.getenv("APEX_CLOUD_URL", "http://localhost:8000")
SYNC_EVERY_SECONDS = 60   # sync كل دقيقة في الخلفية


class CloudSync:

    def __init__(self, config: dict, db):
        self.config    = config
        self.db        = db
        self.base_url  = CLOUD_URL.rstrip("/")
        self._token:   Optional[str] = None
        self._lock     = threading.Lock()
        self._last_sync_sales_id   = self._load_cursor("sales")
        self._last_sync_returns_id = self._load_cursor("returns")

        if not REQUESTS_OK:
            logger.warning("'requests' library not installed. Sync disabled.")
            return

        # login
        self._login()

        # background sync thread
        t = threading.Thread(target=self._background_loop, daemon=True)
        t.start()

    # ── auth ─────────────────────────────────────────────────────
    def _login(self):
        username = self.config.get("cloud_user", "admin")
        password = self.config.get("cloud_pass", "admin")
        try:
            r = requests.post(f"{self.base_url}/auth/login",
                              data={"username": username, "password": password},
                              timeout=10)
            if r.status_code == 200:
                self._token = r.json()["access_token"]
                logger.info("Cloud login OK")
            else:
                logger.error(f"Cloud login failed: {r.text}")
        except Exception as e:
            logger.error(f"Cloud login error: {e}")

    def _headers(self):
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    # ── cursor persistence ────────────────────────────────────────
    def _cursor_file(self): return "apex_sync_cursor.json"

    def _load_cursor(self, key):
        try:
            with open(self._cursor_file()) as f:
                return json.load(f).get(key, 0)
        except Exception:
            return 0

    def _save_cursor(self, sales_id, returns_id):
        try:
            with open(self._cursor_file(), "w") as f:
                json.dump({"sales": sales_id, "returns": returns_id}, f)
        except Exception:
            pass

    # ── build payload ────────────────────────────────────────────
    def _build_payload(self, full=False):
        bid = self.config.get("branch_id", 1)

        # new sales since last sync
        if full:
            sales_rows = self.db.fetchall("SELECT * FROM sales ORDER BY id")
        else:
            sales_rows = self.db.fetchall(
                "SELECT * FROM sales WHERE id > ? ORDER BY id",
                (self._last_sync_sales_id,)
            )

        sales = []
        max_sale_id = self._last_sync_sales_id
        for s in sales_rows:
            sales.append({
                "uuid":       s[13], "invoice": s[1],
                "product_id": s[2],  "name":    s[3],
                "barcode":    s[4],  "qty":     s[5],
                "price":      s[6],  "price_buy": s[7],
                "profit":     s[8],  "method":  s[9],
                "cashier":    s[10], "branch_id": s[11],
                "time":       s[12],
            })
            max_sale_id = max(max_sale_id, s[0])

        # new returns
        if full:
            ret_rows = self.db.fetchall("SELECT * FROM returns ORDER BY id")
        else:
            ret_rows = self.db.fetchall(
                "SELECT * FROM returns WHERE id > ? ORDER BY id",
                (self._last_sync_returns_id,)
            )

        returns = []
        max_ret_id = self._last_sync_returns_id
        for r in ret_rows:
            returns.append({
                "return_id":    r[1],  "invoice":      r[2],
                "product_id":   r[3],  "product_name": r[4],
                "barcode":      r[5],  "qty":          r[6],
                "sell_price":   r[7],  "refund_amount":r[8],
                "reason":       r[9],  "method":       r[10],
                "cashier":      r[11], "branch_id":    r[12],
                "time":         r[13],
            })
            max_ret_id = max(max_ret_id, r[0])

        # current stock snapshot
        stock_rows = self.db.fetchall(
            "SELECT product_id, branch_id, qty, reorder_lvl FROM stock WHERE branch_id=?",
            (bid,)
        )
        stock = [{"product_id": s[0], "branch_id": s[1],
                  "qty": s[2], "reorder_lvl": s[3]} for s in stock_rows]

        # products
        prod_rows = self.db.fetchall(
            "SELECT barcode,name,price_buy,price_sell,expiry,category,brand,model,year FROM products"
        )
        products = [{"barcode":p[0],"name":p[1],"price_buy":p[2],
                     "price_sell":p[3],"expiry":p[4],"category":p[5],
                     "brand":p[6],"model":p[7],"year":p[8]} for p in prod_rows]

        return {
            "branch_id": bid,
            "sales":     sales,
            "returns":   returns,
            "stock":     stock,
            "products":  products,
        }, max_sale_id, max_ret_id

    # ── push to cloud ────────────────────────────────────────────
    def _push(self, full=False) -> bool:
        if not REQUESTS_OK or not self._token:
            return False
        try:
            payload, max_sale_id, max_ret_id = self._build_payload(full)
            if not payload["sales"] and not payload["returns"] and not full:
                return True   # nothing new

            r = requests.post(
                f"{self.base_url}/sync/push",
                json=payload,
                headers=self._headers(),
                timeout=30,
            )
            if r.status_code == 200:
                result = r.json()
                logger.info(f"Sync OK — {result['merged']}")
                self._last_sync_sales_id   = max_sale_id
                self._last_sync_returns_id = max_ret_id
                self._save_cursor(max_sale_id, max_ret_id)
                return True
            elif r.status_code == 401:
                self._login()   # token expired, retry next cycle
            else:
                logger.error(f"Sync push failed: {r.status_code} {r.text[:200]}")
        except Exception as e:
            logger.error(f"Sync push error: {e}")
        return False

    # ── public API ───────────────────────────────────────────────
    def push_after_sale(self):
        """Call after every sale/return — runs in a thread."""
        with self._lock:
            self._push()

    def full_sync(self):
        """Full sync — call once on startup."""
        with self._lock:
            self._push(full=True)

    # ── background loop ──────────────────────────────────────────
    def _background_loop(self):
        while True:
            time.sleep(SYNC_EVERY_SECONDS)
            with self._lock:
                self._push()
