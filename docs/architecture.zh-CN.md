# 架构说明

## 1. 产品定义

`servertool` 当前被定义为：

**一个面向共享账号实验室场景的正式训练 CLI，采用管理员统一部署和共享配置、普通用户只维护个人配置、镜像/共享缓存优先的 env/model 策略，并坚持纯 CLI 与 member-scoped 默认安全边界。**

核心链路：

```text
controller -> ssh/rsync -> runner -> sbatch -> training job
```

## 2. 对外命令结构

当前公开命令面：

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

内部命令：

- `servertool remote ...`
- `servertool runner ...`

这两个内部命令仍保留，因为 controller 侧要通过它们调用远端 runner 能力，但它们不再属于正式公开产品入口。

## 3. 代码分层

当前核心目录：

```text
src/servertool/
  app.py
  commands/
  controller/
  runner/
  shared/
```

职责划分：

### 3.1 `commands/`

参数解析和用户输出层。

负责：

- 解析 CLI 参数
- 调用内部模块
- 打印用户可读输出

不负责：

- 复杂编排逻辑
- 远端状态持久化

### 3.2 `shared/`

controller 和 runner 共用的基础设施层。

核心模块：

- `shared/config.py`：配置加载和分层优先级
- `shared/spec.py`：结构化 spec schema 和校验
- `shared/layout.py`：run_id、项目路径和 run 布局
- `shared/system.py`：系统命令辅助

### 3.3 `controller/`

运行在本地 controller 机器上。

负责：

- 加载配置
- 解析 spec
- 规划远端路径
- 计算 run_id 和审计信息
- 生成 `ssh` / `rsync` 提交流程
- 维护本地 run record
- 拉回远端产物

核心模块：

- `controller/bootstrap.py`
- `controller/transport.py`
- `controller/runs.py`
- `controller/records.py`
- `controller/cleanup.py`

### 3.4 `runner/`

通过远端 `python -m servertool runner ...` 在 Linux 侧执行。

负责：

- 创建 run 目录
- 写 `spec.json`、`meta.json`、`status.json`
- 生成 `launch.sh` 和 `job.sbatch`
- 调用 `sbatch`
- 回写终态
- 发送邮件通知
- 准备 env 和 model

核心模块：

- `runner/assets.py`
- `runner/state.py`
- `runner/notify_email.py`

## 4. 配置加载逻辑

本地正式配置文件：

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

### 4.1 字段白名单边界

`user.env` 只读取用户字段：

- `SERVERTOOL_WORKSPACE_NAME`
- `SERVERTOOL_MEMBER_ID`
- `SERVERTOOL_NOTIFY_EMAIL_TO`
- `SERVERTOOL_LOCAL_RUN_CACHE`

`lab.env` 只读取实验室字段，例如：

- 远端主机、账号、端口、共享目录
- 分区和默认资源时间
- SMTP 设置
- `pip/conda/huggingface/modelscope` 镜像字段
- 共享 `env/model/cache` 根目录

这意味着普通用户无法通过 `user.env` 持久覆盖实验室公共字段。

### 4.2 兼容别名

为兼容旧环境，仍保留：

- `SERVERTOOL_CONFIG_FILE` 作为 `SERVERTOOL_USER_CONFIG_FILE` 的兼容别名
- `SERVERIP` / `SERVERUSERNAME` / `SERVERPSD` 的远端连接兼容别名

但正式文档不再以这些旧名称为主。

## 5. 远端目录布局

共享实验室层：

```text
<shared_home>/trainhub/
  .runner/
    releases/
      <version>/
        servertool/
    current -> releases/<version>
  lab/
    lab.env
    smtp.env
  envs/
  models/
  cache/
    pip/
    conda/
    huggingface/
    modelscope/
```

成员层：

```text
<shared_home>/<workspace>/.servertool/
  config.env
  projects/
```

run 层：

```text
<shared_home>/<workspace>/.servertool/projects/<project>/runs/<run_id>/
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

## 6. 提交流程

controller 侧主链路：

```text
load config
-> load spec
-> build run_id
-> build remote layout
-> rewrite remote asset paths
-> rsync uploads
-> ssh runner prepare
-> ssh runner start
-> write local run record
```

### 6.1 `run submit`

`controller/runs.py` 负责：

- 读取本地 spec
- 把本地路径改写成远端路径
- 对 `env.build` 和 `model.hub` 推导共享目标路径
- 计算审计信息
- 生成完整提交命令序列

### 6.2 `runner prepare`

`commands/runner.py` 和 `runner/assets.py` 负责：

- 校验并准备 code/dataset/env/model
- 创建 run 目录
- 写 `meta.json` 和 `status.json`
- 生成 `launch.sh` 和 `job.sbatch`

### 6.3 `runner start`

负责：

- 调用 `sbatch`
- 从输出中解析 `job_id`
- 把状态更新为 `running`

### 6.4 `runner finalize`

训练退出后，`launch.sh` 自动调用 `runner finalize`。

负责：

- 根据退出码写 `succeeded` 或 `failed`
- 写入 `ended_at`
- 发送邮件通知
- 如通知失败，将错误写入 `notify_error`

## 7. Run 状态机

当前正式状态主要包括：

- `prepared`
- `running`
- `succeeded`
- `failed`
- `stopped`

实际常见路径：

```text
prepared -> running -> succeeded
prepared -> running -> failed
prepared -> failed
```

相关持久化文件：

- `meta.json`：偏静态元信息与审计信息
- `status.json`：偏实时状态
- 本地 run record：偏 controller 侧记录和本地 fetch 信息

### 7.1 `meta.json`

当前会保留：

- `run_id`
- `project`
- `run_name`
- `member_id`
- 路径信息
- 审计信息

审计信息当前包括：

- `submitted_by`
- `controller_user`
- `controller_host`
- `controller_platform`
- `controller_version`
- `git_rev`
- `git_dirty`
- `spec_sha256`

### 7.2 `status.json`

当前会保留：

- `state`
- `job_id`
- `exit_code`
- 时间戳字段
- `message`
- `paths`
- `notify_error`
- `member_id`
- `assets`
- `fetch.include`

## 8. Spec Schema

当前版本号：`version = "2"`。

关键结构：

- `project`
- `run_name`
- `assets.code`
- `assets.dataset`
- `assets.env`
- `assets.model`
- `launch.*`
- `fetch.include`
- `notify.email.*`

### 8.1 支持的来源类型

`dataset`：

- `none`
- `sync`
- `shared_path`

`env`：

- `none`
- `shared_path`
- `build`
- `upload`

`model`：

- `none`
- `hub`
- `shared_path`
- `upload`

### 8.2 关键校验规则

- `launch.scheduler` 目前必须是 `slurm`
- 如果启用邮件通知，`notify.email.to` 不能为空
- `fetch.include` 至少有一个 pattern
- `shared_path` 必须是绝对远端路径
- `model.subpath` 必须是相对路径，且不能越界
- `fetch.include` 不能越过 run 根目录

## 9. Env / Model 准备策略

### 9.1 总原则

正式策略是：

- 镜像源优先
- 共享缓存优先
- 本地上传兜底

### 9.2 `env`

`env.source = shared_path`：

- 直接使用实验室已经准备好的共享环境

`env.source = build`：

- 远端基于 `requirements.txt` 或 `environment.yml` 构建
- 构建时使用共享 `pip/conda` cache 和管理员配置的镜像源
- 构建结果写入共享 `envs/`

`env.source = upload`：

- 从 controller 上传环境目录或包
- 只作为兜底方案

### 9.3 `model`

`model.source = hub`：

- 远端通过镜像 endpoint 下载
- 命中共享 huggingface/modelscope cache
- 最终存入共享 `models/`

`model.source = shared_path`：

- 直接使用实验室已有共享模型目录

`model.source = upload`：

- 上传私有或临时模型
- 只作为兜底方案

### 9.4 共享模型元数据

对于 `model.source = hub`，runner 会在共享模型目录写入 source metadata。

目的：

- 避免不同模型 ID 或 revision 误复用同一个共享目录
- 让共享模型目录具备最小一致性校验能力

### 9.5 runner 注入的缓存与镜像环境变量

为了让 `env.build` 和 `model.hub` 优先命中实验室共享缓存，runner 在 `launch.sh` 中会注入：

- `HF_HOME`
- `HF_HUB_CACHE`
- `MODELSCOPE_CACHE`
- `PIP_CACHE_DIR`
- `CONDA_PKGS_DIRS`
- `PIP_INDEX_URL`
- `PIP_EXTRA_INDEX_URL`
- `HF_ENDPOINT`
- `MODELSCOPE_ENDPOINT`

这些值来自管理员维护的共享 cache root 和镜像配置，因此成员 spec 不需要重复声明这类公共字段。

## 10. `run fetch` 的设计

Phase 3 之后，`run fetch` 不再默认整棵 run 目录硬拉。

它会优先读取：

- 远端 `status.json` 中的 `fetch.include`
- 本地 run record 中的 `fetch_include`

然后将这些 pattern 转换成 rsync include/exclude 规则。

这让：

- 默认 fetch 更轻量
- 大型中间文件不会被无意间拉回本地
- spec 真正成为 controller 和 runner 之间的中间协议

## 11. 安全边界

当前默认安全边界是 member-scoped。

具体表现：

- `run status` 只允许访问当前 member 的 run
- `run logs` 只允许访问当前 member 的 run
- `run fetch` 只允许访问当前 member 的 run
- `run cleanup` 只允许清理当前 member 的 run
- `run list` 默认只显示当前 member 的本地记录

对于旧的 shared-root run，只在本地存在匹配 run record 时才允许继续访问。

管理员能力如果需要增强，应通过 `admin` 命令设计，而不是直接放宽普通成员默认行为。

## 12. 测试覆盖重点

当前测试已经覆盖：

- 公开 CLI 命令面
- 配置分层与字段白名单
- admin deploy / rollback / doctor 的关键路径
- run submit / status / logs / fetch / cleanup
- runner prepare / start / finalize / notify
- 结构化 spec 校验
- env/model 共享路径、build、hub、upload 的主要分支

## 13. 当前文档关系

面向不同读者的正式文档：

- `README.md` / `README.zh-CN.md`：总览入口
- `docs/member-guide.zh-CN.md`：普通成员操作文档
- `docs/admin-guide.zh-CN.md`：管理员部署和维护文档
- `docs/architecture.zh-CN.md`：维护者和开发者文档
