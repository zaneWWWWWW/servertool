# 管理员手册

## 1. 这份手册给谁看

这份手册面向负责实验室共享账号部署和维护的人。

管理员负责：

- 维护 `lab.env`
- 维护 `smtp.env`
- 发布和回滚共享 runner
- 维护共享镜像源和缓存根目录
- 给成员分发 `lab.env` 和使用规范

普通成员不负责这些工作。

## 2. 管理员机器上的本地文件

默认配置目录：

```text
~/.config/servertool/
  lab.env
  smtp.env
  user.env
```

职责：

- `lab.env`：实验室公共配置，必须由管理员维护
- `smtp.env`：SMTP 用户名和密码，推荐由管理员维护
- `user.env`：管理员自己在 controller 机器上的个人配置

说明：

- `admin deploy` 主要依赖 `lab.env` 和可选的 `smtp.env`
- `admin doctor` 也会检查当前 controller 用户对应的 member 远端状态，因此推荐管理员机器上也保留一份正常的 `user.env`

## 3. 推荐部署前准备

先确认：

- 你可以从 controller 机器 `ssh` 到共享账号
- 远端 Linux 环境能运行 `python3`
- 本地有可用的 `rsync`
- 你已经确定共享账号、共享 home、`trainhub` 根目录和分区名

可先检查本地解析结果：

```bash
servertool admin show-config
servertool config show
servertool config path
```

## 4. `lab.env` 该放什么

`lab.env` 负责实验室公共字段。

当前建议至少维护这些字段：

- `SERVERTOOL_REMOTE_HOST`
- `SERVERTOOL_REMOTE_USER`
- `SERVERTOOL_REMOTE_PORT`
- `SERVERTOOL_SHARED_ACCOUNT`
- `SERVERTOOL_SHARED_HOME`
- `SERVERTOOL_REMOTE_ROOT`
- `SERVERTOOL_REMOTE_PYTHON`
- `SERVERTOOL_A40_PARTITION`
- `SERVERTOOL_A6000_PARTITION`
- `SERVERTOOL_A40_MAX_TIME`
- `SERVERTOOL_A6000_MAX_TIME`
- `SERVERTOOL_NOTIFY_EMAIL_FROM`
- `SERVERTOOL_SMTP_HOST`
- `SERVERTOOL_SMTP_PORT`
- `SERVERTOOL_SMTP_USE_SSL`
- `SERVERTOOL_PIP_INDEX_URL`
- `SERVERTOOL_PIP_EXTRA_INDEX_URL`
- `SERVERTOOL_CONDA_CHANNELS`
- `SERVERTOOL_HF_ENDPOINT`
- `SERVERTOOL_MODELSCOPE_ENDPOINT`
- `SERVERTOOL_SHARED_ENV_ROOT`
- `SERVERTOOL_SHARED_MODEL_ROOT`
- `SERVERTOOL_SHARED_CACHE_ROOT`

一个最小示例：

```bash
export SERVERTOOL_REMOTE_HOST=cluster.example.com
export SERVERTOOL_REMOTE_USER=gpu2003
export SERVERTOOL_REMOTE_PORT=22
export SERVERTOOL_SHARED_ACCOUNT=gpu2003
export SERVERTOOL_SHARED_HOME=/share/home/gpu2003
export SERVERTOOL_REMOTE_ROOT=/share/home/gpu2003/trainhub
export SERVERTOOL_REMOTE_PYTHON=python3
export SERVERTOOL_A40_PARTITION=A40
export SERVERTOOL_A6000_PARTITION=A6000
export SERVERTOOL_A40_MAX_TIME=04:00:00
export SERVERTOOL_A6000_MAX_TIME=08:00:00
export SERVERTOOL_NOTIFY_EMAIL_FROM=notify@example.com
export SERVERTOOL_SMTP_HOST=smtp.example.com
export SERVERTOOL_SMTP_PORT=465
export SERVERTOOL_SMTP_USE_SSL=1
export SERVERTOOL_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export SERVERTOOL_CONDA_CHANNELS=pytorch,nvidia,conda-forge
export SERVERTOOL_HF_ENDPOINT=https://hf-mirror.example
export SERVERTOOL_MODELSCOPE_ENDPOINT=https://modelscope.example
export SERVERTOOL_SHARED_ENV_ROOT=/share/home/gpu2003/trainhub/envs
export SERVERTOOL_SHARED_MODEL_ROOT=/share/home/gpu2003/trainhub/models
export SERVERTOOL_SHARED_CACHE_ROOT=/share/home/gpu2003/trainhub/cache
```

不要把下面这些成员字段写进 `lab.env`：

- `SERVERTOOL_WORKSPACE_NAME`
- `SERVERTOOL_MEMBER_ID`
- `SERVERTOOL_NOTIFY_EMAIL_TO`
- `SERVERTOOL_LOCAL_RUN_CACHE`

## 5. `smtp.env` 该放什么

`smtp.env` 只需要 SMTP 凭据：

```bash
export SERVERTOOL_SMTP_USERNAME=notify@example.com
export SERVERTOOL_SMTP_PASSWORD=app-password-or-token
```

它不会发给普通成员。

如果 `smtp.env` 缺失，`admin deploy` 仍然可以完成，但 runner 邮件通知会保持未配置状态。

## 6. 正式部署流程

推荐顺序：

```bash
servertool admin show-config
servertool admin deploy --dry-run
servertool admin deploy
servertool admin doctor
```

`admin deploy` 当前会完成：

- 创建远端共享目录
- 同步当前版本的 `servertool` 包到 `.runner/releases/<version>/servertool`
- 验证 staged release
- 上传共享 `lab.env`
- 如存在则上传 `smtp.env`
- 设置配置文件权限
- 激活 `.runner/current`
- 再次验证远端 runner

部署完成后，远端大致结构如下：

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

## 7. 回滚流程

先查看目标版本是否已经安装，再执行：

```bash
servertool admin rollback 3.0.0 --dry-run
servertool admin rollback 3.0.0
```

回滚本质上只是把：

```text
<shared_home>/trainhub/.runner/current
```

重新指向一个已存在的旧 release。

如果你已经确认旧版本稳定，回滚后再执行一次：

```bash
servertool admin doctor
```

## 8. `admin show-config` 怎么用

`servertool admin show-config` 适合在部署前做人工核对。

当前会显示：

- 本地 `lab.env` 路径
- 本地 `smtp.env` 路径
- 远端 `lab.env` 路径
- 远端 `smtp.env` 路径
- runner release 版本
- staged release 路径
- `.runner/current` 路径
- 共享 `env/model/cache` 根目录
- SMTP 和镜像源相关字段

如果输出和你预期不一致，不要直接部署，先修正本地配置。

## 9. `admin doctor` 检查什么

`servertool admin doctor` 会检查：

- 本地 runner 源码目录
- 本地 `ssh` 和 `rsync`
- 远端 Python
- 共享 `trainhub` 根目录
- 当前 member 的远端状态根目录
- 远端 runner 模块
- 远端 `lab.env`
- 当前 member 的远端 `config.env`
- 远端 `sbatch`
- 共享 `env` 根目录
- 共享 `model` 根目录
- 共享 `cache` 根目录
- 远端 `smtp.env`

输出规则：

- blocker：必须先修复
- warning：部署已可用，但某些辅助能力还没准备好，例如 SMTP

## 10. 镜像源与共享缓存策略

Phase 3 之后，`servertool` 的正式策略是：

- 环境优先用共享环境或远端构建
- 模型优先用远端 hub 镜像和共享缓存
- 本地上传只作为兜底方案

管理员需要重点维护这些字段：

- `SERVERTOOL_PIP_INDEX_URL`
- `SERVERTOOL_PIP_EXTRA_INDEX_URL`
- `SERVERTOOL_CONDA_CHANNELS`
- `SERVERTOOL_HF_ENDPOINT`
- `SERVERTOOL_MODELSCOPE_ENDPOINT`
- `SERVERTOOL_SHARED_ENV_ROOT`
- `SERVERTOOL_SHARED_MODEL_ROOT`
- `SERVERTOOL_SHARED_CACHE_ROOT`

远端共享缓存会被拆成：

- `cache/pip`
- `cache/conda`
- `cache/huggingface`
- `cache/modelscope`

## 11. 成员 onboarding 建议

推荐给成员的最短路径：

1. 将实验室发放的 `lab.env` 放到 `~/.config/servertool/lab.env`
2. 执行 `servertool init`
3. 执行 `servertool doctor`
4. 运行一次 smoke：`spec validate -> run submit --dry-run -> run submit -> run status/logs -> run fetch`

管理员不要让成员自己填写实验室公共字段。

## 12. 常见排障

### 12.1 `SERVERTOOL_REMOTE_HOST is not configured`

原因：

- `lab.env` 没有放到正确位置
- 或者被环境变量覆盖了

处理：

- `servertool config path`
- `servertool admin show-config`
- 修正 `lab.env`

### 12.2 `local runner source` 检查失败

原因：

- 你不在完整仓库里执行命令
- 本地安装内容和当前源码目录不匹配

处理：

- 在仓库根目录重新执行
- 或重新安装当前版本

### 12.3 `remote runner module` 缺失

原因：

- 还没有执行过 `admin deploy`
- 或 `.runner/current` 指向损坏

处理：

- 重新执行 `servertool admin deploy`
- 或 `servertool admin rollback <version>`

### 12.4 SMTP 相关 warning

原因：

- 本地 `smtp.env` 不存在
- 远端 `lab/smtp.env` 还没同步

处理：

- 检查本地 `~/.config/servertool/smtp.env`
- 重新执行 `servertool admin deploy`
- 再跑 `servertool admin doctor`

### 12.5 成员 `doctor` 失败但管理员 `doctor` 正常

原因：

- 共享层已经部署好，但成员还没运行 `servertool init`
- 或者成员的 `workspace_name` / `member_id` 写错了

处理：

- 让成员执行 `servertool init`
- 检查其 `user.env`

## 13. 维护建议

- 每次升级前先执行 `servertool admin deploy --dry-run`
- 升级后立即执行 `servertool admin doctor`
- 给成员分发 `lab.env` 时，同时附带推荐 `workspace_name` 命名规则
- 邮件通知依赖 `smtp.env`，凭据轮换后记得重新部署
- 大模型和大环境优先放入共享目录，不要鼓励成员重复上传
