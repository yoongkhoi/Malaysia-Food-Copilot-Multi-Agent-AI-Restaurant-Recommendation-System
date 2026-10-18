# Malaysia Food Copilot 当前计划

主项目是这个仓库。默认搜索范围是旧巴生路（Old Klang Road）。用户写明 Kuala Lumpur 或 Kulim 时尊重原话。同一会话里的下一句沿用上一句的区域。没有写地点时直接搜旧巴生路，不再询问「旧巴生路还是吉隆坡」。

正式推荐只读 `data/processed/restaurants.json`（5,797 条 OpenStreetMap 记录）。这个文件在 `.gitignore` 里，克隆仓库不会带上它。坐标落在查询范围内，只说明它在定义区域里，不等于门牌已经核实。价格、清真和是否适合某种场合，没有来源就不能标成 `verified`。`not_verified` 是还没查，`unknown` 是查过仍不能确定。两者都不是「非清真」。

界面截图在 `docs/images/`：`copilot.jpg`、`explore.jpg`、`status.jpg`。

## 现在怎么回答

演示进程走 `src/food_copilot/agents/workflow.py`。`ENABLE_AGENT_WORKFLOW` 默认打开。`scripts/demo.ps1` 只改自己的进程：工作流、BM25、网页搜索和 LangGraph 打开，`ENABLE_LLM_AGENT` 和 demo 数据集关闭。测试在 `tests/conftest.py` 里把工作流关掉，用来覆盖旧的确定性图。

```text
Vue  探索 / 对话 / 状态
        |
        v
FastAPI  POST /api/chat
        |
        v
1. 意图        温度 0.1    模型给出 JSON，解析器锁住预算、区域和排除项
2. 检索        温度 0.2    最多三轮 MCP 工具
3. 排序        温度 0.2    只能重排已经检索到的 id
4. 成文        温度 0.7    用户看到的那段话
```

普通问答不检索，温度 0.5。没有密钥或合成失败时，仍然可以出示库存卡片，并标明这不是模型推荐。

MCP 由 API 进程在 lifespan 里拉起一个 stdio 子进程，退出时关掉。子进程复制 API 的环境变量，否则 `ENABLE_BM25` 会丢掉，排序退回 baseline。`/health` 报告的是这次连接，不是环境变量本身。

浏览器不连接 MCP。浏览器只调用 FastAPI。

## 产品规则

- 硬条件在 Python 里执行，并覆盖模型填进工具参数的预算、区域和排除项。
- 缺价格不排除。已核实且高于用户写出的预算上限才排除。
- 用户没问清真时，不要求清真字段。问了但没有认证，回答写未知。
- 氛围是偏好，不是硬过滤。
- 网页搜索结果只作为来源。没有街道信息的页面不写入正式库。
- 评论工具只读 `pilot_corpus.jsonl`，而且只接受已确认的 `unique_name_in_area`。`ENABLE_REVIEW_RAG` 对普通对话保持关闭。
- `restaurants_final_verified_full.json` 不导入。
- 卡片的地点行不打印经纬度。地图和状态页搜索可以显示坐标。
- 浏览器里的 `user_id` 不是账号。

## 目录

依赖、缓存和构建产物不参与业务逻辑：`.venv/`、`.node-src/`、`node_modules/`、`__pycache__/`、`.pytest_cache/`、`frontend/dist/`。`frontend/src/components/ui/` 是 shadcn-vue 基础组件。

### 根目录

| 文件 | 作用 |
|---|---|
| `app.py` | FastAPI。挂载路由、本地 CORS，并在工作流打开时启动 MCP。 |
| `README.md` | 仓库说明、截图、架构和启动方式。 |
| `PLAN.md` | 当前规则、目录和还没做的事。 |
| `pyproject.toml` | 项目名、Python 版本、pytest 的 `pythonpath`。 |
| `requirements.txt` | Python 依赖。 |
| `.env.example` | 变量名和温度。不要提交 `.env`。 |
| `.gitignore` | 密钥、依赖、缓存，以及 `data/processed/*.json`。 |

### `src/food_copilot/`

| 路径 | 作用 |
|---|---|
| `agents/workflow.py` | 默认路径：意图、工具、排序、成文、失败时的标明回退。 |
| `agents/mcp_host.py` | API 使用的 stdio MCP 客户端。测试用内存会话。 |
| `agents/model.py` | 按角色读取温度。接口拒绝温度时重试一次不带温度的调用。日志不写密钥和用户原文。 |
| `agents/intent_router.py` | 意图标签。没有会话的追问说明搜索范围是旧巴生路。 |
| `agents/context.py` | 合并区域、菜系和已展示的店。品牌列表用可读句子，不逐行打印坐标。 |
| `agents/discovery_graph.py` | 工作流关闭时的确定性 LangGraph。 |
| `agents/graph.py` | 旧的两个 LLM agent。演示不走它。 |
| `api/routes.py` | `/api/chat`、`/api/discover`、餐厅读取、记忆和状态板。 |
| `mcp/server.py` | 注册工具。 |
| `mcp/tools.py` | 搜索走 `DiscoveryService`，避免再进入聊天。 |
| `services/discovery.py` | 先过滤再排序，生成卡片。缺区域时填项目默认区域。 |
| `retrieval/constraints.py` | 解析并执行硬条件。 |
| `retrieval/rankers.py` | baseline 与 BM25。BM25 只排序已经合格的记录。 |
| `retrieval/web_search.py` | Bing HTML。 |
| `data/repository.py` | 只读正式 JSON。 |
| `memory/store.py` | 可选的 Redis 短会话和 Postgres 消息。 |
| `reviews/` | 试点语料和离线忠实度检查。 |
| `config/settings.py` | 路径、开关、分角色温度。 |
| `config/regions.py` | 旧巴生路是 `PROJECT_REGION`。 |
| `ui/app.py` | 本机 Gradio。作品集演示用 Vue。 |

### MCP 工具

| 工具 | 作用 |
|---|---|
| `search_restaurants` | 带硬条件的正式库搜索。 |
| `get_restaurant_reviews` | 试点语料，且名称在区域内唯一。 |
| `discover_restaurants` | 旧的发现入口。工作流的搜索不调用它。 |
| `get_restaurant_details` | 按确切 id 读一条。 |
| `get_restaurant_evidence` | 已存储的地址、价格和清真字段。 |
| `get_user_preferences` | 已保存偏好。偏好不是餐厅事实。 |
| `save_user_preference` | 只有 `confirmed` 为 true 才写入。 |
| `get_conversation_summary` | 已存储的消息，不新写摘要。 |

### `frontend/`

Vue 3、Vite、TypeScript、Tailwind。开发服务器把 `/api` 和 `/health` 代理到 `127.0.0.1:8767`。

| 路径 | 作用 |
|---|---|
| `src/views/ExploreView.vue` | 搜索表单。句子里没有地名时补上 Old Klang Road。 |
| `src/views/CopilotView.vue` | 会话、建议句、回答、地图和卡片。诊断折在 “How this answer was made”。 |
| `src/views/StatusView.vue` | Neon、Redis、最近消息、餐厅文件和健康检查。 |
| `src/components/AppShell.vue` | 暖黄侧栏和 Old Klang Road 标记。 |
| `src/components/RestaurantCard.vue` | 菜系标签。出处在 “Record details”。地点行没有经纬度。 |
| `src/components/RestaurantMap.vue` | Leaflet 与 OpenStreetMap。 |
| `src/lib/search.ts` | 探索页补区域，对话页带上一轮条件。 |
| `src/router.ts` | `/`、`/copilot`、`/status`。偏好和证据页重定向到首页。 |

### `scripts/` 与 `docs/`

| 路径 | 作用 |
|---|---|
| `scripts/demo.ps1` | 启动作品集 API，端口 8767。 |
| `scripts/mcp_server.py` | MCP stdio 入口。 |
| `docs/architecture.md` | 当前请求路径、组件、状态和失败行为。 |
| `docs/architecture.mmd` | 默认路径和回退路径。 |
| `docs/request-flow.mmd` | 从对话页到卡片的时序。 |
| `docs/images/` | 探索、对话和状态页截图。 |
| `docs/feature-matrix.md` | 功能与运行时对照。 |
| `docs/verification-report.md` | 当时的验证记录。 |
| `docs/ai_method_audit.md` | 2026-10-17 的方法审计。开头已指向现在的工作流。 |

### `data/`

| 路径 | 作用 |
|---|---|
| `processed/restaurants.json` | 正式库，5,797 条。被 gitignore。 |
| `processed/old_klang_road/restaurants.json` | 旧巴生路子集。这些记录也带吉隆坡区域标签。 |
| `processed/kuala_lumpur/restaurants.json` | 吉隆坡处理后的副本。 |
| `processed/old_klang_road/restaurants_final_verified_full.json` | 已审计的候选稿。不导入。 |
| `processed/reviews/pilot_corpus.jsonl` | 评论工具使用的试点语料。 |
| `raw/` | OSM 快照，不是默认推荐来源。 |
| `history/kulim/` | Kulim 历史数据。 |

## 启动

```powershell
powershell -File scripts/demo.ps1
```

另一个终端：

```powershell
cd frontend
npm install
npm run dev
```

打开 http://127.0.0.1:5173/copilot 。本机 API 使用 `d:\project1\final-project\.python\python.exe`，但只借用这个解释器。不要改 `final-project` 里的应用。

```powershell
$env:PYTHONUTF8 = "1"
d:\project1\final-project\.python\python.exe -m pytest tests -q --ignore=tests/integration/test_memory_roundtrip.py
```

`test_memory_roundtrip.py` 会写 Redis 和 Postgres，日常检查不要跑。

## 还没做

- 混合检索和多语言餐厅向量默认关闭，模型也没有为这条路径下载。
- 评测查询没有人工相关 id，不计算 Recall@5 或 NDCG@5。
- 人工审核工作副本没有导回正式 JSON。
- 数据库配额当前接口读不到，状态页会照实写。
- 没有用户登录。清空会话需要在状态页确认两次，并且不删除餐厅记录。
- 应用是本机演示，不是生产部署。

更细的请求路径见 `docs/architecture.md`。仓库首页见 `README.md`。
