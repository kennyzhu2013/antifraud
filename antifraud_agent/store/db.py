"""案例库存储：SQLite + 内嵌向量检索。

MVP 用 SQLite 存案例 JSON 与向量 BLOB，检索时 numpy 全量算余弦相似度。
案例量上万后可平滑替换为 PostgreSQL + pgvector / Qdrant，接口不变。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from ..embedding import embed
from ..schemas import FraudCase

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id        TEXT PRIMARY KEY,
    fraud_type     TEXT NOT NULL,
    source_url     TEXT,
    raw_text_hash  TEXT UNIQUE,
    payload        TEXT NOT NULL,
    embedding      BLOB NOT NULL,
    created_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cases_fraud_type ON cases(fraud_type);
"""


class CaseStore:
    def __init__(self, db_path: Path | str):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # FastAPI 同步 handler 在线程池中执行，需允许跨线程访问；MVP 单进程下安全
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def upsert_case(self, case: FraudCase) -> bool:
        """入库。同一原文（raw_text_hash 相同）已存在时跳过，返回是否新增。"""
        if case.raw_text_hash:
            row = self.conn.execute(
                "SELECT case_id FROM cases WHERE raw_text_hash = ?", (case.raw_text_hash,)
            ).fetchone()
            if row:
                return False

        vec = embed([case.embedding_text()])[0]
        self.conn.execute(
            "INSERT OR REPLACE INTO cases (case_id, fraud_type, source_url, raw_text_hash, payload, embedding)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                case.case_id,
                case.fraud_type,
                case.source_url,
                case.raw_text_hash or None,
                case.model_dump_json(),
                vec.astype(np.float32).tobytes(),
            ),
        )
        self.conn.commit()
        return True

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]

    def get(self, case_id: str) -> FraudCase | None:
        row = self.conn.execute("SELECT payload FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        return FraudCase.model_validate_json(row[0]) if row else None

    def all_cases(self) -> list[FraudCase]:
        rows = self.conn.execute("SELECT payload FROM cases").fetchall()
        return [FraudCase.model_validate_json(r[0]) for r in rows]

    def search_similar(self, query_text: str, top_k: int = 5) -> list[tuple[FraudCase, float]]:
        """向量检索最相似案例，返回 [(case, 相似度)]，相似度为余弦值 0~1。"""
        rows = self.conn.execute("SELECT payload, embedding FROM cases").fetchall()
        if not rows:
            return []
        matrix = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
        query_vec = embed([query_text])[0]
        scores = matrix @ query_vec
        order = np.argsort(scores)[::-1][:top_k]
        results = []
        for i in order:
            case = FraudCase.model_validate_json(rows[int(i)][0])
            results.append((case, float(max(scores[int(i)], 0.0))))
        return results
