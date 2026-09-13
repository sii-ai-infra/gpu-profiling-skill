# 运行目录和依赖

| 配置 | 含义 |
|---|---|
| `SKILL_ROOT` | 本次 SKILL.md 所在目录；references 与本 skill 脚本相对它解析 |
| `TASK_ROOT` | 任务工作区绝对路径；源码、构建、profile 和报告写在这里 |
| `KOP_ROOT` | 产品宿主根，提供静态检查等 harness 工具 |
| `KERNELWIKI_ROOT` | 固定版本知识 checkout；提供 wiki 页和 scripts/query.py |

配置由任务/宿主提供，显式参数优先于环境变量。不要从当前工作目录猜测安装位置。
运行多 skill 时每份入口的 SKILL_ROOT 不同；宿主 create_task.py 生成的
`docs/runtime-env.sh` 可提供其他三个根。独立使用时配置所需项即可。

```bash
cd "$TASK_ROOT"
python3 "$KERNELWIKI_ROOT/scripts/query.py" --vendor <vendor> --language <language> '<问题>'
python3 "$KOP_ROOT/scripts/resolve_skill_runtime.py" \
  --task-root "$TASK_ROOT" --skill-root "$SKILL_ROOT" --require wiki-query
```

本 skill 自带脚本用 `"$SKILL_ROOT/scripts/<工具>"`，宿主工具用
`"$KOP_ROOT/scripts/<工具>"`。缺项时报告能力名及配置，不能在另一仓找同名脚本替代。
离线阅读不要求设备可用；使用某项工具前才检查该项依赖。

新采集使用 `$TASK_ROOT/profile/<唯一运行名>/`。先以不覆盖方式创建目录；原始记录保留。
产品提供 `resolve_skill_runtime.py --prepare-profile <唯一运行名>`，会拒绝已有目录。
不要把产物写回 skill 安装目录；独立任务按自身归档策略管理 profile，skill 的 .gitignore 不会影响任务仓。

知识服务若替代本地 checkout，必须支持按 wiki 路径读取、检索及返回来源版本和锚点。
宿主负责提供适配器和版本记录；接口未提供时明确报告缺失，不声称知识可用。

Ascend 设备操作在任务指定主机执行。环境所有者提供 CANN_ENV、NPU_PYTHON、设备选择
及空闲显存基线，不假定 ssh 910b 或固定版本目录。加载指定 CANN 环境后检查 npu-smi：
健康正常、无占用进程、AICore 空闲且 HBM 在该主机基线内；状态不明或忙碌时停止设备操作。
GPU 操作同样使用任务指定环境及其占用检查。路径检查不是设备验证。
