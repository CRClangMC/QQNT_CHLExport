# QQNT 聊天记录导出工具

本项目用于将 QQNT 本地聊天数据库解密并导出为易读、便于处理的文件，并提供私聊聊天记录统计功能。支持私聊和群聊，可导出 TXT、JSON、HTML 格式，并保证了完全本地运行，在多次本地测试验证后确认了几乎为零的账号安全风险。

本项目V1.0.1测试版发布时对应的QQNT版本号：9.9.35-52804 (64位)

> 请仅处理你本人有权访问的 QQ 账号及数据。导出的聊天记录、图片和语音可能包含个人隐私，请妥善保管，不要未经授权分享。

## 功能

- 导出私聊、群聊记录，可按 QQ 号或群号筛选。
- 导出为 TXT、JSON 或 HTML。
- 尝试关联 QQ 本地缓存中的图片和语音文件。
- 自动化流程可调用随项目提供的 `qq_dump_db.exe` 提取并解密数据库，然后修复聊天数据库并执行导出。
- 根据私聊 JSON 记录生成单文件或目录汇总统计。

## 工作原理

项目的处理流程分为以下阶段：

1. **获取本地数据库**：自动化脚本 `auto_run_output.py` 调用 `qq_dump_db/qq_dump_db.exe`，根据指定 QQ 号及 QQ 数据库目录提取并解密本地数据库。只导出私聊或群聊时，会跳过不需要的好友或群资料数据库；私聊和群聊消息都位于 `nt_msg.db`，因此该数据库仍会解密。
2. **修复聊天数据库**：运行 `copy_tables_from_corrupt.py`，从提取的聊天数据库中恢复需要的聊天表，并生成可供导出程序读取的数据库。关闭某种聊天导出时会跳过修复对应的消息表。原始提取文件会备份为 `nt_msg_original_corrupt.db`。
3. **读取和筛选消息**：`main.py` 通过 SQLAlchemy 读取数据库，根据配置中的私聊 QQ 号、群号筛选消息，并按时间排序。
4. **转换和写出文件**：导出器解析消息元素（如文字、图片、语音、文件、视频和表情），写出 TXT、JSON 或 HTML 文件；图片和语音缓存位置由配置指定。
5. **生成统计**：统计脚本读取本项目导出的 JSON 私聊记录，计算消息数量、收发情况、聊天时间跨度等，并生成文本报告。

手动运行 `main.py` 时，需要提前准备好可读取的数据库目录；一键流程则会执行数据库提取、修复和导出步骤。

## 环境要求

- Windows
- Python 3.11 或更高版本（项目使用标准库 `tomllib`）
- 已登录并运行的 QQNT（使用自动提取流程时）
- 有权读取的 QQ 本地数据目录

## 安装

安装 Python 3.11 或更高版本后，在项目根目录打开 PowerShell，直接安装依赖：

```powershell
python -m pip install -r requirements.txt
```

## 使用方法

### 方法一：自动提取并导出（推荐）

确保 QQ 已启动并登录。在项目根目录运行以下命令，并将路径、QQ 号替换为自己的实际值：

在 QQ 中打开 **设置 > 存储管理 > 保存位置 > 聊天消息默认保存到**，将该项显示的路径作为下面命令中的 `<聊天消息默认保存到>`，再接上 `你的QQ号\nt_qq\nt_db`。

```powershell
python auto_run_output.py -qq 你的QQ号 -lock_db_dir "<聊天消息默认保存到>\你的QQ号\nt_qq\nt_db" -output_dir "D:\QQ聊天记录导出" -format json
```

详细方法请阅读auto_run_output.py源码中的首段注释。

`-lock_db_dir` 指向 QQ 的原始数据库目录；`-output_dir` 是导出结果目录。

常用筛选参数：

```powershell
# 只导出指定 QQ 号的私聊；未传 -group 时群聊仍按默认配置导出全部
python .\auto_run_output.py -qq 你的QQ号 -lock_db_dir "<聊天消息默认保存到>\你的QQ号\nt_qq\nt_db" -output_dir "D:\QQExport" -c2c "123456,654321" -format json

# 只导出指定群号的群聊
python .\auto_run_output.py -qq 你的QQ号 -lock_db_dir "<聊天消息默认保存到>\你的QQ号\nt_qq\nt_db" -output_dir "D:\QQExport" -group "111111,222222" -format txt

# 只导出群聊，不导出私聊
python .\auto_run_output.py -qq 你的QQ号 -lock_db_dir "<聊天消息默认保存到>\你的QQ号\nt_qq\nt_db" -output_dir "D:\QQExport" -noc2c -format json

# 只导出私聊，不导出群聊
python .\auto_run_output.py -qq 你的QQ号 -lock_db_dir "<聊天消息默认保存到>\你的QQ号\nt_qq\nt_db" -output_dir "D:\QQExport" -nogroup -format txt
```

- 不传 `-c2c` 或 `-group` 时，对应类型默认导出全部；传入逗号分隔的号码可筛选。
- `-noc2c` 和 `-nogroup` 分别关闭私聊、群聊导出，不能同时使用。
- 使用 `-noc2c` 或 `-nogroup` 时，会跳过对应消息表的修复及不需要的好友/群资料数据库解密；两种消息都在 `nt_msg.db`，导出任意一种时仍需解密它。
- 如果导出意外中断，可在相同命令参数中加入 `-continue`（也支持 `--continue`）后重新运行。程序会查找并复用已解密数据库；如果数据库解密中断，则尝试从临时分页文件继续。请保留项目下 `output\<QQ号>` 临时目录，不要在续跑前删除。成功完成后临时目录仍按默认行为清理；传入 `-keeptemp` 可保留它。
- `-format` 必填，可用逗号分隔格式，例如 `txt,json`。支持 `txt`、`json`、`html`。
- 默认会清理本次生成的临时解密目录和项目根目录下自动生成的 `config.toml`。添加 `-keeptemp` 可保留它们，便于排查或再次使用。

导出目录中会按 `c2c`（私聊）和 `group`（群聊）分类保存记录；图片、语音等媒体文件可能分别放在 `chatpic`、`chatvoice` 子目录。

### 方法二：使用配置文件手动导出

1. 将 `example.toml` 复制为自己的配置文件（例如 `config.toml`）。
2. 编辑配置，设置数据库目录、媒体目录、输出目录、筛选条件和输出格式。
3. 确认 `db_path` 指向包含所需解密数据库文件（例如 `nt_msg.db`）的目录。
4. 在项目根目录运行：

```powershell
python .\main.py .\config.toml
```

配置示例：

```toml
db_path = ".\\databases\\"
pic_path = ".\\chatpic\\"
pic_source_path = ".\\nt_data\\Pic\\"
voice_path = ".\\chatvoice\\"
voice_source_paths = [".\\nt_data\\Ptt\\", ".\\Audio\\"]
output_path = ".\\output\\"

c2c_filters = [123456, 654321]
export_c2c = true
group_filters = [111111, 222222]
export_group = true
output_format = ["txt", "json"]
```

- `c2c_filters`、`group_filters` 为空数组时，导出所有对应类型的会话。
- `export_c2c`、`export_group` 控制是否导出私聊和群聊。
- `output_format` 支持 `txt`、`json`、`html`，可以选择一种或多种。
- `pic_source_path`、`voice_source_paths` 用于查找 QQ 原始媒体缓存；找不到对应缓存时，文本记录仍可导出，但媒体内容可能无法还原。

## 聊天记录统计

统计脚本以本项目导出的 **JSON 私聊文件** 为输入。

统计单个私聊 JSON 文件：

```powershell
python .\chat_history_stats.py "D:\QQExport\c2c\联系人.json"
```

统计文本会保存到同一目录下的 `联系人_时光统计.txt`。

汇总指定目录下的 JSON 文件：

```powershell
python .\chat_history_stats_all.py "D:\QQExport\c2c"
```

汇总结果写入输入目录中的 `QQ时光统计局_全部统计.txt`。也可以使用交互式批处理文件：

```powershell
& ".\统计聊天记录(私聊).bat"
& ".\导出全部聊天统计.bat"
```

## 常见问题

- **提示找不到 QQ 主进程或数据库解密失败**：确认 QQNT 已启动并登录；检查 `-qq` 与 `-lock_db_dir` 是否对应同一账号。
- **图片或语音没有导出/显示**：检查配置中的 QQ 媒体缓存源目录是否正确，以及缓存文件是否仍存在。
- **使用手动导出时报数据库文件不存在**：检查 `db_path` 是否指向包含数据库文件的目录，而不是某个单独的 `.db` 文件。
- **统计脚本跳过文件**：统计功能面向私聊 JSON；群聊 JSON 不包含私聊统计所需的收发方向字段，不能作为对应统计输入。
- **更新后本项目失效**：若QQ更新后本项目不可用，请等待本项目与qq_dump_db更新后重试。

## 鸣谢

- [Tealina28/QQNT_Export](https://github.com/Tealina28/QQNT_Export)
- [NapNeko/qq_dump_db](https://github.com/NapNeko/qq_dump_db)

感谢以上开源项目及其作者的工作与分享。本项目在相关工作基础上实现聊天记录整理、格式导出和统计功能；请同时遵循各项目自身的许可协议及使用说明。

## 许可证

本项目采用 [MIT License](./LICENSE)。鸣谢中提及的第三方项目及随项目提供的工具仍分别遵循其各自的许可协议。
