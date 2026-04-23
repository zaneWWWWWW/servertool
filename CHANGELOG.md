# Changelog

## 3.0.0 - 2026-04-23

Initial public release for the shared-account lab training workflow.

### Added

- stable public CLI surface centered on `init`, `config`, `doctor`, `spec`, `run`, and `admin`
- layered config model with `lab.env`, `user.env`, and `smtp.env`
- admin deployment, rollback, doctor, and config inspection commands
- structured spec model for `code`, `dataset`, `env`, and `model` assets
- member-scoped run records, fetch filtering, and safer cleanup behavior
- shared cache and mirror-aware runtime injection for pip, conda, Hugging Face, and ModelScope
- role-specific user manuals for members, admins, and maintainers
- curated `docs/` and `examples/` entrypoints for public repository publishing
- GitHub Actions CI for install, tests, and distribution builds

### Removed

- legacy local helper commands from the formal product surface
- outdated planning and one-off process artifacts from the release-focused repository layout
- checked-in manual test assets and generated validation artifacts

### Notes

- internal `remote` and `runner` commands remain for implementation and maintenance workflows
- editable installs are best done with a modern pip version
