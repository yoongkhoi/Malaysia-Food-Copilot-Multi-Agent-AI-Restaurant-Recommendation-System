# Malaysia Food Copilot 进度与后续计划

主项目在 `malaysia-food-copilot/`。试点是旧巴生路走廊（Old Klang Road），不是整个吉隆坡。扩展池是 Kuala Lumpur。`final-project/` 里的加州 Connoisseur Companion 保持不动，只作为原来的 hash 检索基线。

坐标落在查询范围内，只说明它在这块定义区域里，不等于门牌已经核实。价格、清真、是否适合家庭，没有来源就不能标成 `verified`。`not_verified` 表示还没查，`unknown` 表示查过来源仍不能确定，两者都不是「非清真」或「不适合家庭」。只有用户明确提出的条件才过滤。未知价格不再因为缺价被排除；已核实且高于预算上限的价格仍会排除。

## 目录架构

演示请求从 Vue 页面进 FastAPI，再进 LangGraph 发现图。解析、硬过滤和计数是 Python。BM25 只排序已经通过条件的记录。网页搜索是 Bing HTML。模型只在需要时补一句措辞，不决定哪家店合格。

```text
frontend/          Vue 对话、地图、状态页
app.py             FastAPI 入口，端口 8767
src/food_copilot/
  api/             HTTP 路由
  agents/          意图、会话条件、发现图；旧的多模型图仍在，演示不走它
  services/        过滤、排序、卡片
  retrieval/       条件、BM25、网页搜索、未启用的向量检索
  data/            正式餐厅只读库和网页发现侧车
  memory/          Redis 短会话，Postgres 长期消息
  mcp/             进程内工具，浏览器不连 MCP
data/processed/restaurants.json
                   推荐来源，5797 条 OSM 记录
```

下面只列项目自己的文件。`node_modules/`、`.node-src/`、`__pycache__/`、`.pytest_cache/`、`frontend/dist/` 是依赖、缓存或构建产物，不参与业务逻辑。`frontend/src/components/ui/` 是 shadcn-vue 基础组件，按组件夹说明，不逐个列出按钮和弹层文件。

### 根目录

| 文件 | 作用 |
|---|---|
| `app.py` | FastAPI 应用。挂载路由和本地 CORS。启动时只有 `REDIS_STARTUP_CLEANUP` 打开才会清会话，默认不清。 |
| `PLAN.md` | 进度、产品规则和这份目录说明。 |
| `README.md` | 怎么在本机启动 API 和前端。 |
| `pyproject.toml` | 项目名、Python 版本和 pytest 的 `pythonpath`。 |
| `requirements.txt` | Python 依赖。 |
| `package.json` | 根目录只给 Neon TypeScript 配置做类型检查，不是 Vue 应用。 |
| `package-lock.json` | 根目录 npm 锁文件。 |
| `tsconfig.json` | 根目录 TypeScript 配置，给 `hello.ts` 和 `neon.ts`。 |
| `hello.ts` | Neon Function 的示例响应，不是餐厅接口。 |
| `neon.ts` | Neon 分支和函数配置。`auth` 关闭。 |
| `.neon` | 本机 Neon 项目指针，已在 `.gitignore`。 |
| `.env` | 本机数据库、Redis 和模型地址。不进文档，不进前端。 |
| `.env.example` | 变量名示例。未认证记忆默认关闭。 |
| `.gitignore` | 忽略密钥、依赖、缓存和部分数据产物。 |

### `src/food_copilot/`

| 文件 | 作用 |
|---|---|
| `__init__.py` | 包说明。 |
| `cli.py` | 命令行：查看开关、检查审核表、校验数据、跑评测、做一次发现。 |
| `errors.py` | 功能未开启等应用错误，不是餐厅事实。 |

`config/`

| 文件 | 作用 |
|---|---|
| `settings.py` | 路径、功能开关、模型名。开关在调用时读取，不写进 `.env` 当全局默认。 |
| `regions.py` | Old Klang Road 和 Kuala Lumpur 的范围与名称。查询时的区域来自记录上的 `regions`，不是当场用坐标矩形重判。 |

`api/`

| 文件 | 作用 |
|---|---|
| `routes.py` | `/health`、`/api/chat`、会话列表、消息、清空会话、餐厅搜索。聊天先判断是不是普通问答，再合并会话条件并运行发现图。 |

`agents/`

| 文件 | 作用 |
|---|---|
| `intent_router.py` | 在检索前分流：普通问答、餐厅搜索、延续上一轮、或要求澄清。含糊句子才调用模型；路由失败不会改成餐厅搜索。 |
| `context.py` | 合并并保存区域、菜系、排除菜系、品牌、已展示店名和 ID。新菜系替换旧菜系；只有“还有没有其他”才跳过已展示的店。 |
| `discovery_graph.py` | 演示用的 LangGraph：意图、检索、网页搜索、对照来源、生成回答。 |
| `model.py` | 服务端调用 `gpt-4o-mini`，温度为 0。状态接口不返回密钥。 |
| `graph.py` | 旧的多模型图：记忆、偏好、推荐、再检查 ID。只有 LangGraph 和 LLM agent 同时打开才走这里。 |
| `orchestrator.py` | 不调用模型时的工具路由。 |
| `runtime.py` | 按顺序跑偏好和推荐两个 agent，不是发现图。 |
| `preference.py` | 决定一句偏好能不能写入长期记忆。 |
| `recommendation.py` | 从工具拿候选，再用 Python 检查。 |
| `mcp_client.py` | 在进程内调用 MCP 工具，不打开浏览器连接。 |

`services/`

| 文件 | 作用 |
|---|---|
| `discovery.py` | 解析用户句子，先过滤再排序再过滤，并把记录做成卡片。回答语言跟当前句子。 |
| `restaurant_service.py` | 按已核实字段搜索。排序不能越过硬条件。 |

`retrieval/`

| 文件 | 作用 |
|---|---|
| `constraints.py` | 把句子解析成区域、菜系、排除菜系、品牌、预算、清真、素食和氛围，并在排序前执行硬过滤。没有存档氛围证据时，氛围请求不会用菜系顶上。 |
| `rankers.py` | 词重叠基线和 BM25。演示打开 BM25。它只给已合格记录排序。 |
| `web_search.py` | Bing HTML 搜索。语言课、词典、键盘和榜单页不能当餐厅证据。 |
| `embeddings.py` | 多语言向量接口。模型没有下载，默认不运行。 |
| `metrics.py` | Recall 和 NDCG。没有人工相关标签时不算分。 |

`data/`

| 文件 | 作用 |
|---|---|
| `schema.py` | 正式餐厅记录的字段。缺字段保持未知，不写成否定结论。 |
| `repository.py` | 只读加载正式 JSON。不读审核草稿，不读已删除的 demo 文件。 |
| `discoveries.py` | 网页发现的侧车。写入前要求区域和菜系出现在页面文字里。不改写正式 `restaurants.json`。 |

`domain/`

| 文件 | 作用 |
|---|---|
| `__init__.py` | 领域类型入口。 |
| `models.py` | 请求和结果模型，包括卡片上的来源、坐标和地址。 |

`memory/`

| 文件 | 作用 |
|---|---|
| `store.py` | Redis 保存当前会话消息和条件，Postgres 保存可回看的消息。清空会话不删餐厅，也不 `FLUSHDB`。 |

`ingestion/`

| 文件 | 作用 |
|---|---|
| `normalize.py` | 把 OSM 原始快照转成正式记录，不补造缺失事实。 |
| `validators.py` | 入库前的质量检查。不合格的行不进正式文件。 |
| `review_export.py` | 导出人工审核表。`not_verified` 表示还没查。 |
| `review_audit.py` | 对照基线检查工作副本，不写正式数据。 |
| `candidate_audit.py` | 审计候选 JSON。不把它合并进正式库。 |

`evaluation/`

| 文件 | 作用 |
|---|---|
| `runner.py` | 对检索器出报告。`relevant_restaurant_ids` 为空时记为不可评测。 |

`mcp/`

| 文件 | 作用 |
|---|---|
| `server.py` | stdio 上的 MCP 服务，只暴露已有业务函数。 |
| `tools.py` | 查餐厅、解释条件和发现网页结果的工具实现。 |

`ui/`

| 文件 | 作用 |
|---|---|
| `app.py` | 本机 Gradio 界面，端口 7860。过滤仍走发现服务。作品集演示用的是 Vue，不是这个界面。 |

### `scripts/`

| 文件 | 作用 |
|---|---|
| `demo.ps1` | 启动作品集 API。进程内打开 LangGraph、BM25 和网页搜索，关闭 LLM agent 和 demo 数据集。不改 `.env`。 |
| `verify.ps1` | 本机检查：pytest、审核表、证据、校验、评测，以及前端测试和构建。不是部署流水线。 |
| `copilot.py` | 把项目放进 `sys.path` 后启动 `cli.py`。 |
| `launch_ui.py` | 启动 Gradio。 |
| `mcp_server.py` | 启动 MCP stdio 服务。 |
| `collect_osm.py` | 按配置区域向 Overpass 拉一份 OSM 快照。这是原始数据，不是最终库。 |
| `normalize_data.py` | 把旧巴生路和吉隆坡快照正规化。Kulim 归档保留。 |
| `sample_okr_review.py` | 抽出 25 家和 50 家人工审核样本。不把任何一行标成已核实。 |
| `prepare_okr_review_work.py` | 把第一批 25 家复制成工作副本并核对是否与基线一致。 |
| `check_memory.py` | 对 Neon 和 Redis 做一次往返，然后删掉探测用户。 |

### `tests/`

| 文件 | 作用 |
|---|---|
| `conftest.py` | 测试开始前把项目根和 `src` 放进 Python 路径。 |
| `helpers.py` | 构造测试餐厅。默认价格和清真都是未核实。 |
| `test_api.py` | 健康检查和聊天接口在不同开关下的行为。 |
| `test_constraints.py` | 条件解析和硬过滤。 |
| `test_ingestion.py` | OSM 正规化和校验。 |
| `test_metrics.py` | 检索指标。 |
| `test_regions.py` | 区域归属。 |
| `integration/test_canonical_load.py` | 正式 JSON 能加载，条数与预期一致。 |
| `integration/test_chat_smoke.py` | 没写区域时要求补充，不猜地点。 |
| `safety/test_agent_safety.py` | 回答不泄露密钥，也不把未通过检查的内容当成事实。 |
| `unit/test_agents.py` | 偏好、推荐和 MCP 工具结果。 |
| `unit/test_graph.py` | 旧的多模型图。 |
| `unit/test_discovery_graph.py` | 发现图：缺区域停在澄清，网页入库规则，查找失败不编店名。 |
| `unit/test_intent_routing.py` | 普通问答、品牌计数、菜系替换和区域澄清。 |
| `unit/test_context.py` | 延续上一轮时保留区域，并按新句子更换菜系或品牌。 |
| `unit/test_grounded_dialogue.py` | 多轮对话只使用检索到的店，失败时不从模型记忆补店。 |
| `unit/test_cuisine_switch_dialogue.py` | 连续切换菜系、排除菜系、跳过已展示的店，并拒绝语言学习网页。 |
| `unit/test_constraint_relevance.py` | 西餐不返回纯日料，氛围不沿用上一轮菜系，新会话不继承条件。 |
| `unit/test_hard_constraints.py` | 预算、清真和区域的硬条件。 |
| `unit/test_price_evidence.py` | 搜索链接不能把价格升成已核实。 |
| `unit/test_repository.py` | 只读仓库不加载草稿。 |
| `unit/test_review_audit.py` | 审核工作副本相对基线的检查。 |
| `unit/test_evaluation.py` | 没有相关标签时不编造 Recall 或 NDCG。 |
| `unit/test_memory_keys.py` | 会话键的范围。 |
| `unit/test_memory_bounds.py` | 记忆读写的边界。 |
| `unit/test_mcp_tools.py` | MCP 工具调用现有服务。 |
| `unit/test_security.py` | 接口不回显密钥和连接串。 |

### `frontend/`

Vue 3、Vite、TypeScript 和 Tailwind。开发服务器把 `/api` 和 `/health` 代理到 `127.0.0.1:8767`。

| 文件 | 作用 |
|---|---|
| `index.html` | Vite 页面入口。 |
| `package.json` | 前端依赖和 `dev`、`test`、`build` 脚本。 |
| `package-lock.json` | 前端依赖锁。 |
| `vite.config.ts` | 别名、Tailwind 和 API 代理。 |
| `tsconfig.json`、`tsconfig.app.json`、`tsconfig.node.json` | TypeScript 配置。 |
| `components.json` | shadcn-vue 组件配置。 |
| `README.md` | 前端启动说明。 |
| `.env.example` | 前端环境变量示例。前端不放模型密钥。 |
| `src/main.ts` | 挂载 Vue、路由和 Pinia。 |
| `src/App.vue` | 根组件，渲染 `AppShell`。 |
| `src/router.ts` | `/` 探索，`/copilot` 对话，`/status` 状态。偏好和证据页重定向到首页。 |
| `src/style.css` | 全局样式。 |
| `src/vite-env.d.ts` | Vite 类型声明。 |
| `src/components/AppShell.vue` | 侧栏、导航和主内容区。 |
| `src/views/CopilotView.vue` | 对话。Enter 发送，Shift+Enter 换行。示例句子可点后立即发送。新会话不带上一轮条件。 |
| `src/views/ExploreView.vue` | 用表单选择区域和句子，再交给同一聊天接口。 |
| `src/views/StatusView.vue` | 数据库、Redis 进程内存、餐厅分页搜索，以及两次确认后的会话清理。 |
| `src/views/EvidenceView.vue` | 按 ID 看证据的旧页面。路由已重定向，文件还在。 |
| `src/views/PreferencesView.vue` | 偏好表单旧页面。路由已重定向，文件还在。 |
| `src/components/RestaurantCard.vue` | 餐厅卡片。来源、身份、地址和营业状态分开写。缺数据不标成已核实。 |
| `src/components/RestaurantMap.vue` | Leaflet 地图和 OpenStreetMap 链接。 |
| `src/components/StatusBadge.vue` | 价格状态徽章。 |
| `src/components/PageHeader.vue` | 其他页面的标题。Copilot 主区不再用它显示模型或数据集状态。 |
| `src/components/EmptyState.vue` | 还没有对话时的提示。 |
| `src/components/ErrorState.vue` | 请求失败提示。 |
| `src/components/EvidenceSection.vue` | 证据字段的展示块。 |
| `src/lib/api.ts` | 调用后端。聊天超时 60 秒。 |
| `src/lib/api.test.ts` | 接口客户端测试。 |
| `src/lib/search.ts` | 探索页把所选区域补进句子，已写出的区域不重复。 |
| `src/lib/search.test.ts` | 区域补全测试。 |
| `src/lib/evidence.ts` | 卡片上四行证据文案：来源、身份、地址、营业状态。 |
| `src/lib/evidence.test.ts` | 缺地址和未核实地址不能显示成已核实。 |
| `src/lib/utils.ts` | 样式类名合并。 |
| `src/stores/session.ts` | 当前浏览器会话 ID。这不是用户账号。 |
| `src/types/api.ts` | 聊天和餐厅响应的 TypeScript 类型。 |
| `src/components/ui/` | shadcn-vue 基础件：按钮、输入、卡片、对话框、侧栏、滚动条、提示和骨架屏。业务规则不在这里。 |

### `docs/`

| 文件 | 作用 |
|---|---|
| `ai_method_audit.md` | 哪些步骤是规则，哪些步骤才调用模型。 |
| `end_to_end_workflow_and_test_report.md` | 端到端流程和当时的测试记录。 |
| `production.md` | 本机运行和不能公开部署的限制。 |
| `redis_memory_policy.md` | Redis 只存短期会话，清空范围和进程内存的含义。 |

### `data/`

推荐只读 `data/processed/restaurants.json`。其余文件是原始快照、子集、审核稿、评测或外部语料，不作为默认推荐来源。

| 路径 | 作用 |
|---|---|
| `processed/restaurants.json` | 正式库，5797 条。价格和清真都是 `not_verified`。 |
| `processed/kuala_lumpur/restaurants.json` | 吉隆坡处理后的副本。 |
| `processed/old_klang_road/restaurants.json` | 旧巴生路子集，798 条。这些记录也带 `kuala_lumpur` 区域。 |
| `processed/old_klang_road/restaurants_final_verified_full.json` | 已审计的候选稿，798 条。价格来源不合格，不能导入。 |
| `processed/rejected.json` | 正规化时被拒绝的记录占位。 |
| `processed/discovered_restaurants.json` | 网页发现侧车。只在页面同时有地点和菜系证据时才会生成，不在仓库的固定清单里。 |
| `processed/merge_candidates.json` | 同名但 URL 不同的发现，等待人工决定，不自动合并。 |
| `raw/old_klang_road/osm.json` | 旧巴生路 OSM 原始快照，798 条。 |
| `raw/kuala_lumpur/osm.json` | 吉隆坡 OSM 原始快照。 |
| `raw/osm_kulim.json` | Kulim 原始快照，只归档。 |
| `history/kulim/` | Kulim 的 OSM、餐厅、拒绝行和评论归档。不删除。 |
| `staging/okr_review_batch1_25.csv` | 第一批 25 家审核基线。 |
| `staging/okr_review_batch1_25_work.csv` | 基线的工作副本。不覆盖正式库。 |
| `staging/okr_review_batch1_25_researched_updated.csv` | 带研究备注的草稿，未验收。 |
| `staging/okr_review_batch1_25_updated_with_prices.csv` | 带价格草稿，未验收。 |
| `staging/okr_review_batch1_first5_audit.json` | 前五家的研究记录，结论是信息不足，不是批准。 |
| `staging/okr_review_batch2_50.csv` | 50 家审核清单。 |
| `staging/restaurant_review.csv` | 审核用评论表，不是推荐事实来源。 |
| `eval/queries.jsonl` | 5 条评测问题。`relevant_restaurant_ids` 为空，Recall 和 NDCG 不可评测。 |
| `eval/kulim_queries.jsonl` | Kulim 时期留下的问题，不用于当前试点。 |
| `eval/relevance_review_template.jsonl` | 人工标相关餐厅的空模板。 |
| `eval/reports/latest.json` | 最近一次评测写出的报告。 |
| `eval/reports/restaurants_final_verified_full_audit.json` | 候选全量稿的审计结论。 |
| `demo/` | 空目录。虚构 demo 餐厅文件已删除，不能再当推荐来源。 |
| `Malaysia Restaurant Review Datasets/` | 外部的 Google 和 TripAdvisor 评论语料，覆盖多个城市。当前检索和回答不读取它。 |

## 2026-10-17 晚间修复

第二轮「还有没有其他的推荐」被当成没有地区的新问题，是因为意图解析只看当前这一句。模型改写回答后，上一轮店名也不再是 `- 店名:` 这种格式，所以即使用了 Redis 消息也跳过不了已展示的餐厅。

现在同一会话会保存 `region`、`cuisine` 和 `shown_names`。前端下一句也会把上一轮条件带上。新会话会先清空当前画面，不带上一轮条件。回答不再把 `MY-OSM-...`、halal 和 price unknown 当作主文。地图链接是 OpenStreetMap，结果区有 Leaflet 图钉。`/status` 可以搜索餐厅分页，并在两次确认后只删除会话消息和 Redis 会话键。

重启后的真实请求：第一句服务端 6484 ms，`llm_called=true`，模型 `gpt-4o-mini`，工具 `bm25,web_search,llm`。第二句仍是 `old_klang_road` / `korean`，第一家变成 Midam Korean Barbeque，没有再报地区不支持。随后清掉 24 条消息、7 个会话、15 个 Redis 键，正式餐厅没有删。

## 2026-10-17 这次实际做了什么

这一轮把作品集演示从「8 家虚构 Demo 餐厅 + 价格/清真硬门槛」改成「5,797 家正式 OSM 餐厅 + BM25 + 真实网页搜索」。`final-project/` 没有改。`.env` 里的密钥没有写进代码、日志或这份文档。

### 产品规则

- 用户可以用自然语言要菜系、区域和场景，例如 Korean BBQ、Japanese、Mamak、cafe、家庭聚餐、约会。
- 试点仍是 Old Klang Road，也可以搜整个 Kuala Lumpur。没有写出区域时，系统要求补充，不猜城市。
- 价格和清真不再是默认筛选。有可靠价格才展示区间；没有价格就省略，餐厅仍可出现。
- 用户写出预算上限时，只有 `verified`、`estimated` 或 `demo_example` 且数字高于上限的记录才因价格排除。`not_verified`、`unknown`、没有上限的记录不排除。
- Google 搜索链接不能把价格升成已核实。这种记录在卡片上显示为价格未知，金额清空。
- 只有「certified / verified / must be / only halal」、马来文「halal yang disahkan」、中文「必须清真 / 只要清真」才要求已核实清真。单独说 halal 或清真不再过滤。
- 菜系和素食是硬条件。约会、氛围、家庭是解析出来的偏好，不拿来把 OSM 记录滤成 0，因为这些记录没有氛围标签。
- 不编造地址、评论、营业状态、坐标或认证。没有照片就显示占位，不用另一家店的图。

### 数据

- 推荐来源是 `data/processed/restaurants.json`，5,797 条。旧巴生路子集仍是 `data/processed/old_klang_road/restaurants.json`，798 条。
- `data/demo/restaurants.json` 和 `tests/unit/test_demo_dataset.py` 已删除。`DEMO_DATASET=true` 仍会去找已删除的路径，演示脚本把它设成 `false`。
- 未验收草稿没有导入：`restaurants_final_prices.json`、`restaurants_final_with_urls.json`、`restaurants_final_verified_full.json`，以及两份 researched/updated CSV。工作副本 `okr_review_batch1_25_work.csv` 没有改。
- 新发现不写进正式 JSON。符合条件的网页来源写入 `data/processed/discovered_restaurants.json`。同名但 URL 不同的记录进入 `data/processed/merge_candidates.json`，不自动合并。这次实测 Bing 返回的是语言和维基页面，没有街道信号，所以发现记录数是 0。

### LangGraph 发现流程

演示打开的是 `src/food_copilot/agents/discovery_graph.py`，不是五个互相调用的 LLM。`scripts/demo.ps1` 把 `ENABLE_LANGGRAPH=true`、`ENABLE_LLM_AGENT=false`。这条路径不需要 `OPENAI_API_KEY`。

```text
用户查询
  -> intent：DeterministicIntentParser
       缺区域 -> finalize，直接说明没有猜地点，不调用搜索
       有区域 -> retrieve：BM25 或 baseline，先过滤再排序再过滤
              -> search：Bing HTML
              -> match：对照店名，按规则决定是否写入发现库
              -> finalize：模板回答
```

节点职责：

| 节点 | 输入 | 输出 | 谁执行 |
|---|---|---|---|
| intent | 用户原文 | 区域、菜系、预算、饮食、氛围、是否需要澄清 | Python |
| retrieve | 结构化条件 | 最多 8 张餐厅卡片、排除计数、推荐理由 | Python，BM25 |
| search | 用户原文 | 标题、来源 URL、摘要，或失败原因 | Bing HTML，真实 HTTP |
| match | 本地卡片和网页结果 | 来源列表；可能插入一条未确认发现 | Python |
| finalize | 上面的状态 | `agent_mode=langgraph` 的 JSON | Python |

同时打开 `ENABLE_LLM_AGENT` 和 `ENABLE_LANGGRAPH` 时，`/api/chat` 仍走原来的 `agents/graph.py`：读记忆、Preference Agent、Recommendation Agent、Python 再检查 ID。那条路径缺 Key 返回 503。演示不走它。

### 网页搜索和 RAG

- 搜索实现在 `src/food_copilot/retrieval/web_search.py`。这台机器访问 DuckDuckGo HTML 得到 HTTP 202 和 anomaly 页面，所以没有用。Bing 搜索页返回 HTTP 200。解析的是结果标题、cite 里的来源地址和摘要。
- 搜索失败或 0 条时，回答写 `Web search failed (...)`，本地餐厅仍然列出。不会把失败说成已经联网成功。
- BM25 在 `retrieval/rankers.py`。演示进程 `ENABLE_BM25=true`，`/health` 的 `retrieval` 是 `bm25`。排序只发生在已经通过条件的记录上。
- Embedding 和 Hybrid 没有运行。`intfloat/multilingual-e5-base` 没有下载。
- 网页标题不会变成餐厅卡片。回答里单独有一行「Web sources, not treated as a confirmed branch」。
- 同一规范化店名、而且两边都有坐标时，只保留排序靠前的一家，除非用户在比较分店。没有坐标的测试记录不参与这个合并。

### 新餐厅入库

`src/food_copilot/data/discoveries.py` 的 `consider_web_result`：

1. 没有标题或不是 http(s) URL：跳过。
2. 标题像榜单（best、top、guide、list、review、restaurants 或数字开头）：跳过。
3. 标题和摘要都没有 Jalan、Lorong、Street 或 Old Klang Road：跳过。不因为出现了 “Kuala Lumpur” 就入库。
4. 规范化店名已经在正式库里：记为匹配到现有 ID，不新建。
5. 发现库里已有同一 URL：不重复插入。
6. 发现库里同名但 URL 不同：写入待确认队列，不合并。
7. 其余情况插入一条 `dataset_origin=discovered` 记录。地址、坐标、价格、清真保持空或 unknown。来源字段只记录实际拿到的 `name` 和 `description`。

仓库读取正式 JSON 后再附上这个侧车文件。正式文件不被覆盖。重复运行同一 URL 不会再插一行。

### 前端

导航只剩 Explore、AI Copilot、System Status。`/preferences` 和 `/evidence` 重定向到 `/`。页面文件还在，后端证据接口也还在，因为内部核对和测试仍使用它们。

- Explore 是一句话搜索，加上 Old Klang Road 或 Kuala Lumpur。没有预算滑块，没有清真下拉框。
- 餐厅卡片有菜系、地址或未核实说明、Google 地图链接。有坐标时用坐标查询；没有坐标时用名称和地址搜索，并标明位置未精确核对。没有确认来源的照片时显示占位。
- Copilot 默认例句是 “I want Korean BBQ around Old Klang Road.” 聊天超时是 60 秒。
- System Status 显示 API、数据集和条数、检索方式、LLM 开关、LangGraph、网页搜索是否在本进程打开、发现记录数。数据库配额写的是「无法从当前接口获取」。没有做一键清空正式库。没有 `FLUSHDB` 或 `FLUSHALL`。

### 实测

2026-10-17，重启后的 `http://127.0.0.1:8767`：

| 检查 | 结果 |
|---|---|
| `GET /health` | `dataset=canonical`，`dataset_records=5797`，`llm_agent=false`，`langgraph=true`，`retrieval=bm25`，`web_search=true`，`discovered_records=0` |
| Korean BBQ around Old Klang Road | HTTP 200，1975 ms，8 家 OSM 餐厅。第一家 Sae Ma Eul BBQ，`MY-OSM-node-13542862052`。价格为空。地图链接带该店坐标。同名第二家没有重复出现 |
| Family-friendly, Old Klang Road, under RM20 | HTTP 200，449 ms，8 家。区域 `old_klang_road`，预算 20。价格状态 `unknown`，没有金额。回答说明缺价格的餐厅仍会显示 |
| 单独的 Bing 查询 | 3 个真实页面：Korean language 维基、一个韩语学习站、Korea 维基。没有被存成餐厅 |
| `pytest -q` | 111 passed，2 个第三方库警告 |
| 前端 `npm test` 和 `npm run build` | 5 passed，构建退出码 0 |
| 浏览器 `/status` | 与 `/health` 一致，并显示配额无法从当前接口获取 |

### 删除和保留

删除：`data/demo/restaurants.json`、`tests/unit/test_demo_dataset.py`。它们只服务那 8 家虚构店。

保留：正式 JSON、OSM 原始文件、Kulim 历史、审核 CSV、迁移不存在所以没有删迁移、记忆表、MCP 工具、两个 LLM Agent、旧的 `agents/graph.py`、证据 API。

### 还没有做

- 五个各自调用模型的 Agent。演示故意少调用模型，避免再次超过前端等待时间。
- 带二次确认的数据库清理按钮，以及数据库真实占用字节。Neon 当前接口没有把配额交给这个应用。
- 多语言 embedding、Hybrid、pgvector。
- 评估标签。Recall@5 和 NDCG@5 仍然无法计算。
- 把 Bing 返回的非餐厅页面自动变成门店。当前规则会拒绝它们，这是预期行为。
- 公开部署、登录、速率限制、已测试的备份恢复。

### 启动

```powershell
powershell -File d:\project1\malaysia-food-copilot\scripts\demo.ps1
cd d:\project1\malaysia-food-copilot\frontend
npm run dev
```

打开 http://127.0.0.1:5173/copilot 。API 是 http://127.0.0.1:8767 。

`demo.ps1` 只改当前进程：`DEMO_DATASET=false`、`ENABLE_LLM_AGENT=false`、`ENABLE_LANGGRAPH=true`、`ENABLE_BM25=true`、`ENABLE_WEB_SEARCH=true`。`.env.example` 里这些开关仍是 false。变量名还有 `DATABASE_URL`、`REDIS_URL`、`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`、`ALLOW_UNAUTHENTICATED_MEMORY`。不要把值写进仓库。

可以演示的三句：

- I want Korean BBQ around Old Klang Road.
- Find a family-friendly restaurant in Old Klang Road under RM20.
- Find a good Japanese restaurant in Kuala Lumpur.

## 完成情况

| 项目 | 状态 | 说明 |
|---|---|---|
| OSM 采集与清洗 | 已完成 | 正式数据 5,797 条。旧巴生路 798 条，其余在吉隆坡扩展框 |
| 确定性发现、区域和明确预算过滤 | 已完成 | 缺价格仍可推荐。已知价格高于用户上限才排除 |
| 弹性预算和价格证据等级 | 已完成 | `verified`、`estimated`、`price_range_only`、`unknown`、`not_verified`。搜索链接不能当成已核实价格 |
| Vue 演示和 FastAPI | 已完成 | 页面走 REST。默认 `/api/chat` 不调用模型 |
| Neon 长期记忆和 Redis 短期记忆 | 已完成 | 会话条数、长度和 TTL 可配置。启动清理默认关闭，且不执行 FLUSHDB |
| 记忆接口的身份保护 | 已完成，不能公开 | 浏览器 ID 不是账号。公开服务器必须保持 `ALLOW_UNAUTHENTICATED_MEMORY=false` |
| MCP 六个工具 | 已完成 | 与发现流程共用同一套 Python 规则 |
| 两个 LLM Agent | 已完成，默认关闭 | `ENABLE_LLM_AGENT=false`。此前有过一次真实调用，这次审计没有再调用 |
| LangGraph 发现工作流 | 已完成 | `scripts/demo.ps1` 打开。节点是意图、BM25、Bing 搜索、对照和回答。不调用模型 |
| 证据校验和候选文件审计 | 已完成 | `restaurants_final_verified_full.json` 不能导入 |
| 前 5 家人工查阅记录 | 部分完成 | 有查阅笔记，没有一家被批准导入 |
| 第一批 25 家验收 | 未完成 | 工作副本 25 行仍是 `pending` |
| 第一批导回正式数据 | 未完成 | 正式价格和清真仍全部是 `not_verified` |
| 第二批 50 家核验 | 未完成 | 要等第一批导回之后 |
| 评估标注和 Recall@5、NDCG@5 | 未完成 | 5 条查询的相关 ID 都是空的，指标无法计算 |
| BM25 | 已接入演示 | `ENABLE_BM25=true` 时参与排序。Embedding 和 Hybrid 仍未运行，模型未下载 |
| Few-shot 提示 | 未完成 | 现有提示没有输入输出示例 |
| 生产身份验证、速率限制、备份恢复 | 未完成 | 本地演示可以，不能公开部署 |
| Zero-shot 与 Few-shot 的真实模型对比 | 未运行 | 开关是关闭的，没有为了对比去调用模型 |

## 现在停在哪里

命令行、`POST /api/discover` 和 Gradio 仍走确定性发现：解析、过滤、排序、再过滤。`scripts/demo.ps1` 启动的 `/api/chat` 走上面的 LangGraph 发现图，使用 BM25 和 Bing，不调用模型。成功标准是推荐来自正式记录和真实搜索，同时不把未知价格或网页标题说成已核实事实。

演示界面是 `frontend/` 里的 Vue。页面只有探索、对话和系统状态。浏览器走 FastAPI REST，不连接 MCP，也不在页面里判断预算或清真。Neon 保存会话和明确写入的偏好。Redis 保存当前会话最近消息。餐厅正式数据仍在 JSON，没有迁进 Neon。两个 LLM Agent 和旧的记忆 LangGraph 仍可测试，但演示进程不打开 `ENABLE_LLM_AGENT`。pgvector 还没开始。Gradio 只留作内部测试。

当前目标是用正式 OSM 餐厅做作品集演示。`data/demo/restaurants.json` 已删除，不再作为推荐来源。启动命令是 `scripts/demo.ps1`，它读取 `data/processed/restaurants.json`（5,797 条），打开 BM25、LangGraph 和 Bing 网页搜索，不打开 LLM。网页结果只作为来源列出，不会被写成已确认分店。带街道信息且不像榜单的新来源可以写入 `data/processed/discovered_restaurants.json`，不改正式文件。

人工核验仍停在 **第一批 25 家验收之前**，但这不再阻塞 Demo。正式工作副本 `data/staging/okr_review_batch1_25_work.csv` 与基准 `okr_review_batch1_25.csv` 一致，25 行都是 `pending`，地址、价格、清真都还是空的。这是以后导回正式数据时要对齐的文件。

旁边有未验收草稿，都没有导回正式 `restaurants.json`，也不能覆盖工作副本。

- `okr_review_batch1_25_researched_updated.csv`：22 行是 `needs_more_info`，3 行把地址标成已核（第 7 行 Restoran 83、第 14 行 Ye Look、第 21 行 Taste & Memories）。25 行的价格和清真都仍是 `not_verified`。按文件顺序的前 5 家全部是 `needs_more_info`。
- `okr_review_batch1_25_updated_with_prices.csv`：25 行里 22 行把 `price_status` 写成 `verified`，其中 21 行没有 `price_source_url`。清真 25 行都是 `not_verified`。地址已核和 `reviewed` 仍是那 3 行。备注里还有分店对不上的说明。没有来源 URL 的价格不能当成已核实。
- `data/processed/old_klang_road/restaurants_final_prices.json`：798 行。767 行把价格标成 `verified`，但没有价格来源 URL。31 行仍是 `not_verified`。
- `data/processed/old_klang_road/restaurants_final_with_urls.json`：同样 798 行，767 行 `verified`、31 行 `not_verified`。这 767 行的 URL 写在 `price_range_myr.source_url`，全部是 `https://www.google.com/search?q=...menu+price` 搜索链接，不是菜单或价格页。顶层没有 `price_source_url`。地址 `location_verified` 仍全是 `false`，清真 798 行都是 `not_verified`。搜索链接不能证明价格数字，所以这份文件仍不能导入。

评估问题的 `relevant_restaurant_ids` 仍是空的，所以还不能比较 Baseline、BM25、多语言 embedding 和 Hybrid 的分数。`.env.example` 里 BM25、embedding、Hybrid、LLM 和 LangGraph 仍是 `false`。`scripts/demo.ps1` 只在自己的进程里打开 BM25、LangGraph 和网页搜索。

2026-10-17 规则更新后的检查：`pytest` 111 项通过。前端 Vitest 5 项通过，`npm run build` 通过。更早一次在旧规则下把 LLM Agent 临时打开时，旧巴生路 RM20 返回 0 家，排除计数是 `price_unverified: 798`。那条结果不能再当作当前产品行为。当前行为见上面的实测表。三份候选 JSON 都没有导入。

## 已经完成

### 地理与采集

- 区域配置在 `src/food_copilot/config/regions.py`。主区域 `old_klang_road`，扩展区域 `kuala_lumpur`。范围是近似框，不是官方边界。
- OpenStreetMap Overpass 已按 `node` / `way` / `relation` 重采。原始文件在 `data/raw/old_klang_road/osm.json`（798 条）和 `data/raw/kuala_lumpur/osm.json`（5797 条）。
- 清洗后：旧巴生路 798 家（742 node、52 way、4 relation），其中有店名 767 家，带城市字段 206 家。这 798 家的中心点也都落在吉隆坡扩展框里。只属于扩展框、不属于旧巴生路的有 4998 家。另有 1 条 way 的中心点在框外，`regions` 为空，不会匹配区域查询。
- 去重键是 OSM 类型加 ID，不是店名。同名不同分店不会自动合并。
- Kulim 原始快照留在 `data/raw/osm_kulim.json`。当时的处理和审核文件在 `data/history/kulim/`。没有删除那 18 条南边坐标异常记录。

### 可运行系统

仓库读 `data/processed/restaurants.json`，不读审核草稿。正式数据里 5797 条价格都是 `not_verified`，没有自动标成已核实的清真或地址。

默认流程：

1. 确定性解析区域、菜系、素食、数字预算、已核实清真短语、家庭和约会场景、语言。没有区域时不猜测区域。只说便宜但没有数字时，不猜测 RM 上限。
2. 用 Python 做区域、菜系和素食过滤。用户写出预算时，只排除有可靠金额且高于上限的记录。清真过滤只在用户使用认证类说法时生效，而且 `verified` 必须有来源 URL。
3. 演示进程用 BM25 排序通过过滤的记录，然后再过滤一次。未打开 BM25 时仍是 baseline。相似度不能把不合格记录送回去。
4. 回答只根据过滤结果和实际搜索到的来源。缺价格时省略价格，不把这说成已确认低于预算。

界面和命令：

```powershell
cd d:\project1\malaysia-food-copilot
d:\project1\final-project\.python\python.exe -m pytest tests -q
d:\project1\final-project\.python\python.exe scripts\copilot.py flags
d:\project1\final-project\.python\python.exe scripts\copilot.py validate
d:\project1\final-project\.python\python.exe scripts\copilot.py discover "Find a family-friendly restaurant in Old Klang Road under RM20."
d:\project1\final-project\.python\python.exe scripts\copilot.py evaluate
d:\project1\final-project\.python\python.exe scripts\check_memory.py
d:\project1\final-project\.python\python.exe scripts\launch_ui.py
```

便携版 Python 不读取 `PYTHONPATH`。启动 API 时要把项目根目录和 `src` 放进 `sys.path`，再运行 `uvicorn` 的 `app:app`，端口 8767。直接执行 `python -m uvicorn app:app` 会报 `No module named 'food_copilot'`。

正式演示是 Vue，开发地址 http://127.0.0.1:5173 。启动方式在 `frontend/README.md`。API 在 http://127.0.0.1:8767 。Gradio 在 http://127.0.0.1:7860 ，只作内部测试，有聊天、只读审核查看、评估三个页。审核页可以对照工作副本，但不会批准或导入。Gradio 聊天还没有调用记忆接口。

### Vue 与 REST

浏览器只请求 FastAPI。MCP 留给以后的 Agent，不由页面直接连接。

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | API 是否可到达 |
| `POST` | `/api/discover` | 现有发现流程。请求字段是 `query` |
| `POST` | `/api/chat` | 复用同一条发现流程。同时带上 `user_id` 和 `session_id` 才保存对话 |
| `GET` | `/api/restaurants/{restaurant_id}` | 按确切 ID 读取餐厅 |
| `GET` | `/api/restaurants/{restaurant_id}/evidence` | 读取已存储的地址、价格、清真证据 |
| `GET` | `/api/memory/status` | Postgres 和 Redis 是否已配置 |
| `GET` | `/api/memory/preferences/{user_id}` | 读取已保存偏好 |
| `POST` | `/api/memory/preferences` | 保存偏好。页面未勾选确认时不会发送 |
| `DELETE` | `/api/memory/users/{user_id}` | 删除该浏览器身份的记忆 |

Vue 页面：`/` 探索，`/copilot` 对话，`/status` 状态。`/preferences` 和 `/evidence` 重定向到 `/`。探索页只收集一句话和区域，不提供预算或清真控件。对话页在演示进程里走 LangGraph 发现图，不调用语言模型。记忆接口仍使用浏览器本地 ID，这不是登录账号。没有可靠照片时使用占位。`not_verified` 和 `unknown` 不会用已核实的样式显示。

### 记忆

- 短期记忆：Redis，键 `session:{session_id}:messages`，默认最近 10 条、TTL 24 小时，可用环境变量调整。消息长度和长期偏好条数有上限。`REDIS_STARTUP_CLEANUP` 默认关闭；打开后只整理本应用的 `session:` 键，不执行 FLUSHDB。详见 `docs/redis_memory_policy.md`。
- 长期记忆：Neon 上的 Postgres。运行时由 `src/food_copilot/memory/store.py` 建表：`app_users`、`conversations`、`messages`、`user_preferences`。偏好是显式 API 写入，一次请求不会自动变成永久偏好。用户偏好也不是餐厅事实。
- 删除：`DELETE /api/memory/users/{user_id}` 会级联清掉该用户的 Postgres 记录，并删除对应 Redis 键。
- 配置在 gitignore 的 `.env`：`DATABASE_URL`、`REDIS_URL`，以及 Neon 部署写入的 `DATABASE_URL_UNPOOLED`、`NEON_BRANCH`、`NEON_FUNCTION_HELLO_BASE_URL`。示例文件 `.env.example` 只有空值。连接信息曾出现在聊天里，应在 Neon 和 Redis 控制台轮换后只更新本地 `.env`。
- Neon 项目已用 CLI 接到 `polished-sky-89197512` 的 `production` 分支。`neon.ts` 声明 Postgres 和 Function `hello`。`npm run build` 是 `tsc --noEmit`。
- 记忆路由在 `src/food_copilot/api/routes.py`：状态、追加消息、读取会话、保存偏好、读取偏好、删除用户。缺连接配置时返回 503。
- 这一步没有把 5797 家餐厅写入 Neon，也没有加 pgvector。

`.env.example` 里这些开关默认是 `false`：`ENABLE_BM25`、`ENABLE_MULTILINGUAL_EMBEDDINGS`、`ENABLE_HYBRID_RETRIEVAL`、`ENABLE_LLM_INTENT_PARSER`、`ENABLE_LLM_AGENT`、`ENABLE_LANGGRAPH`。`ENABLE_WEB_SEARCH` 不在示例文件里，未设置时也是关闭。演示脚本在一个进程里打开 BM25、LangGraph 和网页搜索。Embedding 模型没有下载。Hybrid 还要求同时打开 BM25。

Gradio 安装时把 FastAPI 从 0.115.6 升到了 0.143.1。测试是在升级后通过的。

### 审核抽样

- 全量审核表：`data/staging/restaurant_review.csv`（表头加 5797 行）。旧巴生路排在前面。
- 抽样脚本：`scripts/sample_okr_review.py`。随机种子 42。按来源类型 × `location_evidence` 用最大余数法分配名额。先抽 25 家，再从剩余记录补 25 家。第二批是累计 50 家，包含第一批。
- 第一批：`data/staging/okr_review_batch1_25.csv`。23 个 node、1 个 way、1 个 relation；6 条已有地址字段，19 条只有区域查询证据。
- 累计第二批：`data/staging/okr_review_batch2_50.csv`。前 25 行就是第一批。状态没有被改成 verified。
- 工作副本脚本：`scripts/prepare_okr_review_work.py`。已核对 25 个 ID 唯一、每行 `regions` 含 `old_klang_road`、关键字段非空、默认状态正确，并且工作副本与基准的列名、行数、ID 顺序一致。

工作副本前 5 行，也是接下来先验收的顺序：

| 顺序 | restaurant_id | name |
|---|---|---|
| 1 | MY-OSM-node-13403515145 | Sate Kajang Hj Samuri |
| 2 | MY-OSM-node-12084596958 | San Francisco Coffee |
| 3 | MY-OSM-node-13542862083 | Dessert Lab |
| 4 | MY-OSM-node-8541853946 | Oriental Treasure |
| 5 | MY-OSM-node-10239474750 | Nak Won |

### 评估

`data/eval/queries.jsonl` 有 5 条问题：4 条旧巴生路（英文、马来文、中文、中英混合），1 条吉隆坡已核实清真、RM25。`relevant_restaurant_ids` 全部为空。

`evaluation/runner.py` 会跑同一批问题，区分有标签和无标签，并统计预算、区域、清真违规和空结果。没有标签时不计算 Recall@5 或 NDCG@5。指标函数仍在 `retrieval/metrics.py`。

## 状态词

| 值 | 含义 |
|---|---|
| `not_verified` | 还没查，或查了但没有足够来源 |
| `unknown` | 查过仍然不能确定 |
| `verified` | 有来源 URL，而且来源对得上这一家门店 |
| `pending` | 这行还没人工看 |
| `needs_more_info` | 看过，证据不够 |
| `reviewed` | 这行查完了。可以是「已核实」，也可以是「确认仍然未知」 |

地址核实不会自动让价格或清真变成 `verified`。没找到清真证据，就保持 `not_verified`，不要写成 `false` 或「非清真」。

| 情况 | 系统现在的处理 |
|---|---|
| 价格 `not_verified` 或没有金额 | 仍可推荐，卡片不写价格。不把它说成已确认低于预算 |
| 价格已有可靠金额且高于用户写出的上限 | 排除，原因 `price_over_budget` |
| 清真 `not_verified`，且用户要求已核实清真 | 不通过已核实清真过滤 |
| 用户没有要求清真 | 不因为清真字段为空而排除 |
| 地址没有核实 | 不声称已确认门牌 |
| 检索上相关，但不满足硬性条件 | 以后可以记入相关性标签，但不能作为合格推荐 |
| 没有餐厅通过用户明确写出的条件 | 返回空结果并说明缺的是哪一个条件 |
| 只说便宜、没有数字，而且没有区域 | 不猜测区域和预算，要求补充 |
| 只说便宜、没有数字，但区域明确 | 不猜测 RM 上限，可展示已核实价格、标明的估价或大致档次 |

## 接下来

数据核验和工程功能分成两条线，可以并行。记忆、MCP Server、Vue、两个 Agent 和 LangGraph 已经完成。证据校验已经能拒绝没有来源 URL 的 `verified` 价格、清真和地址。`restaurants_final_prices.json` 没有价格来源。`restaurants_final_with_urls.json` 给 767 家补上了 URL，但全部是 Google 搜索链接，还没有打开并核对菜单，所以两份都没有导入。前 5 家的查阅记录在 `data/staging/okr_review_batch1_first5_audit.json`，正式 JSON 和工作副本都没改。`relevant_restaurant_ids` 仍是空的，评估不会计算 Recall@5 或 NDCG@5。下一步是把搜索链接换成能对上该门店的菜单或价格页；对不上的价格改回 `not_verified`。检索对比仍要等人工标签。记忆接口默认关闭，因为浏览器 `user_id` 不是登录；本地演示要显式设置 `ALLOW_UNAUTHENTICATED_MEMORY=true`。这不是生产身份验证。没有速率限制、版本化迁移或已测试的备份恢复。Oriental Treasure 的官网电话与 OSM 相同，但官网没有坐标，`location_verified` 仍是 `false`，工作副本没有改。

### 数据 1. 验收前 5 家

只看工作副本顺序的前 5 行。如果用草稿里的备注，先把通过检查的内容抄回 `okr_review_batch1_25_work.csv`，不要另开一份新的正式表。

每一行检查：

- `restaurant_id` 与 `okr_review_batch1_25.csv` 完全一致，顺序也不变。
- `address_evidence` 的 URL 支持该行地址，而且是这一家门店，不是同品牌另一家分店。对不上就清空地址，`location_verified` 保持 `false`，`review_status` 写 `needs_more_info`。
- 只有门牌对上这一家，`location_verified` 才是 `true`。
- 价格数字必须有菜单或价格页。没有就保持 `price_status=not_verified`，不要填估计区间。
- 清真只有 JAKIM 或该门店官方认证，并且来源覆盖这一家，才能 `verified`。公司主体或产品列表对不上分店时，保持 `not_verified`。
- `review_status` 只用 `reviewed`、`needs_more_info`、`pending`。
- 不要改 `restaurant_id`、`name`、坐标、`regions`、`source_url`、`location_evidence`、`source_type`。

前 5 家有一条不满足，就先改这 5 家，不要把后面 20 家当成已完成。

### 数据 2. 再看剩下 20 家

前 5 家通过后，用同一张清单看第 6 到第 25 行。草稿里那 3 家 `location_verified=true` 也要重新对来源：证据必须指到该 OSM 点对应的门店。Waze 或搜索链接如果不能单独证明门牌，就改回 `false`，备注保留，状态改成 `needs_more_info`。

25 行都落在工作副本里之后，再做一次整表检查：ID 与基准一致，每个 `verified` 都有来源，没有把「没找到」写成否定，导回时不会覆盖 OSM 原始字段。

### 数据 3. 把第一批导回正式数据

只导工作副本里已经 `reviewed` 的字段。`needs_more_info` 可以记备注，但不能把价格或清真改成 `verified`。

导回时保留 OSM 的 ID、坐标、来源链接和区域。人工地址、价格、清真写入对应证据字段，并带上来源 URL 和日期。缺来源的 `verified` 要被校验拒绝。未知价格可以展示但必须省略金额，区域成员仍不等于地址已核实。

### 数据 4. 第一批导回并检查通过后，才用第二批

`okr_review_batch2_50.csv` 的后 25 家按同样规则核。不要在第一批没导回之前改这 50 家的状态。

### 数据 5. 填写评估 ID

用人工判断填写 `data/eval/queries.jsonl` 的 `relevant_restaurant_ids`。

「相关餐厅」和「通过硬性条件的餐厅」分开。人认为相关，但价格或清真仍是 `not_verified` 的，可以出现在相关 ID 里，用来看检索有没有把它找出来；它仍然不能在 RM20 或「已核实清真」的结果列表里被当成合格推荐。ID 必须来自核过的记录，不要猜。

### 工程 1. MCP 和一个共享工具服务

已完成。`src/food_copilot/mcp/server.py` 用 MCP Python SDK 1.16.0 暴露一个 stdio Server。启动命令是 `scripts/mcp_server.py`。工具调用现有 discovery 和记忆服务，没有另写一套预算过滤。普通单元测试使用注入的餐厅记录和内存替身，不连接生产数据库。

第一版工具：

| 工具 | 作用 |
|---|---|
| `discover_restaurants` | 按区域、预算和偏好查找，走现有 discovery |
| `get_restaurant_details` | 按确切 ID 读取餐厅和证据 |
| `get_user_preferences` | 读取已保存的长期偏好 |
| `save_user_preference` | 保存用户确认过的偏好 |
| `get_restaurant_evidence` | 查看价格、地址、清真字段的来源 |
| `get_conversation_summary` | 读取过去会话摘要 |

只做一个 MCP Server。CLI、Gradio、FastAPI 和 MCP 共用同一套 Python 规则。

### 工程 2. 两个 LLM Agent

已完成，默认不启用。模型调用在 FastAPI 后面，使用 OpenAI SDK 1.109.1，不经过浏览器。Recommendation Agent 通过现有 MCP Server 调工具，Python 再检查一次餐厅 ID。Preference Agent 可以提出长期偏好；只有用户原文里有明确的记住或以后都这样的说法，才会写入。已保存的 `malaysia-food-copilot/.env` 已有 `OPENAI_API_KEY`。`ENABLE_LLM_AGENT` 默认仍是 `false`。缺 Key 时返回 503，不会打印 Key。

两个角色和外加的确定性控制层：

- Preference and Memory Agent：理解明确表达的偏好，读取历史记忆，提出要保存的长期偏好。不判断餐厅是否清真，不确认价格，不改餐厅事实。
- Restaurant Recommendation Agent：把需求转成查询，调用餐厅工具，只根据工具返回组织说明。不自行决定某家店价格合格，不把不合格餐厅塞回列表。
- Constraint Validator：继续用现有 Python 过滤。最后再检查一次回答里的餐厅 ID。它不调用 LLM。

一次请求里的「今天想吃辣」不自动写入长期偏好。区域缺失时先询问。未知价格可以出现，但不能写成已确认低于预算。模型文本有误时，最终结果仍必须经过 Python 检查。`ENABLE_LLM_AGENT` 在 `.env` 和演示脚本里都保持关闭。Agent 通过后端的 MCP Client 调用现有 MCP Server，不让浏览器直连。

### 工程 3. LangGraph

两套图都在。`src/food_copilot/agents/graph.py` 仍用 LangGraph 0.6.11 编排两个 LLM Agent，只有 `ENABLE_LLM_AGENT` 和 `ENABLE_LANGGRAPH` 同时为 true 才运行，并且需要 API Key。演示使用的是 `src/food_copilot/agents/discovery_graph.py`：只开 `ENABLE_LANGGRAPH` 时运行，不调用模型。旧图打开之后，同一次请求按这个顺序执行：

1. 读取 Redis 最近消息和 Postgres 长期偏好。
2. 调用现有 Preference Agent。临时需求不会写入；只有原文里有明确记住或以后都这样的说法才保存。
3. 调用现有 Recommendation Agent 和 MCP 工具。
4. 用现有 Python 再检查区域、预算和证据。
5. 回答里若出现未通过校验的餐厅 ID，改回校验结果。
6. 通过现有记忆服务保存这一轮用户和助手消息，然后返回。

请求仍是 `POST /api/chat`，字段是 `query`，可选 `user_id` 和 `session_id`。缺 Key 返回 503。模型调用失败返回 502，错误正文不含 Key。浏览器不连接 OpenAI 或 MCP。

### 工程 4. 三种检索对比

标签就绪之后，在同一批问题上打开可选检索，比较：

- 当前 baseline
- BM25（`ENABLE_BM25=true`）
- `intfloat/multilingual-e5-base`（`ENABLE_MULTILINGUAL_EMBEDDINGS=true`）
- Hybrid RRF（同时打开 BM25；要加入向量时再打开 embedding）

报告 `Recall@5`、`NDCG@5`、预算违规数（目标是 0）、区域违规数，以及没有任何店满足条件时的返回。向量分数不能覆盖预算和区域。结果为空时说明缺哪一类证据，不要放宽 RM20。

向量检索使用 Neon 上的 pgvector，餐厅描述和用户记忆摘要分开存放。查询用户记忆时限定 `user_id`。价格和清真仍从结构化字段和证据读取，不用向量相似度判断。没有人工标签时不计算、也不编造 Recall@5 或 NDCG@5。

这一步之前不要下载 embedding 模型，也不要把它设成默认检索。

## 价格证据和候选文件

正式数据仍是 `data/processed/restaurants.json`，5797 条。聊天和检索不会读取 `restaurants_final_verified_full.json`。系统提示要求模型不要说出内部文件名。

价格状态可以是 `verified`、`estimated`、`price_range_only`、`unknown`、`not_verified`，测试数据里还可以是 `demo_example`。`verified` 和 `estimated` 必须有支持这个数字的非搜索链接。Google 搜索链接会把展示降回未知，并清空金额。用户写出上限时，只排除可靠金额高于上限的记录。没有数字时不会猜一个 RM 上限，也不会因为缺价格把餐厅拿掉。

`data/processed/old_klang_road/restaurants_final_verified_full.json` 有 798 条，全部 ID 已在正式数据里，不能替换 5797 条。其中 767 条标成 verified 的价格来源都是 `www.google.com/search`，按证据等级全部是 unknown。133 条 `location_verified: true` 用的是 `address_string_match`，不是门店证明。清真字段里有 `certified_halal`、`likely_non_halal` 等当前清真状态不接受的值。结论：不能导入，也不能覆盖正式 JSON 或审核工作副本。审计数字在 `data/eval/reports/restaurants_final_verified_full_audit.json`。

## 先不要做

- 不把 `okr_review_batch1_25_researched_updated.csv`、`okr_review_batch1_25_updated_with_prices.csv`、`restaurants_final_prices.json`、`restaurants_final_with_urls.json` 或 `restaurants_final_verified_full.json` 覆盖正式数据或工作副本。Google 搜索链接不是价格证据。没有菜单或价格页支持的价格保持 `not_verified`。
- 不改 50 家清单的核验状态。
- 不填 `relevant_restaurant_ids`。
- 不把 BM25、embedding、Hybrid、`ENABLE_LLM_AGENT` 或 `ENABLE_LANGGRAPH` 写进 `.env` 当作全局默认。演示脚本可以只在一个进程里打开 BM25、LangGraph 和网页搜索。`OPENAI_API_KEY` 只放在 `malaysia-food-copilot/.env`，不要写进前端。
- 不把 5797 家餐厅迁进 Neon，也不另装 Qdrant、Chroma 或 Pinecone。
- 不把用户偏好当成餐厅的价格、地址或清真事实。
- 不把每一句聊天都做成 embedding。
- 不把 `final-project/` 改成马来西亚数据。
- 不发明价格、地址或清真认证。不抓清真目录，不绕过登录或验证码。
- 不把 Kulim 历史数据删掉。
- 不把 `.env`、`.env.local` 或 `.neon` 提交进 git。
- 不以「推荐出了多少家」当作这一阶段的成功标准。
