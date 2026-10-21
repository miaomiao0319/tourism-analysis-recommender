# 数据契约

- 文档状态：已验收基线；契约版本：`1.0`；实现与运行状态见 milestones.md。
- 主要读者：A、B、C 对应的开发 agent。
- 依据：[项目要求](project.md)、[系统架构](architecture.md)、[角色分工](roles.md)。

本文件规定跨模块共享的数据格式与含义。agent 应据此生成、校验、读取和交接数据，不要求成员本人填写字段表、手动清洗或逐条检查记录。字段名区分大小写，代码与交付文件使用下文的英文名称。

**修改、删除、重命名或移动本文件，必须事先获得人工对具体变更的明确批准。** 实际来源、批次记录和字典条目由 agent 按本契约维护，不需要每采集一个来源就修改规范；改变字段含义、统计口径或预算比较规则时，不能通过改数据文件绕过人工批准。

## 1. 约定范围与待定内容

本契约统一标准景点记录、来源证据、字典、批次、数据库结构和统计输出。HTTP 路径、请求参数、分页、推荐函数签名及接口响应封装见 `docx/api-contract.md`，软件版本和 HDFS 根路径配置见 `docx/environment.md`。

以下内容仍按既有决定保留：

- 具体主要与备用来源由 A 自主选择和验证。
- 价格覆盖率、实际采用的票种与适用条件、可比价格政策在实践中根据真实资料确定，不在这里虚构。
- 类型分类根据来源与实际数据建立字典，不提前要求固定的一组旅游类别。
- 推荐排序规则与权重尚未确定；本文件只提供一致的数据与价格资格判断。
- 全国为基础目标，全球可行时扩展；资料时间口径截至 `2026-10`，项目截止日期未定。

## 2. 交付文件与通用编码

| 计划位置 | 格式与作用 | 产出 agent |
| --- | --- | --- |
| `data/raw/<batch_id>/` | 原始内容及解析记录，保留证据，不作为直接计算输入。 | A |
| `data/processed/<batch_id>/attractions.csv` | 本批次唯一的标准景点快照。 | A |
| `data/metadata/<batch_id>/manifest.json` | 批次、输入文件摘要和清洗数量。 | A |
| `data/metadata/<batch_id>/sources.jsonl` | 来源登记。 | A |
| `data/metadata/<batch_id>/evidence.jsonl` | 单条来源观察及原始记录定位。 | A |
| `data/metadata/<batch_id>/dictionaries.json` | 地区、类型、等级体系与获批价格政策。 | A；相关 agent 提出需求 |
| `data/results/<batch_id>/<engine>/statistics.jsonl` | 统一格式的分析结果。 | 对应计算作业的 agent |
| `data/results/<batch_id>/<engine>/run.json` | 运行输入、输出与验证记录。 | 对应计算作业的 agent |

这些路径是交付约定，不代表文件已经生成。`engine` 只取 `mapreduce`、`spark_sql`。HDFS 保存相同批次的标准输入和各自输出，具体地址由环境方案提供。

通用规则：

- 文本采用 UTF-8、无 BOM、LF 换行。JSONL 每个非空物理行是一个完整 JSON 对象；JSON 使用 `null`，禁止 `NaN`、`Infinity` 和注释。SHA-256 统一交付为 64 位小写十六进制字符串。
- CSV 使用逗号分隔、双引号引用，字段中的双引号按 CSV 规则加倍；由 CSV 库读写，不能用 `split(',')` 解析。
- CSV 第一行且仅第一行是固定表头。标准字段中实际的换行、回车、制表符清理为空格，保证每条景点记录占一个物理行；原始文本保存在证据中。
- CSV 的空字段统一表示缺失值；不得用 `0`、`-1`、`未知`、`NULL`、`NaN` 等字符串代替缺失。必填字段不能为空。列表与对象不缺省，分别写 `[]`、`{}`，再交由 CSV 库转义。
- 数值按字段类型显式解析，不依赖类型猜测；标识符始终按字符串读取。Pandas、MapReduce、Spark、MySQL 对空值、JSON 单元格和金额采用同一含义。
- 消费标准输入时遇到格式或约束错误，应报告并停止该次计算或导入，交由 A 修复后发布新快照；不能静默丢行、填默认值后继续发布不同口径的结果。
- 金额最多两位小数，CSV/JSON 中以非负十进制定点字符串表示，例如 `"80.00"`；数据库使用 DECIMAL，不能经二进制浮点中转后参与预算边界比较。
- 超出当前精度、无法可靠解析的报价保留原文与原因，不截断、四舍五入或换汇来制造可比价格。需要扩展金额精度时提出契约变更。

## 3. 标准景点记录

CSV 表头顺序固定如下，新增列或改变顺序需要批准；JSON 或数据库映射按字段名读取。

```text
batch_id,attraction_id,name,country_code,province_key,province_name,city_key,city_name,grade_system,grade_status,grade_level,type_codes,price_form,price_min,price_max,currency,price_basis,price_policy_id,price_raw,source_refs,collected_at
```

| 字段 | 逻辑类型 / MySQL 类型 | 必填与含义 |
| --- | --- | --- |
| `batch_id` | 字符串 / VARCHAR(64) | 必填，与批次清单一致。 |
| `attraction_id` | 字符串 / VARCHAR(64) | 必填，稳定的景点实体标识，不能使用列表序号或运行时随机哈希。 |
| `name` | 字符串 / VARCHAR(512) | 必填，去首尾空白后的景点名称；不随意删除有效标点。 |
| `country_code` | 字符串 / CHAR(2) | 必填，明确识别的两位大写国家或地区代码，例如 `CN`；从来源范围或证据确认，不能一律填 CN。 |
| `province_key` | 字符串 / VARCHAR(64) | 可空，一级地区字典键；境外按其相应一级地区登记。 |
| `province_name` | 字符串 / VARCHAR(128) | 可空，与对应字典键的标签一致。 |
| `city_key` | 字符串 / VARCHAR(64) | 可空，城市字典键，在国家与地区范围中唯一。 |
| `city_name` | 字符串 / VARCHAR(128) | 可空，与对应字典键的标签一致。 |
| `grade_system` | 字符串 / VARCHAR(64) | 必填，已登记的等级体系；未知写 `UNKNOWN`。中国 A 级体系写 `CN_A`。 |
| `grade_status` | 字符串 / VARCHAR(16) | 必填，`rated`、`unrated`、`unknown`、`conflict` 之一。 |
| `grade_level` | 字符串 / VARCHAR(64) | 已知评级时必填；其他状态为空，不能将缺失等级填成 0A。 |
| `type_codes` | 字符串列表 / JSON | 必填，可为 `[]`；元素去重、排序，均在类型字典中登记。CSV 中存 JSON 数组文本。 |
| `price_form` | 字符串 / VARCHAR(16) | 必填，`unknown`、`free`、`exact`、`range`、`from`、`conflict` 之一。 |
| `price_min` | 金额 / DECIMAL(12,2) | 可空，来源报价的数值下界；不等于默认可用于推荐的价格。 |
| `price_max` | 金额 / DECIMAL(12,2) | 可空，来源报价的数值上界；约束见价格规则。 |
| `currency` | 字符串 / CHAR(3) | 可空，明确的报价币种，例如 `CNY`；未知时不凭符号或地名随意猜测。 |
| `price_basis` | 字符串 / TEXT | 可空，来源实际说明的票种、适用对象或条件；未说明则为空。 |
| `price_policy_id` | 字符串 / VARCHAR(64) | 可空，只有符合已批准、已登记的比较政策时填写；为空则不参与预算比较。 |
| `price_raw` | 字符串 / TEXT | 可空，来源价格文本的单行标准化版本；完整原文仍保存在原始证据。 |
| `source_refs` | 对象 / JSON | 必填，按信息组引用来源观察，见来源规则；CSV 中存 JSON 对象文本。 |
| `collected_at` | UTC 时间 / DATETIME(6) | 必填，已采用来源观察的最晚采集时间；文件中用带 `Z` 的 ISO 8601 时间表示。 |

`batch_id`、`attraction_id`、`source_id`、`source_ref`、`price_policy_id` 使用 1—64 位 ASCII 字母、数字、下划线或连字符，不包含路径分隔符。地区键允许额外使用冒号；不得把显示名称当作唯一键。

`province_key` 与 `province_name` 同时有值或同时为空，城市键与名称同理。城市字典需能确定国家和父地区；无法判断城市但能判断省份的记录保留省份，城市留空，不能随意补成省会。

## 4. 主键、实体去重与冲突

- 一个批次中每个 `attraction_id` 只出现一次，数据库主键为 `(batch_id, attraction_id)`。
- 同一景点在不同批次中保持同一实体标识；名称修正、补充来源或票价变化不自动生成新实体。A 保存可重用的来源条目到实体标识映射及合并依据。
- 同来源稳定条目标识优先用于识别重复；跨来源同名与相同地区只能产生候选，不能单凭名称合并。需结合地址、坐标、官方标识、明确对应关系等实际证据确认。
- 景区内部景点与整个景区、同名但不同地点的景点不能未经判断合并。不能确认时保留独立记录与疑似重复说明，不要求人逐条人工清洗，也不伪称已经完全消除重复。
- 多来源补充字段时保留各自证据。等级优先采用可核实的等级发布资料；不确定或存在无法解释的冲突时标为 `conflict`，保留冲突记录，不取最高等级或最低报价掩盖问题。
- 缺少可识别实体、有效名称或国家信息的观察不能直接进入标准快照，保留排除记录与原因；缺少城市、价格或类型本身不构成整条删除的理由。

## 5. 来源、地区与类型字典

### 5.1 来源登记和观察

`sources.jsonl` 每行登记一个来源，至少包含 `source_id`、`name`、`base_url`、`coverage`、`collection_basis`、`redistribution_status`、`notes`。redistribution_status 只取 `allowed`、`restricted`、`unknown`，表达已核实的再分发情况；不是 agent 自行授予许可。缺少依据时如实记录，不能因网页公开就填 allowed。

`evidence.jsonl` 每行至少包含：

| 字段 | 约束 |
| --- | --- |
| `source_ref` | 批次内唯一的观察标识。 |
| `source_id`、`source_item_id` | 来源登记键；来源有稳定条目 ID 时保留，否则后者为 null。 |
| `source_url` | 实际来源页面或数据地址，不使用示例网址冒充。 |
| `collected_at` | 实际采集时间，带 Z 的 UTC 时间。 |
| `source_date` | 资料日期，可为年、年月、年月日或 null，不补造精度。 |
| `source_date_kind` | `published`、`updated`、`unknown` 之一；不能把网页访问日期当作发布日期。 |
| `raw_ref` | 本地原始文件相对路径与条目定位，不含密钥或成员电脑的绝对路径。 |

`source_refs` 的键限定为 `name`、`location`、`grade`、`types`、`price`，值为非空 `source_ref` 数组；名称和位置必须有引用，其他组在采用相应信息或保留冲突证据时引用。所有引用必须在本批次的 evidence 中解析，不能只保留一个首页 URL 代替逐条依据。

资料日期未知可保留并说明，但不能自动认定在 `2026-10` 时点有效。后期网页内容不能直接证明历史票价或历史等级；`collected_at` 与资料时间分别保存，不能互相代替。

### 5.2 字典格式与维护

`dictionaries.json` 包含四个数组：`regions`、`types`、`grade_systems`、`price_policies`。字典随批次保存，消费者按字典读取标签，不在各自代码中另写一份相互冲突的映射。

| 数组 | 每项至少包含 | 规则 |
| --- | --- | --- |
| `regions` | `key`、`name`、`country_code`、`level`、`parent_key` | level 为 province 或 city；parent_key 可空，已填写时可解析。地区键不是地图底图代码。 |
| `types` | `code`、`label`、`definition`、`method`、`basis` | method 为 source 或 rule；记录来源分类或整理规则，不把低置信猜测当作来源事实。 |
| `grade_systems` | `code`、`label`、`levels`、`basis` | CN_A 的 levels 为 1A、2A、3A、4A、5A；其他体系登记后单列，不进行跨体系等级换算。 |
| `price_policies` | `id`、`currency`、`ticket_basis`、`eligibility_rule`、`approval_ref` | 真实政策需有可追溯的人工批准依据，不能仅填写 approval_ref 就视为已批准。 |

地区项可包含 `map_code`、`map_resource`，用于指向实际采用的底图标识与版本；尚未匹配时为 null。匹配失败数量进入质量说明，不能因为地图不认识某地区就删除景点。

A 可以根据真实数据维护地区、类型和等级体系的条目，保留依据并生成新快照；增加普通字典条目不要求改写本文件。改变分类方法导致既有含义变化时需说明影响；改变本契约或产品比较口径仍须人工批准。B/C 读取字典，不要求用户逐个提供类别。

`type_codes=[]` 代表类型未知，不等于“其他类型”。来源明确给出的“其他”可以登记为一个有定义的类别。多标签景点在类型统计中可分别计数，因此类型分组数量之和可能大于景点总数，图表需要说明。

## 6. 等级与价格规则

### 6.1 等级

- `rated`：体系在字典中登记，`grade_level` 属于其 levels；CN_A 仅接受 1A—5A。
- `unrated`：有明确依据表明在所注明体系中未评级，grade_level 为空；未出现在某份名录中本身不够证明未评级。
- `unknown`：没有足够依据识别，grade_system 为 UNKNOWN，grade_level 为空。
- `conflict`：无法消解的等级冲突，grade_system 为 UNKNOWN，grade_level 为空，原始候选值保留在证据或质量记录中。

未知、明确未评级与冲突必须分组保留，不能合并成 0A。境外等级按登记体系单列，不直接映射为中国 A 级。

### 6.2 价格数值与原文

| `price_form` | `price_min` / `price_max` | 含义 |
| --- | --- | --- |
| `unknown` | 均为空 | 没有可靠可解析报价；不代表免费。 |
| `free` | 均为 0.00 | 来源明确免费，不因字段为空或促销文案推断。 |
| `exact` | 相等且大于 0 | 来源明确的一个报价，是否可比较另看政策。 |
| `range` | 均有值且 0 ≤ min < max | 来源价格区间，不默认取最低值、最高值或均值作为推荐价格。 |
| `from` | min ≥ 0，max 为空 | “起价”，不保证实际门票费用等于下界。 |
| `conflict` | 均为空 | 无法消解的报价冲突，候选报价在证据中保留。 |

币种和票种无法确认时仍可保留来源报价与原文，但 `price_policy_id` 必须为空。免费报价没有注明币种时，可在有依据的已批准政策下记录该政策币种；不能为其他报价随意推断币种。

### 6.3 可比价格与预算资格

真实票种、适用对象、生效条件等尚未决定，因此初始真实批次允许 `price_policies=[]`，所有 `price_policy_id` 为空。A/B 可以先实现缺失处理和构造测试，但不能宣称真实价格比较与预算推荐已经验收。

实践中由 agent 从真实样本提出比较方案，经人工确认后落实政策；若涉及改变本契约的规则，先批准修改。不得将“成人票”“旺季票”等当前未定条件擅自固定为所有来源的统一口径。

V1 的可比记录需同时满足：

1. `price_policy_id` 在本批次字典中存在，其真实政策已经批准。
2. 报价的币种、票种和适用条件符合该政策，有相应来源证据。
3. price_form 为 free 或 exact，min 与 max 相等，金额合法。

预算匹配还需政策与请求所用币种一致，且该金额小于或等于预算上限。预算为零可匹配确认免费的记录；未知、起价、区间、冲突或未绑定政策的报价不承诺满足预算。不自动换汇，也不将某币种金额直接与另一币种预算比较。

价格统计使用同样的政策资格和金额，按币种、政策分别计算，不能在推荐时使用一套价格、图表中使用另一套价格。原始报价存在率可以单独报告，但不能冒充可比价格覆盖率。

## 7. 批次清单与质量对账

`manifest.json` 至少包含以下内容，由 A 从实际文件和清洗过程生成，不要求人手工填写：

| 字段 | 约束 |
| --- | --- |
| `contract_version`、`batch_id` | 分别为字符串 "1.0" 和本批次标识。 |
| `data_kind` | real 或 test；构造样本只能为 test。 |
| `data_cutoff_month`、`created_at` | 分别为 2026-10 和实际批次生成 UTC 时间。 |
| `standard_file`、`standard_sha256` | 标准 CSV 的项目内相对路径与完整字节的 SHA-256。 |
| `dictionaries_sha256` | 本批次 dictionaries.json 完整字节的 SHA-256。 |
| `raw_count`、`excluded_count`、`accepted_source_count`、`merged_extra_count`、`standard_count` | 非负整数，单位为单个景点的来源观察或标准实体，不能把网页请求数混入。 |
| `quality` | 缺失、冲突、疑似重复、地区覆盖及地图无法匹配等质量数量与说明。 |

数量关系：`raw_count = excluded_count + accepted_source_count`；每条接受的来源观察归属一个标准实体，`standard_count = accepted_source_count - merged_extra_count`。merged_extra_count 表示同实体合并掉的额外来源观察，包括信息互补的来源，不只指完全相同的重复行。不能通过丢弃未计数记录凑齐关系。

`standard_count` 等于 CSV 数据行数及批次内不同 attraction_id 数量；零条有效景点不能标记为可用演示数据。未知城市、未知类型与未知价格计入各自质量数量，不从总量中消失。字典、来源和证据的条目 ID 必须唯一，所有引用必须可解析。

真实来源的小样本可以标为 real；包含人工构造或人为改值记录的测试批次必须标为 test，不混入 real 快照。测试政策不能用来给真实数据赋予比较资格。

标准 CSV 与字典发布给计算模块后保持固定；修改清洗、来源选择或字典含义产生新快照与新批次。身份映射需要一并保留，保证重新处理后实体标识稳定。

HDFS 输入必须对应 manifest 记录的标准文件。核对实际文件字节摘要，不能把其他算法或其他文件的校验值当作该 SHA-256。两个框架的 run.json 都记录实际输入摘要。

## 8. MapReduce 与 Spark SQL 的统一统计输出

### 8.1 JSONL 记录封装

每条 `statistics.jsonl` 记录固定包含：

| 字段 | 约束 |
| --- | --- |
| `batch_id`、`engine` | 对应实际输入批次与 mapreduce / spark_sql。 |
| `metric` | 下表规定的指标名。 |
| `dimensions` | 分组对象；只包含该指标需要的维度，键名固定，不以中文标签代替键。 |
| `status` | ok、no_data、pending_policy 之一。 |
| `value` | 指标结果对象；pending_policy 时为 null，不能伪造统计。 |

| metric | dimensions 与 value |
| --- | --- |
| `attraction_count` | scope 为 all、province、city、grade、city_grade 或 type；value 为 `{ "count": 非负整数 }`。 |
| `price_summary` | scope 为 all、city 或 grade，并带 currency、price_policy_id；value 含 candidate_count、valid_count、coverage、min、max、mean。 |
| `price_histogram` | 与价格汇总相同的政策及分组；value 含 valid_count 和 bins，每个箱含 lower、upper、count。 |
| `data_quality` | dimensions 为 `{ "scope": "all" }`；value 含 standard_count、missing_city_count、unknown_grade_count、conflicting_grade_count、missing_type_count、unknown_price_count、conflicting_price_count。 |

分组维度规则：

- all 仅有 scope；province 增加 country_code、province_key；city 增加 country_code、city_key。
- grade 增加 country_code、grade_system、grade_status、grade_level；city_grade 在此基础上增加 city_key；type 增加 country_code、type_code。
- 地区缺失时对应 key 使用 JSON null，保留未知分组；等级 level 为空时同理。类型列表为空时，type_code 使用 null 表示未知组。
- 标签从字典取得；相同中文名称但不同城市键不能合并。等级按体系和国家分别统计。
- 价格维度中的 scope 为 all、city、grade 时，沿用相应分组维度，再添加币种和政策；未确定真实政策时可输出 `{ "scope": "all", "currency": null, "price_policy_id": null }`、status 为 pending_policy、value 为 null。

data_quality 的 missing_city_count 按 city_key 为空计数；unknown_grade_count 和 conflicting_grade_count 分别按 grade_status 为 unknown 和 conflict 计数；missing_type_count 按 type_codes 为空数组计数；unknown_price_count 和 conflicting_price_count 分别按 price_form 为 unknown 和 conflict 计数。各指标可能重叠，不能把缺失数量相加当作无效实体总数。

MapReduce 至少产生城市与等级的 attraction_count。Spark SQL 至少产生总体、地区、等级、城市等级构成的数量统计、数据质量与需求规定的价格分析；类型统计在类型数据可用时提供。MapReduce 原生输出可以保留，但交付 agent 需转换为本格式，转换阶段不改变统计数值。

### 8.2 数值和空结果

- 数量使用整数，不以字符串或浮点数交付。数量为零是有效计数，不等于作业失败。
- price_summary 的 candidate_count 是该地区或等级分组内全部景点数；valid_count 是符合所选政策的可比记录数。
- coverage 为 valid_count / candidate_count，按四舍五入保留六位小数的字符串；分母为零时为 null。价格覆盖率不设提前通过门槛。
- min、max、mean 使用两位小数金额字符串；均值使用十进制计算，最终按 ROUND_HALF_UP 保留两位。valid_count 为零时 status 为 no_data，三项金额为 null，不填零。
- 直方图边界同为金额字符串，各箱按 `[lower, upper)` 计数，最后一个 upper 可为 null 表示无上界；从 0 起、连续递增、不重叠。分箱由 B 根据数据选择并写入结果，不要求用户手工指定。
- 直方图只计同一政策的可比价格，各箱 count 之和等于 valid_count。没有可比记录时 bins 为 []、status 为 no_data；政策未定时为 pending_policy、value 为 null。
- 所有普通统计成功时 status 为 ok。运行失败不产生一条冒充成功的零计数，错误进入运行记录。

### 8.3 对账与展示来源

同一批次、相同维度下，MapReduce 与 Spark SQL 的城市及等级数量必须一致。包含未知组后的城市计数与等级计数分别可汇总回 standard_count；按国家分组时先合计所有国家，不能漏掉境外记录。类型多标签统计不适用此总和等式。

V1 数量图表发布 Spark SQL 结果，MapReduce 同指标保留为对账证据，两者不得相加。不能用某个框架的结果文件冒充另一框架的运行记录。

run.json 至少记录 batch_id、engine、contract_version、input_sha256、实际输入输出位置、执行入口或命令、起止时间、运行结果和对账说明。未执行或未通过的检查如实标记，不能预填成功。

## 9. MySQL 逻辑结构与导入

数据库实际名称由环境方案确定，A 实现以下逻辑表及初始化、导入过程。本文件规定含义、类型与唯一性，不要求其他 agent 从表结构自行猜接口。

| 表 | 主键与主要内容 |
| --- | --- |
| `dataset_batches` | batch_id VARCHAR(64) 主键；contract_version VARCHAR(16)、standard_sha256 CHAR(64)；manifest_json、dictionaries_json、sources_json 使用 JSON，后者为来源登记数组；state VARCHAR(16)，为 loading、ready、failed。 |
| `attractions` | 主键 (batch_id, attraction_id)，包含第 3 节全部标准字段，类型按该表映射。 |
| `source_records` | 主键 (batch_id, source_ref)，两者均为 VARCHAR(64)；包含 source_id VARCHAR(64)、source_item_id TEXT 可空、source_url TEXT、collected_at DATETIME(6)、source_date VARCHAR(10) 可空、source_date_kind VARCHAR(16)、raw_ref TEXT；其余观察说明可放入 payload_json JSON。 |
| `analysis_results` | 主键 (batch_id, engine, metric, dimension_key)，对应 VARCHAR(64)、VARCHAR(16)、VARCHAR(32)、CHAR(64)；保存 dimensions_json JSON、status VARCHAR(16)、value_json JSON，分别对应统计封装中的 dimensions、status、value。pending_policy 的 value_json 存 SQL NULL。 |

dimension_key 由导入程序统一生成：对 dimensions 按键排序，使用无多余空格、ASCII 转义的 JSON 序列化，再对 UTF-8 字节计算 SHA-256。维度值只用字符串或 null，避免不同语言的浮点序列化差异。计算产出 agent 不需要另造一套哈希规则。

导入要求：

- batch_id、来源引用、字典引用均在导入前验证；JSON 引用关系不因使用 JSON 列就省略检查。
- 标识符与字典键按精确字符串匹配，数据库键列使用与此一致的比较规则，不能因默认大小写不敏感而吞并两个不同标识；显示名称的搜索规则与标识符比较分开处理。
- SQL 时间字段保存 UTC，文件中的 Z 在解析时明确处理，不能按成员电脑时区静默转换；source_date 保留原有日期精度。
- CSV 金额直接解析为十进制，数组和对象按 JSON 解析；不得把空字段导入成字符串 NULL，或让 NaN 落库。
- 对同一批次重复导入应幂等：相同输入不增加行数，内容变化不得悄悄覆盖同一已发布批次，应按新批次处理。
- 标准景点与统计分别检查唯一性；同维度重复统计应报错，不按后读覆盖或再次累加。
- 只有景点、字典、证据与所需统计导入并校验完成，批次才置为 ready。新批次导入失败置为 failed，不破坏已有 ready 批次；更新和恢复遵循架构中的离线流程。
- 同库可保留历史 ready 批次，但服务从统一配置中选定唯一批次，所有查询明确限定该 batch_id，并先确认其状态为 ready。不能由不同接口各自猜测“最新批次”；配置名称与切换步骤见环境文档。
- 为当前批次查询、地区筛选与统计读取设置必要索引，由 A 根据确定的查询实现；不额外引入一套数据库或未经验证的版本要求。

## 10. agent 可复核的构造样例

下表是 **test 批次中的记录摘要，不是完整标准 CSV，也不是真实采集数据**。真实样本仍由 A 从实际来源提供。test_policy 是构造测试政策，只能用于 data_kind=test，不能当作已获批准的真实比较口径。

| 标识 | 城市 | 等级状态 | 价格形式与原币金额 | 测试政策资格 |
| --- | --- | --- | --- | --- |
| T1 | 北京 | CN_A / rated / 5A | free，0.00 / 0.00 CNY | test_policy |
| T2 | 北京 | CN_A / rated / 4A | exact，80.00 / 80.00 CNY | test_policy |
| T3 | 杭州 | CN_A / unrated / null | unknown，null / null | null |
| T4 | 杭州 | UNKNOWN / unknown / null | range，60.00 / 100.00 CNY | null |
| T5 | 城市未知 | UNKNOWN / unknown / null | from，50.00 / null CNY | null |
| T6 | 北京 | UNKNOWN / conflict / null | conflict，null / null | null |

这六条标准实体均属于 CN，地区键由测试字典提供。agent 将摘要补成完整测试记录，并自动验证：

- standard_count=6；北京=3、杭州=2、城市未知=1，两个框架结果一致。
- 等级分组中 5A=1、4A=1、unrated=1、unknown=2、conflict=1，总和为 6。
- test_policy 的 valid_count=2，candidate_count=6，coverage="0.333333"，min="0.00"、max="80.00"、mean="40.00"。
- CNY 预算 80.00 时，价格资格只允许 T1/T2；预算 79.99 或 0.00 时只允许 T1。这里只验证资格，不规定推荐排序或忽略用户的其他约束。
- T3 不因缺失价格成为免费，T4/T5 不因下界低于预算成为保证符合预算的记录，T6 不从冲突报价中选最低值。
- 为同一实体再增加一条确认重复的来源观察，合并后标准实体数量仍为 6，并保留新增来源依据与数量对账。
- 补充检查同名异地实体、CSV 字段含逗号和双引号、JSON 单元格、重复导入、错误批次和无法解析的引用。

这些检查由 agent 执行并如实记录。规范约定和构造样例本身不证明真实数据、数据库、计算作业或价格政策已经验证，实际状态查里程碑及运行证据。

## 11. 变更边界

普通来源新增、字典条目补充和新批次产出，在本契约允许范围内由对应 agent 自主完成；已发布快照保持固定。实际发现价格、类型或地区资料不足时，先保留未知和质量说明，继续可独立开展的任务，不要求用户手工补数据。

需要新增字段、修改空值或键规则、调整金额精度、改变预算资格、统计定义或交付格式时，agent 应给出具体差异、受影响模块和迁移方式，获得人工明确批准后再更新契约与实现。不能为了当前代码通过而放宽验证，或以配置文件替代规范修改审批。
