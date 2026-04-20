# Servertool

Python CLI for managing compute resources, resource requests, and SLURM jobs on Ubuntu server clusters.

**Author:** zanewang  
**Version:** 3.0.0

## Scope

`servertool` is built for shared compute environments where users need a single CLI to:

- inspect cluster and node status
- request GPU resources
- inspect and cancel SLURM jobs
- monitor shared disk quota usage
- validate job submission paths

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

## Command Surface

```bash
servertool status [full|quick|gpu|jobs|network]
servertool jobs [list|all|who|gpu|info|cancel]
servertool disk [show|detail|update|auto]
servertool request [guide|light|medium|heavy|a6000|custom]
servertool quickstart
servertool test [job|quick]
servertool help [status|jobs|disk|request|quickstart|test]
servertool version
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

Override deployment-specific values with environment variables. A sanitized `.env.example` is included as a deployment template.

| Variable | Purpose |
|----------|---------|
| `SERVERTOOL_SHARED_ACCOUNT` | Shared account name used in owner inference |
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

## Open Source Safety

This repository deliberately does not contain:

- production IP addresses
- cluster passwords
- private usernames tied to a real server
- private authentication endpoints

Use local environment variables, deployment scripts, or an ignored operator config file to inject private values outside source control.

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
│       ├── config.py
│       ├── context.py
│       ├── output.py
│       ├── system.py
│       └── commands/
│           ├── disk.py
│           ├── jobs.py
│           ├── quickstart.py
│           ├── request.py
│           ├── status.py
│           └── testjob.py
└── tests/
```

`servertool` now uses a standard Python package layout at the repository root and is ready to be developed as a standalone open-source cluster operations toolkit.
