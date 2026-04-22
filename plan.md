# Servertool Plan

## Goal

Extend `servertool` from a local Linux cluster helper into a cross-platform controller for `macOS + Windows` that uses `ssh + rsync + a lightweight Linux runner` to execute a structured training workflow:

```text
plan -> sync -> prepare -> launch -> monitor -> notify -> fetch
```

v1 goals:

- support `macOS + Windows` as controllers
- keep the runner on Linux only
- keep a single CLI name: `servertool`
- preserve existing local cluster commands
- add controller/runner workflow under new subcommands
- use email as the first notification backend
- use `JSON` for `spec`, `meta`, and `status`

## Core Decisions

- redefine the controller as `local machine`, not `Mac only`
- keep Linux servers as the only runner target
- keep a single CLI: `servertool`
- use `spec.json`, `meta.json`, and `status.json` in v1
- default remote root to `<shared_home>/trainhub`
- implement notification with email first
- use a shared lab QQ mailbox as the sender
- use a personal QQ mailbox as the recipient
- use QQ SMTP authorization codes for authentication

## Support Matrix

Official v1 support:

- controller: `macOS`
- controller: `Windows 10/11`
- runner: `Ubuntu / Linux`

Windows v1 toolchain constraints:

- Python 3.11+
- Windows OpenSSH client
- WSL2
- `rsync` provided through WSL2

Not supported in v1:

- cwRsync
- Cygwin rsync
- Git Bash rsync compatibility matrix
- multiple native Windows `rsync.exe` variants

## Architecture

```text
User
  |
  v
Local Controller (macOS / Windows)
  ├─ servertool spec ...
  ├─ servertool run ...
  ├─ servertool remote ...
  └─ ssh / rsync transport
  |
  v
Linux Server
  └─ servertool runner ...
       ├─ prepare
       ├─ start
       ├─ status
       ├─ tail
       └─ notify
```

## Command Surface

Existing Linux-local commands remain unchanged:

```bash
servertool status
servertool jobs
servertool disk
servertool request
servertool quickstart
servertool test
servertool config
```

New Scheme A command groups:

```bash
servertool spec init
servertool spec show SPEC
servertool spec validate SPEC

servertool remote doctor
servertool remote install-runner
servertool remote cleanup RUN_ID

servertool run submit SPEC
servertool run status RUN_ID
servertool run logs RUN_ID
servertool run fetch RUN_ID
servertool run list
servertool run cleanup RUN_ID

servertool runner prepare SPEC_PATH
servertool runner start RUN_ID
servertool runner status RUN_ID
servertool runner tail RUN_ID
servertool runner notify RUN_ID
servertool runner notify --test you@qq.com
```

## Remote Layout

```text
<shared_home>/trainhub/
  projects/
    <project_name>/
      assets/
        code/
        envs/
        datasets/
        models/
      runs/
        <run_id>/
          spec.json
          meta.json
          status.json
          launch.sh
          job.sbatch
          stdout.log
          stderr.log
          outputs/
          ckpts/
```

## Schema

`spec.json` v1 minimum fields:

- `version`
- `project`
- `run_name`
- `assets.code`
- `assets.env`
- `assets.dataset`
- `assets.model`
- `launch.scheduler`
- `launch.partition`
- `launch.gpus`
- `launch.cpus`
- `launch.mem`
- `launch.time`
- `launch.workdir`
- `launch.command`
- `fetch.include`
- `notify.email.enabled`
- `notify.email.to`

`status.json` v1 minimum fields:

- `version`
- `run_id`
- `state`
- `job_id`
- `pid`
- `exit_code`
- `created_at`
- `started_at`
- `ended_at`
- `updated_at`
- `message`
- `paths`
- `notify_error`

State enum:

- `created`
- `assets_ready`
- `prepared`
- `running`
- `succeeded`
- `failed`
- `stopped`

## Asset Strategy

v1 keeps the first end-to-end path small:

- `code`: `sync`
- `dataset`: `sync`
- `env`: `reference`
- `model`: `reference`

This means:

- code and datasets move through `rsync`
- environments and models initially reference existing server paths

## Cross-Platform Rules

- use `Path` for local controller paths
- use `PurePosixPath` for remote Linux paths
- never mix local and remote path types
- do not depend on `bash` or `zsh` on the controller
- do not build long inline shell strings on the controller
- push complex logic into `servertool runner`
- treat the installed Python console script as the official entrypoint
- keep the repo-root helper launcher as development-only
- reduce shell-specific config assumptions over time

## Config Plan

Controller-side configuration:

- `SERVERTOOL_REMOTE_HOST`
- `SERVERTOOL_REMOTE_USER`
- `SERVERTOOL_REMOTE_PORT`
- `SERVERTOOL_REMOTE_ROOT`
- `SERVERTOOL_REMOTE_PYTHON`
- `SERVERTOOL_LOCAL_RUN_CACHE`
- `SERVERTOOL_NOTIFY_EMAIL_TO`
- `SERVERTOOL_RSYNC_BACKEND`
- `SERVERTOOL_SSH_BIN`
- `SERVERTOOL_RSYNC_BIN`

Windows v1 default:

- `SERVERTOOL_RSYNC_BACKEND=wsl`

Runner-side public mail configuration:

- `SERVERTOOL_NOTIFY_EMAIL_FROM`
- `SERVERTOOL_SMTP_HOST=smtp.qq.com`
- `SERVERTOOL_SMTP_PORT=465`
- `SERVERTOOL_SMTP_USE_SSL=1`

Runner-side secrets file:

- `SERVERTOOL_SMTP_USERNAME=<lab mailbox>`
- `SERVERTOOL_SMTP_PASSWORD=<qq smtp auth code>`

Rules:

- keep secrets out of git
- keep secret storage separate from public config
- keep SMTP credentials on the server side only

## Email Notification Plan

v1 notification events:

- task succeeded
- task failed

Subject format:

```text
[servertool] <project> <run_id> succeeded
[servertool] <project> <run_id> failed
```

Body should include:

- project
- run_id
- state
- job_id
- started_at
- ended_at
- duration
- remote run path
- outputs path
- ckpts path
- stderr tail summary

Failure policy:

- a mail delivery failure does not change the primary training state
- the failure is recorded in `notify_error`

## File Mapping

Modify:

- `src/servertool/app.py`
- `src/servertool/config.py`
- `src/servertool/commands/__init__.py`
- `src/servertool/system.py`
- `src/servertool/commands/configure.py`
- `README.md`
- `README.zh-CN.md`

Add:

- `src/servertool/spec.py`
- `src/servertool/remote.py`
- `src/servertool/layout.py`
- `src/servertool/runner_state.py`
- `src/servertool/notify_email.py`
- `src/servertool/commands/spec.py`
- `src/servertool/commands/run.py`
- `src/servertool/commands/remote.py`
- `src/servertool/commands/runner.py`
- `tests/test_spec.py`
- `tests/test_layout.py`
- `tests/test_runner.py`
- `tests/test_run_command.py`
- `tests/test_remote.py`

## Backward Compatibility Rules

The following behavior stays stable:

- `servertool status` means local node and cluster status
- `servertool jobs` means local SLURM job inspection
- `servertool request` means local resource allocation guidance and execution
- `servertool disk` means local shared-disk monitoring
- `servertool config` continues to work for the current shared-account workflow
- the current entrypoints continue to work:
  - `servertool`
  - package `__main__`
  - repo-local helper launcher

New remote orchestration belongs under:

- `servertool run ...`
- `servertool runner ...`

## Phase Plan

### Phase 1: Foundation

Goals:

- define schema
- define controller and runner config fields
- define remote layout rules
- implement `spec + runner prepare + runner status`

Tasks:

1. extend `config.py`
2. add controller / runner config layering
3. add `layout.py`
4. add `spec.py`
5. implement `spec init/show/validate`
6. implement `runner prepare/status`
7. add unit tests

Outputs:

- `spec.json`
- `meta.json`
- `status.json`
- remote run directory creation
- generated `launch.sh`
- generated `job.sbatch`

### Phase 2: Transport + Remote

Goals:

- add structured transport primitives
- prepare cross-platform controller execution

Tasks:

1. add `remote.py`
2. implement `ssh` and `rsync` command builders
3. implement `remote doctor`
4. implement `remote install-runner`
5. support `--dry-run`

### Phase 3: Run Controller

Goals:

- run the controller-side workflow from the local machine

Tasks:

1. implement `run submit`
2. implement `run status`
3. implement `run logs`
4. implement `run fetch`
5. implement `run list`
6. add `--json`

### Phase 4: Email Notify

Goals:

- send mail on run completion

Tasks:

1. add `notify_email.py`
2. implement `runner notify`
3. implement `runner notify --test`
4. connect QQ SMTP credentials
5. trigger notification after run completion

### Phase 5: Cross-Platform Polish

Goals:

- make the controller experience stable on both supported desktop platforms

Tasks:

1. improve Windows `doctor` checks
2. document macOS and Windows installation separately
3. reduce shell-specific config usage
4. clean up Unix-only examples in the controller flow

## Phase 1 Detailed Execution Order

1. extend `config.py` with additive fields only
2. define `RunSpec`, `RunMeta`, and `RunStatus` models
3. add `layout.py` and freeze the remote path protocol
4. implement `spec init/show/validate`
5. implement `runner prepare` and `runner status`
6. register new command groups in `app.py`
7. add tests for schema, layout, and runner behavior
8. update the project plan and usage examples
9. run compatibility checks against existing commands

Phase 1 minimum closure:

```text
local spec.json
-> validate
-> remote-compatible run directory prepare
-> generate launch.sh / meta.json / status.json
-> read prepared status
```

Phase 1 excludes:

- launching real training
- result fetch
- email delivery
- uploaded env/model assets
- YAML support
- web UI

## Acceptance Criteria

v1 is considered usable when:

- `servertool` installs and runs on macOS
- `servertool` installs and runs on Windows
- `remote doctor` can verify `ssh + WSL2 + rsync` on Windows
- `servertool spec validate spec.json` succeeds
- `servertool run submit --dry-run spec.json` shows the planned workflow
- the server creates the standard run directory layout
- the server writes `launch.sh`, `job.sbatch`, and `status.json`
- `servertool run status` returns structured status output
- `servertool run logs` can read remote logs
- `servertool run fetch` can retrieve logs and outputs
- `servertool runner notify --test <email>` can deliver a test mail
- SMTP credentials never appear in git

## Risks

- Windows `rsync` compatibility
- SMTP port reachability
- local-path and remote-path mixups
- controller-side shell quoting complexity
- multi-user shared-account notification conflicts

Mitigations:

- support `WSL2 rsync` only in Windows v1
- prefer `smtp.qq.com:465` first
- model remote paths explicitly as POSIX paths
- keep controller execution shell-free
- store recipient mail in the per-run spec
- keep sender credentials on the runner side only

## Final Conclusion

`servertool` remains the single CLI. The controller becomes cross-platform for `macOS + Windows`, the runner stays Linux-only, the workflow is built around `ssh + rsync + JSON`, and email is the first notification backend.
