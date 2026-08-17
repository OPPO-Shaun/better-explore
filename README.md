# better-explore

> 自动化预研平台：测试开源方案，产出可落地的分析文档

## 项目简介

`better-explore` 是一个自动化预研框架，主要用于：

1. **开源方案调研** — 系统化评估开源工具/框架的功能、性能与成熟度
2. **自动化测试** — 通过脚本自动运行候选方案的核心场景，收集客观数据
3. **分析文档产出** — 基于模板生成标准化的可落地分析报告

---

## 目录结构

```
better-explore/
├── docs/
│   ├── templates/          # 报告模板
│   └── reports/            # 产出的分析报告（按主题归档）
├── scripts/                # 自动化调研脚本
├── tools/                  # 辅助工具与 Makefile targets
└── README.md
```

---

## 快速开始

### 1. 创建新的调研任务

复制评估模板并填写基本信息：

```bash
cp docs/templates/evaluation-template.md docs/reports/<topic>/<solution-name>.md
```

### 2. 运行自动化测试脚本

```bash
bash scripts/evaluate.sh <solution-name>
```

### 3. 查看报告

所有已产出的分析报告位于 `docs/reports/` 目录，按调研主题归档。

---

## 报告模板字段说明

详见 [`docs/templates/evaluation-template.md`](docs/templates/evaluation-template.md)。

---

## 贡献指南

1. 在 `docs/reports/<topic>/` 下新建报告，命名格式：`<solution-name>.md`
2. 调研脚本放在 `scripts/` 目录，按方案命名
3. 报告须包含：方案概述、核心能力、测试结果、落地评估、结论与建议