"""命令行入口。

用法：
  python -m antifraud_agent.cli crawl --seeds data/seed_sources.json   # 按白名单抓取并入库
  python -m antifraud_agent.cli ingest-local data/sample_articles      # 离线样例入库
  python -m antifraud_agent.cli ingest-csv 标注数据.csv                 # 人工标注通话转写入库
  python -m antifraud_agent.cli detect "对方说我涉嫌洗钱要转账到安全账户"
  python -m antifraud_agent.cli stats
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .config import settings
from .crawler import crawl_urls, load_local_articles
from .crawler.pipeline import load_seed_sources
from .detection import CallRiskDetector
from .extraction import extract_case
from .store import CaseStore


def _ingest(store: CaseStore, docs) -> int:
    new = 0
    for doc in docs:
        case = extract_case(doc)
        if case and store.upsert_case(case):
            new += 1
            print(f"  + [{case.fraud_type}] {case.title}  (confidence={case.confidence})")
    return new


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="反诈案例采集与通话检测 Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p_crawl = sub.add_parser("crawl", help="按来源白名单抓取并入库")
    p_crawl.add_argument("--seeds", type=Path, required=True, help="seed_sources.json 路径")

    p_local = sub.add_parser("ingest-local", help="从本地目录读取文章 JSON 并入库（离线）")
    p_local.add_argument("directory", type=Path)

    p_csv = sub.add_parser("ingest-csv", help="导入人工标注的通话转写 CSV（content=转写文本, comment=诈骗类型）")
    p_csv.add_argument("csv_path", type=Path)
    p_csv.add_argument("--content-col", default="content")
    p_csv.add_argument("--label-col", default="comment")
    p_csv.add_argument("--id-col", default="data_id")

    p_detect = sub.add_parser("detect", help="检测一段通话文本")
    p_detect.add_argument("transcript")

    sub.add_parser("stats", help="案例库统计")

    args = parser.parse_args()
    store = CaseStore(settings.db_path)

    if args.command == "crawl":
        urls, names = load_seed_sources(args.seeds)
        docs = crawl_urls(urls, names)
        n = _ingest(store, docs)
        print(f"抓取 {len(docs)} 篇，新增案例 {n} 条，案例库共 {store.count()} 条")

    elif args.command == "ingest-local":
        docs = load_local_articles(args.directory)
        n = _ingest(store, docs)
        print(f"读取 {len(docs)} 篇，新增案例 {n} 条，案例库共 {store.count()} 条")

    elif args.command == "ingest-csv":
        from .csv_import import ingest_csv

        stats = ingest_csv(store, args.csv_path, args.content_col, args.label_col, args.id_col)
        print(f"共 {stats.total_rows} 行：新增 {stats.ingested}，重复 {stats.duplicated}，"
              f"乱码跳过 {stats.corrupted}，类型无法判定 {stats.unmapped}")
        if stats.label_distribution:
            print("入库类型分布:", json.dumps(stats.label_distribution, ensure_ascii=False))
        print(f"案例库共 {store.count()} 条")

    elif args.command == "detect":
        result = CallRiskDetector(store).detect(args.transcript)
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))

    elif args.command == "stats":
        cases = store.all_cases()
        by_type: dict[str, int] = {}
        for c in cases:
            by_type[c.fraud_type] = by_type.get(c.fraud_type, 0) + 1
        print(json.dumps({"total": len(cases), "by_fraud_type": by_type}, ensure_ascii=False, indent=2))

    store.close()


if __name__ == "__main__":
    main()
