<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md"><strong>简体中文</strong></a>
</p>

<p align="center">
  <img src="assets/logo.svg" alt="litellmgen 图标" width="132">
</p>

<h1 align="center">litellmgen</h1>

<p align="center">
  <strong>把五类模型来源汇成一份 LiteLLM 配置，每个字段都按来源优先级取值。</strong>
</p>

litellmgen 会读取 LiteLLM 自带的成本表、在线模型目录、各 provider 的 `/models`、GitHub Copilot 账户目录和厂商文档，最后写出唯一一份 `litellm.yml`。所有模型信息都会先归一成扁平的 `Facts`，再逐字段合并：高优先级来源只覆盖它明确给出的字段，不会因为没提到某个字段就把它清空。

## 快速开始

需要 Python 3.12 或更高版本。

```bash
git clone https://github.com/ZisIsNotZis/litellmgen.git
cd litellmgen
python3 -m pip install aiohttp pydantic PyYAML
```

打开 `litellmgen.py`，把顶部的 `BACKUP_PATH`、`CONFIG_PATH`、`OUTPUT_PATH` 改成你机器上的路径。`BACKUP_PATH` 应指向已安装的 LiteLLM 里那份 `model_prices_and_context_window_backup.json`，`CONFIG_PATH` 指向你自己的 `lm.yml`（写法见下文[配置结构](#配置结构)）。然后运行：

```bash
python3 litellmgen.py
```

生成的 router 配置写到 `OUTPUT_PATH`；仓库里预置的是作者本机的 `/home/z/litellm.yml`，记得改掉。如果最后没有算出任何模型，脚本会直接退出，不会写出一个空的 `model_list`。

## 现在能做什么

- **五类信息来源**：LiteLLM 自带备份、LiteLLM 在线目录、provider 的 `/models`、GitHub Copilot 账户目录，以及通过声明式规则提取的厂商文档。
- **逐字段合并**：`None` 表示“这个来源没有意见”，所以高优先级来源不会因为缺字段而抹掉低优先级来源的值。
- **不编造缺失值**：来源没说的能力就保持未设置，不会写成 `false`；输出时用 `exclude_none` 把它们去掉。
- **用 roster 决定成员**：每个组的 `roster:` 决定哪些模型名可以进入配置，其他来源只负责补充信息。这样即使某个 `/models` 返回整个平台，也不会把订阅用不了的模型带进来。
- **一个模型一个别名**：每个模型按组内每个 key 导出一次，名字固定为 `<group>/<model>`。
- **配置直通**：`models:` 下可以写任意扁平字段，既用来补充模型名，也用来覆盖前面所有来源的事实。
- **失败看得见**：某个 catalog、endpoint、文档页或 Copilot token 交换失败时会打印错误并跳过，其他来源继续工作。
- **按来源计数**：每个组都会打印各来源贡献了多少模型，某个来源悄悄失效时一眼就能发现。

### 来源与优先级

| 优先级 | 来源 | 提供什么 |
| --- | --- | --- |
| 最低 | LiteLLM 自带备份 | 价格、上下文上限、能力标记 |
| | LiteLLM 在线目录 | 同类事实，实时拉取 |
| | provider `/models` | 发现模型名，以及端点愿意给出的元数据 |
| | GitHub Copilot 目录 | 账户维度的能力和上限 |
| | 厂商文档 | 按配置里声明的规则抽取事实 |
| 最高 | 配置里的 `models:` | 手写覆盖值与额外模型名 |

provider 端点只在 `roster:` 要求时使用，或者在两个 LiteLLM 来源都为空时作为兜底。只有组的 roster 包含 `copilot` 时，才会走 Copilot 通道。

### 配置结构

`CONFIG_PATH` 是一个按 provider 分组的 YAML 映射。每组可以写：

- `openai`：provider 的 API base。
- `style`：写进 `litellm_params.model` 的 LiteLLM provider 前缀，默认等于组名。
- `keys`：key 标签到 API key 的映射。
- `roster`：允许决定成员来源的通道，例如 `[backup, catalog]`、`[docs]` 或 `[copilot]`。
- `models`：额外模型名和逐模型断言。
- `docs`：厂商页面，以及 `roster`、`inline_code`、`patterns` 这套抽取规则。

下面是某个组完整的写法，只表示形状，不对应任何真实 provider：

```yaml
# lm.yml —— 每个 provider 组一个顶层键。里面有凭据，所以不纳入版本控制。
myprovider:                              # 组名就是别名前缀：myprovider/<model>
  openai: https://api.example.com/v1      # provider 的 API base
  style: openai                           # 写进 litellm_params.model 的前缀，默认等于组名
  keys:
    main: <你的 API key>                   # 不需要 key 的端点可以不写
  roster: [backup, catalog]               # 只有这些通道能决定成员
  models:
    some-model: {max_output_tokens: 128000}   # 补充模型名/字段断言，优先级高于所有来源
  docs:
    - url: https://docs.example.com/models
      roster: ['(?P<name>model-[\d.]+)']   # 页面自己声明的模型名
      inline_code: ['model-[\d.]+']        # 对页面标为字面 id 的 span 做 fullmatch
      units: {'k': 1000}                   # 规则里 `unit` 分组的换算倍数
      patterns:
        - {field: max_input_tokens, pattern: '(?P<value>\d+)\s*上下文'}   # `value` 就是取到的事实
```

组里没实现的键会打印出来并忽略；但 `docs` 或 `patterns` 里拼错键名会被当成配置错误。凭据只放在仓库外的 `CONFIG_PATH` 里；这个文件故意不纳入版本控制。

## 架构

```text
LiteLLM 备份 ───┐
LiteLLM 目录 ───┤
provider /models ─┼─→ Facts（扁平、带类型）─→ 逐字段合并 ─→ roster 过滤 ─→ entries ─→ litellm.yml
Copilot 目录 ───┤
厂商文档 ───────┤
你的 models: ───┘
```

- `Facts` 声明了所有允许进入 `model_info` 的扁平字段，未声明的字段会被忽略。
- `merge()` 在主来源有值时保留主来源，缺失的字段由兜底来源补上。
- `absorb()` 按优先级逐个模型折叠来源。
- `build()` 在 `guard()` 下收集各通道，处理 roster 成员关系，并接收文档贡献的模型名。
- `entries()` 为每个模型和每个 key 导出一条 router 条目，并带上 `drop_params: true`。

## 开发

项目没有构建步骤，也没有需要安装的包，全部实现只有一个脚本。

```bash
python3 -m py_compile litellmgen.py   # 语法检查
python3 litellmgen.py                 # 需要本机路径和网络
```

- `litellmgen.py` 是唯一的实现文件；除非有明确理由，不要拆分它。
- 稳定的命令行入口和自动化测试刻意不在范围内。验证方式是真正跑一遍，再检查生成的 YAML。
- 配置路径和备份路径都是机器相关的。不要把贡献者的家目录写死进提交的示例。
- 不要提交 API key、Copilot token，或包含密钥的生成配置。

项目的定位和暂缓事项见 [`docs/project-status.md`](docs/project-status.md)。

## 参与贡献

先读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。简要原则：改动要小、要有证据；保留逐字段优先级和“不编造事实”的规则；报告你运行了什么、检查了什么。

## 路线图

### 已实现

- 五类带优先级的信息来源，包括账户维度的 Copilot 目录和声明式的厂商文档抽取。
- 逐字段合并，`None` 表示“没有意见”，不编造 `false`。
- 由 roster 决定成员，并按 `<group>/<model>` 生成别名。
- 成本归一：来源里的 `0.0` 表示“价格未知”，不是“免费”。
- 单来源失败隔离、文档规则命中计数，以及未知配置键告警。

### 计划中

项目已按里程碑关闭：除非 LiteLLM 的配置格式或上游来源发生变化，否则没有新功能计划。以下事项被刻意暂缓：

- 稳定的命令行入口。
- 自动化测试。
- 可移植、不依赖本机路径的配置。

### 未来设想

增加一个 provider 或一个模型，应该始终只是改几行 YAML，而不是在五个后台和一张表格之间来回查。如果上游生态最终有了机器可读的权威来源，litellmgen 应该能把它当作又一条通道接进来，而不需要改动合并、优先级和导出这三件事的做法。

## 许可证

[AGPL-3.0](LICENSE.md) © 2026 ZisIsNotZis。
