# 模块调用与 HTTP 接口契约

- 文档状态：已验收基线；API 版本：`v1`；实现与运行状态见 milestones.md。
- 主要读者：负责查询、推荐、接口与网页接入的 A/B/C agent。
- 依据：[项目要求](project.md)、[系统架构](architecture.md)、[角色分工](roles.md)、[数据契约](data-contract.md)。

agent 按本文件实现、调用和验证接口，不要求成员本人编写请求、填写接口表或手动搬运模块信息。用户只指定角色时，agent 自行找到对应职责与接入要求。

**修改、删除、重命名或移动本文件，必须事先获得人工对具体变更的明确批准。** 路由、字段、参数含义、错误码及模块调用约定是共享契约，不能由某个 agent 为适应自己的实现单方面更改。以下路径和函数是待实施约定，不表示已有服务可调用。

## 1. 共同边界与响应封装

- 前缀为 `/api/v1`，主机、端口、前端 API 地址与同源接入要求见环境文档。
- 最小接口只读取已准备的数据并计算当次偏好推荐，不提供采集启动、SQL 执行、数据修改、文件上传、登录或用户行为记录接口。
- C 组织 Flask 路由与响应，A 提供数据库查询函数，B 提供推荐函数。请求中不启动 HDFS 操作、MapReduce 或 Spark 作业。
- 请求与响应使用 UTF-8 JSON；金额保持十进制字符串，数组、对象、null 与 UTC 时间遵守数据契约，不把数据库 Decimal、时间对象或 JSON 文本字符串直接泄露为不一致格式。

所有 API 响应包含 `data`、`meta`、`error` 三个顶层字段。成功时 error 为 null；失败时 data 为 null，不能用 HTTP 200 包装业务错误。

| 字段 | 约定 |
| --- | --- |
| `data` | 本接口定义的结果对象；错误时为 null。 |
| `meta` | 固定包含 batch_id、data_kind、contract_version，均为字符串或 null。业务成功时对应实际服务批次，contract_version 为数据契约的 "1.0"。 |
| `error` | 成功时为 null；错误时包含 code、message、details。code 是下文稳定标识，message 为可展示的中文说明，details 为对象。 |

尚未加载有效批次时，meta 三项均为 null；已加载当前批次时，即使请求失败，也返回实际当前批次的 meta，不冒充请求中的旧批次。`v1` 是 API 路径版本，不等于数据契约版本。

以下是构造的错误示例，不是当前系统状态：

```json
{
  "data": null,
  "meta": {
    "batch_id": "test_no_price_001",
    "data_kind": "test",
    "contract_version": "1.0"
  },
  "error": {
    "code": "PRICE_POLICY_NOT_READY",
    "message": "当前批次尚未确定可用于预算比较的价格政策。",
    "details": {"field": "budget"}
  }
}
```

## 2. 接口清单与批次规则

| 方法 | 路径 | 作用 | 需要请求 batch_id |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | 确认 Flask 进程能响应。 | 否 |
| GET | `/api/v1/dataset` | 获取当前数据批次、字典、来源说明和可用统计。 | 否 |
| GET | `/api/v1/attractions` | 搜索、筛选和分页查询景点。 | 是，查询参数 |
| GET | `/api/v1/attractions/{attraction_id}` | 获取景点与公开来源证据。 | 是，查询参数 |
| GET | `/api/v1/statistics` | 分页读取已产出的统计分组。 | 是，查询参数 |
| POST | `/api/v1/recommendations` | 根据当次偏好返回景点及理由。 | 是，JSON 字段 |

服务使用环境配置选定的唯一 ready 批次。客户端先请求 dataset，C 的前端代码自动保存其 meta.batch_id，后续业务请求携带该值，不要求用户手动输入。

请求 batch_id 必须等于当前选定批次，不能借此查询任意历史数据。合法格式但不同批次返回 HTTP 409 / BATCH_MISMATCH；客户端清除旧批次相关结果，重新获取 dataset，再以同一新批次重新加载所需接口，不能混合显示不同批次。

health 不访问数据库，成功时 data 为 `{ "service_status": "ok" }`，meta 三项均为 null；这只证明进程可响应，不证明数据、推荐或计算作业已就绪。其余接口需要可访问且契约有效的 ready 数据，否则按错误表返回，不返回假数据。

## 3. 参数、校验与分页

- GET 只接受对应接口列出的查询参数；POST 只接受列出的 JSON 字段。未知字段、重复查询参数、重复 JSON 对象键均报错，不静默采用其中一个值。
- POST 的 Content-Type 必须为 application/json，JSON 顶层必须为对象。布尔值不能当作整数，字符串 "null" 不能当作真正的 null。
- batch_id、attraction_id、price_policy_id 等标识格式沿用数据契约；地区键允许冒号。地区、类型、等级与价格政策需能在当前批次解析，不根据显示标签猜键。
- optional GET 参数缺省即不施加该条件；不使用空字符串或字面量 null 表示未知分组。q 例外，去首尾空白后为空视为未搜索。POST 的可选字段可省略或按其规定使用 null / []。
- 金额输入必须是非负十进制字符串，允许 "80"、"80.0"、"80.00"，格式为 ASCII 数字及可选的一到两位小数，不带空白、正负号、千分隔符或指数，数值不超出 DECIMAL(12,2)。服务以 Decimal 校验并标准化为两位小数字符串；不接受 JSON 数值、NaN 或悄悄舍入。预算 "0.00" 是有效条件，不能因值为零而跳过。
- 币种使用三位大写代码，国家或地区使用两位大写代码；相互矛盾的国家、省份、城市条件返回 INVALID_FILTER。
- 先做语法、允许字段与类型校验，再加载当前批次、检查 batch_id，最后按字典检查业务条件并执行。不存在的资源与依赖失败不能混为一类。

列表和统计共用分页格式：page 默认 1，为 1—2147483647 的整数；page_size 默认 20，为 1—100 的整数。GET 中只接受十进制整数字符串，不接受小数、布尔或指数形式。

分页 data 固定包含 `items`、`page`、`page_size`、`total`、`total_pages`。total 是本次筛选后的完整结果数，total_pages 为向上取整；total=0 时 total_pages=0、items=[]。超出最后一页返回 200 和空 items，不能伪造 total 或自动切回最后一页。

查询与统计有稳定的次级排序，不能因翻页出现随机重复。推荐使用 limit，不套用分页；limit 默认 10，范围 1—50。

## 4. 当前数据与字典：GET /dataset

无查询参数。成功返回的 data 为 DatasetInfo：

| 字段 | 来源与含义 |
| --- | --- |
| `data_cutoff_month`、`created_at` | manifest 中的数据截止月与批次生成 UTC 时间；截止月为 "2026-10"，不代表项目截止日期。 |
| `standard_count` | 当前标准景点数量，与实际服务批次一致。 |
| `countries` | 本批次景点中不同 country_code 的排序字符串数组，例如 ["CN"]。 |
| `quality` | manifest 中可公开的质量数量、覆盖与说明，不包含内部文件路径或私有内容。 |
| `sources` | 来源登记的 source_id、name、base_url、coverage、collection_basis、redistribution_status、notes。 |
| `dictionaries` | regions、types、grade_systems、price_policies 四个数组，使用数据契约的名称；缺少可选 map_code/map_resource 时返回 null。 |
| `available_statistics` | 当前 spark_sql 输出中实际存在的 metric、scope、currency、price_policy_id 组合数组；非价格指标的后两项为 null。不是尚未执行任务的愿望清单。 |

对外 price_policies 仅返回 id、currency、ticket_basis、eligibility_rule，不公开内部 approval_ref。其他数据按公开字段组织，不直接把整个数据库 manifest、原始内容或内部运行记录输出。

前端从字典生成筛选和兴趣选项，不硬编码一套旅游类型；价格政策数组为空时展示“价格比较口径暂未确定”。data_kind=test 时，页面显著标为测试数据，不能冒充真实采集成果。

## 5. 景点查询

### 5.1 GET /attractions

| 查询参数 | 约束与默认行为 |
| --- | --- |
| `batch_id` | 必填，按批次规则校验。 |
| `q` | 可选，去首尾空白，最长 100 个字符，按景点名称的普通子串匹配；% 和 _ 等输入作为文字，不当作 SQL 通配语法。 |
| `country_code`、`province_key`、`city_key` | 可选，按当前国家集合和地区字典精确过滤；同时指定时须属于一致地区。 |
| `grade_system`、`grade_status`、`grade_level` | 可选，按下述等级组合规则过滤。 |
| `type_code` | 可选，当前类型字典中的一个 code；景点 type_codes 包含该项即匹配。 |
| `max_price` | 可选，单个景点门票金额上限，包含等于上限；不能不带币种与政策就比较。 |
| `currency`、`price_policy_id` | 指定 max_price 或价格排序时两项必填；两者须匹配当前政策。未进行价格过滤或排序时不单独传入。 |
| `sort` | 默认 name_asc；允许 name_asc、price_asc、price_desc。 |
| `page`、`page_size` | 使用共同分页规则。 |

等级组合：grade_system 非保留值时应已登记；UNKNOWN 即使字典未列出也是合法保留值。grade_status 仅取数据契约的四个值。传 grade_level 时必须有明确且非 UNKNOWN 的体系，level 在其字典中；未传 status 时规范化为 rated，传入非 rated 则报错。unknown/conflict 不能与已知体系或非空 level 同时使用，不能把 0A 当合法等级。

max_price 和价格排序只对符合数据契约中政策资格的 free/exact 记录生效；policy、币种或适用条件不满足的记录不能参与比较。name_asc 无价格条件时保留未知价格记录，不能为了列表整齐将其删除。

name_asc 按后端统一的名称比较规则升序；价格排序按 Decimal 金额升降序；同值时均以 attraction_id 升序稳定排序。客户端不在当前页上另做全量价格排序。

返回分页对象，items 每项为 Attraction：**完整保留数据契约第 3 节的 21 个字段**，含 null，金额为字符串，type_codes 为数组，source_refs 为对象。不能私自改名为景点名称、price 或 location 等另一套字段。

### 5.2 GET /attractions/{attraction_id}

只接受 batch_id 查询参数。成功 data 固定为 `{ "attraction": Attraction, "evidence": EvidencePublic[] }`。

evidence 为 attraction.source_refs 实际引用的观察，去重后按 source_ref 排序，每项包含 source_ref、source_id、source_url、collected_at、source_date、source_date_kind。原始定位 raw_ref、数据库路径和密钥不对外返回。

合法标识但当前批次中不存在该景点时，返回 404 / NOT_FOUND；批次冲突先返回 BATCH_MISMATCH，不查询别的历史批次来凑结果。

## 6. 统计读取：GET /statistics

读取已导入的 spark_sql 统计，返回共同分页对象，items 直接使用数据契约中 `batch_id/engine/metric/dimensions/status/value` 的六字段封装。total 是匹配的统计分组记录数，不是景点数量。数据状态 no_data 或 pending_policy 原样保留，不变成数值零，也不在路由中重新运行分析。

参数包括 batch_id、metric、scope、该 scope 允许的分组过滤字段、currency、price_policy_id、sort、page、page_size。metric 必填，scope 默认 all；其他字段须符合下表，不能用任意筛选组合要求后端即时聚合。

| metric / scope | 可选的分组过滤字段 |
| --- | --- |
| attraction_count / all | 无。 |
| attraction_count / province | country_code、province_key。 |
| attraction_count / city | country_code、city_key。 |
| attraction_count / grade | country_code、grade_system、grade_status、grade_level。 |
| attraction_count / city_grade | country_code、city_key、grade_system、grade_status、grade_level。 |
| attraction_count / type | country_code、type_code。 |
| price_summary 或 price_histogram / all | 无；另按价格上下文规则处理币种与政策。 |
| price_summary 或 price_histogram / city | country_code、city_key；另带价格上下文。 |
| price_summary 或 price_histogram / grade | country_code、grade_system、grade_status、grade_level；另带价格上下文。 |
| data_quality / all | 无。 |

这里只筛选现成的统计分组，不对其再组合计算。需要某个城市的等级构成应使用 city_grade，不能给 grade 偷加 city_key。不能向 all 添加 country_code 后仍返回全数据总数冒充该国总数。

sort 默认 key_asc，按数据契约的 dimension_key 升序；attraction_count 还支持 count_desc，按 count 降序、dimension_key 升序。其他 metric 不接受 count_desc。HTTP 不开放 engine 参数覆盖图表来源，MapReduce 结果保留作对账证据。

价格上下文与可用性：

- 有政策时，价格查询必须同时指定匹配的 currency、price_policy_id，不擅自默认某个票种或币种。
- 政策数组为空时，价格 scope=all 且未传币种和政策的请求，可读取已有 pending_policy 记录，成功返回 200；请求预算筛选或特定价格上下文则返回 PRICE_POLICY_NOT_READY。
- 先确认当前批次确实已产出所请求的 metric/scope，以及价格请求对应的政策上下文；未产出返回 409 / STATISTIC_NOT_AVAILABLE，不当作统计为零。
- 该上下文已有统计，但分组过滤没有匹配项时，返回 200、total=0、items=[]；已有 no_data 分组则返回原记录。
- 所有合法未知分组都保留 null 维度。前端显示未知标签，不能丢弃它们后仍宣称计数覆盖全部数据。

地图需加载所选统计上下文的全部分页，再展示完整覆盖；城市 Top N 使用 count_desc 和对应 page_size，并标明 Top N。不能只取第一页就宣称全部景点分布，也不能把城市数量榜称作游客热度榜。

## 7. 偏好推荐：POST /recommendations

| JSON 字段 | 约束与默认值 |
| --- | --- |
| `batch_id` | 必填。 |
| `country_code`、`province_key`、`city_key` | 可选字符串或 null，缺省为 null；遵循同一地区一致性规则。 |
| `type_codes` | 可选字符串数组，缺省为 []，最多 10 项；按字典检查，去重排序后使用。 |
| `budget` | 缺省或 null 表示不施加预算条件；有值时为只含 amount、currency、price_policy_id 的对象，三项均必填。 |
| `limit` | 整数，默认 10，范围 1—50。 |

至少有一项明确的地区、非空兴趣或预算偏好；全部为空返回 400 / EMPTY_PREFERENCES。类型列表使用“至少匹配一项”的语义；地区与预算等不同条件之间同时满足，不在无结果时静默放宽。

budget.amount 是单个景点门票预算上限。无可用政策时返回 409 / PRICE_POLICY_NOT_READY；不能自动忽略用户预算，前端可解释原因并由用户自行改选无预算条件，服务端不替用户改偏好。

推荐 data 固定包含：

| 字段 | 含义 |
| --- | --- |
| `items` | 按实际推荐规则排序的数组；每项仅含 attraction、reasons，前者为完整 Attraction，后者为非空说明字符串数组。 |
| `candidate_count` | 评估完整候选范围、满足所有硬条件后、截取 limit 之前的数量。 |
| `returned_count`、`limit` | 分别等于 items 长度和规范化后的请求 limit。items 长度应为 min(candidate_count, limit)。 |
| `rule_version` | B 实际实现的规则版本标识；不能把文档示例值当作生产默认值。 |
| `preferences` | 规范化后的 country_code、province_key、city_key、type_codes、budget；未选条件为 null 或 []，金额为两位字符串。 |
| `empty_reason` | 有结果时 null；没有满足条件的候选时为 NO_MATCHING_CANDIDATES。 |

无匹配是 200、items=[]、candidate_count=0，不是算法异常。算法未实现或未接入时返回 RECOMMENDER_UNAVAILABLE，不能随机填结果或以空列表假装推荐成功。

推荐不只读取当前列表页；所有参与数据必须属于同一批次。reasons 对应真实偏好与数据，未设置预算时不声称预算匹配，未知价格不声称免费；不返回虚构准确率。最终排序与权重仍由 B 根据实际数据实现和说明，本文件不预填算法权重。

### 7.1 构造的请求与响应样例

以下仅描述一个含单条构造景点及相应字典、证据的 test 批次，**不是已有服务或真实数据**。test_policy、test_nature、test_rule_v1 仅供测试，不确立真实票种、旅游类别或推荐权重。前端请求的 JSON 由 C 的代码生成，不要求用户手工编写。

```json
{
  "batch_id": "test_api_001",
  "country_code": "CN",
  "city_key": "cn:bj:bj",
  "type_codes": ["test_nature"],
  "budget": {"amount": "0.00", "currency": "CNY", "price_policy_id": "test_policy"},
  "limit": 10
}
```

```json
{
  "data": {
    "items": [
      {
        "attraction": {
          "batch_id": "test_api_001",
          "attraction_id": "test_attraction_1",
          "name": "构造景点甲",
          "country_code": "CN",
          "province_key": "cn:bj",
          "province_name": "北京市",
          "city_key": "cn:bj:bj",
          "city_name": "北京市",
          "grade_system": "CN_A",
          "grade_status": "rated",
          "grade_level": "5A",
          "type_codes": ["test_nature"],
          "price_form": "free",
          "price_min": "0.00",
          "price_max": "0.00",
          "currency": "CNY",
          "price_basis": "构造测试政策中的票种",
          "price_policy_id": "test_policy",
          "price_raw": "构造测试：免费",
          "source_refs": {
            "name": ["test_ref_1"],
            "location": ["test_ref_1"],
            "grade": ["test_ref_1"],
            "types": ["test_ref_1"],
            "price": ["test_ref_1"]
          },
          "collected_at": "2026-10-19T08:00:00Z"
        },
        "reasons": ["符合所选城市", "匹配所选测试类型", "已确认免费，符合 0.00 CNY 门票预算"]
      }
    ],
    "candidate_count": 1,
    "returned_count": 1,
    "limit": 10,
    "rule_version": "test_rule_v1",
    "preferences": {
      "country_code": "CN",
      "province_key": null,
      "city_key": "cn:bj:bj",
      "type_codes": ["test_nature"],
      "budget": {"amount": "0.00", "currency": "CNY", "price_policy_id": "test_policy"}
    },
    "empty_reason": null
  },
  "meta": {"batch_id": "test_api_001", "data_kind": "test", "contract_version": "1.0"},
  "error": null
}
```

## 8. A/B/C 的内部函数交付

内部函数返回普通 Python 字典、列表或迭代器，不返回 Flask Response，不依赖 request 对象。下列类型名是结构说明，不要求新增 DTO 类、框架或 HTTP 服务。

| 类型名 | 结构 |
| --- | --- |
| `Attraction` | 数据契约的 21 字段 JSON 兼容字典；金额为字符串，时间为带 Z 字符串，列表与对象已解析。 |
| `DatasetContext` | `{ "meta": 业务批次 meta, "info": DatasetInfo }`，仅表示加载并验证的 ready 批次；对调用方只读。 |
| `Page` | items、page、page_size、total、total_pages 的分页字典。 |
| `ListFilters` | q、country_code、province_key、city_key、grade_system、grade_status、grade_level、type_code、max_price、currency、price_policy_id；未选字段为 null。 |
| `StatisticsQuery` | metric、scope、filters；filters 只含本次实际施加的合法分组字段及价格上下文，不含分页和 sort。 |
| `Preferences` | 推荐 data.preferences 的五个字段；预算或地区未选时 null，兴趣未选时 []。 |
| `RecommendationResult` | 第 7 节全部七个返回字段组成的字典，不含 HTTP 顶层封装。 |

| 负责人 | 函数约定 | 返回与边界 |
| --- | --- | --- |
| A | `load_dataset(batch_id)` | 返回 DatasetContext；检查选定批次存在、ready、契约版本及元数据有效，不自行猜最新批次。 |
| A | `list_attractions(batch_id, filters, page, page_size, sort)` | 返回 Page[Attraction]；使用参数化查询与白名单排序，返回完整筛选数量。 |
| A | `get_attraction(batch_id, attraction_id)` | 返回含 attraction、evidence 的字典；不存在返回 None，由 C 映射为 NOT_FOUND。 |
| A | `list_statistics(batch_id, query, page, page_size, sort)` | 返回 Page[六字段统计记录]；区分未产出上下文和已有上下文中筛选为空，不重算统计。 |
| A | `iter_recommendation_candidates(batch_id, preferences)` | 返回 Iterable[Attraction]；至少按地区缩小范围，不能按展示分页或 limit 提前截断，不能遗漏满足偏好的候选。 |
| B | `recommend(candidates, preferences, limit, dataset)` | 返回完整 RecommendationResult；校验批次，对候选落实地区、类型与价格资格并排序、计数、生成理由，不直接查询数据库。 |
| C | 路由与公共错误适配 | 从环境配置取得服务批次、调用 load_dataset，规范化参数，再调用 A/B；最终组装 data/meta/error。 |

同一批次的查询与推荐使用相同规则。A 可在候选读取时进一步使用已约定的类型或价格条件优化，但不能采用不同的资格判断；B 仍按契约核对硬条件。迭代器需正确释放读取资源，读取或排序中途失败不能返回一份冒充完整评估的部分结果。

C 维护计划中的 `backend/app/errors.py` 公共 `AppError(code, message, details)`，A/B 用其报告受控错误，code 使用下一节枚举，不在查询或推荐模块中决定 HTTP 状态码。C 统一映射状态；意外异常归 INTERNAL_ERROR 并记录供 agent 排查的实际错误，不向前端输出 SQL、连接信息、原始堆栈或私有路径。

## 9. 错误码与前端处理

| HTTP | code | 含义 |
| --- | --- | --- |
| 400 | `INVALID_PARAMETER` | JSON 语法、对象结构、未知或重复字段、类型、范围等不合法，details 可指出 field。 |
| 400 | `INVALID_FILTER` | 字典值不存在、地区或等级组合冲突、币种与政策不匹配、统计维度组合不支持。 |
| 400 | `EMPTY_PREFERENCES` | 推荐没有任何有效偏好。 |
| 404 | `NOT_FOUND` | 当前批次景点不存在，或访问了不存在的 API 路径。 |
| 405 | `METHOD_NOT_ALLOWED` | 对路径使用了不支持的方法。 |
| 409 | `BATCH_MISMATCH` | 请求批次与当前服务批次不同；meta 返回实际批次。 |
| 409 | `PRICE_POLICY_NOT_READY` | 已请求价格比较或预算，但当前批次尚无可用比较政策。 |
| 409 | `STATISTIC_NOT_AVAILABLE` | 所需指标、分组或价格上下文尚未产出。 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | POST 未使用 application/json。 |
| 503 | `DATASET_NOT_READY` | 未配置服务批次、批次不存在或尚非 ready。 |
| 503 | `DATASET_INVALID` | 服务批次的契约、引用或读取数据不符合数据契约。 |
| 503 | `DEPENDENCY_UNAVAILABLE` | 数据库等在线依赖不可用。 |
| 503 | `RECOMMENDER_UNAVAILABLE` | 推荐模块尚未实现、接入或准备完成。 |
| 500 | `INTERNAL_ERROR` | 其他未预期异常，不能包装为无匹配。 |

通过基本结构校验的价格请求，在字典中没有任何价格政策时先返回 PRICE_POLICY_NOT_READY；已有政策但请求指定不存在的 ID 或错误币种时，返回 INVALID_FILTER。缺少必填字段或字段类型错误仍先返回 INVALID_PARAMETER。合法偏好但没有候选、列表筛选为空、翻页越界是正常 200，不是上述错误。

前端按 code 处理：批次变化清除并重载；政策或统计未就绪显示明确说明；无匹配提示调整条件；服务错误保留可理解反馈。不能自动删除预算、切到其他批次、展示旧图表冒充新结果，或把 message 文本作为唯一判断依据。

## 10. agent 执行的接口验证与交接

- C 从共同样本、字典和上述构造示例生成请求与检查，不要求成员手工用调试工具逐项验收。
- A 验证查询、分页总量、稳定排序、来源引用、地区与等级筛选、正确批次及数据库异常映射。
- B 验证完整候选范围、类型至少匹配一项、预算零值与临界值、未绑定政策的报价排除、理由一致与无匹配结果。
- C 验证六个路径、共同封装、未知字段、错误类型、JSON 媒体类型、批次冲突、缺失政策、未产出统计及网页错误反馈；404/405 等 API 错误也返回统一 JSON。
- 将推荐预算设为数据契约样例的 80.00、79.99、0.00，资格结果应与数据契约一致；接口排序仍使用 B 实际规则，不从样例推导新权重。
- 查询页有 20 条、实际合格候选超过 20 条时，推荐不能仅使用这 20 条；统计图和地图验证是否正确读取所需全部分页。
- policies=[] 时，地区/类型推荐与普通查询仍可运行；预算请求返回明确错误，价格统计只在有实际 pending_policy 输出时返回该状态，不能声称真实价格功能已验收。
- 交接时由 agent 生成实际使用的请求、响应、检查结果与尚未通过的事项；构造样例、测试替身和真实服务运行记录清楚区分。

本文件规定接口约定，不代表后端、前端、公共异常文件或测试样本已经实现，也不证明服务运行通过。版本、部署与 Hadoop/MapReduce 任务归属查环境和分工规范；实际开发及交付范围以用户授权与里程碑为准。
