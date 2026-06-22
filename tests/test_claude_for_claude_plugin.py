import json
import os
import pathlib
import re
import shutil
import subprocess
import textwrap


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "claude-for-claude"
NODE = os.environ.get("NODE_BINARY") or shutil.which("node") or "node"

EXPECTED_COMMANDS = {
    "setup.md",
    "doctor.md",
    "review.md",
    "adversarial-review.md",
    "multi-review.md",
    "plan-review.md",
    "plan.md",
    "assisted-review.md",
    "status.md",
    "result.md",
    "cancel.md",
    "roles.md",
    "github-actions.md",
    "review-gate.md",
    "mailbox.md",
    "leases.md",
    "rescue.md",
    "report.md",
}


def minimal_env(extra=None):
    keys = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "NODE_BINARY")
    env = {key: value for key in keys if (value := os.environ.get(key))}
    env.update(extra or {})
    return env


def timeout_text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf8", errors="replace")
    return str(value)


def run_node(repo_root, script, args=None, env=None, timeout=30):
    merged_env = minimal_env(env)
    command = [NODE, str(repo_root / script), *(args or [])]
    try:
        return subprocess.run(
            command,
            cwd=repo_root,
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=timeout_text(error.stdout),
            stderr=timeout_text(error.stderr) or f"timed out after {timeout} seconds",
        )


def read_json(path):
    return json.loads(path.read_text(encoding="utf8"))


def read_text(path):
    return path.read_text(encoding="utf8")


def all_text(root):
    assert root.exists(), f"missing expected path: {root}"
    chunks = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            chunks.append(path.read_text(encoding="utf8"))
    return "\n".join(chunks)


def command_files():
    commands_dir = PLUGIN / "commands"
    assert commands_dir.is_dir(), f"missing commands directory: {commands_dir}"
    files = {path.name: path for path in commands_dir.glob("*.md")}
    assert set(files) == EXPECTED_COMMANDS
    return files


def assert_no_shell_argument_interpolation(text):
    assert text.count("$ARGUMENTS") == 1
    assert '"$ARGUMENTS"' not in text
    assert "`$ARGUMENTS`" not in text
    assert "\\\"$ARGUMENTS\\\"" not in text
    assert not re.search(r"```(?:bash|sh)\s+[\s\S]*?\$ARGUMENTS[\s\S]*?```", text)
    assert not re.search(r"<<\s*['\"]?\w+['\"]?[\s\S]*?\$ARGUMENTS", text)
    assert not re.search(r"Bash\([^)]*\$ARGUMENTS", text, re.DOTALL)
    assert not re.search(r"node\s+[^\n`]*\$ARGUMENTS", text)


def markdown_files(*relative_dirs):
    files = []
    for relative in relative_dirs:
        root = PLUGIN / relative
        assert root.is_dir(), f"missing markdown directory: {root}"
        files.extend(sorted(root.rglob("*.md")))
    return files


def test_claude_marketplace_lists_claude_for_claude():
    marketplace = read_json(ROOT / ".claude-plugin" / "marketplace.json")

    assert marketplace["name"] == "external-models-for-claude"
    assert marketplace["metadata"]["description"]
    assert marketplace["metadata"]["version"] == "0.2.0"
    plugins = {item["name"]: item for item in marketplace["plugins"]}
    assert plugins["claude-for-claude"]["source"] == "./plugins/claude-for-claude"
    assert plugins["claude-for-claude"]["version"] == "0.1.0"
    assert plugins["claude-for-claude"]["category"] == "Productivity"
    assert "Claude CLI" in plugins["claude-for-claude"]["description"]
    assert {"codex", "gemini-for-claude", "antigravity-for-claude", "claude-for-claude"} <= set(plugins)
    assert len(plugins) == len(marketplace["plugins"])


def test_claude_for_claude_manifest_is_claude_native():
    manifest = read_json(PLUGIN / ".claude-plugin" / "plugin.json")

    assert manifest["name"] == "claude-for-claude"
    assert manifest["version"] == "0.1.0"
    assert "Claude CLI" in manifest["description"]
    assert manifest["homepage"] == "https://github.com/yilibinbin/external-models-for-claude"
    assert manifest["repository"] == "https://github.com/yilibinbin/external-models-for-claude"
    assert "claude-code" in manifest["keywords"]
    assert "claude-cli" in manifest["keywords"]
    assert "review" in manifest["keywords"]


def test_claude_command_files_are_argument_safe():
    for path in command_files().values():
        text = read_text(path)
        assert "disable-model-invocation: true" in text
        assert "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" in text
        assert "User arguments (untrusted slash-command text):\n$ARGUMENTS" in text
        assert_no_shell_argument_interpolation(text)


def test_claude_status_command_invokes_status_not_jobs():
    text = read_text(command_files()["status.md"])

    assert 'claude-companion.mjs" status' in text
    assert 'claude-companion.mjs" jobs' not in text


def test_claude_skills_do_not_publish_raw_argument_placeholders():
    for path in markdown_files("skills"):
        text = read_text(path)
        assert "$ARGUMENTS" not in text, path
        assert "<parsed-argv>" not in text, path
        assert "node plugins/claude-for-claude/scripts/" not in text, path


def test_claude_assisted_review_skill_uses_schema_verdict_literal():
    text = read_text(PLUGIN / "skills/claude-assisted-review/SKILL.md")

    assert "needs-attention" in text
    assert "needs_attention" not in text


def test_claude_for_claude_has_no_cross_provider_host_leakage():
    shipped = all_text(PLUGIN)
    forbidden = [
        "CODEX_PLUGIN_ROOT",
        "CODEX_PLUGIN_DATA",
        "GEMINI_FOR_CLAUDE",
        "ANTIGRAVITY_FOR_CLAUDE",
        "GEMINI_FOR_CODEX",
        "ANTIGRAVITY_FOR_CODEX",
        "Gemini",
        "gemini",
        "GEMINI",
        "Antigravity",
        "antigravity",
        "ANTIGRAVITY",
        "agy",
        "gfc_",
        "gemini-for-codex",
        "antigravity-for-codex",
        ".codex/",
    ]
    for token in forbidden:
        assert token not in shipped


def test_claude_hooks_use_claude_plugin_root_and_fail_open_gate():
    hooks = read_json(PLUGIN / "hooks" / "hooks.json")
    serialized = json.dumps(hooks)

    assert "Stop" in hooks["hooks"]
    assert "review-gate" in serialized
    assert "${CLAUDE_PLUGIN_ROOT}" in serialized
    assert "CODEX_PLUGIN_ROOT" not in serialized
    assert "CLAUDE_FOR_CLAUDE_REVIEW_GATE" in all_text(PLUGIN / "hooks")
    assert "CLAUDE_FOR_CLAUDE_CHILD" in all_text(PLUGIN / "hooks")


def test_claude_state_uses_claude_host_env_names():
    scripts = all_text(PLUGIN / "scripts")

    assert "CLAUDE_PLUGIN_DATA" in scripts
    assert "CLAUDE_FOR_CLAUDE_DATA" in scripts
    assert "CLAUDE_FOR_CLAUDE_RESOURCE_LOCK_DIR" in scripts
    assert "CLAUDE_FOR_CLAUDE_REVIEW_GATE" in scripts
    assert "CODEX_PLUGIN_DATA" not in scripts


def test_claude_status_prefers_claude_plugin_data(tmp_path):
    plugin_data = tmp_path / "plugin-data"
    result = run_node(
        ROOT,
        "plugins/claude-for-claude/scripts/claude-companion.mjs",
        ["status", "--json"],
        env={"CLAUDE_PLUGIN_DATA": str(plugin_data)},
    )

    assert result.returncode == 0, result.stderr
    assert str(plugin_data) in result.stdout


def test_claude_runtime_invokes_child_claude_safely(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "capture.json"
    fake_claude = bin_dir / "claude"
    fake_claude.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env node
            const fs = require('fs');
            fs.writeFileSync({json.dumps(str(capture))}, JSON.stringify({{
              argv: process.argv.slice(2),
              child: process.env.CLAUDE_FOR_CLAUDE_CHILD || '',
              toolsIndex: process.argv.indexOf('--tools'),
              toolsValue: process.argv[process.argv.indexOf('--tools') + 1]
            }}));
            process.stdout.write('SAFE-CLAUDE-OK');
            """
        ),
        encoding="utf8",
    )
    fake_claude.chmod(0o755)
    source = (
        "const r = await import('./plugins/claude-for-claude/scripts/lib/claude-runtime.mjs');"
        "const result = r.runClaude(['Reply exactly OK.'], {env: process.env, timeout: 5000});"
        "process.stdout.write(JSON.stringify(result));"
    )
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", source],
        cwd=ROOT,
        env=minimal_env({"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    captured = json.loads(capture.read_text(encoding="utf8"))
    assert payload["status"] == 0
    assert payload["stdout"] == "SAFE-CLAUDE-OK"
    assert "-p" in captured["argv"]
    assert "--safe-mode" in captured["argv"]
    assert "--no-session-persistence" in captured["argv"]
    assert captured["toolsIndex"] >= 0
    assert captured["toolsValue"] == ""
    assert captured["child"] == "1"


def test_claude_project_instructions_are_deduped(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    review = workspace / ".claude" / "review.md"
    review.parent.mkdir()
    review.write_text("Review once only.\n", encoding="utf8")
    source = (
        "const m = await import('./plugins/claude-for-claude/scripts/lib/project-instructions.mjs');"
        f"const result = m.loadProjectInstructions({json.dumps(str(workspace))}, "
        "{files:['.claude/review.md','.claude/review.md']});"
        "process.stdout.write(JSON.stringify({defaults:m.DEFAULT_PROJECT_INSTRUCTION_FILES, result}));"
    )
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", source],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["defaults"].count(".claude/review.md") == 1
    assert [block["path"] for block in payload["result"]["blocks"]] == [".claude/review.md"]


def test_claude_scorecard_rejects_non_string_finding_evidence_clearly():
    score = {
        "weight": 0.2,
        "score": 100,
        "evidence": ["ok"],
    }
    payload = {
        "verdict": "needs-attention",
        "score": {
            "total": 100,
            "threshold": 85,
            "dimensions": {
                "correctness": score,
                "tests": {**score, "exempt": False, "exemption_reason": ""},
                "code_quality": score,
                "security": score,
                "performance": score,
            },
        },
        "findings": [{
            "severity": "low",
            "blocking": False,
            "file": "x.js",
            "line": 1,
            "description": "desc",
            "evidence": None,
            "recommendation": "fix",
        }],
        "residual_risks": [],
        "next_steps": [],
    }
    source = (
        "const m = await import('./plugins/claude-for-claude/scripts/lib/scorecard.mjs');"
        "try {"
        f"  m.normalizeScorecardOutput({json.dumps(payload)});"
        "  process.stdout.write('unexpected-ok');"
        "} catch (error) {"
        "  process.stdout.write(error.message);"
        "}"
    )
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", source],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "scorecard finding evidence must be a string."


def test_claude_scorecard_requires_blocking_finding_evidence():
    score = {
        "weight": 0.2,
        "score": 100,
        "evidence": ["ok"],
    }
    payload = {
        "verdict": "needs-attention",
        "score": {
            "total": 100,
            "threshold": 85,
            "dimensions": {
                "correctness": score,
                "tests": {**score, "exempt": False, "exemption_reason": ""},
                "code_quality": score,
                "security": score,
                "performance": score,
            },
        },
        "findings": [{
            "severity": "high",
            "blocking": True,
            "file": "x.js",
            "line": 1,
            "description": "desc",
            "evidence": "   ",
            "recommendation": "fix",
        }],
        "residual_risks": [],
        "next_steps": [],
    }
    source = (
        "const m = await import('./plugins/claude-for-claude/scripts/lib/scorecard.mjs');"
        "try {"
        f"  m.normalizeScorecardOutput({json.dumps(payload)});"
        "  process.stdout.write('unexpected-ok');"
        "} catch (error) {"
        "  process.stdout.write(error.message);"
        "}"
    )
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", source],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "blocking scorecard findings require evidence."


def test_claude_validation_evidence_tail_truncation_is_consistent(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    evidence = workspace / "validation.log"
    evidence.write_text("HEAD-LINE\n" + ("middle\n" * 20) + "TAIL-SENTINEL\n", encoding="utf8")
    source = (
        "const m = await import('./plugins/claude-for-claude/scripts/lib/validation-evidence.mjs');"
        f"const result = m.loadValidationEvidence({{cwd:{json.dumps(str(workspace))}, "
        "files:[{kind:'validation-log', file:'validation.log'}], maxBytes:64});"
        "process.stdout.write(JSON.stringify(result));"
    )
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", source],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["items"][0]["truncated"] is True
    assert payload["items"][0]["text"].startswith("[truncated] ")
    assert "TAIL-SENTINEL" in payload["items"][0]["text"]
    assert "HEAD-LINE" not in payload["items"][0]["text"]


def test_claude_reserved_job_worker_command_contract(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    data = tmp_path / "plugin-data"
    companion = str(ROOT / "plugins/claude-for-claude/scripts/claude-companion.mjs")
    source = (
        "const jobs = await import('./plugins/claude-for-claude/scripts/lib/jobs.mjs');"
        "const cwd = process.argv[1];"
        "const data = process.argv[2];"
        "const companion = process.argv[3];"
        "const env = {CLAUDE_PLUGIN_DATA: data, HOME: process.env.HOME || ''};"
        "const good = jobs.reserveJob(cwd, {id:'job-good', command:'review'}, "
        "[process.execPath, companion, 'run-reserved-job', '--job-id', 'job-good'], env);"
        "const claimed = jobs.claimReservedJob(cwd, 'job-good', 12345, env);"
        "const secondClaim = jobs.claimReservedJob(cwd, 'job-good', 12345, env);"
        "jobs.reserveJob(cwd, {id:'job-mismatch', command:'review'}, "
        "[process.execPath, companion, 'run-reserved-job', '--job-id', 'other-job'], env);"
        "const mismatch = jobs.claimReservedJob(cwd, 'job-mismatch', 12345, env);"
        "jobs.reserveJob(cwd, {id:'job-missing-command', command:'review'}, "
        "[process.execPath, companion, 'review', '--job-id', 'job-missing-command'], env);"
        "const missingCommand = jobs.claimReservedJob(cwd, 'job-missing-command', 12345, env);"
        "process.stdout.write(JSON.stringify({good, claimed, secondClaim, mismatch, missingCommand}));"
    )
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", source, str(workspace), str(data), companion],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["good"]["status"] == "queued"
    assert payload["claimed"]["status"] == "claimed"
    assert payload["claimed"]["job"]["status"] == "running"
    assert payload["secondClaim"]["status"] == "not_claimed"
    assert payload["mismatch"]["status"] == "not_claimed"
    assert payload["mismatch"]["reason"] == "Job is not a valid host-forwarded reservation."
    assert payload["missingCommand"]["status"] == "not_claimed"


def test_claude_review_includes_untracked_file_content(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for index in range(24):
        (repo / f"new-review-target-{index:02d}.txt").write_text(f"filler {index}\n", encoding="utf8")
    target = repo / "zz-review-target.txt"
    target.write_text("UNTRACKED REVIEW SENTINEL BEYOND OLD LIMIT\n", encoding="utf8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "prompt.txt"
    fake_claude = bin_dir / "claude"
    fake_claude.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env node
            const fs = require('fs');
            if (process.argv.includes('--version')) {{
              process.stdout.write('2.1.183');
              process.exit(0);
            }}
            if (process.argv.includes('--help')) {{
              process.stdout.write('--print --safe-mode --no-session-persistence --tools --input-format --output-format');
              process.exit(0);
            }}
            let prompt = '';
            process.stdin.setEncoding('utf8');
            process.stdin.on('data', chunk => prompt += chunk);
            process.stdin.on('end', () => {{
              fs.writeFileSync({json.dumps(str(capture))}, JSON.stringify({{
                prompt,
                promptBytes: Buffer.byteLength(prompt)
              }}));
              process.stdout.write(JSON.stringify({{
                result: JSON.stringify({{
                  verdict: 'approve',
                  summary: 'fake review',
                  findings: [],
                  next_steps: []
                }})
              }}));
            }});
            """
        ),
        encoding="utf8",
    )
    fake_claude.chmod(0o755)
    result = subprocess.run(
        [
            NODE,
            str(ROOT / "plugins/claude-for-claude/scripts/claude-companion.mjs"),
            "review",
            "--scope",
            "working-tree",
            "--json",
        ],
        cwd=repo,
        env=minimal_env({
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin-data"),
        }),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    captured = json.loads(capture.read_text(encoding="utf8"))
    prompt = captured["prompt"]
    assert captured["promptBytes"] > 0
    assert "Untracked files (25):" in prompt
    assert "- zz-review-target.txt" in prompt
    assert "Untracked file: zz-review-target.txt" in prompt
    assert "UNTRACKED REVIEW SENTINEL BEYOND OLD LIMIT" in prompt


def test_claude_review_honors_model_env_for_child_invocations(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    (repo / "target.txt").write_text("review me\n", encoding="utf8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "argv.json"
    fake_claude = bin_dir / "claude"
    fake_claude.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env node
            const fs = require('fs');
            if (process.argv.includes('--version')) {{
              process.stdout.write('2.1.183');
              process.exit(0);
            }}
            if (process.argv.includes('--help')) {{
              process.stdout.write('--print --safe-mode --no-session-persistence --tools --input-format --output-format --model');
              process.exit(0);
            }}
            let prompt = '';
            process.stdin.setEncoding('utf8');
            process.stdin.on('data', chunk => prompt += chunk);
            process.stdin.on('end', () => {{
              fs.writeFileSync({json.dumps(str(capture))}, JSON.stringify({{
                argv: process.argv.slice(2),
                child: process.env.CLAUDE_FOR_CLAUDE_CHILD || '',
                promptBytes: Buffer.byteLength(prompt),
                toolsIndex: process.argv.indexOf('--tools'),
                toolsValue: process.argv[process.argv.indexOf('--tools') + 1]
              }}));
              process.stdout.write(JSON.stringify({{
                result: JSON.stringify({{
                  verdict: 'approve',
                  summary: 'fake review',
                  findings: [],
                  next_steps: []
                }})
              }}));
            }});
            """
        ),
        encoding="utf8",
    )
    fake_claude.chmod(0o755)
    result = subprocess.run(
        [
            NODE,
            str(ROOT / "plugins/claude-for-claude/scripts/claude-companion.mjs"),
            "review",
            "--scope",
            "working-tree",
            "--json",
        ],
        cwd=repo,
        env=minimal_env({
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin-data"),
            "CLAUDE_FOR_CLAUDE_MODEL": "env-model-alias",
        }),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    captured = json.loads(capture.read_text(encoding="utf8"))
    argv = captured["argv"]
    model_index = argv.index("--model")
    assert argv[model_index + 1] == "env-model-alias"
    assert "-p" in argv
    assert "--safe-mode" in argv
    assert "--no-session-persistence" in argv
    assert "--input-format" in argv
    assert argv[argv.index("--input-format") + 1] == "text"
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert captured["promptBytes"] > 0
    assert captured["toolsIndex"] >= 0
    assert captured["toolsValue"] == ""
    assert captured["child"] == "1"


def test_claude_github_actions_model_argument_is_shell_quoted():
    malicious_models = [
        "$(echo injected)",
        "`uname`",
        "$HOME",
        "o'clock",
    ]

    for model in malicious_models:
        result = run_node(
            ROOT,
            "plugins/claude-for-claude/scripts/claude-companion.mjs",
            ["github-actions", "render", "--model", model],
        )
        assert result.returncode == 0, result.stderr
        workflow = result.stdout
        assert f'--model "{model}"' not in workflow
        if model == "o'clock":
            assert "--model 'o'\\''clock'" in workflow
        else:
            assert f"--model '{model}'" in workflow


def test_claude_github_actions_annotations_render_and_validate():
    rendered = run_node(
        ROOT,
        "plugins/claude-for-claude/scripts/claude-companion.mjs",
        ["github-actions", "render", "--annotations"],
    )
    assert rendered.returncode == 0, rendered.stderr
    assert "checks: write" in rendered.stdout
    assert "github.rest.checks.create" in rendered.stdout
    plain = run_node(
        ROOT,
        "plugins/claude-for-claude/scripts/claude-companion.mjs",
        ["github-actions", "render"],
    )
    assert plain.returncode == 0, plain.stderr
    assert "checks: write" not in plain.stdout
    assert "github.rest.checks.create" not in plain.stdout

    validation = run_node(
        ROOT,
        "plugins/claude-for-claude/scripts/claude-companion.mjs",
        ["github-actions", "validate", "--annotations"],
    )
    assert validation.returncode == 0, validation.stderr
    payload = json.loads(validation.stdout)
    assert payload["ok"] is True
    checks = {item["name"]: item["ok"] for item in payload["checks"]}
    assert checks["checks-permission-when-annotations"] is True
    assert checks["checks-api-submit"] is True


def test_claude_multi_review_serializes_at_model_limit_one(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    (repo / "target.txt").write_text("review me\n", encoding="utf8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "multi-argv.json"
    fake_claude = bin_dir / "claude"
    fake_claude.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env node
            const fs = require('fs');
            if (process.argv.includes('--version')) {{
              process.stdout.write('2.1.183');
              process.exit(0);
            }}
            if (process.argv.includes('--help')) {{
              process.stdout.write('--print --safe-mode --no-session-persistence --tools --input-format --output-format --model');
              process.exit(0);
            }}
            let prompt = '';
            process.stdin.setEncoding('utf8');
            process.stdin.on('data', chunk => prompt += chunk);
            process.stdin.on('end', () => {{
              fs.writeFileSync({json.dumps(str(capture))}, JSON.stringify({{
                argv: process.argv.slice(2),
                child: process.env.CLAUDE_FOR_CLAUDE_CHILD || '',
                promptBytes: Buffer.byteLength(prompt)
              }}));
              process.stdout.write(JSON.stringify({{result: 'role review ok'}}));
            }});
            """
        ),
        encoding="utf8",
    )
    fake_claude.chmod(0o755)
    result = subprocess.run(
        [
            NODE,
            str(ROOT / "plugins/claude-for-claude/scripts/claude-companion.mjs"),
            "multi-review",
            "--roles",
            "correctness,tests",
            "--scope",
            "working-tree",
        ],
        cwd=repo,
        env=minimal_env({
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin-data"),
            "CLAUDE_FOR_CLAUDE_RESOURCE_LOCK_DIR": str(tmp_path / "locks"),
            "CLAUDE_FOR_CLAUDE_GLOBAL_MAX_MODEL_CALLS": "1",
            "CLAUDE_FOR_CLAUDE_MULTI_REVIEW_MAX_PARALLEL": "2",
        }),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "capacity_blocked" not in result.stderr
    assert "sequential Claude CLI role review" in result.stdout
    assert "role review ok" in result.stdout
    captured = json.loads(capture.read_text(encoding="utf8"))
    assert captured["child"] == "1"
    assert captured["promptBytes"] > 0
    assert "--input-format" in captured["argv"]
    assert captured["argv"][captured["argv"].index("--input-format") + 1] == "text"


def test_claude_multi_review_has_no_outer_model_call_lease():
    source = read_text(PLUGIN / "scripts/claude-companion.mjs")
    start = source.index("async function runClaudeMultiReview(rawArgs)")
    end = source.index("async function runClaudePlanReview(rawArgs)")
    body = source[start:end]

    assert "Do not acquire an outer model-call lease here" in body
    assert 'withResourceLeaseSync("model-call"' not in body
    assert 'withResourceLeaseAsync("model-call"' not in body
    assert "multiReviewConcurrency()" in body
    assert "claudePrintAsync(prompt, args)" in body


def test_claude_companion_prompt_is_delivered_via_stdin_not_argv():
    source = read_text(PLUGIN / "scripts/claude-companion.mjs")
    start = source.index("function claudePrintArgs(prompt, options = {})")
    end = source.index("function claudePrint(prompt, options = {})")
    args_body = source[start:end]
    sync_call = source[source.index("function claudePrintUnguarded"):source.index("function parseClaudeJson")]
    async_call = source[source.index("async function claudePrintAsyncUnguarded"):source.index("async function mapWithConcurrency")]

    assert "--input-format" in args_body
    assert '"text"' in args_body
    assert "args.push(prompt)" not in args_body
    assert "input: prompt" in sync_call
    assert "input: prompt" in async_call
    assert "...(options.env ?? {})" in source
    assert 'CLAUDE_FOR_CLAUDE_CHILD: "1"' in source


def test_claude_capacity_blocked_message_omits_lock_root():
    source = (
        "const r = await import('./plugins/claude-for-claude/scripts/lib/resource-governor.mjs');"
        "const msg = r.capacityBlockedMessage('claude-for-claude', "
        "{kind:'model-call', active:2, limit:2, root:'/tmp/private-lock-root'});"
        "process.stdout.write(msg);"
    )
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", source],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout
    assert "capacity_blocked" in result.stdout
    assert "/tmp/private-lock-root" not in result.stdout


def test_claude_release_check_smoke():
    result = run_node(
        ROOT,
        "plugins/claude-for-claude/scripts/claude-companion.mjs",
        ["release-check", "--ci-simulate", "--json"],
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload.get("ok") is True


def test_claude_companion_import_is_side_effect_free():
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", "await import('./plugins/claude-for-claude/scripts/claude-companion.mjs')"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
