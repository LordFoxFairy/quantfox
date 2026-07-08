import json
import sqlite3
from pathlib import Path

import pandas as pd


class Ledger:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        c = self._conn()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS predictions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TEXT, symbol TEXT, type TEXT, signal TEXT, signal_numeric INTEGER,
              confidence REAL, horizons TEXT, price_ref REAL, evidence_json TEXT,
              rationale TEXT, framework_version TEXT, schema_version TEXT
            );
            CREATE TABLE IF NOT EXISTS outcomes (
              prediction_id INTEGER, horizon INTEGER, realized_return REAL,
              excess REAL, hit INTEGER,
              PRIMARY KEY (prediction_id, horizon)
            );
            """
        )
        c.commit()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def log_signal(
        self, *, symbol, type, signal, signal_numeric, confidence, horizons,
        price_ref, evidence_json, rationale, framework_version, schema_version, ts,
    ) -> int:
        c = self._conn()
        cur = c.execute(
            "INSERT INTO predictions (ts,symbol,type,signal,signal_numeric,confidence,horizons,"
            "price_ref,evidence_json,rationale,framework_version,schema_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, symbol, type, signal, signal_numeric, confidence, json.dumps(horizons),
             price_ref, evidence_json, rationale, framework_version, schema_version),
        )
        c.commit()
        return cur.lastrowid

    def compute_outcomes(self, prediction_id, price_series: pd.DataFrame, benchmark_series=None):
        c = self._conn()
        row = c.execute("SELECT * FROM predictions WHERE id=?", (prediction_id,)).fetchone()
        if row is None:
            return []
        horizons = json.loads(row["horizons"])
        ref = row["price_ref"]
        sign = row["signal_numeric"]
        s = price_series.reset_index(drop=True)
        pos = s.index[s["date"] > row["ts"]]
        start = int(pos[0]) if len(pos) else 0
        results = []
        for h in horizons:
            idx = start + h
            if idx >= len(s):
                continue
            realized = float(s["value"].iloc[idx] / ref - 1.0)
            if sign == 0:
                hit = 1 if abs(realized) < 0.01 else 0
            else:
                hit = 1 if (realized > 0) == (sign > 0) else 0
            c.execute(
                "INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?,?)",
                (prediction_id, h, realized, None, hit),
            )
            results.append({"horizon": h, "realized_return": realized, "excess": None, "hit": hit})
        c.commit()
        return results

    def track_record_for(self, symbol):
        c = self._conn()
        rows = c.execute(
            "SELECT o.hit, o.realized_return, p.signal_numeric FROM outcomes o "
            "JOIN predictions p ON p.id=o.prediction_id WHERE p.symbol=?",
            (symbol,),
        ).fetchall()
        n_pred = c.execute(
            "SELECT COUNT(*) n FROM predictions WHERE symbol=?", (symbol,)
        ).fetchone()["n"]
        if not rows:
            if n_pred == 0:
                return None
            return {"past_signals": n_pred, "hit_rate": None, "ic": None, "vs_benchmark": None}
        hits = [r["hit"] for r in rows]
        hit_rate = sum(hits) / len(hits)
        ic = None
        if len(rows) >= 3:
            sn = pd.Series([r["signal_numeric"] for r in rows], dtype=float)
            rr = pd.Series([r["realized_return"] for r in rows], dtype=float)
            ic = None if sn.std() == 0 or rr.std() == 0 else float(sn.corr(rr))
        return {"past_signals": n_pred, "hit_rate": hit_rate, "ic": ic, "vs_benchmark": None}

    def review(self, symbol=None, since_version=None):
        c = self._conn()
        q = (
            "SELECT p.symbol, o.hit, o.realized_return, p.signal_numeric, p.confidence "
            "FROM outcomes o JOIN predictions p ON p.id=o.prediction_id WHERE 1=1"
        )
        args = []
        if symbol:
            q += " AND p.symbol=?"
            args.append(symbol)
        if since_version:
            q += " AND p.framework_version>=?"
            args.append(since_version)
        rows = c.execute(q, args).fetchall()
        if not rows:
            return {"n": 0, "note": "暂无已到期的预测，数据不足"}
        hits = [r["hit"] for r in rows]
        return {
            "n": len(rows),
            "hit_rate": sum(hits) / len(hits),
            "note": "样本量小，仅供参考" if len(rows) < 20 else "ok",
        }
