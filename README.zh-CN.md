# Servertool

`servertool` 是一个面向共享账号实验室场景的正式训练 CLI。

它围绕一条固定主流程工作：

```text
spec -> sync -> prepare -> launch -> monitor -> notify -> fetch
```

当前目标运行环境：

- controller：`macOS` 或 `Windows`
- runner：`Linux`
- 传输：`ssh + rsync`
- 调度：`SLURM / sbatch`
- 部署模型：管理员统一部署共享 runner，成员各自维护个人 workspace

## 正式文档

- 文档导航：`docs/README.md`
- English overview: `README.md`
- 实验室成员手册：`docs/member-guide.zh-CN.md`
- 管理员手册：`docs/admin-guide.zh-CN.md`
- 架构说明：`docs/architecture.zh-CN.md`
- 贡献指南：`CONTRIBUTING.md`
- 维护者说明书：`MAINTAINERS.md`
- 版本记录：`CHANGELOG.md`
- 示例资产：`examples/README.md`

## 仓库结构

- `src/servertool/`：源码
- `tests/`：自动化测试
- `docs/`：长期维护的正式文档
- `examples/`：公开示例与配置模板
- `.github/workflows/`：CI 与打包校验

## 公开命令面

当前正式公开命令只有下面这些：

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

内部的 `remote` 和 `runner` 命令仍然存在，但属于实现和维护接口，不再作为普通成员主文档的一部分。

## 快速开始

从仓库安装：

```bash
python3 -m pip install .
servertool version
servertool help
```

如果你在开发 `servertool` 本身，建议先升级 pip 再做 editable install：

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -e .
```

如果你暂时不想安装，也可以直接从源码运行：

```bash
python3 -m servertool version
./servertool version
```

## 管理员流程

先准备本地配置目录：

```text
~/.config/servertool/
  lab.env
  smtp.env
  user.env
```

推荐管理员流程：

```bash
servertool admin show-config
servertool admin deploy --dry-run
servertool admin deploy
servertool admin doctor
```

`admin deploy` 会完成：

- 将共享 runner 发布到 `<shared_home>/trainhub/.runner/releases/<version>`
- 更新 `.runner/current`
- 上传共享 `lab.env`
- 如存在则上传 `smtp.env`
- 准备共享 `envs/`、`models/`、`cache/` 根目录
- 验证当前 runner release 可用

回滚方式：

```bash
servertool admin rollback 3.0.0 --dry-run
servertool admin rollback 3.0.0
```

## 成员流程

管理员分发 `lab.env` 后，普通成员只需要维护自己的 `user.env`。

推荐首次使用流程：

```bash
servertool init
servertool doctor
servertool spec init spec.json --project my-project --run-name smoke
servertool spec validate spec.json
servertool run submit spec.json --dry-run
servertool run submit spec.json
```

运行中常用命令：

```bash
servertool run status RUN_ID
servertool run logs RUN_ID
servertool run logs RUN_ID --follow
servertool run fetch RUN_ID
servertool run list
servertool run cleanup RUN_ID --dry-run
```

## Smoke 教程

仓库自带一个可直接跟踪的 smoke spec：`spec.smoke.train.json`。

在仓库根目录运行：

```bash
servertool spec validate spec.smoke.train.json
servertool run submit spec.smoke.train.json --dry-run
servertool run submit spec.smoke.train.json
```

拿到返回的 `RUN_ID` 后继续：

```bash
servertool run status RUN_ID
servertool run logs RUN_ID --follow
servertool run fetch RUN_ID
```

这个 smoke 会在 `outputs/` 和 `ckpts/` 下生成很小的示例产物，包括 `outputs/metrics.jsonl`、`outputs/summary.json` 和 `ckpts/last.ckpt`。

## 配置模型

默认本地文件：

```text
~/.config/servertool/
  lab.env
  user.env
  smtp.env
```

优先级：

```text
environment > user.env > lab.env > built-in defaults
```

职责划分：

- `lab.env`：实验室公共字段，例如远端主机、共享根目录、分区、镜像源、SMTP 设置
- `user.env`：成员个人字段，例如 `workspace_name`、`member_id`、通知邮箱、本地 run cache
- `smtp.env`：仅管理员维护的 SMTP 用户名和密码

可用命令：

- `servertool config show`：查看当前生效配置
- `servertool config path`：查看 `lab.env`、`user.env`、`smtp.env` 路径

公开配置模板放在 `examples/config/`。

## 结构化 Spec

`servertool` 现在使用结构化 `spec.json`。

支持的资产来源类型：

- `assets.code.source`：`sync`
- `assets.dataset.source`：`none | sync | shared_path`
- `assets.env.source`：`none | shared_path | build | upload`
- `assets.model.source`：`none | hub | shared_path | upload`

设计规则：

- 环境优先使用 `shared_path` 或 `build`
- 模型优先使用 `hub` 或 `shared_path`
- `upload` 只作为兜底
- `shared_path` 必须是绝对远端路径
- `fetch.include` 必须是相对 run 根目录的 pattern，`run fetch` 会按这些 pattern 拉回产物
- runner 会注入共享缓存和镜像相关环境变量，例如 `HF_HOME`、`HF_HUB_CACHE`、`MODELSCOPE_CACHE`、`PIP_CACHE_DIR`、`CONDA_PKGS_DIRS`、`PIP_INDEX_URL`、`PIP_EXTRA_INDEX_URL`、`HF_ENDPOINT`、`MODELSCOPE_ENDPOINT`

## 远端目录布局

实验室共享层：

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

成员层：

```text
<shared_home>/<workspace>/.servertool/
  config.env
  projects/<project>/runs/<run_id>/
```

## 安全默认值

当前 CLI 默认是 member-scoped：

- `run status`、`logs`、`fetch`、`cleanup` 默认只允许访问当前成员的 run
- `run list` 默认只显示当前成员的本地记录
- legacy 共享根 run 只有在存在匹配本地 run record 时才允许继续访问
- cleanup 默认保守，非终态 run 需要显式 `--force`

## FAQ

### 管理员只给了我 `lab.env`，下一步做什么？

先把它放到 `~/.config/servertool/lab.env`，然后执行 `servertool init` 和 `servertool doctor`。

### 为什么 `run fetch` 拉回来的文件比我预期少？

`run fetch` 会按 spec 里的 `fetch.include` 和远端 `status.json` 里记录的抓取规则过滤文件。需要更多产物时，先把目标路径补进 `fetch.include`。

### 普通成员可以直接用 `servertool remote` 或 `servertool runner` 吗？

不建议。它们属于内部实现接口，日常流程应只用 `init`、`doctor`、`spec`、`run`、`admin`。

### 为什么提示某个 run 属于别的成员？

这是 member-scoped 默认安全边界在生效。先运行 `servertool config show`，确认当前 `workspace_name` 和 `member_id` 是否与你要访问的 run 一致。

### 去哪里看当前生效的配置文件？

执行 `servertool config path` 看路径，执行 `servertool config show` 看最终生效值。

## 开发与校验

常用本地校验：

```bash
python3 -m compileall src
python3 -m unittest discover tests
python3 -m build
```

仓库不会包含真实生产服务器地址、凭据和私有内部地址。请通过本地配置文件或环境变量在源码外注入这些值。
