# Servertool

`servertool` 是一个统一命令行工具，既保留原有集群运维命令，也支持 controller 到 runner 的远程训练工作流。

**作者：** zanewang  
**版本：** 3.0.0

## 项目定位

这个项目的核心目标是提供一个统一命令行入口，方便在共享集群环境中完成：

- 集群与节点状态检查
- GPU 资源申请
- SLURM 作业查看与取消
- 共享磁盘配额监控
- 作业提交流程验证
- 在控制端机器上生成和校验训练 spec
- 把代码和数据同步到 Linux runner 服务器
- 不手动 SSH 登录也能启动、查看和拉取远程训练结果

仓库中已主动移除敏感部署信息。真实服务器地址、密码、内部认证地址、私有用户名等内容不应进入公开仓库，而应通过环境变量、部署脚本或本地未纳入版本控制的配置注入。

当前仓库根目录 `servertool/` 就是正式项目根目录，Python 包位于 `src/servertool/`。部署相关配置应始终放在被忽略的本地配置中，而不是提交到源码仓库。

## 快速开始

开发环境安装：

```bash
python3 -m pip install -e .
```

然后先运行：

```bash
servertool help
servertool status
servertool request guide
```

首次使用集群流程时可运行：

```bash
servertool quickstart
```

如果要使用 controller/runner 训练流程，首次建议先执行：

```bash
servertool remote bootstrap
servertool remote doctor
servertool runner notify --test you@example.com
```

## 命令结构

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

## Controller / Runner 工作流

控制端命令的目标是让你不必为了同步物料和启动训练而手动 SSH 到集群里敲命令。

### 1. 初始化远端 runner

```bash
servertool remote bootstrap
servertool remote doctor
```

`remote bootstrap` 会在 Linux runner 上创建 `trainhub/.runner` 和 `~/.config/servertool`，上传 runner 包，并同步 runner 侧邮件配置。

### 2. 创建训练 spec

```bash
servertool spec init spec.json --project vision --run-name smoke
servertool spec validate spec.json
servertool spec show spec.json
```

### 3. 在控制端提交任务

```bash
servertool run submit spec.json --dry-run
servertool run submit spec.json
```

### 4. 查看日志与拉取结果

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

`run cleanup` 默认是保守的：它会清理远端 run 目录和本地 run record；只有当拉取目录位于默认 fetched cache 下时，才会自动一起删除。本命令默认拒绝删除非终态任务；确实需要强制清理时再使用 `--force`。如果只想清理本地或远端，可分别使用 `--local-only` 和 `--remote-only`。

如果只想清理远端 runner 侧产物，可以使用：

```bash
servertool remote cleanup RUN_ID --dry-run
servertool remote cleanup RUN_ID
```

### 5. Runner 侧命令

这些命令主要给 Linux runner 主机本地使用，或者由 controller 通过 SSH 远程调用：

```bash
servertool runner prepare SPEC_PATH
servertool runner start RUN_ID
servertool runner status RUN_ID
servertool runner tail RUN_ID
servertool runner notify RUN_ID
servertool runner notify --test you@example.com
```

## 安全 Smoke Spec

仓库里现在保留了两个 smoke spec：

- `spec.smoke.json`：只打印一行 smoke 日志
- `spec.smoke.train.json`：运行 `examples/smoke_train.py`，并写出 `outputs/metrics.jsonl`、`outputs/summary.json` 和 `ckpts/last.ckpt`

更贴近训练流程的 smoke spec 仍然保持了很小的资源占用，适合做 controller/runner 端到端冒烟验证：

```bash
servertool spec validate spec.smoke.train.json
servertool run submit spec.smoke.train.json --dry-run
```

## 常见流程

### 1. 查看资源申请说明

```bash
servertool request guide
```

### 2. 申请推荐资源

```bash
servertool request medium
```

### 3. 检查节点和 GPU

```bash
servertool status quick
nvidia-smi
echo $CUDA_VISIBLE_DEVICES
```

### 4. 查看作业

```bash
servertool jobs
servertool jobs who
servertool jobs info JOBID
```

### 5. 查看共享磁盘

```bash
servertool disk show
servertool disk detail
servertool disk update
```

## 配置方式

`servertool` 现在支持“按共享账号保存”的本地配置文件。登录到某个共享账号后，建议先执行一次：

```bash
servertool config setup
```

默认会把配置写入 `~/.config/servertool/config.env`，后续命令会自动读取。只有在自动化场景下，才需要再用环境变量覆盖这些值。

注意：不要把密码或 SSH 私钥写入这个配置文件。`servertool` 只需要共享账号、共享目录、分区、时长、认证地址这类集群元信息。

对于 controller 工作流，还会用到远端主机、远端根目录、本地 run 缓存和 SMTP 路径等配置。SMTP 用户名和授权码应单独放在本地 secrets 文件中，例如 `~/.config/servertool/smtp.env`。

仓库中附带了一份脱敏的 `.env.example` 作为部署模板：

- `SERVERTOOL_SHARED_ACCOUNT`
- `SERVERTOOL_WORKSPACE_NAME`
- `SERVERTOOL_SHARED_HOME`
- `SERVERTOOL_AUTH_URL`
- `SERVERTOOL_NETWORK_PROBE_URL`
- `SERVERTOOL_A40_PARTITION`
- `SERVERTOOL_A6000_PARTITION`
- `SERVERTOOL_A40_MAX_TIME`
- `SERVERTOOL_A6000_MAX_TIME`
- `SERVERTOOL_DEFAULT_COMPUTE_HOST`
- `SERVERTOOL_QUOTA_LIMIT`
- `SERVERTOOL_CACHE_FILE`
- `SERVERTOOL_TEST_OUTPUT_DIR`
- `SERVERTOOL_INSTALL_PATH`
- `SERVERTOOL_CONFIG_FILE`
- `SERVERTOOL_REMOTE_HOST`
- `SERVERTOOL_REMOTE_USER`
- `SERVERTOOL_REMOTE_PORT`
- `SERVERTOOL_REMOTE_ROOT`
- `SERVERTOOL_REMOTE_PYTHON`
- `SERVERTOOL_LOCAL_RUN_CACHE`
- `SERVERTOOL_NOTIFY_EMAIL_TO`
- `SERVERTOOL_NOTIFY_EMAIL_FROM`
- `SERVERTOOL_SMTP_HOST`
- `SERVERTOOL_SMTP_PORT`
- `SERVERTOOL_SMTP_USE_SSL`
- `SERVERTOOL_SMTP_SECRETS_FILE`

兼容说明：控制端也支持把 `SERVERIP` 和 `SERVERUSERNAME` 作为 `SERVERTOOL_REMOTE_HOST` 与 `SERVERTOOL_REMOTE_USER` 的回退来源。

## 开源安全

当前仓库不会包含以下信息：

- 真实生产服务器 IP
- 集群密码
- 私有认证地址
- 与真实服务器强绑定的用户名

如需在内部环境使用，请通过本地配置文件或部署时单独注入这些值，不要直接写入源码仓库。

当前源码默认不包含任何字面量服务器 IP。网络连通性探测改为使用可配置的 `SERVERTOOL_NETWORK_PROBE_URL`，避免把固定地址写入公开仓库。

## 开发校验

```bash
python3 -m compileall src
python3 servertool help
python3 -m unittest discover tests
```

## 目录结构

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

现在内部代码已按 `controller/`、`runner/`、`shared/` 三层拆分，但对外仍保持单一 CLI 名称 `servertool`。
