import { normalizeArgv } from "./args.mjs";

function optionNameForMessage(rawKey, short = false) {
  return `${short ? "-" : "--"}${rawKey}`;
}

function missingValueMessage(optionName, nextValue) {
  if (nextValue === undefined) {
    return `${optionName} requires a value.`;
  }
  return `${optionName} requires a value. If the value intentionally starts with "-", use ${optionName}=${nextValue}.`;
}

export function assertSafeTokens(tokens) {
  for (const token of tokens) {
    if (String(token).includes("\0")) {
      throw new Error("Command arguments must not contain NUL bytes.");
    }
  }
}

export function parseStrictCommandInput(command, rawArgv, allowed = {}) {
  const tokens = normalizeArgv(rawArgv).map((token) => String(token));
  assertSafeTokens(tokens);

  const valueOptions = new Set(allowed.valueOptions ?? []);
  const booleanOptions = new Set(allowed.booleanOptions ?? []);
  const actions = new Set(allowed.actions ?? []);
  const aliasMap = allowed.aliasMap ?? {};
  const promptAfterFirstPositional = Boolean(allowed.promptAfterFirstPositional);
  const options = {};
  const positionals = [];
  let action = null;
  let passthrough = false;
  let positionalPassthrough = false;

  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];

    if (passthrough || positionalPassthrough) {
      positionals.push(token);
      continue;
    }

    if (token === "--") {
      passthrough = true;
      continue;
    }

    if (!token.startsWith("-") || token === "-") {
      if (actions.has(token) && action == null && positionals.length === 0) {
        action = token;
      } else {
        positionals.push(token);
        positionalPassthrough = promptAfterFirstPositional;
      }
      continue;
    }

    if (token.startsWith("--")) {
      const body = token.slice(2);
      const equalsIndex = body.indexOf("=");
      const rawKey = equalsIndex === -1 ? body : body.slice(0, equalsIndex);
      const inlineValue = equalsIndex === -1 ? undefined : body.slice(equalsIndex + 1);
      const key = aliasMap[rawKey] ?? rawKey;
      const optionName = optionNameForMessage(rawKey);

      if (booleanOptions.has(key)) {
        options[key] = inlineValue === undefined ? true : inlineValue !== "false";
        continue;
      }

      if (valueOptions.has(key)) {
        if (inlineValue !== undefined) {
          options[key] = inlineValue;
          continue;
        }
        const nextValue = tokens[index + 1];
        if (nextValue === undefined || nextValue.startsWith("-")) {
          throw new Error(missingValueMessage(optionName, nextValue));
        }
        options[key] = nextValue;
        index += 1;
        continue;
      }

      throw new Error(`Unsupported option ${optionName} for ${command}.`);
    }

    const rawKey = token.slice(1);
    const key = aliasMap[rawKey] ?? rawKey;
    const optionName = optionNameForMessage(rawKey, true);

    if (booleanOptions.has(key)) {
      options[key] = true;
      continue;
    }

    if (valueOptions.has(key)) {
      const nextValue = tokens[index + 1];
      if (nextValue === undefined || nextValue.startsWith("-")) {
        throw new Error(missingValueMessage(optionName, nextValue));
      }
      options[key] = nextValue;
      index += 1;
      continue;
    }

    throw new Error(`Unsupported option ${optionName} for ${command}.`);
  }

  return action == null ? { options, positionals } : { options, positionals, action };
}
