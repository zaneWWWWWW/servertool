# Examples

This directory contains public-safe example assets that are intended to stay publishable.

## Contents

- `config/lab.env.example`: admin-managed lab config template
- `config/user.env.example`: member-managed personal config template
- `config/smtp.env.example`: admin-managed SMTP secrets template
- `smoke_train.py`: tiny training script that writes outputs under `$SERVERTOOL_RUN_DIR`

## Usage

Use the config templates as starting points for real deployments:

```bash
cp examples/config/lab.env.example ~/.config/servertool/lab.env
cp examples/config/user.env.example ~/.config/servertool/user.env
```

For release validation, use `../spec.smoke.train.json` with a staging lab configuration and confirm `submit -> status -> logs -> fetch` still works.
