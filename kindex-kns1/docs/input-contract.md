# 输入契约

知识快照为 JSON 对象。当前 KN-S-1 使用旧知识快照的字段，不直接接收 `mrg-requirements-v1`。

| 字段 | 类型 | 意义 |
|---|---|---|
| `id` | 非空字符串 | 不可变快照标识 |
| `projects` | 项目标识→对象 | 每项有 `mns.SOP_refs` 根 SOP ID 数组，可提供 repo/license/commit |
| `entities` | 实体 ID→对象 | SOP 有字符串 name/goal，以及可选 sub_sop_refs、node_refs、entry_conditions、completion_conditions；node_refs 对应实体的输入输出可作为回退文本 |
| `rows` | 功能 SOP ID→对象 | 功能补充信息；没有 row 的 SOP 作为 root 类型索引，有 row 的作为 feature |
| `trees` | 项目标识→对象，可选 | 每项提供 commit、nodes；type 为 unit 的节点进入实现单元索引 |

SOP 的父子关系从 `sub_sop_refs` 得到，ID 在整个快照中唯一。输入保护检查悬空引用、重复归属、多个父节点、循环和跨项目父子关系。`rows` 中的 ID 必须归属于项目中的 SOP。其余元数据应遵循下面的字段类型；这不是业务真实性校验。

`rows` 可包含：

- `aliases`: 字符串数组。
- `inputs` / `outputs`: 建议使用业务文本；缺失时从 SOP 的 node_refs 对应实体读取。
- `industry` / `interface_kind` / `independence_level` / `mapping_status`: 字符串。
- `functional_evidence`: 已有依据的数组，仅供现有评分特征计数，索引器不重新核实证据。
- `runtime_verified`: 布尔值，索引器不会把源码定位自动改成运行验证。
- `capability_profile.details.scenarios` / `limitations`: 数组。
- `code_modules`: 可选对象数组，commit 可作为版本字段回退。

实现单元要求 `id/type/parent/name/purpose/confidence`，其 parent 必须指向同项目的已有索引节点。`inputs/outputs/preconditions/steps` 为数组，文本字段使用字符串。`code_locations` 可选；存在定位只表明源码位置，并不表示运行通过。

完成度、场景特化和 evidence_level 是沿用的索引排序/过滤特征，不是自动业务质量评分。请勿为提高召回而填造证据或验证状态。

未来接入 KD-S-3 需求型 MRG 时需要一个明确的适配层：处理 purpose→goal、parent_sop_id→包含关系、语义端口和项目身份；MN/OMN 不能自动变成独立功能 SOP，业务 ME 不能写成父子归属。该适配不在本次封装范围内。
