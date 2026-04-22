# Servertool

Python CLI for shared cluster operations and controller-to-runner remote training workflows.

**Author:** zanewang  
**Version:** 3.0.0

## Scope

`servertool` is built for shared compute environments where users need a single CLI to:

- inspect cluster and node status
- request GPU resources
- inspect and cancel SLURM jobs
- monitor shared disk quota usage
- validate job submission paths
- prepare remote training specs on a controller machine
- sync code and datasets to a Linux runner host
- launch and monitor remote SLURM training runs without manual SSH sessions

Sensitive deployment details are intentionally excluded from this repository. Real login hosts, authentication URLs, usernames, passwords, and internal addresses must be injected during deployment through environment variables or local operator configuration.

The repository root `servertool/` is the canonical project root. The Python package lives under `src/servertool/`, and deployment-specific values belong in ignored local configuration, not in tracked source files.

## Quick Start

Install in editable mode during development:

```bash
python3 -m pip install -e .
```

Then start with:

```bash
servertool help
servertool status
servertool request guide
```

If this is your first time using the cluster workflow, run:

```bash
servertool quickstart
```

If you are using the controller-to-runner workflow, the typical first setup is:

```bash
servertool remote bootstrap
servertool remote doctor
servertool runner notify --test you@example.com
```

## Command Surface

```bash
servertool status [full|quick|gpu|jobs|network]
servertool jobs [list|all|who|gpu|info|cancel]
servertool disk [show|detail|update|auto]
servertool config [setup|show|path]
servertool request [guide|light|medium|heavy|a6000|custom]
servertool quickstart
servertool test [job|quick]
servertool spec [init|show|validate]
servertool remote [doctor|install-runner|bootstrap|cleanup]
servertool runner [prepare|start|status|tail|notify|finalize]
servertool run [submit|status|logs|fetch|list|cleanup]
servertool help [status|jobs|disk|config|request|quickstart|test]
servertool version
```

## Controller Workflow

The controller-side commands are designed so you do not need to manually log in to the cluster just to sync files or start a run.

### 1. Bootstrap the remote runner

```bash
servertool remote bootstrap
servertool remote doctor
```

`remote bootstrap` creates `trainhub/.runner` and `~/.config/servertool` on the Linux runner host, uploads the runner package, and syncs runner-side mail configuration.

### 2. Create a run spec

```bash
servertool spec init spec.json --project vision --run-name smoke
servertool spec validate spec.json
servertool spec show spec.json
```

### 3. Submit from the controller

```bash
servertool run submit spec.json --dry-run
servertool run submit spec.json
```

### 4. Monitor and fetch results

```bash
servertool run status RUN_ID
servertool run logs RUN_ID
servertool run logs RUN_ID --follow
servertool run fetch RUN_ID
servertool run list
servertool run list --json
servertool run cleanup RUN_ID --dry-run
servertool run cleanup RUN_ID
```

`run cleanup` is intentionally conservative. It removes the remote run directory plus the local run record, and it only removes fetched files automatically when they live under the default fetched cache. It refuses to delete non-terminal runs unless you pass `--force`. Use `--local-only` or `--remote-only` when you only want one side cleaned up.

If you only want to clean the remote runner side, use:

```bash
servertool remote cleanup RUN_ID --dry-run
servertool remote cleanup RUN_ID
```

### 5. Runner-side commands

These commands are mainly for the Linux runner host and for remote execution through the controller:

```bash
servertool runner prepare SPEC_PATH
servertool runner start RUN_ID
servertool runner status RUN_ID
servertool runner tail RUN_ID
servertool runner notify RUN_ID
servertool runner notify --test you@example.com
```

## Safe Smoke Spec

Two smoke specs are tracked in the repository:

- `spec.smoke.json`: prints a single smoke line
- `spec.smoke.train.json`: runs `examples/smoke_train.py` and writes `outputs/metrics.jsonl`, `outputs/summary.json`, and `ckpts/last.ckpt`

The training-oriented smoke spec stays intentionally small so it is safer for controller-to-runner smoke tests:

```bash
servertool spec validate spec.smoke.train.json
servertool run submit spec.smoke.train.json --dry-run
```

## Common Workflow

### 1. Review the request presets

```bash
servertool request guide
```

### 2. Request a recommended GPU node

```bash
servertool request medium
```

### 3. Verify the allocated environment

```bash
servertool status quick
nvidia-smi
echo $CUDA_VISIBLE_DEVICES
```

### 4. Inspect active jobs

```bash
servertool jobs
servertool jobs who
servertool jobs info JOBID
```

### 5. Monitor shared disk usage

```bash
servertool disk show
servertool disk detail
servertool disk update
```

## Configuration

`servertool` now supports a local per-account config file. Run this once after logging into a shared account:

```bash
servertool config setup
```

This writes a local config file to `~/.config/servertool/config.env` by default. The CLI loads it automatically on future runs. Use environment variables only when you need to override that local file for automation.

Important: do not put passwords or SSH private keys into the config file. `servertool` only needs cluster metadata such as the shared account, shared home path, partitions, and auth URL.

For the controller workflow, `servertool` also uses local runner/controller settings such as the remote host, remote root, local run cache, and SMTP paths. The runner-side SMTP credentials should live in a separate local secrets file such as `~/.config/servertool/smtp.env`.

A sanitized `.env.example` is still included as a deployment template.

| Variable | Purpose |
|----------|---------|
| `SERVERTOOL_SHARED_ACCOUNT` | Shared account name used in owner inference |
| `SERVERTOOL_WORKSPACE_NAME` | Your personal workspace folder under the shared home |
| `SERVERTOOL_SHARED_HOME` | Shared home root used for workdir ownership mapping |
| `SERVERTOOL_AUTH_URL` | Authentication URL shown in network guidance |
| `SERVERTOOL_NETWORK_PROBE_URL` | Public or internal URL used for connectivity probing |
| `SERVERTOOL_A40_PARTITION` | Standard GPU partition name |
| `SERVERTOOL_A6000_PARTITION` | Large GPU partition name |
| `SERVERTOOL_A40_MAX_TIME` | Max wall time label for the standard GPU partition |
| `SERVERTOOL_A6000_MAX_TIME` | Max wall time label for the large GPU partition |
| `SERVERTOOL_DEFAULT_COMPUTE_HOST` | Internal host used for connectivity probing |
| `SERVERTOOL_QUOTA_LIMIT` | Shared quota label |
| `SERVERTOOL_CACHE_FILE` | Disk cache file path. Defaults to `~/.cache/servertool/disk-cache.json` |
| `SERVERTOOL_TEST_OUTPUT_DIR` | Directory for temporary job test output |
| `SERVERTOOL_INSTALL_PATH` | Installed CLI path used in cron examples |
| `SERVERTOOL_CONFIG_FILE` | Override path for the local config file |
| `SERVERTOOL_REMOTE_HOST` | Linux runner host used by controller commands |
| `SERVERTOOL_REMOTE_USER` | SSH username for the runner host |
| `SERVERTOOL_REMOTE_PORT` | SSH port for the runner host |
| `SERVERTOOL_REMOTE_ROOT` | Remote trainhub root, usually `<shared_home>/trainhub` |
| `SERVERTOOL_REMOTE_PYTHON` | Python executable on the runner host |
| `SERVERTOOL_LOCAL_RUN_CACHE` | Local cache for submitted run records and fetched outputs |
| `SERVERTOOL_NOTIFY_EMAIL_TO` | Default recipient copied into new specs |
| `SERVERTOOL_NOTIFY_EMAIL_FROM` | Runner-side mail sender |
| `SERVERTOOL_SMTP_HOST` | SMTP host for runner notifications |
| `SERVERTOOL_SMTP_PORT` | SMTP port for runner notifications |
| `SERVERTOOL_SMTP_USE_SSL` | Whether runner mail uses SSL |
| `SERVERTOOL_SMTP_SECRETS_FILE` | Local and runner-side path to SMTP username/password |

Compatibility note: `SERVERIP` and `SERVERUSERNAME` are also accepted as controller-side fallbacks for `SERVERTOOL_REMOTE_HOST` and `SERVERTOOL_REMOTE_USER`.

## Open Source Safety

This repository deliberately does not contain:

- production IP addresses
- cluster passwords
- private usernames tied to a real server
- private authentication endpoints

Use the local config file, environment variables, deployment scripts, or an ignored operator config file to inject private values outside source control.

The default source tree contains no literal server IP addresses. Network checks use the configurable `SERVERTOOL_NETWORK_PROBE_URL` setting instead of a hardcoded endpoint.

## Development

Validate the code locally with:

```bash
python3 -m compileall src
python3 servertool help
python3 -m unittest discover tests
```

## Repository Layout

```text
servertool/
├── .gitignore
├── LICENSE
├── pyproject.toml
├── README.md
├── README.zh-CN.md
├── servertool
├── src/
│   └── servertool/
│       ├── __init__.py
│       ├── __main__.py
│       ├── app.py
│       ├── commands/
│       ├── controller/
│       ├── context.py
│       ├── runner/
│       ├── shared/
│       ├── config.py
│       ├── layout.py
│       ├── notify_email.py
│       ├── output.py
│       ├── remote.py
│       ├── runner_state.py
│       ├── spec.py
│       ├── system.py
└── tests/
```

Internally the code is now split into `controller/`, `runner/`, and `shared/`, while keeping the public CLI name and command surface as a single `servertool` tool.
