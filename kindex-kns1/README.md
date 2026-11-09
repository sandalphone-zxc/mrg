# KIndex / KN-S-1

可独立安装和分享的分层知识索引模块。基类为 **`KIndex`**，实现类为 **`HierarchicalIndex`**，策略名为 **`KN-S-1`**。

输入知识快照，生成 SQLite FTS5 关键词索引、可选向量索引以及 SOP/实现单元的父子归属关系。支持内容缓存复用、中文双字切分、英文词切分、名称与别名加权检索、过滤和祖先/后代回溯。无需 KDiscovery、M2、Web 服务、GitHub Token 或主应用数据库。

## 安装

Python 3.11+，SQLite 需支持 FTS5。

```sh
git clone https://github.com/sandalphone-zxc/mrg.git
cd mrg/kindex-kns1
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -e .
kindex strategies
```

也可直接从仓库安装：`python -m pip install "git+https://github.com/sandalphone-zxc/mrg.git#subdirectory=kindex-kns1"`。

关键词和层级索引仅依赖 NumPy 与 Python 自带 SQLite，不调用模型。使用远程向量服务时安装 `python -m pip install -e ".[remote]"`；测试及打包使用 `python -m pip install -e ".[dev]"`。

## 不调用模型的完整示例

```sh
kindex build examples/snapshot.json --db index.sqlite
kindex search demo-v1 "导出报告" --db index.sqlite
kindex relatives demo-v1 SOP.export --db index.sqlite --direction parents
kindex search demo-v1 "渲染" --db index.sqlite --include-units
```

```python
import json
from pathlib import Path
from kindex import KIndex, SQLiteStore

snapshot = json.loads(Path('examples/snapshot.json').read_text(encoding='utf8'))
index = KIndex.create('github', 'KN-S-1', SQLiteStore('index.sqlite'))
print(index.build(snapshot))
print(index.search(snapshot['id'], '导出报告', use_vectors=False))
print(index.relatives(snapshot['id'], 'SOP.export', direction='parents'))
```

也可直接构造 `HierarchicalIndex(store, providers=None)`。自定义 store 的 `connect()` 必须返回支持事务的上下文管理器，连接使用 `sqlite3.Row`。

## 输入格式必须明确

**当前输入是知识快照，不是 KD-S-3 的单个 `mrg.json`。** 必须提供 `id / projects / entities / rows`；实现单元通过可选 `trees` 提供。参考 [examples/snapshot.json](examples/snapshot.json) 和 [docs/input-contract.md](docs/input-contract.md)。本版本不自动转换需求型 MRG，也不读取源码来补造功能、依赖或置信度。

同一个快照 ID 对应不可变数据；改变正文、许可证、实现状态或层级时使用新 ID。新快照可以复用相同模型、相同索引文本的向量缓存。同名不同项目的 SOP 必须使用不同 ID。

## 可选向量服务

CLI 必须显式添加 `--vectors` 才使用远程服务，并从环境变量读取：

- `KINDEX_EMBEDDING_ENDPOINT`：完整 HTTPS `/embeddings` 地址。
- `KINDEX_EMBEDDING_MODEL`：向量模型名称。
- `KINDEX_API_KEY`：访问密钥。

```sh
kindex build examples/snapshot.json --db index.sqlite --vectors
kindex search demo-v1 "生成报告文件" --db index.sqlite --vectors
```

这些命令会将索引文本或查询发送给配置服务，可能产生费用。不要把环境变量真实值提交到 Git。构建每批最多 24 条未缓存文本；这里是**批大小**，不是总请求预算。HTTP 适配器不自动重试。成功批次缓存保留；向量构建失败时关键词索引仍可使用，后续调用可复用成功缓存。未知服务结果须由调用方确认后决定是否重新构建。

库调用可注入本地或远程模型，只需实现 `status()`、`vector_identity()`、`embed(texts)`。协议和适配器见 `src/kindex/providers.py`。`vector_identity()` 必须区分服务端点、模型及会改变向量空间的设置；执行期间保持配置不变。自定义提供者应抛出本模块 `ProviderError` 表达服务失败。

## 输出及边界

- `build()` 返回节点数、关键词/向量状态、嵌入和缓存复用数量；`embedded` 是新嵌入的唯一文本数，不是请求数。
- `search()` 返回节点元数据、融合分数和命中依据。过滤包括实现单元、完整度、场景特化程度、代码定位和许可证。
- `relatives()` 返回祖先或后代及层级距离，最多向下/上递归 100 层。
- `kn_edges` 是**父子归属**，不是功能执行依赖；无边不能解释为无业务依赖。项目身份作为节点元数据保存，项目根 SOP 可参与检索。
- 原 BM25 权重和向量相似度加分保持不变；分数不是成功概率，不代表代码可运行或已验证复用。
- 语义服务失败或向量维度不相容时，查询可能只保留关键词结果。需要显式告警和计费记录的应用应在提供者层记录调用状态；HTTP 适配器仅保留最近一次响应的 `last_usage`，未知为 `None`。
- 包内不包含历史知识、私有代码、凭据或用户索引数据库。建议为此模块使用独立数据库；本版本不自动迁移主应用数据库。

## 维护

```sh
python -X utf8 -m pytest -q
python -m build
```

原始文件哈希和封装变更见 [provenance.json](provenance.json)，设计见 [docs/architecture.md](docs/architecture.md)。版本 `0.1.0` 是独立封装版本，策略标识仍是 KN-S-1。原应用代码及此前发布的 KD-S-3 包保持独立。未指定额外开源许可，许可由仓库所有者决定。
