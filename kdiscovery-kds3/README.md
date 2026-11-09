# KDiscovery / KD-S-3

独立的 GitHub 需求挖掘模块。公共基类保持 **`KDiscovery`**；本包只注册 **`github / KD-S-3`**。从项目文档、轻量源码索引和实际实现中提取业务功能、内部步骤与有依据的交接，输出需求型 MRG。

当前算法来源：`KD-S-3/handoff-budget-11`。这是工程封装版本 `0.1.0`，不是新的挖掘策略，也没有通过重新实验宣称效果提升。原文件哈希和封装适配见 [provenance.json](provenance.json)。

## 安装与离线检查

Python 3.11+。建议独立虚拟环境；无需 Joern、JDK、Docker 或主应用数据库。

```sh
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[dev]"
kdiscovery strategies
kdiscovery doctor
python -X utf8 -m pytest -q
python -m build
```

Tree-sitter 核心和语法包版本固定；`doctor` 检查版本并计算实际二进制哈希。不支持的语言、动态调用和未读取实现作为缺口记录，不等于项目没有该能力。不同平台的语法包需有相应 Python wheel；本次本地验收平台为 Windows，其他平台需自行运行测试。

## 使用

先设置环境变量，不将密钥写入代码、参数或 Git：

- `GITHUB_TOKEN`：可选，用于 GitHub API 鉴权。
- `KDISCOVERY_MODEL_ENDPOINT`：完整 HTTPS Chat Completions 地址，如 `https://your-provider.example/v1/chat/completions`。
- `KDISCOVERY_API_KEY`：模型服务密钥。

```sh
kdiscovery init ./workspace
kdiscovery mine --workspace ./workspace --repo owner/repository --commit <40位固定commit> --run-id run-001 --model deepseek-v4-pro
```

`mine` 会读取仓库并调用模型，产生实际费用。没有自动批量任务或额外轮次。每个运行最多 24 次实际模型请求、200,000 个新增模型可见原文字符；重试、修复均占原预算。默认温度 0，DeepSeek V4 使用低推理强度，单次调用上限沿用算法。

重复相同命令仅在原运行中使用成功缓存和剩余预算；不能修改模型或 endpoint 后混用断点。已记录的未知请求结果会阻止自动继续。不要删除账本或换 run-id 绕过未知结果与预算；人工确认处理后再安排新实验。

保存布局保持原策略约定：

```text
workspace/
  mrg.format.json
  github-cache.sqlite
  mrg-project/knowledge/<repo>/
    .repository.json
    KD-S-3/<commit>/<run-id>/
      manifest.json, mrg.json, report.html
      evidence.json, implementation-map.json, coverage.json, usage.json
      provider-usage.json, run-config.json
      sources/, file-index/, code-index/, requests/, calls/, ...
```

`provider-usage.json` 单独保存每次模型请求的服务端用量，缺失值为 `null`，不是 0。`usage.json` 保存挖掘请求、字符预算与缓存统计。运行资料包含源码与模型输入，应由调用方管理访问权限；本仓库不包含真实成果或凭据。

```sh
kdiscovery verify <运行目录>
```

打开该目录的 `report.html` 查看功能树、内部流程、关系及缺口。核验通过只说明结构和保存文件一致，不代表完整业务覆盖。

## 作为库嵌入

```python
from kdiscovery import KDiscovery, initialize_workspace

workspace = initialize_workspace('./workspace')
engine = KDiscovery.create('github', 'KD-S-3', provider, workspace, github_api)
result = engine.extract(
    {'repo': 'owner/repository', 'commit': fixed_commit},
    {},
    {'model': model_name, 'model_url': endpoint, 'model_config_hash': config_hash},
    'run-001',
    progress=print,
)
```

`provider.json(instruction, data, **policy)` 返回 JSON 对象；`github_api.get(url, params=None)` 返回具有 `.json()` / `.content` 的响应。接口允许注入现有服务，便于离线假模型测试。调用方负责独占一个 run-id、冻结模型参数、用量记录与未知结果恢复策略；不允许两个进程同时写同一运行。

## 边界与已知限制

- SOP 是业务功能；MN/OMN 是其内部步骤。内部 ME 与功能间 ME 分层保存，代码引用不能直接当作业务依赖。
- 文档功能、代码入口及工作包仍可能存在粒度差异，预算内可能漏掉业务能力或分支。部分成果不表示全项目扫描完成。
- 既有实验未证明 KD-S-3 全面优于 KD-S-2；功能目标收缩、契约遗漏、未生成关系、恢复后的来源登记缺口仍需后续研究。本次封装不掩盖这些局限。
- 历史文件名 `kd_s2_*` 在本包中代表沿用的公共材料、MRG、证据和组装工具，不注册 KD-S-2，也不需要 M0 成果。
- 不含 Web 工作台、后台 worker、WF-S-1、模型密钥管理服务、研究批次控制器、Joern 旧执行器或真实知识成果。
- 仅当前包自身生成的断点承诺同版本恢复；不自动导入主应用历史任务。封装路径、解析器装载及模型适配器改变会产生独立指纹。

详细设计见 [docs/architecture.md](docs/architecture.md)，发布与安全边界见 [docs/maintenance.md](docs/maintenance.md)。仓库未授予额外开源许可；发布许可由项目所有者决定。
