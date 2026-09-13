# 验证范围

`.github/workflows/skill-validation.yml` 在 PR 和 main push 上执行仓内结构、链接和内容判据自检。
`scripts/checkers.sha256` 标识共享的三份检查器；维护源在 kernel-opt-pipeline/scripts，六仓使用相同字节。更新检查器时需一起同步文件与哈希。

```bash
sha256sum -c scripts/checkers.sha256
python3 scripts/check_skill_layout.py . --strict
python3 scripts/check_wiki_anchors.py . --strict --local-only
python3 scripts/run_skill_content_evals.py --selfcheck .
```

本地链接检查明确不包含知识依赖。涉及私有 KernelWiki 的仓可手动触发 knowledge job，使用只读 `KERNELWIKI_READ_TOKEN`；未配置时该 job 失败并指出缺失能力。本次未替维护者创建密钥。
也可在具备依赖的宿主执行完整检查：

```bash
python3 scripts/check_wiki_anchors.py . --strict --wiki-root "$KERNELWIKI_ROOT"
```

Triton-Ascend 的链接检查还要求按 gitlink 初始化 external/triton-ascend，仅一层，不递归其 third_party。
CANNBench 当前没有 wiki_refs，跨仓知识覆盖为零；不能从零条引用推断知识依赖可用。

结构通过、判据自检通过、模型回答通过与 kernel 正确性/性能通过是四种不同证据。自动判分仅解析指定 JSON 字段；reason 的事实、适用条件和自相矛盾由行为评测人工复核。PACKAGE.txt 通过表示发布输入自洽，不表示打包器已执行它。
