# Servertool

`servertool` 是一个面向 Ubuntu 服务器集群的 Python CLI，用于统一管理资源查询、GPU 申请、SLURM 作业查看与共享磁盘监控。

**作者：** zanewang  
**版本：** 3.0.0

## 项目定位

这个项目的核心目标是提供一个统一命令行入口，方便在共享集群环境中完成：

- 集群与节点状态检查
- GPU 资源申请
- SLURM 作业查看与取消
- 共享磁盘配额监控
- 作业提交流程验证

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

## 命令结构

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

部署相关配置建议通过环境变量覆盖。仓库中附带了一份脱敏的 `.env.example` 作为部署模板：

- `SERVERTOOL_SHARED_ACCOUNT`
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

## 开源安全

当前仓库不会包含以下信息：

- 真实生产服务器 IP
- 集群密码
- 私有认证地址
- 与真实服务器强绑定的用户名

如需在内部环境使用，请在部署时单独注入这些值，不要直接写入源码仓库。

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

现在仓库已经摒弃最初的临时结构，根目录即正式项目，后续功能建议继续沿用 `src/servertool/commands/` 进行扩展。
