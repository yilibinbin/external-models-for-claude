export const MACHINE_PATH_PATTERN_SOURCE = String.raw`(?:^|[\s"'=(:<\x60\[,|{])(?:(?:file://(?:localhost)?)?/(?:Users/[A-Za-z0-9._-]+/|home/(?!(runner|vscode|ubuntu|circleci|runneradmin)\b)[A-Za-z0-9._-]+/|private/var/folders/|var/folders/|Volumes/(?!(?:<[^/\r\n]+>|\$\{[^}/\r\n]+\})/)[^/\r\n]+/)|(?:file://(?:localhost)?/)?[A-Za-z]:(?:\\{1,2}|/)Users(?:\\{1,2}|/)(?!(?:<[^\\/\r\n]+>|\$\{[^}\\/\r\n]+\})(?:\\{1,2}|/))[^\\/\r\n]+(?:\\{1,2}|/))`;
const LOCAL_PATH_PATTERN = new RegExp(MACHINE_PATH_PATTERN_SOURCE, "m");

export function hasMachinePath(text) {
  return LOCAL_PATH_PATTERN.test(String(text ?? ""));
}
