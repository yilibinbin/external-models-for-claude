# Codex 智力档能力自适应改造 — 设计文档 (v6)

**日期**: 2026-07-12
**范围**: 仅 `plugins/codex`(antigravity **零改动零升版**)
**版本**: codex-for-claude `1.1.0-fh.3 → 1.1.0-fh.4`(patch)
**评审**: Claude → Gemini(agy)→ Codex(companion task, xhigh)三模型串行,v1–v5 逐版被审阅推翻/补强后重写。**v6 = v5 两轮审阅后 GO_WITH_FIXES 的 5 项修订落地**(fast/standard/strong 不丢档、N4 copy hops、model/list 契约硬门禁、§6 测试补全、resolveModelEntry 文档化)

> **版本演进（诚实记录）**
> - **v1**「`xhigh` 是最强档、底层无 discovery」被 Codex 读 `models_cache.json` 证伪。
> - **v2** 排除 `ultra`(误判委派绕过 governor)—— 实测推翻(ultra 是普通单 turn)。
> - **v3** 取数组末项 + `model=null→xhigh` 兜底 —— 被 Codex 证伪(无升序契约 / 主路径没修 / 未知模型假成功 / 现存双向 bug)。
> - **v4** 用 app-server `model/list` 驱动按模型路由 —— 被三模型串行审阅判 **NO-GO**:**地基错误 N1**(effort 解析层放错——`executeTaskRun`/`executeReviewRun` 在 companion 层拿不到 `client`,`withAppServer` 只在 `codex.mjs` 的 `runAppServerTurn`/`runAppServerReview` 内打开)+ **哨兵对象崩 3 条路径**(task parse 崩 / 两 review 路径静默透传垃圾对象)+ **model/list 失败处理不全**(`validateEffortForModel(v, undefined)` 崩、空数组静默降档、§3.4/§3.5 自相矛盾、native-review 无 effort 通道却被派 discovery)。
> - **v5**:把解析**下沉到 `codex.mjs` 的 `runAppServerTurn` 回调内单一 resolver**;哨兵双字段契约;model/list 失败 **omit-for-all**;空表 fail-loud;native-review 排除 discovery。两轮三模型审阅判 **GO_WITH_FIXES**:7/8 阻断项真闭合,但 Codex 抓到 **v5 新 HIGH 回归**(照字面改 task `:1094` 为 `normalizeReasoningEffort(options.effort)` 会丢 fast/standard/strong 默认档)+ **N4 PARTIALLY**(`wantsHighestEffort` 未列全 copy hops)+ model/list 契约未声明(Gemini HIGH→Codex MED 反驳收敛)+ §6 漏结构测试。
> - **v6(本版)**:落地 v5 两轮审阅的 5 项 fix——task `:1094` 保留 `?? quality.effort`(不丢档)、列全 `wantsHighestEffort` copy hops(`executeTaskRun:561`/`buildAdversarialReviewTurnOptions:324`)、model/list 补 `app-server-protocol.d.ts` 契约 + §9 probe 设**硬门禁**、§6 补 fast/standard/strong 回归测试与结构字符串匹配测试、resolveModelEntry 精确匹配文档化;resolver 分支①加 `effort==null` 条件保证 `--effort` 显式优先于哨兵。

---

## 1. 背景与问题(四个真实 bug,v1–v4 逐层暴露)

用户诉求:「修复类似问题,使其更自然、通用、兼容最新模型和智力水平」,并明确「还是需要卡合法值,多一个验证步」。

1. **`--quality max` 达不到最强档**:`quality-policy.mjs:22` 的 `max.effort` 写死 `"high"`。三入口:`codex-companion.mjs:1045`(adversarial-review)/`:1093`(task)/`:1535`(multi-review),均经 `resolveQuality`。
2. **现存 `VALID_REASONING_EFFORTS` 双向 bug(比 #1 更根本)**:全局集合 `{none,minimal,low,medium,high,xhigh}`(`codex-companion.mjs:91`)**拦截了 `gpt-5.6-sol` 真实支持的 `max`/`ultra`**——`--model gpt-5.6-sol --effort ultra` 直接被拒(实测)。同时放行所有模型都不支持的 `none`/`minimal`。
3. **effort 能力按模型变化,全局校验/映射无法正确**(实测 models_cache):sol/terra=`[low,medium,high,xhigh,max,ultra]`,luna=`[…,max]`,5.5/5.4/mini/auto-review=`[…,xhigh]`。
4. **`:154` 硬编码的六档错误信息** + **`task` usage 漏 `--quality`**。

## 2. 经实测校准的关键事实(设计地基)

| 事实 | 证据 |
|---|---|
| app-server 有 **`model/list`** 方法,返回权威模型能力 | 实测 `client.request("model/list",{})` → `{data:[...], nextCursor}` |
| **默认模型可知**:模型带 `isDefault` 标记 | `model/list` 中 `gpt-5.6-sol` 有 `isDefault:true`(model=null 时 codex 实际用它) |
| **按模型的 effort 能力** | 每模型有 `supportedReasoningEfforts` + `defaultReasoningEffort` |
| **⚠ 字段名须以 app-server `model/list` 实际返回为准** | models_cache.json 用 `slug` + 元素 `{effort, description}`;app-server `model/list` 协议字段名(`id`/`model`、元素 `reasoningEffort`/`effort`)**在实现阶段必须用真实 probe 确认**,不得照抄 cache 字段名(§3.2/§9 落实) |
| `ultra` 是普通单 turn,**不绕过 governor** | 实测 `effort=ultra`+sol → 单 turn 38s OK;governor 计 companion 发起的 turn 数 |
| `supportedReasoningEfforts` **无 rank 字段**,数组顺序无契约 | 元素仅 `{effort/reasoningEffort, description}`(Codex 坚持:不能盲取末项) |
| `model/list` 开销可忽略 | roundtrip **51ms**;`runAppServerTurn` 本就在 `withAppServer` 内起 app-server,同 client 顺带调用无冷启动 |
| **`withAppServer` 只在 `codex.mjs` 的 `runAppServerTurn`/`runAppServerReview` 内打开** | 定义 `codex.mjs:618`;回调在 `:925`(review)/`:981`(turn);**companion 层的 `executeTaskRun`/`executeReviewRun` 是调用方,从不持有 `client`**(v4 地基错误 N1 的更正) |
| **native review(`review/start`)无 effort 通道** | `effort` 在 `codex.mjs` 仅出现于 `:1020` turn/start;`review/start`(`:943`)不接 effort;既有测试定义 native review 的 quality 为 metadata-only |

## 3. 设计:解析下沉到 `runAppServerTurn` 单一 resolver

### 3.1 层次更正(v4 地基错误 N1 的修复)

effort 的**最终解析与按模型校验,全部发生在 `codex.mjs` 的 `runAppServerTurn` 的 `withAppServer(cwd, async (client) => …)` 回调内**(`:981` 之后、`turn/start` `:1016` 之前),因为只有这里持有 `client`。companion 层**不再**预解析 effort,而是把「用户显式 effort(scalar)」与「是否要最强档(哨兵 boolean)」**双字段透传**下来。

- **native review 路径(`runAppServerReview` / `review/start`)显式排除 effort discovery**:该路径 quality 保持 metadata-only,不调用 model/list,不受本次改造影响。effort discovery 仅作用于 `runAppServerTurn`。

### 3.2 新增:`plugins/codex/scripts/lib/effort-policy.mjs`

> **字段名注意**:下方 `supportedEffortsOf`/`resolveModelEntry` 里的字段名(`supportedReasoningEfforts`/`reasoningEffort`/`id`/`isDefault`)**以 app-server `model/list` 真实返回为准**;实现首步先 probe 一次 `model/list` 打印结构(§9),按实测字段名定稿,再写死。

```js
// 已知 effort 强度显式序(仅用于「已知档取最强」比较,不作为合法性来源)。
// 【维护点】codex 出新档时在此追加;未在此列的档触发 fail-loud(见 highestKnownEffort)。
// none/minimal 保留仅为排序完整性——无任何模型在 supportedReasoningEfforts 里列它们,故永不会被选为最强。
const EFFORT_ORDER = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"];

// 从 model/list 的一条模型记录取其 supported effort 列表(纯数据变换,无 I/O)。字段名以实测为准。
export function supportedEffortsOf(modelEntry) {
  return (modelEntry?.supportedReasoningEfforts || []).map((lv) => lv.reasoningEffort);
}

// 从 model/list 结果选出「当前模型」记录:显式 model 优先,否则 isDefault。
export function resolveModelEntry(models, requestedModel) {
  if (requestedModel) {
    return models.find((m) => (m.id || m.model) === requestedModel) || null; // 未命中 -> null(调用方决定)
  }
  return models.find((m) => m.isDefault) || null;
}

// 该模型的最强档:在其 supported 内、按 EFFORT_ORDER 取最强。
// 空/非数组 supported -> fail-loud(修复 v4 MED:reduce(空) 返回 undefined 会静默降档)。
// supported 含 EFFORT_ORDER 之外的未知档 -> fail-loud(不静默选错)。
export function highestKnownEffort(supported) {
  if (!Array.isArray(supported) || supported.length === 0) {
    throw new Error("Codex returned an empty reasoning-effort capability list; refusing to guess the strongest tier.");
  }
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

// 按模型校验用户显式 effort(保留「验证步」;按真实模型能力,不是全局白名单)。
// 仅在 supported 可用时调用;supported 不可用(model/list 失败)时调用方绝不进这里(见 §3.4)。
export function validateEffortForModel(value, supported) {
  if (value == null) return null;
  const normalized = String(value).trim().toLowerCase();
  if (!normalized) return null;
  if (!Array.isArray(supported)) {
    throw new Error("validateEffortForModel called without a capability list; caller must guard on model/list failure.");
  }
  if (!supported.includes(normalized)) {
    throw new Error(
      `Model does not support reasoning effort "${value}". Supported: ${supported.join(", ")}.`
    );
  }
  return normalized;
}
```

### 3.3 哨兵传输契约(v4 N3/N4 的修复——哨兵对象绝不碰 normalizeReasoningEffort / turn/start)

**问题**:v4 让 `quality.effort` 变成对象 `{wantsHighestEffort:true}`,导致 task 路径 `String(对象)` 崩、两 review 路径把对象原样发给 app-server。

**契约**:companion 层与 `runAppServerTurn` 之间用**两个独立字段**传递意图,哨兵永远是 boolean,不是对象:

1. **`quality-policy.mjs`**:`max` 返回 `{ quality:"max", effort:null, wantsHighestEffort:true, … }`(effort 置 `null`,新增 boolean 标记);`strong`→`effort:"high"`,`standard`/`fast` 不变;`max` 仍是合法 quality(**不删不改兼容**)。
2. **三入口(companion)**:向 `executeTaskRun`/`executeReviewRun`(进而 `runAppServerTurn`)传 `effort` 与 `wantsHighestEffort` **两个字段**。绝不把哨兵对象塞进 effort。**关键(v5 新 HIGH 回归的修复)**:非 max 的 fast/standard/strong **仍必须把 `quality.effort` 作为 effort 传下**,否则它们的默认档(low/medium/high)会丢失,静默降成 app-server 默认——这是 v5 §3.3 照字面「改成 `normalizeReasoningEffort(options.effort)`」会引入的回归,Codex 抓到、主线复现。
   - **`effort` 字段的值**:`options.effort`(用户显式)优先,否则 `quality.effort`(fast=low/standard=medium/strong=high;**max 时 `quality.effort=null`**)。即 **`options.effort ?? quality.effort`**——**保留原有 `|| quality.effort` 兜底语义**,不能删。因为 max 的 `quality.effort=null`,该表达式对 max 得 null(交给哨兵),对非 max 得其默认档(不丢),两者都对。
   - **`wantsHighestEffort` 字段**:`quality.wantsHighestEffort === true`(仅 max 为 true)。
   - task 路径 `:1094`:改为 `const effort = normalizeReasoningEffort(options.effort ?? quality.effort);`——仍保留 `?? quality.effort`(不能像 v5 那样删成 `normalizeReasoningEffort(options.effort)`);因 max 的 `quality.effort=null`,normalize 得 null,由下游哨兵解析;非 max 得默认档,不丢。`normalizeReasoningEffort` 只做**语法预检**(见 §3.4),不再查全局白名单。另传 `wantsHighestEffort: quality.wantsHighestEffort === true`。
   - adversarial-review `:1065`、multi-review `:1556`:effort 传 `quality.effort`(非 max 得默认档、max 得 null;这两路径本就无 `--effort`)+ `wantsHighestEffort`(仅当 quality=max 为 true)。
   - **N4 完成——`wantsHighestEffort` 的 copy hops(v5 只说「传两字段」但没列全,Codex+Gemini 标 PARTIALLY,主线复现)**:该 boolean 必须显式穿过以下每一跳,漏任一跳都会让 max 静默再降级:
     * `executeTaskRun`(`:561` `runAppServerTurn(workspaceRoot, {…})` 对象内**新增** `wantsHighestEffort: request.wantsHighestEffort`);其 `request` 由 task(`:1147`/`:1238`)与 multi-review(`:1552`)构造,均须带上该字段。
     * `buildAdversarialReviewTurnOptions`(`:324` 返回对象内**新增** `wantsHighestEffort: request.wantsHighestEffort`);其 `request` 由 `executeReviewRun`(`:493`)传入,`handleReviewCommand`(`:1058`)构造 request 时须带上。
     * `runAppServerTurn` 的 `options.wantsHighestEffort` 即上述透传结果,resolver(下条)读它。
3. **`runAppServerTurn`(codex.mjs,单一 resolver,回调内、turn/start 前)**。解析顺序(哨兵**最高优先**,因为 max 时 `options.effort` 已是 null,而非 max 时 `wantsHighestEffort=false`,两者不冲突):
   - 先 `client.request("model/list", {})`(try/catch,见 §3.4)。model/list 失败 → 走 §3.4 omit-for-all,不进下面分支。
   - `resolveModelEntry(models, options.model)` 定当前模型;命中 → `supportedEffortsOf(entry)` 得 supported;未命中(显式未知模型)→ §3.4 fail-loud。
   - **① 哨兵优先**:若 `options.wantsHighestEffort === true` → `highestKnownEffort(supported)` 得最终 effort。(此时 `options.effort` 恒为 null,见 §3.3.2;故哨兵与显式 effort 不会同时非空。)
   - **② 显式/默认 effort 校验**:否则若 `options.effort` 非空(用户显式档 **或** 非 max 预设的默认档 low/medium/high)→ `validateEffortForModel(options.effort, supported)` 得最终 effort。
   - **③ 兜底**:否则 → `null`(codex 默认)。
   - **`--effort` 与哨兵的优先级**:因 quality-policy 只在 max 时置 `wantsHighestEffort=true` 且同时把 `quality.effort=null`,`options.effort` 对 max 只可能来自用户显式 `--effort`;若用户 `--effort high --quality max`,§3.3.2 的 `options.effort ?? quality.effort` = `high`(非 null),此时**同时** `wantsHighestEffort=true`——**分支①会先命中,覆盖显式 high**。故为满足「`--effort` 显式优先于哨兵」,resolver 分支①须加条件 `options.wantsHighestEffort === true && options.effort == null`;当用户显式 effort 存在时跳过哨兵,走分支②校验其显式值。**(此为 §3.3 的精确语义,实现与测试都以此为准。)**
   - 把解析出的最终 effort 传给 `turn/start`(`:1020`)。
4. **`codex-companion.mjs` 清理**:**删除 `:91` 全局 `VALID_REASONING_EFFORTS` 与 `:154` 硬编码六档错误信息**(问题 #2/#4)。`normalizeReasoningEffort` 降级为纯语法预检(§3.4)。
5. **usage 补 `--quality`**(`task` 的 `:104`);**默认 model / `MODEL_ALIASES` 不动**(别名 `spark→gpt-5.3-codex-spark` 在 `normalizeRequestedModel` 已 canonical 化,`resolveModelEntry` 收到的是规范 id)。

### 3.4 model/list 失败与语法预检(v4 N2/C2 修复 + C3 三模型收敛)

**语法预检(parse 时,保留早拒)**:`normalizeReasoningEffort` 仍在 parse 时对用户显式 `--effort` 做**静态语法检查**——非空、`String(...).trim().toLowerCase()`、且**在 `EFFORT_ORDER` 并集内**(拦明显乱打的值,如 `hyper`),避免浪费 governor lease + app-server 启动。但**按模型的合法性**(该模型是否支持此档)下沉到 session 内。语法预检不认识的值直接 parse 时报错;并集内、但当前模型不支持的值,由 session 内 `validateEffortForModel` fail-loud。

**model/list 失败矩阵(session 内 try/catch,统一规则)**:

| 情况 | 处理 |
|---|---|
| model/list 成功 + 命中模型 | 正常:显式 effort 按模型校验;`wantsHighestEffort` → `highestKnownEffort` |
| model/list 成功 + 显式 `--model X` 但无 X | **fail-loud**:「未知模型 X,无法验证其 effort 能力」 |
| model/list 成功 + model=null 但无 isDefault | `wantsHighestEffort` 时 **fail-loud**(无模型无法定义「最强」);否则 **omit effort**(不谎称最强),让 app-server 用默认 |
| **model/list 请求失败(网络/协议)** | **对所有模型 omit effort**(三模型 C3 收敛):不调用 `validateEffortForModel`(避免 `undefined.includes` 崩);`onProgress` 告警「未能确认模型能力,已按 app-server 默认档运行(降级)」。**不提交任何未经证实的 effort 字符串**——omit 永远合法、零能力数据依赖、失败方向安全(欠交付而非报错)。显式 `--effort` 亦 omit + 告警(不 fail-loud,保留离线/旧 server 可用性;但不冒险发可能非法的档) |

> **C3 收敛链(完整反驳循环,非平均)**:Claude 提 fail-loud → Gemini 驳(太激进,应 bypass+warn)→ Codex 驳(xhigh 对未知/别名/版本偏移模型可能**非法**,产生 invalid turn,非仅降级)→ Gemini 让步提「用 models_cache.json 做第二权威」→ Codex 终裁(cache 未接入插件、会过期/缺失、违背 v4 单源设计)→ **收敛:omit-for-all**。omit effort 无需任何能力数据,对所有模型永远合法。

### 3.5 路由分支(全部实测验证)

| 场景 | 当前模型 | `--quality max` → |
|---|---|---|
| model=null(默认) | isDefault=`gpt-5.6-sol` | **`ultra`**(主路径到顶,修好 v3 证伪 B) |
| 显式 `--model gpt-5.6-luna` | luna | `max` |
| 显式 `--model gpt-5.5` | 5.5 | `xhigh` |
| 显式未知模型 | — | **fail-loud**(不猜) |
| model=null 且无 isDefault | — | **fail-loud**(max 时)/ omit(非 max) |
| **model/list 失败** | — | **omit effort + 告警**(不谎称最强,不发未证实档) |

## 4. 决策记录(三模型串行审阅收敛 + 用户产品决策)

- **决策1 antigravity**:No touch, no bump。
- **决策2 `--quality max`(用户已定)**:路由到该模型真·最高档,**含 `ultra`**(实测 ultra 不绕过 governor)。
- **A(数组末项)**:**不盲取末项**,用显式 `EFFORT_ORDER` 取最强,未知档/空表 **fail-loud**。
- **B(主路径)**:用 `model/list` 的 `isDefault` 拿真实默认模型 → 主路径也到 ultra。
- **C(未知模型)**:**fail-loud**,不静默放行。
- **D(全局白名单)**:删除全局 `VALID_REASONING_EFFORTS`;按模型 `supportedReasoningEfforts` 校验。
- **N1(v4 地基错误,Codex+Gemini 一致 + 主线复现)**:解析层从 companion 下沉到 `codex.mjs` `runAppServerTurn` 回调内(唯一持 client 处),覆盖全部三入口。
- **N3/N4(哨兵崩溃)**:双字段传输契约(scalar effort + boolean wantsHighestEffort),哨兵永不为对象,不碰 normalizeReasoningEffort/turn/start。
- **N2(undefined supported 崩)**:model/list 失败时绝不调 `validateEffortForModel`;omit effort。
- **C3(三模型完整反驳收敛)**:model/list 失败 → **omit-for-all**(非 xhigh、非 cache-gated、非 fail-loud)。
- **空表(Codex MED)**:`highestKnownEffort` 对空/非数组 fail-loud。
- **native review(Codex MED)**:显式排除 effort discovery,保持 metadata-only。
- **【round-2】fast/standard/strong 不丢档(Codex 新 HIGH,Claude+Gemini 本轮漏,主线复现)**:task `:1094` 保留 `?? quality.effort` 兜底(不能像 v5 删成 `normalizeReasoningEffort(options.effort)`);review 两路径 effort 传 `quality.effort`。否则非 max 预设默认档静默丢失。
- **【round-2】N4 completion(Codex+Gemini PARTIALLY,主线复现)**:`wantsHighestEffort` 须显式穿过 `executeTaskRun:561` / `buildAdversarialReviewTurnOptions:324` 两跳,漏传则 max 静默再降级。
- **【round-2】model/list 契约(Gemini HIGH → Codex MED,反驳收敛)**:RPC 在 app-server 运行时确实可调(主线 v4 实测返回 `{data,nextCursor}`;Codex `strings` codex 0.144.1 命中 model/list/supportedReasoningEfforts/isDefault),但**未在插件契约 `app-server-protocol.d.ts:58-65` 声明**(仅 8 方法,无 model/list)。降级安全(omit-for-all)故非 foundational。修:补 d.ts 类型 + §9 probe 设硬门禁。
- **【round-2】resolveModelEntry 精确匹配(Codex LOW)**:`(m.id||m.model)===requestedModel` 对 `MODEL_ALIASES` 外的 server 端别名会 miss → fail-loud(安全但偏严);文档化,不改行为。

## 5. 不做什么(YAGNI)

- **不给 antigravity 加 effort 维度**。
- **不盲取数组末项**。
- **不静默猜测/放行**(未知模型、未知档、空表显式处理)。
- **不引入 models_cache.json 依赖**(Codex 终裁:未接入、会过期、违背单源;omit-for-all 更简更安全)。
- **不给 native review 加 effort discovery**(review/start 无 effort 通道)。

## 6. 测试(每条 fail-on-revert)

| 测试 | 断言 |
|---|---|
| 默认模型路由 | `resolveModelEntry(models, null)` 命中 `isDefault`;其 `wantsHighestEffort` → `highestKnownEffort` = fixture sol `ultra` |
| 显式模型路由 | luna → `max`;5.5 → `xhigh`(fixture) |
| 未知档 fail-loud | `highestKnownEffort(["low","hyper"])` **抛错** |
| **空表 fail-loud** | `highestKnownEffort([])` **抛错**(修 v4 MED:不再返回 undefined 静默降档) |
| 乱序 supported | `highestKnownEffort(["ultra","low","high"])` === `ultra`(不靠数组顺序) |
| 按模型校验 | `validateEffortForModel("ultra", sol.supported)` 通过;`validateEffortForModel("max", gpt5.5.supported)` **抛错** |
| **undefined supported 守卫** | `validateEffortForModel("xhigh", undefined)` **抛错**(明确「caller must guard」,证明 §3.4 不会误调) |
| 现存 bug 修复 | 删全局 `VALID_REASONING_EFFORTS` 后,`--model gpt-5.6-sol --effort ultra` **不再被拦**(改回全局集合 → 变红,锚定问题 #2) |
| **哨兵不崩 task 路径** | `task --quality max` 无 `--effort` → parse **不抛**「Unsupported reasoning effort」,session 内解析到模型最强档(修 v4 N3) |
| **哨兵不透传 review 路径** | adversarial-review/multi-review `--quality max` → `turn/start` 收到的 effort 是**解析后的字符串**(如 `ultra`),**非对象**(修 v4 N4) |
| 未知模型 fail-loud | 显式 `--model bogus` + model/list 无 bogus → 抛错 |
| **model/list 失败 omit(max)** | 模拟 model/list 抛错 → `--quality max` → `turn/start` effort **省略/null** + 告警(不发 xhigh,不崩,修 C3+N2) |
| **model/list 失败 omit(显式 effort)** | 模拟 model/list 抛错 + `--effort xhigh` → `turn/start` effort **省略/null** + 告警(不调 validateEffortForModel,不崩 undefined.includes) |
| `--effort` 优先 | `--effort high --quality max` → resolver 分支①条件 `effort==null` 不满足,跳过哨兵,走分支②校验 `high` → 实际用 `high`(显式优先于哨兵) |
| **fast/standard/strong 不丢档(v5 新 HIGH 回归)** | `task --quality standard`(无 `--effort`)→ `turn/start` 收 `medium`(**非 null**);`fast`→`low`;`strong`→`high`。**改回 v5 的 `normalizeReasoningEffort(options.effort)`(删 `?? quality.effort`)→ 三者变 null → 变红**,锚定回归 |
| **三入口端到端** | task / adversarial-review / **每个 multi-review role** 各一条:`--quality max` + mock model/list(sol) → `turn/start` 收 `ultra`(证明 N1 resolver + `wantsHighestEffort` copy hops 覆盖全部三入口,非只 task);**任一 copy hop 漏传 `wantsHighestEffort` → 该入口 `turn/start` 收 null 而非 ultra → 变红**(锚定 N4 completion) |
| native review 不受影响 | native `Review`(非 Adversarial)`--quality max` → 不调 model/list,保持 metadata-only(证明 Codex MED 排除) |
| `strong` 不变 | `resolveQuality("strong").effort === "high"` |
| 更新既有断言 | `test_codex_for_claude_plugin.py:7616`/`:7630` 的 `maxq["effort"]=="high"` 改为新哨兵语义:`maxq["effort"] is None` 且 `maxq["wantsHighestEffort"] is True` |
| **结构字符串匹配测试(Codex round-2 catch)** | wiring 改动会打破 `test_codex_for_claude_plugin.py` 中对 `runAppServerTurn`/`buildAdversarialReviewTurnOptions` 调用形状做字符串/结构断言的测试(**实现阶段 grep 定位**:候选 `:7726`/`:7728`/`:7744` 一带的 `assert "effort"` / 调用形状断言;`:7644` 的 adversarial 断言只投影 `{effort,model,sandbox}`,加 `wantsHighestEffort` 键**不破**——Codex 已自证)。实现首步先跑全量、定位真实被打破的行号,再逐一更新为新形状 |

外加 codex 全量回归 + `release-check` 0 FAIL。

## 7. 发布流程

回归 green → 版本 `fh.3→fh.4`(plugin.json/marketplace.json/version.mjs/README/CHANGELOG/plugin_versions.py)→ CodeRabbit 至 0 findings → 合并 → 本地 re-pin(uninstall+install)→ 验证 `installed_plugins.json` 指向 fh.4 → `graphify update .`。

## 8. 决策/风险记录(诚实)

- **`EFFORT_ORDER` 仍需在 codex 出新档时手动追加**——但未列入的新档触发 **fail-loud**(明确报错),非静默选错。合法值本身来自 model/list(按模型)。
- **`model/list` 增量开销 ~51ms/次**(仅 `runAppServerTurn` 路径,且需按模型解析时);native review 不查。
- **`isDefault` 依赖 model/list 如实标记**:若某版本不返回,退回「model=null 无 isDefault」分支(max fail-loud / 非 max omit)。
- **model/list 失败一律 omit effort**:降级为 app-server 默认档 + 告警;不冒险发未证实的 effort。
- **【行为变更须写 CHANGELOG,Gemini Q1】**:改为按模型校验后,原本经全局白名单放行、但**该模型 `supportedReasoningEfforts` 实际不含**的 effort(如某模型不支持 `xhigh` 却 `--effort xhigh`),现在会 **session 内 fail-loud**(以前静默透传给 app-server)。这是**有意的能力校验**(用户要的「验证步」),非回归,但对当前「能跑」的命令是行为变更,须在 CHANGELOG 明示。

## 9. 实现首步(**硬门禁**,防字段名照抄 + 补协议契约)

**这是实现的第 0 步,未通过不得写 `effort-policy.mjs`——round-2 三模型收敛设为硬门禁(model/list 未在插件契约声明)。**

1. **真实 probe**:在目标环境跑一次——`withAppServer` 内 `client.request("model/list",{})` 并 `console.error(JSON.stringify(结果.data[0], null, 2))`,**实测确认**:(a) 模型 id 字段是 `id`/`model`/`slug`;(b) `isDefault` 字段名;(c) supported 列表字段名(`supportedReasoningEfforts`?)及元素内档名字段(`reasoningEffort`? `effort`?)。**不得照抄 models_cache.json 的字段名**(那是 CLI cache `{slug, effort}`,与 app-server 协议可能不同)。
2. **补协议契约**:把 `model/list` 加进 `plugins/codex/scripts/lib/app-server-protocol.d.ts` 的方法映射(`:58-65` 现仅声明 8 方法,无 model/list),按 probe 实测的 params/result 结构定义类型。
3. **按实测字段名定稿** `effort-policy.mjs`(`supportedEffortsOf`/`resolveModelEntry` 的字段名),再写测试 fixture。fixture 的字段名必须与 probe 一致,否则测试通过但实现在真实 model/list 上失败(假绿)。
4. **门禁校验**:probe 输出连同选定字段名记入实现 PR 描述/CHANGELOG,供 CodeRabbit/审阅复核;fixture 与 probe 字段名一致性作为一条测试断言。
