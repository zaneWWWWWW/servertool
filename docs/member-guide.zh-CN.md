# 实验室成员手册

## 1. 这份手册给谁看

这份手册面向普通实验室成员。

你的职责只有两件事：

- 维护自己的个人配置
- 编写 spec 并提交训练任务

你不需要负责：

- 部署共享 runner
- 维护实验室公共配置
- 维护镜像源和共享缓存
- 维护 SMTP 凭据

这些都由管理员负责。

## 2. 开始前你需要拿到什么

第一次使用前，请先向管理员确认下面几项：

- 你已经拿到实验室提供的 `lab.env`
- 管理员已经执行过 `servertool admin deploy`
- 管理员已经建议好你的 `workspace_name`
- 远端共享账号已经可以通过 `ssh` 访问

如果 `lab.env` 还没有准备好，你即使安装了 CLI，也无法正常完成远端训练流程。

## 3. 安装

在 controller 机器上安装：

```bash
python3 -m pip install .
servertool version
servertool help
```

Windows 使用要求：

- Python 3.11+
- OpenSSH Client
- WSL2
- `rsync` 通过 WSL2 提供

## 4. 本地配置目录

默认配置目录：

```text
~/.config/servertool/
  lab.env
  user.env
  smtp.env
```

对普通成员来说：

- `lab.env` 由管理员提供
- `user.env` 由你通过 `servertool init` 生成
- `smtp.env` 不是你要维护的文件

当前优先级：

```text
environment > user.env > lab.env > built-in defaults
```

可用检查命令：

```bash
servertool config path
servertool config show
```

## 5. 第一次初始化

运行：

```bash
servertool init
```

它会交互式询问你：

- `Workspace name`
- `Member ID`
- `Default notify email`
- `Local run cache`

写入的都是个人字段，`user.env` 中不会保存实验室公共配置。

初始化完成后，CLI 会继续做远端 member 初始化，生成：

```text
<shared_home>/<workspace_name>/.servertool/config.env
```

如果你只想先写本地 `user.env`，可以用：

```bash
servertool init --skip-remote
```

## 6. 自检

运行：

```bash
servertool doctor
```

它会检查：

- 本地 `ssh` 和 `rsync`
- 本地是否能找到 runner 源码包
- 远端 Python
- 共享 `trainhub` 根目录
- 当前 member 的远端状态根目录
- 远端 runner 模块
- 远端 `lab.env` 和 member `config.env`
- 远端 `sbatch`
- 你的默认通知邮箱是否已配置

如果 `doctor` 失败，先不要提交任务，先把报错解决掉。

## 7. 公开命令面

普通成员只需要使用下面这些命令：

```bash
servertool init
servertool config [show|path]
servertool doctor
servertool spec [init|show|validate]
servertool run [submit|status|logs|fetch|list|cleanup]
servertool help [init|config|doctor|spec|run|admin]
servertool version
```

不要把 `remote` 或 `runner` 当作普通使用入口。

## 8. 写 Spec

生成一个新 spec：

```bash
servertool spec init spec.json --project vision --run-name smoke
servertool spec show spec.json
servertool spec validate spec.json
```

当前 `spec.json` 采用结构化 schema。

### 8.1 资产来源类型

`code`：

- 只支持 `sync`

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

### 8.2 推荐策略

- 数据集：优先用 `shared_path`，只有确实需要时再 `sync`
- 环境：优先用 `shared_path` 或 `build`
- 模型：优先用 `hub` 或 `shared_path`
- `upload` 只作为兜底方案

### 8.3 路径规则

- `shared_path` 必须写绝对远端路径
- `model.subpath` 必须是相对路径，不能写绝对路径，也不能包含 `..`
- `fetch.include` 必须是相对 run 根目录的 pattern，不能写绝对路径，也不能包含 `..`

### 8.4 一个常见示例

```json
{
  "version": "2",
  "project": "vision",
  "run_name": "bert-finetune",
  "assets": {
    "code": {
      "source": "sync",
      "path": "."
    },
    "dataset": {
      "source": "shared_path",
      "path": "/share/datasets/imagenet"
    },
    "env": {
      "source": "build",
      "type": "pip",
      "file": "requirements.txt",
      "name": "torch2.3-cu121"
    },
    "model": {
      "source": "hub",
      "provider": "huggingface",
      "id": "bert-base-uncased",
      "revision": "main"
    }
  },
  "launch": {
    "scheduler": "slurm",
    "partition": "A40",
    "gpus": 1,
    "cpus": 8,
    "mem": "32G",
    "time": "04:00:00",
    "workdir": ".",
    "command": "python train.py"
  },
  "fetch": {
    "include": [
      "outputs/**",
      "ckpts/**"
    ]
  },
  "notify": {
    "email": {
      "enabled": true,
      "to": [
        "you@example.com"
      ]
    }
  }
}
```

## 9. 提交任务

先预览：

```bash
servertool run submit spec.json --dry-run
```

正式提交：

```bash
servertool run submit spec.json
```

提交时会发生：

- 生成 `run_id`
- 规划远端目录
- 同步代码和必要资产
- 上传远端重写后的 `spec.json`
- 远端执行 `runner prepare`
- 远端执行 `runner start`
- 写本地 run record

本地 run record 默认写到：

```text
~/.cache/servertool/runs/<run_id>.json
```

## 10. 查看运行状态和日志

```bash
servertool run status RUN_ID
servertool run logs RUN_ID
servertool run logs RUN_ID --follow
```

`run status` 读取远端 `status.json`。

`run logs` 默认读 `stdout.log`，`--stderr` 可以改读 `stderr.log`。

## 11. 拉回结果

```bash
servertool run fetch RUN_ID
servertool run fetch RUN_ID --dest ./downloads
```

重要说明：

- `run fetch` 不再默认整目录硬拉
- 实际拉回内容由 `spec.fetch.include` 控制
- 默认 spec 一般会拉回 `outputs/**` 和 `ckpts/**`

默认本地落点：

```text
~/.cache/servertool/runs/fetched/<run_id>/
```

## 12. 查看本地历史

```bash
servertool run list
servertool run list --json
servertool run list --json --all-members
```

默认只显示当前 `member_id` 的本地记录。

`--all-members` 只用于你明确想查看整个本地缓存的时候。

## 13. 清理

先预览：

```bash
servertool run cleanup RUN_ID --dry-run
```

正式清理：

```bash
servertool run cleanup RUN_ID
```

部分清理：

```bash
servertool run cleanup RUN_ID --local-only --dry-run
servertool run cleanup RUN_ID --remote-only --dry-run
```

安全规则：

- 默认拒绝删除非终态 run
- 默认只清当前 member 的 run
- 默认只会自动删除位于默认 fetched cache 下的拉回目录
- 如确实需要强制清理，再显式使用 `--force`

## 14. Smoke 教程

仓库自带一个安全 smoke spec：`spec.smoke.train.json`。

在仓库根目录运行：

```bash
servertool spec validate spec.smoke.train.json
servertool run submit spec.smoke.train.json --dry-run
servertool run submit spec.smoke.train.json
```

然后按顺序检查：

```bash
servertool run status RUN_ID
servertool run logs RUN_ID --follow
servertool run fetch RUN_ID
```

这个 smoke spec 会运行一个很小的训练示例，并生成：

- `outputs/metrics.jsonl`
- `outputs/summary.json`
- `ckpts/last.ckpt`

## 15. 常见报错与处理

### 15.1 `SERVERTOOL_REMOTE_HOST is not configured`

原因：

- `lab.env` 没有放到本地配置目录
- 或者环境变量覆盖把远端配置清空了

处理：

- 先运行 `servertool config path`
- 确认 `lab.env` 是否在正确位置
- 再运行 `servertool doctor`

### 15.2 `Run 'xxx' belongs to member 'yyy'`

原因：

- 你正在访问别人的 run
- 或者当前 `member_id` / `workspace_name` 配置不对

处理：

- 先运行 `servertool config show`
- 确认自己的 `member_id`
- 使用自己提交的 `run_id`

### 15.3 `Log file not found`

原因：

- 任务刚提交，`stdout.log` / `stderr.log` 还没生成

处理：

- 先看 `servertool run status RUN_ID`
- 稍等一会儿再执行 `run logs`

### 15.4 `shared_path` 校验失败

原因：

- 你把 `shared_path` 写成了相对路径

处理：

- 改成绝对远端路径，例如 `/share/datasets/imagenet`

### 15.5 邮件没有发出

可能原因：

- 当前 run 的 `notify.email.enabled` 是 `false`
- `notify.email.to` 为空
- 管理员没有上传 `smtp.env`

处理：

- 先看 spec 里的通知配置
- 再联系管理员检查 `servertool admin doctor`

## 16. 日常建议

- 每次正式提交前，先跑一次 `servertool spec validate`
- 对新项目，先跑 `--dry-run`
- 大数据集和大模型优先走共享路径，不要默认上传
- 让 `fetch.include` 只包含你真正需要拉回的目录
- 如果你要更换 `workspace_name`，先和管理员确认命名规则
