# Codex 智力档能力自适应改造 — 设计文档 (v3)

**日期**: 2026-07-12
**范围**: 仅 `plugins/codex`(antigravity **零改动零升版**)
**版本**: codex-for-claude `1.1.0-fh.3 → 1.1.0-fh.4`(patch)
**评审**: Claude → Gemini(agy)→ Codex(companion task, xhigh)三模型串行

> **版本演进**
> - **v1** 地基「`xhigh` 是最强档、底层无 effort discovery」被 Codex 读取本机 `models_cache.json` 证伪(已复核)。
> - **v2** 改为模型分组白名单派生,但**排除 `ultra`**(误判其委派会绕过 governor)。
> - **v3(本版)**:实测推翻 v2 的 ultra 排除 —— `ultra` 就是最新模型顶级 effort,实测为普通单 turn、不绕过 governor。`--quality max` 路由到该模型**真·最高档(含 ultra)**。

---

## 1. 背景与问题

用户诉求:「修复类似问题,使其更自然、通用、兼容最新模型和智力水平」,并明确「还是需要卡合法值,多一个验证步」。落到 codex 插件:

1. **`--quality max` 达不到最强档(bug)**。`quality-policy.mjs` 里 `max.effort` 与 `strong.effort` 都写死 `"high"`,而模型支持更高档。三个真实入口生效:`adversarial-review`(入口固定传 `reviewName: "Adversarial Review"`,`:1619` → `:1065` 条件恒真)、`task`(`:1094`)、`multi-review`(`:1556`)。**不是死代码。**
2. **effort 能力按模型变化,单一硬编码无法正确**。见 §2。

## 2. 经实测校准的关键事实(设计地基)

| 事实 | 证据 |
|---|---|
| codex CLI **自己生成** `models_cache.json`,含每模型 `supported_reasoning_levels` | 文件顶层 `fetched_at`/`client_version`(0.144.0);路径 `$CODEX_HOME/models_cache.json`,默认 `~/.codex/` |
| **effort 上限按模型变化** | sol/terra→ultra, luna→max, 5.5/5.4/mini/auto-review/image-2→xhigh |
| 强度顺序 | `low < medium < high < xhigh < max < ultra`;`ultra` 是最新模型(sol/terra)**顶级档** |
| **`ultra` 实测就是普通单 turn,不绕过 governor** | `runAppServerTurn("/tmp",{effort:"ultra",model:"gpt-5.6-sol"})` → `msg=OK`,单 turn,38s,无异常;governor 计 companion 发起的 turn 数(`acquireResourceLease("model-call")` :1029),ultra 与 max/xhigh 同为一个 turn;`supports_parallel_tool_calls=false` |
| effort 走 **app-server 协议** `turn/start.effort` 字段(非 CLI flag) | codex.mjs:1020;`codex exec --help` 无 effort flag |
| app-server 对未知 effort **静默接受不报错** | `runAppServerTurn("/tmp",{effort:"ultra"})` → 不报错 |
| **model=null(默认)时插件拿不到确切模型 slug** | `config/read` 未读 `config.model`;`getSessionRuntimeStatus` 无 model 字段 |

## 3. 设计:模型分组白名单 + 自动路由(派生式)

### 3.1 核心:按当前模型路由到「它支持的最高档」

`--quality max` 不再映射到写死的档,而是**按当前选定模型,从 codex 自己的 `models_cache.json` 派生出该模型支持的最高 effort 档**。这是真·自适应:codex 出新模型 → 缓存自动更新 → 路由自动跟随,**零代码改动**;且给到该模型能提供的**真·最强智力**(含 ultra)。

**分组(从 `models_cache.json` 运行时派生,当前快照示意)**:

| 最高档 | 模型 |
|---|---|
| `ultra` | gpt-5.6-sol / terra |
| `max` | gpt-5.6-luna |
| `xhigh` | gpt-5.5 / 5.4 / 5.4-mini / codex-auto-review / gpt-image-2 |

### 3.2 新增:`plugins/codex/scripts/lib/effort-policy.mjs`

```js
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// effort 强度顺序(仅用于「取最强」比较,不作为合法性来源)。
const EFFORT_ORDER = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"];

// 跨所有已知模型都支持的档交集的最强 —— cache 缺失/损坏/未知模型时的安全兜底。
export const FALLBACK_MAX_EFFORT = "xhigh";

function modelsCachePath(env = process.env) {
  const home = env.CODEX_HOME || path.join(os.homedir(), ".codex");
  return path.join(home, "models_cache.json");
}

// 读 codex 自己的缓存;任何失败都返回 null,由调用方兜底(不抛)。
function readModelsCache(env = process.env) {
  try {
    return JSON.parse(fs.readFileSync(modelsCachePath(env), "utf8"));
  } catch {
    return null;               // 缺失/损坏/无权限 -> 兜底路径
  }
}

// 该模型支持的 effort 全集(合法值来源:按模型,不是全局白名单)。
export function supportedEffortsForModel(model, env = process.env) {
  const cache = readModelsCache(env);
  const entry = cache?.models?.find((m) => m.slug === model);
  if (!entry) return null;     // 未知模型 / 无缓存
  return (entry.supported_reasoning_levels || []).map((lv) => lv.effort);
}

// 按当前模型取「最高档」;拿不到模型能力时兜底 FALLBACK_MAX_EFFORT。
export function highestEffortForModel(model, env = process.env) {
  const supported = supportedEffortsForModel(model, env);
  if (!supported || !supported.length) return FALLBACK_MAX_EFFORT;
  return supported.reduce((best, e) =>
    EFFORT_ORDER.indexOf(e) > EFFORT_ORDER.indexOf(best) ? e : best, supported[0]);
}

// 合法值校验(保留用户要的「验证步」)。有模型能力时按模型校验;拿不到时按已知全集兜底。
export function validateEffort(value, model = null, env = process.env) {
  if (value == null) return null;
  const normalized = String(value).trim().toLowerCase();
  if (!normalized) return null;
  const supported = (model && supportedEffortsForModel(model, env)) || EFFORT_ORDER;
  if (!supported.includes(normalized)) {
    throw new Error(
      `Unsupported reasoning effort "${value}". Supported: ${supported.join(", ")}.`
    );
  }
  return normalized;
}
```

### 3.3 codex 改造(复用现有链路)

1. **`quality-policy.mjs`**:`max` 不再写死 effort;改为**运行时按当前模型解析**。因 quality-policy 本身不知道模型,把「解析最高档」延后到调用点:`resolveQuality("max")` 返回一个标记(如 `effort: null` + `wantsHighestEffort: true`),调用点(`:1065/1094/1556`)拿到当前 `model` 后调 `highestEffortForModel(model)` 得出实际 effort。`strong` 保持 `"high"`,`standard`/`fast` 不变。`max` 仍是合法 quality 值(**不删、不改兼容**)。
2. **`codex-companion.mjs`**:`normalizeReasoningEffort` 委托 `validateEffort`(传入当前 model 做按模型校验);**删除 `:154` 硬编码的六档错误信息**(改由 `validateEffort` 动态抛出);删除本地 `VALID_REASONING_EFFORTS`。
3. **usage 补 `--quality`**:`task` 的 usage(`:104`)补上 `[--quality <fast|standard|strong|max>]`(它 `valueOptions` 已接受,只是没文档化)。
4. **默认 model / `MODEL_ALIASES` 不动**。

### 3.4 路由的三个分支(全部实测验证)

| 场景 | 当前 model | `--quality max` → | 依据 |
|---|---|---|---|
| 显式顶级 | gpt-5.6-sol/terra | `ultra` | 该模型 supported 最强档 |
| 显式次级 | gpt-5.6-luna | `max` | 同上 |
| 显式次代 | gpt-5.5/5.4/... | `xhigh` | 同上 |
| 未知模型 / model=null | spark / null | `xhigh`(`FALLBACK_MAX_EFFORT`) | cache 无此 slug → 兜底 |

## 4. 决策记录(三模型串行审阅 + 用户产品决策)

- **决策1 antigravity**:No touch, no bump。理由**修正**(Codex Q-B 翻案):antigravity `selectAgyModel` 的硬编码 default 是「首选匹配目标」(`agy-capabilities.mjs:124` `catalogModels.find((model) => model === fallback) || catalogModels[0]`),**不是**「仅 catalog 失败时兜底」。决策不变(范围限定 codex),但删除「已完全自适应/仅失败兜底」的错误表述。
- **决策2 `--quality max` 语义(用户已定,v3 修正)**:路由到**该模型的真·最高档,含 `ultra`**。v2 曾排除 ultra,理由是「委派绕过 governor」;**实测推翻**:ultra 是普通单 turn,governor 计 companion 发起的 turn 数,ultra 与 max/xhigh 无差别,不绕过。故给用户该模型能提供的最强智力。
- **Q-A(三方一致)**:用显式策略,不靠数组末项派生「最强」。v3 用 `EFFORT_ORDER` 显式序 + 按模型 supported 取最强(`reduce` 比较序号),非「数组末项」。
- **R1(Codex 翻案,Gemini 让步)**:adversarial-review 入口固定生效,spec 未夸大覆盖面。
- **R2/R3(三方 CONFIRM)**:usage 补 `--quality`;删 `:154` 硬编码错误信息。

## 5. 不做什么(YAGNI)

- **不给 antigravity 加 effort 维度**:抽象泄漏,且范围限定 codex。
- **不手写分组表**:派生式自动跟随最新模型(用户决策),避免回到硬编码。
- **不排除任何档**:`--quality max` 给该模型真·最强(v3 修正,ultra 不再排除)。

## 6. 测试(每条 fail-on-revert)

| 测试 | 断言 |
|---|---|
| 按模型路由最高档 | `highestEffortForModel("gpt-5.6-sol")==="ultra"`;`("gpt-5.6-luna")==="max"`;`("gpt-5.5")==="xhigh"` |
| 未知/空模型兜底 | `highestEffortForModel("spark")` 和 `(null)` 都 === `FALLBACK_MAX_EFFORT`("xhigh") |
| cache 缺失兜底 | 指向不存在的 `CODEX_HOME` → 返回 `FALLBACK_MAX_EFFORT`,不抛 |
| `validateEffort` 按模型 | 对 gpt-5.5 传 `"ultra"` 抛错(5.5 不支持);对 sol 传 `"ultra"` 通过 |
| `validateEffort` 拼写 | 传 `"bogus"` 抛错,信息含 supported 列表(**非硬编码**) |
| `--quality max` 端到端 | 经 `resolveQuality`+路由,sol 下 effort 落到 `ultra`、默认/未知模型落到 `xhigh`(**改回 `"high"` → 变红**,锚定原始 bug) |
| `strong` 不变 | `resolveQuality("strong").effort === "high"` |
| 更新既有断言 | `test_codex_for_claude_plugin.py:7616` 和 `:7630`(两个 quality-policy 测试)的 `maxq["effort"] == "high"` 断言随之更新为按模型解析后的值 |

外加 codex 全量回归 + `release-check` 0 FAIL。

## 7. 发布流程

回归 green → 版本 `fh.3→fh.4`(plugin.json/marketplace.json/version.mjs/README/CHANGELOG/plugin_versions.py)→ CodeRabbit 至 0 findings → 合并 → 本地 re-pin(uninstall+install)→ 验证 `installed_plugins.json` 指向 fh.4。

## 8. 已知维护点 / 残留风险(诚实记录)

- **`FALLBACK_MAX_EFFORT="xhigh"` 是唯一软性假设**:它是「所有当前已知模型都支持的档交集的最强」。派生路径对已知模型自动正确,此兜底仅影响 model=null/未知模型的场景。若未来所有模型都升到更高档且 xhigh 被弃用,需人工复核。
- **model=null 拿不到确切模型**:app-server 协议现状(未回报默认 model),故默认场景走兜底 `xhigh` 而非「CLI 真实默认模型的最强档」。若 codex 后续在 `config/read` 暴露选定 model,可移除此兜底、走完全路由。
- **`ultra` 委派的长期观察项**:实测当前为单 turn、不绕过 governor;但 ultra 的服务端委派语义(`multi_agent_version: "v2"`)若未来演进为对客户端可见的多 turn,需重新评估 governor 计数(当前无此行为,不构成本次风险)。
