# ontology_schema

Palantir 式「结构 + 动作」本体的开源落地方案：**结构层用 Neo4j 官方的
[ontology-graph-spec](https://github.com/neo4j/ontology-graph-spec)，动作层（ActionType）
独立成文档，两者通过 id 引用耦合，由跨文档校验器保证一致性。**

LLM agent 读取两份定义做推理与决策；执行器按参数校验 → 审批门 → 前置检查 → 绑定执行的
流水线落地，全程留审计。

## 目录结构

```
ontology_spec/
├── examples/
│   └── movies/                          # 示例：电影领域
│       ├── model.ontology.yaml          #   结构层（纯官方格式）
│       ├── model.actions.yaml           #   动作层（3 个 ActionType，覆盖低/中/高风险）
│       └── dist/                        #   构建产物（generated，不入库）
├── schemas/
│   ├── ontology-graph-spec.schema.json  # Neo4j 官方 1.1.0 JSON Schema（离线备份）
│   └── actions.schema.json              # 动作格式的 JSON Schema（仿官方风格）
├── tools/
│   ├── validate.py                      # 三层校验：官方 schema + 动作 schema + 跨文档规则
│   ├── compile.py                       # 合并成单文件分发产物 dist/model.combined.yaml
│   ├── export_mcp.py                    # 导出 MCP 工具清单 dist/tools.mcp.json
│   └── run_action.py                    # 执行器（dry-run / 真执行，含审批门与审计）
└── README.md
```

依赖：Python 3.10+，`pip install pyyaml jsonschema`（真执行再装 `neo4j`）。

所有工具默认作用于 `examples/movies`；换目录传位置参数（`run_action.py` 用 `--example`）：

```bash
python tools/validate.py                          # ① 校验（三层）
python tools/compile.py                           # ② 合并单文件（仍过官方 schema）
python tools/export_mcp.py                        # ③ 导出 MCP 工具清单

python tools/run_action.py assign_actor_to_movie --param actor_id=nm1 --param movie_id=mv1          # dry-run
python tools/run_action.py update_movie_genre --param movie_id=mv1 --param genre=DRAMA --execute   # 真执行
```

## 与 Palantir Ontology 的概念对照

| Palantir | 本方案 | 位置 |
|---|---|---|
| Object Type / Link Type | nodes / relationships | model.ontology.yaml |
| Action Type parameters | parameters（binds 锚定本体属性） | model.actions.yaml |
| Function 绑定 | binding（cypher / mcp / http） | 同上 |
| Submission criteria | governance（risk / approval / reversible / undo） | 同上 |
| Write-back 声明 | targets（node/relationship + mode） | 同上 |
| OSDK / AIP agent | MCP 工具清单 + LLM 读取定义 | dist/tools.mcp.json |

## 为什么「独立文档」而不是塞 custom 或 fork

- **独立文档**：动作与本体版本节奏不同、归属不同的人；可单独做 JSON Schema 校验；
  Neo4j 官方格式升级零影响。
- **compile.py 生成的合并文件**只是分发产物：动作嵌入 `extensions.custom["acme.actions.v1"]`
  （规范明确"不赋予含义"的逃生舱），合并文件重新过官方 schema 校验，官方库
  decode/encode 原样保留，Neo4j 工具不认识就忽略——双向不干扰。
- **不 fork**：官方 schema 全部 `additionalProperties: false`，顶层加字段必须 fork
  三个语言库（JVM/JS/Go），且上游在活跃演进，维护成本不值。

## 跨文档校验规则（validate.py 第三层）

错误（阻断）：
1. `actions.ontology.id/version` 必须与本体文档一致；
2. `binds.node/relationship` 必须存在于本体；`binds.property` 必须是该对象已定义属性；
3. `parameters.*.type` 必须与本体属性类型一致；
4. `parameters.*.enum` 必须与本体属性 `one_of` 完全一致（枚举漂移即错）；
5. `targets[].node/relationship` 必须存在于本体；
6. `governance.risk: high` 必须 `approval: true`。

警告（提示）：参数未 binds / 未在 cypher 中引用 / description 过短（<16 字符，影响 LLM 推理质量）。

## 执行器安全流（run_action.py）

```
参数校验（含枚举） → 审批门（high 风险拒绝 --execute） → precondition check（Cypher 布尔）
→ binding 执行 → dist/audit.jsonl 审计（含被拒绝的尝试）
```

## 改成你自己的

- 组织命名空间：把 `compile.py` 的 `NAMESPACE = "acme.actions.v1"` 和两份文档里的
  `schema:` URI 换成你的域名；
- 加新领域：新建 `examples/<name>/`，放一对 `model.ontology.yaml` + `model.actions.yaml`，
  三个构建工具传目录参数即可；
- 动作格式演进：`schemas/actions.schema.json` 独立版本化（$id 里的 1.0.0）；
- 接真实 MCP server：`dist/tools.mcp.json` 的 tools 结构与 MCP tool 定义同构
  （name/description/inputSchema），包一层 `@modelcontextprotocol/sdk` 即可对外服务。

## 设计依据（为什么这些字段）

- `preconditions`/`effects` 双写（自然语言 + 机器可查）：OWL-S IOPE 模型的 P/E；
  自然语言版给 LLM 推理，Cypher 版执行前真查——Palantir submission criteria 的低成本等价物。
- `targets.mode`：MERGE/CREATE 复用 spec 的 MappingMode 词汇，UPDATE/DELETE 为本格式扩展。
- `description` 是给 agent 的主语义载体，校验器对过短的描述发警告。

## 致谢与许可

- `schemas/ontology-graph-spec.schema.json` 来自
  [neo4j/ontology-graph-spec](https://github.com/neo4j/ontology-graph-spec)（Apache License 2.0），
  此处为离线校验备份，版权归 Neo4j 所有。
- 其余文件为本项目原创，按仓库许可证发布。
