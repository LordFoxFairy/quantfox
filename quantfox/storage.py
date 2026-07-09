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

    def calibration(self, symbol=None):
        """按当时信心分桶，看真实命中率——衡量"说 80% 把握时是否真 80% 对"。"""
        c = self._conn()
        q = ("SELECT p.confidence AS conf, o.hit AS hit FROM outcomes o "
             "JOIN predictions p ON p.id=o.prediction_id WHERE p.confidence IS NOT NULL")
        args = []
        if symbol:
            q += " AND p.symbol=?"
            args.append(symbol)
        rows = c.execute(q, args).fetchall()
        edges = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 1.01)]
        buckets = []
        for lo, hi in edges:
            sub = [r for r in rows if lo <= r["conf"] < hi]
            label = f"{lo:.2f}-{min(hi, 1.0):.2f}"
            if not sub:
                buckets.append({"range": label, "n": 0, "avg_confidence": None,
                                "hit_rate": None, "gap": None})
                continue
            hr = sum(r["hit"] for r in sub) / len(sub)
            ac = sum(r["conf"] for r in sub) / len(sub)
            buckets.append({"range": label, "n": len(sub),
                            "avg_confidence": round(ac, 3), "hit_rate": round(hr, 3),
                            "gap": round(ac - hr, 3)})
        return {"n": len(rows), "buckets": buckets,
                "note": "gap>0=过度自信(说得比做得好)，<0=过度保守；理想≈0。样本<20 仅供参考"}
