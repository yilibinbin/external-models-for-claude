# Codex 智力档能力自适应改造 — 设计文档

**日期**: 2026-07-12
**范围**: 仅 `plugins/codex`(antigravity **零改动零升版**)
**版本**: codex-for-claude `1.1.0-fh.3 → 1.1.0-fh.4`(patch)
**评审**: Claude → Gemini(agy)→ Codex(companion task, xhigh)三模型串行,已收敛零分歧

---

## 1. 背景与问题

用户诉求:「修复类似问题,使其更自然、通用、兼容最新模型和智力水平」,并明确「还是需要卡合法值,多一个验证步」。

落到 codex 插件,现状有两个具体问题:

1. **`--quality max` 达不到最强档(bug)**。`quality-policy.mjs` 里 `max.effort` 和 `strong.effort` 都写死为 `"high"`,而 codex 支持更高的 `xhigh`。用户以为 `--quality max` 跑最强,实际只到 `high`。此映射在三个真实入口生效:`adversarial-review`、`task`、`multi-review`(codex-companion.mjs:1065/1094/1556),**不是死代码**。
2. **合法值散落硬编码,加新档要改多处**。`VALID_REASONING_EFFORTS`(codex-companion.mjs:91)是封闭集合;「最强档」概念散落。将来 codex 出比 `xhigh` 更强的档,需改多处。

## 2. 经实测校准的关键事实(设计地基)

| 事实 | 证据 |
|---|---|
| codex **CLI 无 `--effort` flag** | `codex exec --help` 只有 `-c model=...`,无 effort/reasoning flag |
| effort 走 **codex app-server 协议**的 `turn/start.effort` 字段(不是 CLI flag) | codex.mjs:1020 `effort: options.effort ?? null` |
| `--effort xhigh` **实测生效** | companion `task --effort xhigh` → `captured: OK` |
| app-server **对未知 effort 静默接受、不报错**(测 `ultra` 照跑) | `runAppServerTurn("/tmp",{effort:"ultra"})` → `msg=OK err=none` |
| app-server **无 effort discovery 接口**(拿不到「可用 effort 列表」) | `config/read` 只返回 provider/model |

**推论(设计的核心逻辑)**:因为底层对无效 effort **静默不报错**,若无插件层校验,用户拼错档(`--effort higer`)会**静默不生效**、毫无察觉。所以「卡合法值 + 验证步」不是偏好,是**唯一安全选择**。合法值清单**只能由插件自维护**(底层不提供)。

## 3. 设计

### 3.1 新增单一权威源:`plugins/codex/scripts/lib/effort-policy.mjs`

```js
// 合法 reasoning effort 清单。codex CLI/app-server 不暴露「可用 effort 列表」,
// app-server 对未知 effort 静默接受不报错,因此合法值必须由插件把关。
// 【维护点】codex CLI 升级新增更高档时,在此数组末尾追加,并更新 HIGHEST_EFFORT。
export const KNOWN_EFFORTS = Object.freeze([
  "none", "minimal", "low", "medium", "high", "xhigh"
]);

// 「最强档」显式常量(不靠数组顺序推断 —— Codex 对抗点采纳)。
// 断言它属于 KNOWN_EFFORTS,防止清单/常量不一致。
export const HIGHEST_EFFORT = "xhigh";

export function validateEffort(value) {
  if (value == null) return null;
  const normalized = String(value).trim().toLowerCase();
  if (!normalized) return null;
  if (!KNOWN_EFFORTS.includes(normalized)) {
    throw new Error(
      `Unsupported reasoning effort "${value}". Use one of: ${KNOWN_EFFORTS.join(", ")}.`
    );
  }
  return normalized;
}

export function highestEffort() {
  return HIGHEST_EFFORT;
}
```

模块加载时断言 `KNOWN_EFFORTS.includes(HIGHEST_EFFORT)`(一致性护栏)。

### 3.2 codex 改造(3 处,复用现有链路)

1. **`codex-companion.mjs`**:`normalizeReasoningEffort` 委托 `validateEffort`;删除本地 `VALID_REASONING_EFFORTS`,从 `effort-policy.mjs` 导入。行为对既有合法值不变(保留你要的「验证步」)。
2. **`quality-policy.mjs`**:`max.effort: "high" → highestEffort()`(**修 bug**;`max` 自动跟随最强档)。`strong` 保持 `"high"`(次强);`standard`/`fast` 不变。`max` 仍是合法 quality 值 —— **不删除、不改兼容性**(Codex 对抗点:避免已有 `--quality max` 调用行为回退)。
3. **默认 model / `MODEL_ALIASES` 不动**:默认 model=null 已交给 codex CLI(本就自适应),不在本次范围。

### 3.3 antigravity:No touch, no bump(决策 1+2,三模型收敛)

- **不改任何代码、不加注释、不升版**。理由:antigravity 的 `selectAgyModel` 优先级已是「显式 → env → 运行时 catalog(`agy models`)→ default 兜底」,模型选择**已自适应**;它无独立 effort 维度,硬塞会造成抽象泄漏与两套语义。
- 兜底模型 `Gemini 3.1 Pro (High)` / `Claude Sonnet 4.6 (Thinking)` **就是当前最新旗舰**,且仅在 catalog 拉取失败时启用 —— **无修改依据**(Gemini 的「兜底过旧」疑虑经核实在此案例不成立)。
- 「经审计 antigravity 已原生满足自适应需求,故本次不作变更」写入 PR 描述。

## 4. 不做什么(YAGNI)

- **不做运行时发现 effort 档** —— 底层无 discovery 接口,做不了,强做是假自适应。
- **不给 antigravity 硬塞 effort 维度** —— 制造两套语义。
- **不动 codex 默认 model** —— 已自适应。

## 5. 测试(每条 fail-on-revert)

| 测试 | 断言 | 改回 bug 时 |
|---|---|---|
| `validateEffort` 卡非法 | `validateEffort("bogus")` 抛错并列出 KNOWN_EFFORTS | — |
| `validateEffort` 收全部已知档 | 6 档全部通过、归一化为小写 | — |
| **`--quality max` = xhigh** | `resolveQuality("max").effort === HIGHEST_EFFORT`(`=== "xhigh"`) | 回到 `"high"` → 变红(锚定最初发现的 bug) |
| `strong` 仍为 high | `resolveQuality("strong").effort === "high"` | — |
| `HIGHEST_EFFORT` 一致性 | `KNOWN_EFFORTS.includes(HIGHEST_EFFORT)` | — |
| 加新档跟随(模拟) | 若在清单+常量加 `xxhigh`,`highestEffort()` 跟随 | — |

外加 codex 全量回归 + `release-check` 0 FAIL。

## 6. 发布流程(与前两轮一致)

回归 green → 版本轴 `fh.3→fh.4`(plugin.json/marketplace.json/version.mjs/README/CHANGELOG/plugin_versions.py)→ CodeRabbit 至 0 findings → 合并 → 本地 re-pin(uninstall+install)→ 验证 `installed_plugins.json` 指向 fh.4。

## 7. 三模型评审记录

| 决策/对抗点 | Claude | Gemini | Codex(xhigh) |
|---|---|---|---|
| 决策1: antigravity 方案 A(No touch) | A | CONFIRM | CONFIRM |
| 决策2: No touch, no bump | 倾向 | REFINE→No touch | CONFIRM |
| Q1: HIGHEST_EFFORT 靠数组顺序? | 应显式 | — | CONFIRM「显式常量+校验 ∈ KNOWN_EFFORTS 更稳妥」 |
| Q2: 兜底模型需更新? | 否 | 疑虑 | CONFIRM「仍是最新旗舰、仅失败兜底 → 无依据」 |

**Codex 新增隐患(已采纳)**:(a) `KNOWN_EFFORTS` 硬编码将来可能落后于 CLI → 已加「维护点」注释;(b) `max` 不可直接删或改兼容 → 设计明确保留 `max` 为合法值,仅改其映射目标。
