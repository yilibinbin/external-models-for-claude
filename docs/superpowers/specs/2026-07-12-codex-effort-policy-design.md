# Codex 智力档能力自适应改造 — 设计文档 (v4)

**日期**: 2026-07-12
**范围**: 仅 `plugins/codex`(antigravity **零改动零升版**)
**版本**: codex-for-claude `1.1.0-fh.3 → 1.1.0-fh.4`(patch)
**评审**: Claude → Gemini(agy)→ Codex(companion task, xhigh)三模型串行,v1/v2/v3 均被审阅推翻后重写

> **版本演进（诚实记录）**
> - **v1**「`xhigh` 是最强档、底层无 discovery」被 Codex 读 `models_cache.json` 证伪。
> - **v2** 排除 `ultra`(误判委派绕过 governor)—— 实测推翻(ultra 是普通单 turn)。
> - **v3** 取 `supported_reasoning_levels` 数组末项 + `model=null→xhigh` 兜底 —— 被 Codex 证伪:(A) 数组无升序契约不能盲取末项;(B) `model=null` 是主路径,兜底 xhigh 没修好原始 bug;(C) 未知模型放行未声明档=假成功;(D) 现存 `VALID_REASONING_EFFORTS` 有更根本的双向 bug(拦截 sol 真实支持的 max/ultra)。
> - **v4(本版)**:探明 app-server **`model/list`** 方法(带 `isDefault` 标记 + 按模型 `supportedReasoningEfforts`),解决 B/C/D;A 用「显式序 + 未知档 fail loud」处理。

---

## 1. 背景与问题(v4 修正后的完整问题集)

用户诉求:「修复类似问题,使其更自然、通用、兼容最新模型和智力水平」,并明确「还是需要卡合法值,多一个验证步」。三模型审阅逐层暴露出**四个真实问题**:

1. **`--quality max` 达不到最强档**:`quality-policy.mjs` 的 `max.effort` 写死 `"high"`(三入口生效:`:1065` adversarial-review 固定生效 / `:1094` task / `:1556` multi-review)。
2. **现存 `VALID_REASONING_EFFORTS` 双向 bug(比 #1 更根本)**:全局集合 `{none,minimal,low,medium,high,xhigh}`(codex-companion.mjs:91)**拦截了 `gpt-5.6-sol` 真实支持的 `max`/`ultra`**——用户现在 `--model gpt-5.6-sol --effort ultra` 直接被拒(实测)。同时放行所有模型都不支持的 `none`/`minimal`。
3. **effort 能力按模型变化,全局校验/映射无法正确**:sol/terra→ultra, luna→max, 5.5/5.4/mini→xhigh。
4. **`:154` 硬编码的六档错误信息** + **`task` usage 漏 `--quality`**。

## 2. 经实测校准的关键事实(设计地基)

| 事实 | 证据 |
|---|---|
| app-server 有 **`model/list`** 方法,返回权威模型能力 | 实测 `client.request("model/list",{})` → `{data:[...], nextCursor}` |
| **默认模型可知**:模型带 `isDefault` 标记 | `model/list` 中 `gpt-5.6-sol` 有 `isDefault:true`(model=null 时 codex 实际用它) |
| **按模型的 effort 能力** | 每模型有 `supportedReasoningEfforts`(元素 `{reasoningEffort, description}`)+ `defaultReasoningEffort` |
| effort 上限按模型变化 | sol/terra→ultra, luna→max, 5.5/5.4/mini→xhigh |
| `ultra` 是普通单 turn,**不绕过 governor** | 实测 `effort=ultra`+sol → 单 turn 38s OK;governor 计 companion 发起的 turn 数;`supports_parallel_tool_calls=false` |
| `supportedReasoningEfforts` **无 rank 字段**,数组顺序无契约 | 元素仅 `{reasoningEffort, description}`(Codex 坚持:不能盲取末项) |
| `model/list` 开销可忽略 | roundtrip **51ms**;companion 跑 task 本就在 `withAppServer` 内起 app-server,同 client 顺带调用无额外冷启动 |
| `config/read` / `config.toml` **拿不到默认模型** | `config/read` 返回 `model=null`;config.toml 无 model 键 |

## 3. 设计:app-server model/list 驱动的按模型 effort 路由

### 3.1 核心:在 `withAppServer` 块内解析真实模型能力

effort 解析**延后到 app-server session 内**(`executeTaskRun`/`executeReviewRun` 已在 `withAppServer(cwd, async (client) => …)` 块中):拿到 `client` 后,先 `client.request("model/list")` 得到模型能力表,再据此:
- 确定**当前模型**:显式 `--model X` → 用 X;`model=null` → 用 `isDefault:true` 的模型。
- 该模型的 `supportedReasoningEfforts` = 合法档全集(**校验来源**)。
- `--quality max` → 该模型 supported 里**按 `EFFORT_ORDER` 显式序取最强**(不盲取末项)。

### 3.2 新增:`plugins/codex/scripts/lib/effort-policy.mjs`

```js
// 已知 effort 强度显式序(仅用于「已知档取最强」比较,不作为合法性来源)。
// 【维护点】codex 出新档时在此追加;未在此列的档触发 fail-loud(见 highestKnownEffort)。
const EFFORT_ORDER = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"];

// 从 model/list 的一条模型记录取其 supported effort 列表(纯数据变换,无 I/O)。
export function supportedEffortsOf(modelEntry) {
  return (modelEntry?.supportedReasoningEfforts || []).map((lv) => lv.reasoningEffort);
}

// 从 model/list 结果选出「当前模型」记录:显式 model 优先,否则 isDefault。
export function resolveModelEntry(models, requestedModel) {
  if (requestedModel) {
    return models.find((m) => (m.id || m.model) === requestedModel) || null; // 未命中 -> null(调用方 fail loud)
  }
  return models.find((m) => m.isDefault) || null;
}

// 该模型的最强档:在其 supported 内、按 EFFORT_ORDER 取最强。
// 若 supported 含 EFFORT_ORDER 之外的未知档 -> 抛错(fail loud,不静默选错)。
export function highestKnownEffort(supported) {
  const unknown = supported.filter((e) => !EFFORT_ORDER.includes(e));
  if (unknown.length) {
    throw new Error(
      `Codex reported unknown reasoning effort(s) [${unknown.join(", ")}] not in this plugin's known set ` +
      `[${EFFORT_ORDER.join(", ")}]; update effort-policy.mjs. Refusing to guess the strongest tier.`
    );
  }
  return supported.reduce((best, e) =>
    EFFORT_ORDER.indexOf(e) > EFFORT_ORDER.indexOf(best) ? e : best, supported[0]);
}

// 按模型校验用户所选 effort(保留「验证步」;按真实模型能力,不是全局白名单)。
export function validateEffortForModel(value, supported) {
  if (value == null) return null;
  const normalized = String(value).trim().toLowerCase();
  if (!normalized) return null;
  if (!supported.includes(normalized)) {
    throw new Error(
      `Model does not support reasoning effort "${value}". Supported: ${supported.join(", ")}.`
    );
  }
  return normalized;
}
```

### 3.3 codex 改造

1. **`codex.mjs`**:在 `withAppServer` 块内、`turn/start`/`review/start` 之前,新增一次 `client.request("model/list", {})`,把结果传给 effort 解析。**model/list 失败 → 兜底**(见 §3.4)。
2. **`quality-policy.mjs`**:`max` 不再写死 effort;返回哨兵 `wantsHighestEffort: true`(effort 由调用点按当前模型解析)。`strong`→`high`,`standard`/`fast` 不变。`max` 仍是合法 quality(**不删不改兼容**)。
3. **`codex-companion.mjs`**:
   - `normalizeReasoningEffort` 的**校验从全局 `VALID_REASONING_EFFORTS` 改为按模型**(委托 `validateEffortForModel`,用 model/list 拿到的 supported)。**删除 `:91` 全局集合与 `:154` 硬编码错误信息**(它们正是问题 #2/#4)。
   - 因校验需要 model 能力(app-server session 内才有),把「非法 effort 拦截」下沉到 session 内的解析点;命令行层只做语法预检(非空、无注入),真正的按模型合法性在 session 内 fail loud。
   - **`--effort` 显式值优先于 `--quality max` 哨兵**(不能让哨兵覆盖用户显式 effort)。
4. **usage 补 `--quality`**(`task` 的 `:104`);**默认 model / `MODEL_ALIASES` 不动**。

### 3.4 兜底策略(model/list 不可用时,fail loud 而非假成功)

| 情况 | 处理 |
|---|---|
| model/list 成功 + 命中模型 | 正常按模型路由/校验 |
| 显式 `--model X` 但 model/list 无 X | **fail loud**:报错「未知模型 X,无法验证其 effort 能力」,不静默放行 |
| model=null 且无 isDefault 模型 | **fail loud** 或退回 codex 默认 effort(不谎称「最强」) |
| model/list 请求失败(网络/协议) | `--quality max` 退回一个**保守且明确标注**的档(`FALLBACK="xhigh"`,所有已知模型都支持),并 `onProgress` 告警「未能确认模型能力,已用保守档 xhigh」——**不静默谎称最强** |

### 3.5 路由分支(全部实测验证)

| 场景 | 当前模型 | `--quality max` → |
|---|---|---|
| model=null(默认) | isDefault=`gpt-5.6-sol` | **`ultra`**(主路径现在也到顶,修好 v3 证伪 B) |
| 显式 `--model gpt-5.6-luna` | luna | `max` |
| 显式 `--model gpt-5.5` | 5.5 | `xhigh` |
| 显式未知模型 | — | **fail loud**(不猜) |
| model/list 失败 | — | `xhigh` + 告警(不谎称最强) |

## 4. 决策记录(三模型串行审阅收敛 + 用户产品决策)

- **决策1 antigravity**:No touch, no bump(理由已修正:default 是首选匹配非仅兜底,`agy-capabilities.mjs:124`)。
- **决策2 `--quality max`(用户已定)**:路由到该模型真·最高档,**含 `ultra`**(实测 ultra 不绕过 governor)。
- **A(数组末项,Codex 坚持 / Gemini 让步)**:**不盲取末项**。用显式 `EFFORT_ORDER` 取最强;遇未知档 **fail loud**(不猜)。
- **B(Codex,主路径没修)**:v4 用 `model/list` 的 `isDefault` 拿真实默认模型 → **主路径(默认 sol)也到 ultra**,解决。
- **C(Codex,未知模型放行=假成功)**:未知模型 **fail loud**,不静默放行。
- **D(Gemini 自查强化)**:删除全局 `VALID_REASONING_EFFORTS`;按模型 `supportedReasoningEfforts` 校验。
- **V-Q2(三方一致)**:仅 3 处 `resolveQuality` 入口(1045/1093/1535),无第 4 处;但需加测「`--effort` 显式优先于 `--quality max` 哨兵」。

## 5. 不做什么(YAGNI)

- **不给 antigravity 加 effort 维度**(抽象泄漏,范围限定 codex)。
- **不盲取数组末项**(无升序契约,Codex 对)。
- **不静默猜测/放行**(未知模型、未知档、model/list 失败都显式处理)。

## 6. 测试(每条 fail-on-revert)

| 测试 | 断言 |
|---|---|
| 默认模型路由 | `resolveModelEntry(models, null)` 命中 `isDefault` 模型;其 `--quality max` → 该模型最强档(fixture sol → `ultra`) |
| 显式模型路由 | luna → `max`;5.5 → `xhigh`(fixture) |
| 未知档 fail loud | `highestKnownEffort(["low","hyper"])` **抛错**(不静默选 low/hyper) |
| **乱序 supported** | `highestKnownEffort(["ultra","low","high"])` === `ultra`(证明**不靠数组顺序**) |
| 按模型校验 | `validateEffortForModel("ultra", sol.supported)` 通过;`validateEffortForModel("max", gpt5.5.supported)` **抛错**(5.5 不支持 max) |
| 现存 bug 修复 | 删掉全局 `VALID_REASONING_EFFORTS` 后,`--model gpt-5.6-sol --effort ultra` **不再被拦**(改回全局集合 → 变红,锚定问题 #2) |
| 未知模型 fail loud | 显式 `--model bogus` + model/list 无 bogus → 抛错,不静默兜底 |
| model/list 失败兜底 | 模拟 model/list 抛错 → `--quality max` 得 `xhigh` + 告警(不静默称最强) |
| `--effort` 优先 | `--effort high --quality max` → 实际用 `high`(显式优先于哨兵) |
| `strong` 不变 | `resolveQuality("strong").effort === "high"` |
| 更新既有断言 | `test_codex_for_claude_plugin.py:7616`/`:7630` 的 `maxq["effort"]=="high"` 断言更新为哨兵语义 |

外加 codex 全量回归 + `release-check` 0 FAIL。

## 7. 发布流程

回归 green → 版本 `fh.3→fh.4`(plugin.json/marketplace.json/version.mjs/README/CHANGELOG/plugin_versions.py)→ CodeRabbit 至 0 findings → 合并 → 本地 re-pin(uninstall+install)→ 验证 `installed_plugins.json` 指向 fh.4。

## 8. 已知维护点 / 残留风险(诚实记录)

- **`EFFORT_ORDER` 仍需在 codex 出新档时手动追加**——但 v4 的关键改进是:未列入的新档触发 **fail loud**(明确报错提示更新),而非 v3 的静默选错。合法值本身来自 model/list(按模型),EFFORT_ORDER 仅用于「已知档排序」。
- **`model/list` 增量开销 ~51ms/次**(仅 `--quality max` 或需按模型校验时;显式 `--effort` 且值合法时理论上可跳过,但为统一校验默认都查)。companion 本就在 `withAppServer` 内,无额外冷启动。
- **`isDefault` 依赖 model/list 如实标记**:若 codex 某版本不返回 isDefault,退回 model/list 失败兜底(xhigh + 告警)。
