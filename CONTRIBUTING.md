# Contributing

## Scope

`servertool` is a training CLI for shared-account lab workflows.

Before changing behavior, keep these product rules stable unless the change is intentional and documented:

- public CLI surface stays at `init`, `config`, `doctor`, `spec`, `run`, `admin`, `help`, `version`
- `remote` and `runner` are internal implementation interfaces
- config layering stays `lab.env` + `user.env` + `smtp.env`
- member-scoped defaults are a safety boundary, not an optional UX detail

## Development Setup

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -e .
```

If you do not want to install the package yet:

```bash
python3 -m servertool version
./servertool version
```

## Required Checks

Run these before opening a PR:

```bash
python3 -m compileall src
python3 -m unittest discover tests
python3 -m build
```

If you change the public CLI, config model, runner asset handling, or docs examples, update tests and user docs in the same change.

## Docs To Update Together

When behavior changes, keep these documents aligned:

- `README.md`
- `README.zh-CN.md`
- `docs/member-guide.zh-CN.md`
- `docs/admin-guide.zh-CN.md`
- `docs/architecture.zh-CN.md`

## Staging Validation Expectations

Use a staging lab or disposable remote workspace for end-to-end checks when changing deployment, runner behavior, or fetch behavior.

At minimum, re-check:

- admin deploy / admin doctor
- member init / doctor / validate / submit / fetch
- one advanced asset scenario if you touched env/model/dataset logic

## Secrets And Private Infrastructure

Do not commit:

- real `lab.env`, `user.env`, or `smtp.env`
- private cluster addresses
- credentials, tokens, or app passwords

Use placeholders in examples and keep real values in local ignored files.

## Pull Request Checklist

- behavior matches the current product model
- tests pass locally
- docs are updated
- no private infrastructure details were added
- generated files and build artifacts are excluded
