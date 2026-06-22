export const MACHINE_PATH_PATTERN_SOURCE = String.raw`(?:^|[\s"'=(:<\x60\[,|{])(?:(?:file://(?:localhost)?)?/(?:Users/[A-Za-z0-9._-]+/|home/(?!(runner|vscode|ubuntu|circleci|runneradmin)\b)[A-Za-z0-9._-]+/|private/var/folders/|var/folders/|Volumes/(?!(?:<[^/\r\n]+>|\$\{[^}/\r\n]+\})/)[^/\r\n]+/)|(?:file://(?:localhost)?/)?[A-Za-z]:(?:\\{1,2}|/)Users(?:\\{1,2}|/)(?!(?:<[^\\/\r\n]+>|\$\{[^}\\/\r\n]+\})(?:\\{1,2}|/))[^\\/\r\n]+(?:\\{1,2}|/))`;
const LOCAL_PATH_PATTERN = new RegExp(MACHINE_PATH_PATTERN_SOURCE, "m");
const LOCAL_PATH_GLOBAL_PATTERN = new RegExp(MACHINE_PATH_PATTERN_SOURCE, "gm");

export function hasMachinePath(text) {
  return LOCAL_PATH_PATTERN.test(String(text ?? ""));
}

export function redactMachinePaths(text, replacement = "<local-path>") {
  return String(text ?? "").replace(LOCAL_PATH_GLOBAL_PATTERN, (match) => {
    const pathStart = match.search(/(?:file:\/\/(?:localhost)?)?\/|(?:file:\/\/(?:localhost)?\/)?[A-Za-z]:(?:\\{1,2}|\/)/);
    if (pathStart < 0) {
      return replacement;
    }
    return `${match.slice(0, pathStart)}${replacement}`;
  });
}
