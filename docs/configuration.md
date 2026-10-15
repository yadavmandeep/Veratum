# Configuration

Settings live in `.veratum/config.json` (commit it to share them with your team).

| Key | Default | Meaning |
|---|---|---|
| `enforcement` | `"strict"` | `strict` blocks out-of-scope edits and drift. `advisory` allows them but still reports. `off` disables scope checks (the gate still checks evidence) |
| `trivial_bypass` | `false` | Allow edits without a contract. Per session: `VERATUM_TRIVIAL=1` |
| `read_before_write` | `true` | Block edits to files not read, or changed since they were read, in this task (hook hosts). The `eco` profile turns it off |
| `max_retries` | `2` | Failed verifications before the engine tells the agent to roll back or escalate |
| `compact_max_lines` | `40` | Line budget for compacted failure output |
| `verify_timeout_sec` | `1800` | Kill verify commands that run longer (exit 124) |
| `stop_gate_max_blocks` | `3` | Stop-hook circuit breaker. After N blocked stops the agent may stop, but the ledger records `gate_overridden`. `0` = never let it stop unverified |
| `fingerprint_exclude` | `[]` | Extra glob patterns ignored by the tree hash, e.g. `["generated/**", "*.snap"]` |
| `protected_paths` | evidence files | Paths agents may not edit directly |
| `installed_adapters` | set by installer | Which IDE adapters `doctor` and `update` manage |

## Environment variables

| Variable | Effect |
|---|---|
| `VERATUM_ROOT` | Force the workspace root |
| `VERATUM_TRIVIAL=1` | Skip scope checks for this process |
| `VERATUM_PYTHON` | Python command used by the OpenCode plugin |
| `VERATUM_VERIFY=1` | Set *by* Veratum while a verify command runs, so your scripts can detect it |
