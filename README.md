# 反诈案例采集与通话风险检测 Agent

按 `思路.txt` 的设计落地的 MVP：**合规爬取 → 正文清洗/PII 脱敏 → LLM/规则抽取 → 校验入库 → 向量检索 → 通话风险检测**。

```
公开来源(白名单) → Crawler(robots.txt/限速/去重) → PII 脱敏
  → Extraction(LLM 优先, 规则兜底) → Validation(金额/日期/PII/防幻觉)
  → SQLite 案例库 + 向量索引
  → Call Detection(规则初筛 + 相似案例检索 + 可选 LLM 研判) → 风险等级/信号/相似案例/处置建议
```

## 快速开始（完全离线，无需任何 API key）

```bash
pip install -r requirements.txt

# 1. 导入离线样例文章（5 类诈骗，含 PII 自动脱敏演示）
python -m antifraud_agent.cli ingest-local data/sample_articles

# 2. 检测一段通话转写文本
python -m antifraud_agent.cli detect "我是公安局的，你涉嫌洗钱，要保密，把钱转到安全账户"

# 2.5 导入人工标注的通话转写 CSV（content=转写文本, comment=人工审核的诈骗类型）
python -m antifraud_agent.cli ingest-csv 标注数据.csv \
    --content-col content --label-col comment --id-col data_id

# 3. 启动 HTTP 服务
uvicorn antifraud_agent.api:app --port 8000
# POST /detect {"transcript": "..."}   通话风险检测
# POST /crawl  {"urls": [...]}         抓取并入库
# GET  /cases/{case_id} | GET /stats

# 4. 在线爬取（把 data/seed_sources.json 换成你的真实来源白名单）
python -m antifraud_agent.cli crawl --seeds data/seed_sources.json
```

## 模块对应关系

| 设计文档中的 Agent | 代码位置 | 说明 |
| --- | --- | --- |
| Crawler Agent | `antifraud_agent/crawler/` | robots.txt 检查、域级限速、重试、正文提取（trafilatura 可选，自动降级 BeautifulSoup）、内容去重 |
| PII 脱敏 | `antifraud_agent/pii.py` | 手机号/身份证/银行卡/邮箱/姓名正则脱敏，入库前强制执行 |
| Extraction Agent | `antifraud_agent/extraction/` | LLM 抽取（OpenAI 兼容接口）优先；无 key 或失败时用知识库规则兜底，字段全部来自原文 |
| Validation Agent | `antifraud_agent/extraction/validator.py` | JSON 字段、金额/日期合理性、PII 残留、话术与原文匹配度（防幻觉降置信度）、按原文哈希去重 |
| Risk Tagging | `antifraud_agent/knowledge.py` | 12 类诈骗类型知识库（关键词/风险信号/防范提示），抽取、打标、检测三处共用 |
| 案例库 + 向量索引 | `antifraud_agent/store/db.py` | SQLite 存案例 JSON 与向量；MVP 用 numpy 余弦检索，可平滑替换 pgvector/Qdrant |
| Call Detection Agent | `antifraud_agent/detection/` | 风险分 = 0.45×规则分 + 0.35×相似案例分 + 0.20×LLM 分；输出风险等级、命中信号、相似案例、研判理由、处置建议 |
| 标注转写导入 | `antifraud_agent/csv_import.py` | 人工标注通话 CSV 入库：编码自动探测（UTF-8/GB18030）、乱码行检测跳过、标签映射到统一类型、left:/right: 说话人解析、骗子侧话术抽取、PII 脱敏、按内容哈希去重；人工标签置信度 0.9 |

### 标注 CSV 的编码注意事项

`ingest-csv` 会自动识别 UTF-8 与 GBK/GB18030，**不要**对 GBK 文件做 UTF-8 强转——
强转产生的"锟斤拷"替换符是不可逆的，原文已丢失。直接提供原始编码的文件即可。
工具会统计并跳过乱码行，在日志中给出提示。

## 接入 LLM / 更换 Embedding（可选）

不配置时全流程走规则模式。配置后抽取质量与检测召回显著提升：

```bash
export AF_LLM_API_KEY=sk-...                  # OpenAI 兼容接口均可
export AF_LLM_BASE_URL=https://api.openai.com/v1
export AF_LLM_MODEL=gpt-4o-mini

export AF_EMBEDDING_BACKEND=local             # hash(默认) / local / openai
export AF_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5   # local 需 pip install sentence-transformers
```

其他配置见 `antifraud_agent/config.py`（限速、重试、风险阈值等均可用环境变量覆盖）。

## 实时通话接入

本项目输入为文本。实时场景的接法：通话语音 → ASR（Whisper/FunASR/云厂商）→ 按 5-10 秒滑动窗口取最近一段转写文本 → 反复调用 `POST /detect` → 风险升级到 medium/high 时触发提醒。

## 测试

```bash
python -m pytest tests/ -q   # 17 个测试，覆盖脱敏/抽取/检测/API，全程离线
```

## 合规要点

- 只抓取 `data/seed_sources.json` 白名单内的公开来源，遵守 robots.txt 并限速。
- 所有文本入库前强制 PII 脱敏，校验层二次检查残留。
- 保留 `source_url` 与原文哈希，便于审计与溯源。
- 规则抽取不产生幻觉字段；LLM 抽取结果与原文做匹配度校验。
- 检测输出定位为“风险提示”，不做法律定性；建议保留人工抽检机制。
