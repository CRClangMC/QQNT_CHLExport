# qq_dump_db

> 在极为安全的情况下，自动提取并解密 NTQQ 的 SQLCipher 数据库。

## Why

NTQQ 将聊天记录等数据保存在本地 SQLCipher 加密数据库中，密钥仅存在于进程内存里，用户无法直接导出自己的数据。
本工具让你能够 **拿回属于你自己的聊天记录**。

## 原理

登录 QQ 后，程序通过 `OpenProcess` + `VirtualQueryEx` 遍历 `wrapper.node` 进程的可读内存区域，用正则匹配 `x'<64hex_key><32hex_salt>'` 模式的字符串，几秒内即可精准定位 SQLCipher 密钥与盐值（salt 本身也存储在 db 文件头部，用于交叉验证）。

拿到密钥后，自动通过 PBKDF2-SHA512 派生解密密钥，对数据库每页执行 AES-256-CBC 解密 + HMAC-SHA1 校验，最终将明文数据写入可直接用 SQLite 打开的 `.db` 文件。

## 为什么安全

| 特性 | 说明 |
|---|---|
| **无注入** | 全程不 inject 任何 DLL 到 QQ 进程 |
| **无 Hook** | 不修改 QQ 的任何函数或内存 |
| **纯外部读取** | 仅使用 `OpenProcess` + `ReadProcessMemory`，属于外部进程调用系统内核的行为 |
| **极短暴露窗口** | 扫描耗时 1-2 秒，随用随走 |

NTQQ 即使 hook 自身的这些 API 也无法检测到外部进程的调用。除非对所有进程进行注入检测或采用更高权限的内核级方案，这在实践中极为困难。即便存在进程名识别，随机命名即可规避。

## 使用方式

### C++ 版（推荐，无额外依赖）

```bash
qq_dump_db.exe --qq <QQ号>
qq_dump_db.exe --qq <QQ号> --pid <PID>       # 可选：手动指定进程 PID
qq_dump_db.exe --qq <QQ号> --db-dir <目录>   # 可选：手动指定 db 搜索目录
```

### Python 版

```bash
pip install cryptography
python dump_qq_key_auto.py --qq <QQ号>
```

解密后的数据库文件将输出到 `output/<QQ号>/` 目录。

## 构建

```bash
cmake -B build -A x64
cmake --build build --config Release
```

生成的可执行文件位于 `build/Release/qq_dump_db.exe`。

## License

MIT

转载或引用请注明来源：[https://github.com/NapNeko/qq_dump_db](https://github.com/NapNeko/qq_dump_db)