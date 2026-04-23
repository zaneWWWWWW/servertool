# Servertool

`servertool` is an official training CLI for shared-account lab environments.

It is built around one stable workflow:

```text
spec -> sync -> prepare -> launch -> monitor -> notify -> fetch
```

The design target is:

- controller: `macOS` or `Windows`
- runner: `Linux`
- transport: `ssh + rsync`
- scheduler: `SLURM / sbatch`
- deployment model: lab-managed shared runner + member-scoped workspaces

## Official Docs

- Documentation map: `docs/README.md`
- Chinese overview: `README.zh-CN.md`
- Member guide: `docs/member-guide.zh-CN.md`
- Admin guide: `docs/admin-guide.zh-CN.md`
- Maintainer architecture doc: `docs/architecture.zh-CN.md`
- Contribution guide: `CONTRIBUTING.md`
- Maintainer guide: `MAINTAINERS.md`
- Release notes: `CHANGELOG.md`
- Public examples: `examples/README.md`

## Repository Layout

- `src/servertool/`: package source
- `tests/`: automated coverage
- `docs/`: long-form product and architecture docs
- `examples/`: public-safe templates and smoke assets
- `.github/workflows/`: CI and packaging checks

## Public CLI

The public command surface is intentionally small:

```bash
servertool init
servertool config [show|path]
servertool doctor
servertool spec [init|show|validate]
servertool run [submit|status|logs|fetch|list|cleanup]
servertool admin [deploy|rollback|doctor|show-config]
servertool help [init|config|doctor|spec|run|admin]
servertool version
```

Internal `remote` and `runner` commands still exist for implementation and maintenance, but they are not part of the normal user-facing workflow.

## Quick Start

Install from a checked-out repository:

```bash
python3 -m pip install .
servertool version
servertool help
```

For local development:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -e .
```

If you do not want to install a local editable package yet, you can also run from source with:

```bash
python3 -m servertool version
./servertool version
```

## Admin Workflow

Prepare the local config files first:

```text
~/.config/servertool/
  lab.env
  smtp.env
  user.env
```

Recommended admin flow:

```bash
servertool admin show-config
servertool admin deploy --dry-run
servertool admin deploy
servertool admin doctor
```

What `admin deploy` does:

- stages or upgrades the shared runner release under `<shared_home>/trainhub/.runner/releases/<version>`
- repoints `.runner/current`
- uploads shared `lab.env`
- uploads `smtp.env` if present
- prepares shared `envs/`, `models/`, and `cache/` roots
- verifies the active runner release

Rollback is explicit:

```bash
servertool admin rollback 3.0.0 --dry-run
servertool admin rollback 3.0.0
```

## Member Workflow

After the admin provides `lab.env`, each member only needs a personal config layer.

Recommended first-use flow:

```bash
servertool init
servertool doctor
servertool spec init spec.json --project my-project --run-name smoke
servertool spec validate spec.json
servertool run submit spec.json --dry-run
servertool run submit spec.json
```

Monitor and fetch results:

```bash
servertool run status RUN_ID
servertool run logs RUN_ID
servertool run logs RUN_ID --follow
servertool run fetch RUN_ID
servertool run list
servertool run cleanup RUN_ID --dry-run
```

## Smoke Tutorial

The repository includes a tracked smoke spec: `spec.smoke.train.json`.

Run it from the repository root:

```bash
servertool spec validate spec.smoke.train.json
servertool run submit spec.smoke.train.json --dry-run
servertool run submit spec.smoke.train.json
```

Then use the returned `RUN_ID`:

```bash
servertool run status RUN_ID
servertool run logs RUN_ID --follow
servertool run fetch RUN_ID
```

This smoke run writes small artifacts under `outputs/` and `ckpts/`, including `outputs/metrics.jsonl`, `outputs/summary.json`, and `ckpts/last.ckpt`.

## Configuration Model

Default local files:

```text
~/.config/servertool/
  lab.env
  user.env
  smtp.env
```

Precedence:

```text
environment > user.env > lab.env > built-in defaults
```

Responsibilities:

- `lab.env`: lab-managed shared values such as remote host, shared roots, partitions, mirrors, and SMTP settings
- `user.env`: member-managed values such as `workspace_name`, `member_id`, notify email, and local run cache
- `smtp.env`: admin-only SMTP credentials

Use `servertool config show` to inspect effective values and `servertool config path` to inspect file locations.

Public-safe config templates live under `examples/config/`.

## Structured Spec Model

`servertool` uses a structured `spec.json` schema.

Supported asset source types:

- `assets.code.source`: `sync`
- `assets.dataset.source`: `none | sync | shared_path`
- `assets.env.source`: `none | shared_path | build | upload`
- `assets.model.source`: `none | hub | shared_path | upload`

Design rules:

- use `shared_path` or `build` for environments whenever possible
- use `hub` or `shared_path` for models whenever possible
- keep `upload` as the fallback path
- `shared_path` values must be absolute remote paths
- `fetch.include` patterns are relative to the run root and control what `run fetch` pulls back locally
- the runner injects shared cache and mirror variables such as `HF_HOME`, `HF_HUB_CACHE`, `MODELSCOPE_CACHE`, `PIP_CACHE_DIR`, `CONDA_PKGS_DIRS`, `PIP_INDEX_URL`, `PIP_EXTRA_INDEX_URL`, `HF_ENDPOINT`, and `MODELSCOPE_ENDPOINT`

## Remote Layout

Shared lab side:

```text
<shared_home>/trainhub/
  .runner/
    releases/<version>/servertool/
    current -> releases/<version>
  lab/
    lab.env
    smtp.env
  envs/
  models/
  cache/
```

Member side:

```text
<shared_home>/<workspace>/.servertool/
  config.env
  projects/<project>/runs/<run_id>/
```

## Safety Defaults

The CLI is member-scoped by default.

- `run status`, `logs`, `fetch`, and `cleanup` only operate on the current member's runs by default
- `run list` only shows local records for the current member by default
- legacy shared-root runs are only accessible when a matching local run record exists
- cleanup stays conservative and refuses non-terminal runs unless `--force` is passed

## FAQ

### The admin gave me `lab.env`. What do I do next?

Put it at `~/.config/servertool/lab.env`, then run `servertool init` and `servertool doctor`.

### Why did `run fetch` pull back fewer files than I expected?

`run fetch` follows `fetch.include` from the run spec and remote `status.json`. Add the paths you need to `fetch.include`, then resubmit or fetch that run's tracked outputs.

### Can I use `servertool remote` or `servertool runner` directly?

Treat them as internal interfaces. Normal workflows should stay on `init`, `doctor`, `spec`, `run`, and `admin`.

### Why does a run say it belongs to another member?

The CLI is member-scoped by default. Check `servertool config show` and confirm that your current `workspace_name` and `member_id` match the run you are trying to access.

### Where can I see which config files are active?

Run `servertool config path` for file locations and `servertool config show` for effective values.

## Development

Useful local checks:

```bash
python3 -m compileall src
python3 -m unittest discover tests
python3 -m build
```

The repository intentionally excludes real production endpoints, credentials, and private server details. Inject private values through local config files or environment variables outside source control.
