# Malaysia Food & Local Discovery Copilot

面向 Kuala Lumpur 的餐厅发现。试点是 Old Klang Road，用户也可以搜索整个吉隆坡。推荐来自 `data/processed/restaurants.json` 里的 5,797 家 OpenStreetMap 餐厅，再加上一次真实网页搜索的来源列表。

`final-project/` 里的加州 Connoisseur Companion 保持不动。Kulim 历史数据留在 `data/raw/osm_kulim.json` 和 `data/history/kulim/`。

坐标落在查询范围里，只说明它在这块定义区域内，不等于门牌已经核实。没有来源的价格、清真和地址保持未知。系统不编造地址、评论、营业状态或认证。

## 现在怎么推荐

用户用一句话描述需求。Python 解析区域、菜系、场景和用户明确写出的条件。BM25 在已经符合条件的正式记录里排序。Bing 搜索同时运行，结果只作为网页来源列出，不会被当成已确认分店。

价格和清真不是默认筛选：

- 有可靠价格才显示区间。没有价格就省略，餐厅仍可推荐。
- 用户写出预算上限时，只有可靠金额高于上限的记录才排除。
- 用户没有问清真时，不要求清真字段完整。问了但没有可靠认证时，回答说明未知。

## 架构

```text
Vue Explore / Copilot
        |
        v
POST /api/chat
        |
        v
LangGraph discovery graph          只在演示进程打开，不调用模型
  intent -> BM25 retrieve -> Bing search -> match -> answer
        |
        v
正式 JSON 5,797 条 + 可选的 discovered_restaurants.json
```

`ENABLE_LLM_AGENT` 关闭时不调用语言模型。两个旧 Agent 和它们的 LangGraph 仍在 `src/food_copilot/agents/`，只有同时打开 `ENABLE_LLM_AGENT` 和 `ENABLE_LANGGRAPH` 才运行，并且需要 `OPENAI_API_KEY`。

| 模块 | 作用 | 当前状态 |
|---|---|---|
| `services/discovery.py` | 过滤、排序、地图链接、回答 | 启用 |
| `retrieval/constraints.py` | 区域、菜系、素食、明确预算、认证类清真 | 启用 |
| `retrieval/rankers.py` | baseline；演示进程使用 BM25 | BM25 由 `demo.ps1` 打开 |
| `retrieval/web_search.py` | Bing HTML 搜索 | 演示进程打开。失败会写明错误 |
| `agents/discovery_graph.py` | 上面这条 LangGraph | 演示进程打开 |
| `data/discoveries.py` | 把带街道信息的新来源写入侧车文件 | 启用。榜单和无法定位的页面不入库 |
| `agents/graph.py` | 两个 LLM Agent 的旧工作流 | 代码在，演示不运行 |
| `mcp/server.py` | 六个 MCP 工具 | 启用。浏览器不连接它 |
| `frontend/` | Vue 3 演示 | 探索、对话、系统状态 |

## 状态词

| 值 | 含义 |
|---|---|
| `not_verified` | 还没查，或没有足够来源 |
| `unknown` | 查过仍然不能确定 |
| `verified` | 来源对得上这一家，而且有 URL。搜索链接不算 |
| `pending` / `needs_more_info` / `reviewed` | 人工审核进度，不是价格或清真属性 |

没找到清真证据时保持未知，不要写成非清真。地址没核实，不要说门牌已确认。

## 运行

这台机器使用便携 Python。演示用一条命令启动 API，它不修改 `.env`：

```powershell
powershell -File d:\project1\malaysia-food-copilot\scripts\demo.ps1
```

另一个终端：

```powershell
cd d:\project1\malaysia-food-copilot\frontend
$env:PATH = "d:\project1\malaysia-food-copilot\.node-src\node-v22.21.0-win-x64;" + $env:PATH
npm install
npm run dev
```

打开 http://127.0.0.1:5173/copilot 。API 是 http://127.0.0.1:8767 。`GET /health` 应显示 `dataset` 为 `canonical`、`dataset_records` 为 5797、`retrieval` 为 `bm25`、`langgraph` 为 true、`web_search` 为 true。

便携版 Python 不读取 `PYTHONPATH`。不要直接执行 `python -m uvicorn app:app`。`demo.ps1` 会把项目根目录和 `src` 放进 `sys.path`。

检查：

```powershell
cd d:\project1\malaysia-food-copilot
$env:PYTHONUTF8 = "1"
d:\project1\final-project\.python\python.exe -m pytest tests -q
d:\project1\final-project\.python\python.exe scripts\copilot.py validate
d:\project1\final-project\.python\python.exe scripts\copilot.py evaluate
```

可以先试这三句：

- `I want Korean BBQ around Old Klang Road.`
- `Find a family-friendly restaurant in Old Klang Road under RM20.`
- `Find a good Japanese restaurant in Kuala Lumpur.`

第一句在 2026-10-17 的实测里返回了 Sae Ma Eul BBQ 等 OSM 餐厅，价格留空，并附上 Bing 来源。第二句返回旧巴生路餐厅，没有因为缺价格被排除。

## MCP 工具

`scripts/mcp_server.py` 用 stdio 启动。餐厅工具读本地 JSON。记忆工具使用 `.env` 里的 `DATABASE_URL` 和 `REDIS_URL`；没有配置时返回 `memory_unavailable`。

| 工具 | 作用 |
|---|---|
| `discover_restaurants` | 调用现有 discovery |
| `get_restaurant_details` | 按确切 `restaurant_id` 读取餐厅和证据 |
| `get_restaurant_evidence` | 读取已存储的地址、价格和清真字段 |
| `get_user_preferences` | 读取明确保存的偏好。偏好不是餐厅事实 |
| `save_user_preference` | 只有 `confirmed` 为 true 才写入 |
| `get_conversation_summary` | 读取已存储的消息，不生成新摘要 |

## 功能开关

`.env.example` 里的开关默认是 false。`scripts/demo.ps1` 只给自己的进程设置下面三行，不改文件。

| 变量 | 示例文件 | 演示进程 |
|---|---|---|
| `DEMO_DATASET` | false | false。旧 Demo 文件已删除 |
| `ENABLE_BM25` | false | true |
| `ENABLE_LANGGRAPH` | false | true，走发现图 |
| `ENABLE_WEB_SEARCH` | false | true，Bing |
| `ENABLE_LLM_AGENT` | false | false |
| `ENABLE_MULTILINGUAL_EMBEDDINGS` | false | false。模型未下载 |
| `ENABLE_HYBRID_RETRIEVAL` | false | false |
| `ALLOW_UNAUTHENTICATED_MEMORY` | false | 不由演示脚本改。本地 `.env` 可以打开，这不是登录 |

其他变量名：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`、`DATABASE_URL`、`REDIS_URL`。不要把值写进前端或文档。

## 现在的限制

- 正式价格和清真几乎都是 `not_verified`。卡片会省略价格，而不是声称符合预算。
- Bing 可能返回和餐厅无关的网页。这些网页只出现在来源列表。没有街道信息的结果不会入库。
- `data/eval/queries.jsonl` 的 `relevant_restaurant_ids` 是空的。评估不计算 Recall@5 或 NDCG@5。
- 人工审核工作副本还没验收，也没有导回 JSON。
- 没有照片来源时使用占位。地图链接使用 OSM 坐标；没有坐标时用地址搜索，并标明未精确核对。
- 数据库配额当前接口读不到，状态页会这样写。没有提供清空正式库的按钮。
- 应用还不是生产系统。浏览器 `user_id` 不是账号。

更细的过程和实测见 `PLAN.md`、`docs/architecture.md`、`docs/architecture-audit.md`、`docs/feature-matrix.md` 与 `docs/verification-report.md`。图在 `docs/architecture.mmd` 和 `docs/request-flow.mmd`。

当前对话屏幕会把已经展示过的餐厅 id 一并送给下一句。刷新页面后，如果记忆接口没有打开，这些 id 不会从服务器恢复。新会话不继承上一会话的区域或排除列表。
