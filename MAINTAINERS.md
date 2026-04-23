# Maintainer Guide

## Repository Intent

`servertool` is maintained as a releaseable GitHub project, not just an internal experiment.

The repository should stay organized around a small public CLI, explicit docs, repeatable tests, and safe example assets.

## Repository Layout

Top-level directories that should remain first-class:

- `src/servertool/`: package source
- `tests/`: unit and CLI tests
- `docs/`: long-form docs
- `examples/`: public example assets and config templates
- `.github/workflows/`: CI

Top-level files that should remain curated:

- `README.md`
- `README.zh-CN.md`
- `docs/README.md`
- `CONTRIBUTING.md`
- `CHANGELOG.md`
- `LICENSE`

Avoid re-introducing planning drafts, throwaway reports, or one-off process notes at the repository root.

## Repository Hygiene

Keep the repository publishable at all times:

- keep example endpoints and email addresses placeholder-safe
- prefer moving long-form docs into `docs/` instead of adding new root markdown files

## Stable Product Contracts

These are the main contracts to preserve unless there is an explicit product decision to change them:

### CLI surface

Public commands:

- `init`
- `config`
- `doctor`
- `spec`
- `run`
- `admin`
- `help`
- `version`

Internal commands:

- `remote`
- `runner`

If you add or remove public commands, update `tests/test_cli_surface.py` and all user-facing docs.

### Config model

Persistent config is split into:

- `lab.env`: lab-managed shared config
- `user.env`: member-managed personal config
- `smtp.env`: admin-only SMTP secrets

Do not collapse these back into a single shared config file.

### Runtime model

Submission stays:

```text
controller -> ssh/rsync -> runner -> sbatch -> run outputs -> fetch
```

Do not introduce hidden services or background daemons unless the product model is intentionally changing.

## Code Map

### `src/servertool/app.py`

Builds the public CLI parser and hides internal commands from normal help output.

### `src/servertool/commands/`

CLI argument parsing and user-facing output.

Keep orchestration logic thin here.

### `src/servertool/controller/`

Controller-side planning:

- deployment and rollback planning
- remote transport command construction
- submit/fetch/cleanup workflows
- local run records

### `src/servertool/runner/`

Runner-side execution:

- asset preparation
- run metadata and status
- email notification

### `src/servertool/shared/`

Shared primitives used on both controller and runner:

- config loading
- spec validation
- layout rules
- system helpers

## Important Maintenance Rules

### Runner-affecting code requires redeploy

If you change any logic that executes on the remote Linux side, local tests are not enough.

Typical examples:

- `src/servertool/runner/*`
- `src/servertool/commands/runner.py`
- runner deployment/bootstrap code

After such changes, the shared remote release must be updated with `servertool admin deploy`, otherwise member submissions still run the old `.runner/current` code on the cluster.

### Write artifacts into the run directory

Public examples and smoke assets should write outputs under:

- `$SERVERTOOL_RUN_DIR/outputs`
- `$SERVERTOOL_RUN_DIR/ckpts`

This keeps them compatible with `fetch.include` and `run fetch`.

### Be conservative with compatibility wrappers

Thin import-compatibility modules such as `servertool.config` and `servertool.spec` are still useful for tests and external imports.

Remove dead code, but do not break obvious public import paths casually.

## Tests

Minimum local checks:

```bash
python3 -m compileall src
python3 -m unittest discover tests
python3 -m build
```

Useful focused test targets:

```bash
python3 -m unittest tests.test_cli_surface
python3 -m unittest tests.test_run_command
python3 -m unittest tests.test_runner
python3 -m unittest tests.test_config
python3 -m unittest tests.test_spec
```

## Staging Validation

The repository no longer carries a checked-in manual-test kit.

For release validation, use a staging lab and confirm at least:

- admin deploy / admin doctor
- member init / doctor
- `spec.smoke.train.json` validate / submit / fetch
- one asset-heavy scenario if you changed env/model/dataset handling

## Packaging And Release

Release checklist:

1. Update docs and examples.
2. Run unit tests.
3. Run `python3 -m build`.
4. Verify install from the built wheel.
5. If runner logic changed, redeploy on a staging lab and execute a smoke submit/fetch cycle.
6. Update `CHANGELOG.md`.
7. Tag and publish the release.

## CI Expectations

The GitHub Actions workflow should keep verifying:

- install from source
- CLI entrypoint works
- unit tests pass
- wheel/sdist build succeeds

If build or install steps change, keep the workflow aligned.

## Documentation Policy

The root README is the first public entry point.

Detailed role-specific docs belong in:

- `docs/member-guide.zh-CN.md`
- `docs/admin-guide.zh-CN.md`
- `docs/architecture.zh-CN.md`

When you change behavior, prefer updating the existing canonical doc instead of adding a new ad hoc note.
