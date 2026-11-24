"""Persistence into agent-service's own database schema (Alembic revision d3f9a0c15e27).

Optional: with no AGENT_SERVICE_DATABASE_URL, Store() is a no-op and the shim
keeps its ledger in memory only.

  sessions            one row per shim session, agent_id from the container's AGENT_ID
  runs                one row per turn, with usage, model_usage and cost_usd
  events              the run's StoredEvents (user, assistant, result, system)
  transcript_entries  the agent CLI's OWN transcript lines, verbatim, as `entry`.
                      session_key is `<kind>-<worktree basename>/<agent session id>`,
                      and uuid is the record's own id (uuid / id), else `o<byte offset>`.
                      Its unique (session_key, uuid) index deduplicates resyncs. agent_id is
                      stamped from AGENT_ID too: this table has no foreign key to sessions.

A database failure never fails a turn. It is logged, and `last_error` says so.
"""
from __future__ import annotations

import json
import os
import sys
import threading

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:  # the shim still runs without the driver, memory only
    psycopg = None


class Store:
    def __init__(self, url: str | None = None):
        self.url = url or os.environ.get("AGENT_SERVICE_DATABASE_URL")
        self.enabled = bool(self.url and psycopg)
        self.last_error: str | None = None
        self._lock = threading.Lock()
        self._conn = None

    def _c(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.url, autocommit=True)
        return self._conn

    def _do(self, sql: str, params=(), fetch: bool = False):
        if not self.enabled:
            return None
        try:
            with self._lock:
                cur = self._c().execute(sql, params)
                return cur.fetchall() if fetch else cur.rowcount
        except Exception as e:  # noqa: BLE001 -- persistence must not fail the turn
            self.last_error = repr(e)
            sys.stderr.write(f"store: {e!r}\n")
            try:
                self._conn and self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None
            return None

    # ---- writes

    def upsert_session(self, s: dict) -> None:
        self._do("""INSERT INTO sessions (id, sdk_session_id, title, status, model, permission_mode, created_at,
                                          last_used_at, closed_at, total_cost_usd, total_turns, agent_id)
                    VALUES (%s, %s, %s, %s, %s, %s, to_timestamp(%s), to_timestamp(%s),
                            CASE WHEN %s = 'closed' THEN now() END, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET sdk_session_id = EXCLUDED.sdk_session_id, status = EXCLUDED.status,
                        model = EXCLUDED.model, last_used_at = EXCLUDED.last_used_at,
                        closed_at = COALESCE(sessions.closed_at, EXCLUDED.closed_at),
                        total_cost_usd = EXCLUDED.total_cost_usd, total_turns = EXCLUDED.total_turns""",
                 (s["session_id"], s.get("sdk_session_id"), f"{s['kind']}:{s['cwd']}", s["status"],
                  s.get("model") or s["options"].get("model"), s["options"].get("permission_mode"),
                  s["created_at"], s["last_used_at"], s["status"], s.get("total_cost_usd"), s["turns"],
                  os.environ.get("AGENT_ID") or None))

    def insert_run(self, r: dict) -> None:
        self._do("INSERT INTO runs (id, session_id, sdk_session_id, prompt) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                 (r["run_id"], r["session_id"], r.get("sdk_session_id"), r["prompt"]))

    def finish_run(self, r: dict) -> None:
        self._do("""UPDATE runs SET sdk_session_id = %s, finished_at = now(), result_text = %s, result_subtype = %s,
                        duration_ms = %s, cost_usd = %s, usage = %s, model_usage = %s, errors = %s, is_error = %s,
                        interrupted = %s, timed_out = %s, outcome_missing = %s
                    WHERE id = %s""",
                 (r.get("sdk_session_id"), r.get("result_text"), r.get("result_subtype"), r.get("duration_ms"),
                  r.get("cost_usd"), _j(r.get("usage")), _j(r.get("model_usage")), _j(r.get("errors")),
                  r.get("is_error"), bool(r.get("interrupted")), bool(r.get("timed_out")),
                  bool(r.get("outcome_missing")), r["run_id"]))

    def insert_event(self, e: dict) -> None:
        self._do("INSERT INTO events (run_id, seq, type, subtype, content) VALUES (%s, %s, %s, %s, %s) "
                 "ON CONFLICT (run_id, seq) DO NOTHING",
                 (e["run_id"], e["seq"], e["type"], e["subtype"], _j(e["content"])))

    def insert_transcript(self, session_key: str, entries: list[tuple[str, dict]], agent_id: str | None = None) -> int:
        n = 0
        for uuid, entry in entries:
            got = self._do("INSERT INTO transcript_entries (session_key, uuid, entry, agent_id) VALUES (%s, %s, %s, %s) "
                           "ON CONFLICT (session_key, uuid) WHERE uuid IS NOT NULL DO NOTHING",
                           (session_key, uuid, Jsonb(entry), agent_id))
            n += got or 0
        return n

    # ---- reads (what survives a shim restart)

    def usable(self) -> bool:
        """`/healthz`'s `database_usable`: one round trip, now."""
        return self._do("SELECT 1", fetch=True) == [(1,)]

    def has_session(self, session_id: str) -> bool:
        return bool(self._do("SELECT 1 FROM sessions WHERE id = %s", (session_id,), fetch=True))

    def get_run(self, run_id: str) -> dict | None:
        rows = self._do("""SELECT id, session_id, sdk_session_id, started_at, finished_at, prompt, result_text,
                                  result_subtype, duration_ms, cost_usd, usage, model_usage, errors, is_error,
                                  interrupted, timed_out, outcome_missing
                           FROM runs WHERE id = %s""", (run_id,), fetch=True)
        if not rows:
            return None
        (rid, sid, sdk, started, finished, prompt, text, sub, dur, cost, usage, mu, errs, is_err, intr, to, om) = rows[0]
        # A run with no finish row was cut off by a restart: nothing is still driving it.
        return {"run_id": rid, "session_id": sid, "sdk_session_id": sdk, "started_at": started.isoformat(),
                "finished_at": finished.isoformat() if finished else None, "prompt": prompt,
                "state": "ended" if finished else "lost", "result_text": text, "result_subtype": sub,
                "duration_ms": dur, "cost_usd": float(cost) if cost is not None else None, "usage": usage,
                "model_usage": mu, "errors": errs, "is_error": is_err, "interrupted": intr, "timed_out": to,
                "outcome_missing": om, "source": "database"}

    def events_of_session(self, session_id: str, after: int, limit: int) -> list[dict]:
        rows = self._do("""SELECT e.id, e.run_id, e.seq, e.at, e.type, e.subtype, e.content FROM events e
                           JOIN runs r ON r.id = e.run_id WHERE r.session_id = %s AND e.id > %s
                           ORDER BY e.id LIMIT %s""", (session_id, after, limit), fetch=True) or []
        return [{"id": i, "run_id": r, "seq": s, "at": a.isoformat(), "type": t, "subtype": st, "content": c}
                for (i, r, s, a, t, st, c) in rows]

    def transcript_entries(self, session_key: str, after: int, limit: int) -> list[dict]:
        rows = self._do("SELECT seq, uuid, at, entry FROM transcript_entries WHERE session_key = %s AND seq > %s "
                        "ORDER BY seq LIMIT %s", (session_key, after, limit), fetch=True) or []
        return [{"seq": s, "uuid": u, "at": a.isoformat(), "entry": e} for (s, u, a, e) in rows]


def _j(v):
    return None if v is None else Jsonb(v)
