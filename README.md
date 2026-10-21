# 旅游景点数据分析与智能推荐系统

《大数据综合分析和处理》课程的三人协作项目。目标是采集真实景点资料，完成清洗、存储和分析，以网页展示景点分布、支持查询，并按地区、门票预算和兴趣提供可解释推荐。

技术路线：Python / Scrapy / Pandas → Hadoop/HDFS、MapReduce、Spark SQL → MySQL → Flask → Vue / ECharts。

## Agent 从这里开始

先读 [AGENTS.md](AGENTS.md)。用户说“我负责 B”等简短表述即可指定角色，由 agent 根据当前阶段定位任务、读取相关约定并推进，不要求成员手工通读或填写开工表。

每次开始或恢复开发，先由 agent 按 Git 规范检查并同步远端代码，再读取最新规范推进；成员无需手工执行拉取命令。

| 需要了解 | 阅读入口 |
| --- | --- |
| 项目目标、范围与验收要求 | [project.md](docx/project.md) |
| 数据流、模块与目录边界 | [architecture.md](docx/architecture.md) |
| A/B/C 分工、代码归属与交接 | [roles.md](docx/roles.md) |
| 字段、批次、质量与统计口径 | [data-contract.md](docx/data-contract.md) |
| 查询/推荐调用、HTTP 接口与错误 | [api-contract.md](docx/api-contract.md) |
| 环境、依赖、配置与运行方式 | [environment.md](docx/environment.md) |
| 分支、提交、PR 与冲突处理 | [git-workflow.md](docx/git-workflow.md) |
| 当前阶段、就绪任务、进度与验证证据 | [milestones.md](docx/milestones.md) |
| 已确认决定、提案、待定事项与批准依据 | [decisions.md](docx/decisions.md) |

项目阶段和可运行状态以里程碑中的实际记录为准；环境与启动入口查环境文档，并核对对应代码及验证证据。规范中的规划目录、命令和构造样例不表示系统已经实现或运行通过。

## 规范保护

**除 `docx/milestones.md` 按约定更新日常进度外，README、AGENTS、CLAUDE、`docx/` 规范及共享配置说明、Git 规则、PR 模板的修改、删除、重命名或移动，必须事先获得人工对具体变更的明确批准。** 具体执行与协作边界遵循 AGENTS.md，详细约定以对应专项文档为准。
