import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def round_trip_cost(horizon_trading_days: int, asset_type: str, subscribe: float = 0.0015) -> float:
    """往返交易成本估计（诚实扣钱）。
    场外基金：申购费(打折~0.15%) + 按持有期的赎回费（7日内 1.5% 是硬伤）。
    黄金：用买卖价差近似。交易日→自然日约 *1.4。
    """
    if asset_type == "gold":
        return 0.004
    cal = horizon_trading_days * 1.4
    if cal < 7:
        redeem = 0.015
    elif cal < 30:
        redeem = 0.005
    elif cal < 365:
        redeem = 0.0025
    else:
        redeem = 0.0
    return round(subscribe + redeem, 4)


def classify_delta(delta: float) -> str:
    """对账判定：|delta|≤0.05 元四舍五入误差；≤0.5 元口径小差；再大就是真不对。"""
    a = abs(delta)
    if a <= 0.05:
        return "ok"
    if a <= 0.5:
        return "rounding"
    return "mismatch"


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
              rationale TEXT, framework_version TEXT, schema_version TEXT,
              created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS outcomes (
              prediction_id INTEGER, horizon INTEGER,
              gross_return REAL, cost REAL, realized_return REAL, base_up REAL, hit INTEGER,
              PRIMARY KEY (prediction_id, horizon)
            );
            CREATE TABLE IF NOT EXISTS holdings (
              symbol TEXT PRIMARY KEY, type TEXT, status TEXT,
              entry_price REAL, entry_date TEXT, target_price REAL, note TEXT
            );
            CREATE TABLE IF NOT EXISTS lots (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              symbol TEXT, type TEXT, amount REAL, order_date TEXT,
              confirm_nav REAL, shares REAL, confirm_date TEXT, note TEXT
            );
            CREATE TABLE IF NOT EXISTS reconciliations (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              symbol TEXT NOT NULL,
              trade_date TEXT NOT NULL,
              expected_daily_pnl REAL,
              app_daily_pnl REAL,
              delta REAL,
              expected_total_pnl REAL,
              verdict TEXT,
              note TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alerts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              symbol TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
              message TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS report_issues (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              issue_date TEXT NOT NULL, board TEXT NOT NULL, rank INTEGER NOT NULL,
              symbol TEXT NOT NULL, name TEXT, nav_at_issue REAL, created_at TEXT NOT NULL
            );
            """
        )
        cols = [r["name"] for r in c.execute("PRAGMA table_info(predictions)").fetchall()]
        if "created_at" not in cols:
            c.execute("ALTER TABLE predictions ADD COLUMN created_at TEXT")
        c.commit()

    # --- 监控清单（两态：watching 观测找买点 / holding 持有看离场）---
    def add_watching(self, symbol, type, target_price=None, note=""):
        c = self._conn()
        c.execute(
            "INSERT OR REPLACE INTO holdings (symbol,type,status,entry_price,entry_date,target_price,note) "
            "VALUES (?,?,'watching',NULL,NULL,?,?)", (symbol, type, target_price, note))
        c.commit()

    def mark_bought(self, symbol, type, entry_price, entry_date, note=""):
        c = self._conn()
        cur = c.execute(
            "UPDATE holdings SET status='holding',entry_price=?,entry_date=? WHERE symbol=?",
            (entry_price, entry_date, symbol))
        if cur.rowcount == 0:
            c.execute(
                "INSERT INTO holdings (symbol,type,status,entry_price,entry_date,target_price,note) "
                "VALUES (?,?,'holding',?,?,NULL,?)", (symbol, type, entry_price, entry_date, note))
        c.commit()

    def list_holdings(self):
        c = self._conn()
        return [dict(r) for r in c.execute("SELECT * FROM holdings ORDER BY status,symbol").fetchall()]

    def remove_holding(self, symbol):
        c = self._conn()
        cur = c.execute("DELETE FROM holdings WHERE symbol=?", (symbol,))
        c.execute("DELETE FROM lots WHERE symbol=?", (symbol,))  # 连带清掉分笔
        c.commit()
        return cur.rowcount

    # --- 按金额分笔记账（lots）：支持多笔分批建仓，聚合出加权成本 ---
    def add_lot(self, symbol, type, amount, confirm_nav, order_date, confirm_date=None, note=""):
        """记一笔买入：金额 + 支付宝确认净值 → 份额。追加不覆盖；自动更新持仓加权成本。"""
        shares = round(amount / confirm_nav, 4) if confirm_nav else None
        c = self._conn()
        c.execute(
            "INSERT INTO lots (symbol,type,amount,order_date,confirm_nav,shares,confirm_date,note) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (symbol, type, amount, order_date, confirm_nav, shares, confirm_date or order_date, note))
        c.commit()
        self._recompute_holding(symbol, type)
        return shares

    def list_lots(self, symbol):
        c = self._conn()
        return [dict(r) for r in
                c.execute("SELECT * FROM lots WHERE symbol=? ORDER BY order_date, id", (symbol,)).fetchall()]

    def _recompute_holding(self, symbol, type):
        lots = self.list_lots(symbol)
        if not lots:
            return
        confirmed = [x for x in lots if x["shares"]]
        if not confirmed:
            return  # 全是 pending：净值未出，不动持仓成本
        tot_amt = sum(x["amount"] for x in confirmed if x["amount"])
        tot_sh = sum(x["shares"] for x in confirmed)
        wcost = round(tot_amt / tot_sh, 4) if tot_sh else None
        first = min(x["order_date"] for x in confirmed)
        c = self._conn()
        cur = c.execute("UPDATE holdings SET status='holding',entry_price=?,entry_date=? WHERE symbol=?",
                        (wcost, first, symbol))
        if cur.rowcount == 0:
            c.execute("INSERT INTO holdings (symbol,type,status,entry_price,entry_date,target_price,note) "
                      "VALUES (?,?,'holding',?,?,NULL,'')", (symbol, type, wcost, first))
        c.commit()

    def position(self, symbol, latest_nav=None):
        """持仓聚合：总金额/总份额/加权成本；给 latest_nav 则算现值与浮盈亏。"""
        lots = self.list_lots(symbol)
        if not lots:
            return None
        confirmed = [x for x in lots if x["shares"]]
        pending = [x for x in lots if not x["shares"]]
        tot_amt = round(sum(x["amount"] for x in confirmed if x["amount"]), 2)
        tot_sh = round(sum(x["shares"] for x in confirmed), 4)
        wcost = round(tot_amt / tot_sh, 4) if tot_sh else None
        out = {"symbol": symbol, "lots": lots, "total_amount": tot_amt,
               "total_shares": tot_sh, "weighted_cost": wcost, "pending_lots": pending}
        if pending:
            out["pending_note"] = f"{len(pending)} 笔净值未出（不计成本），出值后 quantfox watch confirm {symbol} 补记"
        if latest_nav and tot_sh:
            cur_val = round(tot_sh * latest_nav, 2)
            out.update({"latest_nav": latest_nav, "current_value": cur_val,
                        "pnl": round(cur_val - tot_amt, 2),
                        "pnl_pct": round(cur_val / tot_amt - 1, 4) if tot_amt else None})
        return out

    def pending_lots(self, symbol=None):
        c = self._conn()
        q = "SELECT * FROM lots WHERE shares IS NULL"
        args = []
        if symbol:
            q += " AND symbol=?"
            args.append(symbol)
        return [dict(r) for r in c.execute(q + " ORDER BY order_date, id", args).fetchall()]

    def fill_lot(self, lot_id, nav):
        """补记 pending lot：净值公布后回填份额。已确认的拒绝改（成本不可覆盖）。"""
        c = self._conn()
        row = c.execute("SELECT * FROM lots WHERE id=?", (lot_id,)).fetchone()
        if row is None or row["shares"] is not None:
            return None
        shares = round(row["amount"] / nav, 4)
        c.execute("UPDATE lots SET confirm_nav=?, shares=? WHERE id=?", (nav, shares, lot_id))
        c.commit()
        self._recompute_holding(row["symbol"], row["type"])
        return shares

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
            "price_ref,evidence_json,rationale,framework_version,schema_version,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, symbol, type, signal, signal_numeric, confidence, json.dumps(horizons),
             price_ref, evidence_json, rationale, framework_version, schema_version,
             datetime.now(timezone.utc).isoformat()),
        )
        c.commit()
        return cur.lastrowid

    def compute_outcomes(self, prediction_id, price_series: pd.DataFrame):
        c = self._conn()
        row = c.execute("SELECT * FROM predictions WHERE id=?", (prediction_id,)).fetchone()
        if row is None:
            return []
        horizons = json.loads(row["horizons"])
        sign = row["signal_numeric"]
        atype = row["type"]
        s = price_series.reset_index(drop=True)
        full = s["value"].astype(float)
        pos = s.index[s["date"] > row["ts"]]
        if not len(pos):
            return []  # 没有预测日之后的价格 → 无法结算，绝不用序列开头乱算污染账本
        start = int(pos[0])
        entry = float(s["value"].iloc[start])  # 实际可成交净值（决策后第一个交易日，修 T+1 错位）
        results = []
        for h in horizons:
            idx = start + h
            if idx >= len(s):
                continue
            gross = float(s["value"].iloc[idx] / entry - 1.0)
            # 买入才扣往返成本；回避/观望不产生交易成本
            cost = round_trip_cost(h, atype) if sign > 0 else 0.0
            net = round(gross - cost, 6)
            # 基准上涨基率：全序列 h 期前瞻收益为正的比例（去"牛市啥都涨"的虚高）
            fwd = full.shift(-h) / full - 1.0
            base_up = float((fwd.dropna() > 0).mean()) if fwd.notna().any() else 0.5
            if sign == 0:
                hit = 1 if abs(gross) < 0.01 else 0
            elif sign > 0:
                hit = 1 if net > 0 else 0          # 买：净收益(扣成本)为正才算赢
            else:
                hit = 1 if gross < 0 else 0        # 回避/减：标的下跌才算避对
            c.execute("INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?,?,?,?)",
                      (prediction_id, h, round(gross, 6), cost, net, round(base_up, 4), hit))
            results.append({"horizon": h, "gross_return": round(gross, 6), "cost": cost,
                            "realized_return": net, "base_up": round(base_up, 4), "hit": hit})
        c.commit()
        return results

    def _agg(self, rows):
        hits = [r["hit"] for r in rows]
        hit_rate = sum(hits) / len(hits)
        nets = [r["realized_return"] for r in rows if r["realized_return"] is not None]
        base = [r["base_up"] for r in rows if r["base_up"] is not None]
        avg_net = round(sum(nets) / len(nets), 4) if nets else None
        base_up = round(sum(base) / len(base), 4) if base else None
        # edge = 我们的命中率 − 无条件上涨基率（≈0 表示没本事，只是跟大盘涨）
        edge = round(hit_rate - base_up, 4) if base_up is not None else None
        return hit_rate, avg_net, base_up, edge

    def track_record_for(self, symbol):
        c = self._conn()
        rows = c.execute(
            "SELECT o.hit, o.realized_return, o.base_up, p.signal_numeric FROM outcomes o "
            "JOIN predictions p ON p.id=o.prediction_id WHERE p.symbol=?", (symbol,),
        ).fetchall()
        n_pred = c.execute("SELECT COUNT(*) n FROM predictions WHERE symbol=?", (symbol,)).fetchone()["n"]
        if not rows:
            return None if n_pred == 0 else {"past_signals": n_pred, "hit_rate": None,
                                             "ic": None, "net_return": None, "edge_vs_baserate": None}
        hit_rate, avg_net, base_up, edge = self._agg(rows)
        ic = None
        if len(rows) >= 3:
            sn = pd.Series([r["signal_numeric"] for r in rows], dtype=float)
            rr = pd.Series([r["realized_return"] for r in rows], dtype=float)
            ic = None if sn.std() == 0 or rr.std() == 0 else round(float(sn.corr(rr)), 4)
        return {"past_signals": n_pred, "hit_rate": round(hit_rate, 4), "ic": ic,
                "net_return": avg_net, "base_up_rate": base_up, "edge_vs_baserate": edge}

    def review(self, symbol=None, since_version=None):
        c = self._conn()
        q = ("SELECT o.prediction_id, o.hit, o.realized_return, o.base_up, p.signal_numeric AS sn FROM outcomes o "
             "JOIN predictions p ON p.id=o.prediction_id WHERE 1=1")
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
        hit_rate, avg_net, base_up, edge = self._agg(rows)
        n_predictions = len({r["prediction_id"] for r in rows})

        def sub(rs):
            if not rs:
                return None
            hr, net, bu, e = self._agg(rs)
            return {"n": len({r["prediction_id"] for r in rs}), "n_outcomes": len(rs),
                    "hit_rate": round(hr, 4), "net_return": net, "edge_vs_baserate": e}

        return {
            "n": n_predictions,
            "n_outcomes": len(rows),
            "hit_rate": round(hit_rate, 4),
            "net_return": avg_net,
            "base_up_rate": base_up,
            "edge_vs_baserate": edge,
            "buy": sub([r for r in rows if r["sn"] > 0]),      # 买入信号：net_return 是真实资金胜率/收益
            "avoid": sub([r for r in rows if r["sn"] < 0]),    # 回避信号：net_return 是"避开的跌幅"，非资金收益
            "note": ("买入看 buy.net_return（真实资金）；回避看方向对不对，其 net 非资金收益。"
                     "edge=命中率−无条件上涨基率，≈0=只是跟涨。"
                     + ("样本<20 仅供参考。" if len(rows) < 20 else "")),
        }

    def calibration(self, symbol=None):
        """按当时信心分桶，看真实(扣成本后)命中率——衡量"说 80% 把握时是否真 80% 对"。"""
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
                "note": "命中率已扣成本；gap>0=过度自信，<0=过度保守；理想≈0。样本<20 仅供参考"}

    # --- 对账留痕（append-only）：预期收益/对账结论必须落库，不许只留在对话里 ---
    def daily_expectation(self, symbol, prices: pd.DataFrame):
        """t 日预期当日收益 = confirm_date < t 的已确认份额 × (nav_t − nav_{t−1})（对齐 App 口径：
        确认当日不计当日盈亏）。累计浮盈亏只算已确认笔。"""
        lots = [x for x in self.list_lots(symbol) if x["shares"]]
        if not lots or prices is None or len(prices) < 2:
            return None
        s = prices.reset_index(drop=True)
        dates = s["date"].astype(str).str[:10]
        t, prev = dates.iloc[-1], dates.iloc[-2]
        nav_t, nav_prev = float(s["value"].iloc[-1]), float(s["value"].iloc[-2])
        counted = round(sum(x["shares"] for x in lots if (x["confirm_date"] or "") < t), 4)
        all_sh = round(sum(x["shares"] for x in lots), 4)
        invested = round(sum(x["amount"] for x in lots if x["amount"]), 2)
        return {"symbol": symbol, "trade_date": t, "prev_date": prev,
                "expected_daily_pnl": round(counted * (nav_t - nav_prev), 2),
                "expected_total_pnl": round(all_sh * nav_t - invested, 2),
                "shares_counted": counted}

    def add_reconciliation(self, *, symbol, trade_date, expected_daily_pnl=None,
                           app_daily_pnl=None, delta=None, expected_total_pnl=None,
                           verdict="pending", note=""):
        c = self._conn()
        cur = c.execute(
            "INSERT INTO reconciliations (symbol,trade_date,expected_daily_pnl,app_daily_pnl,"
            "delta,expected_total_pnl,verdict,note,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (symbol, trade_date, expected_daily_pnl, app_daily_pnl, delta,
             expected_total_pnl, verdict, note, datetime.now(timezone.utc).isoformat()))
        c.commit()
        return cur.lastrowid

    def reconciliations_for(self, symbol, trade_date=None):
        c = self._conn()
        q = "SELECT * FROM reconciliations WHERE symbol=?"
        args = [symbol]
        if trade_date:
            q += " AND trade_date=?"
            args.append(trade_date)
        return [dict(r) for r in c.execute(q + " ORDER BY id", args).fetchall()]

    def latest_reconciliation(self, symbol):
        c = self._conn()
        r = c.execute("SELECT * FROM reconciliations WHERE symbol=? ORDER BY id DESC LIMIT 1",
                      (symbol,)).fetchone()
        return dict(r) if r else None

    # --- 告警去重状态（append-only）与周报榜单存档 ---
    def add_alert(self, symbol, kind, state, message=""):
        c = self._conn()
        cur = c.execute("INSERT INTO alerts (symbol,kind,state,message,created_at) VALUES (?,?,?,?,?)",
                        (symbol, kind, state, message, datetime.now(timezone.utc).isoformat()))
        c.commit()
        return cur.lastrowid

    def latest_alert(self, symbol, kind):
        c = self._conn()
        r = c.execute("SELECT * FROM alerts WHERE symbol=? AND kind=? ORDER BY id DESC LIMIT 1",
                      (symbol, kind)).fetchone()
        return dict(r) if r else None

    def add_report_issue(self, issue_date, board, rank, symbol, name, nav_at_issue):
        c = self._conn()
        cur = c.execute(
            "INSERT INTO report_issues (issue_date,board,rank,symbol,name,nav_at_issue,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (issue_date, board, rank, symbol, name, nav_at_issue,
             datetime.now(timezone.utc).isoformat()))
        c.commit()
        return cur.lastrowid

    def issues_for(self, issue_date):
        c = self._conn()
        return [dict(r) for r in c.execute(
            "SELECT * FROM report_issues WHERE issue_date=? ORDER BY board, rank",
            (issue_date,)).fetchall()]

    def latest_issue_date(self, before):
        c = self._conn()
        r = c.execute("SELECT MAX(issue_date) d FROM report_issues WHERE issue_date<?",
                      (before,)).fetchone()
        return r["d"] if r and r["d"] else None
