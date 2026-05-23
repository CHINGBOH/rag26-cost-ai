# Ubuntu 解压中文乱码解决方案

## 问题原因

Ubuntu 文件管理器（Nautilus）自带的解压工具使用 UTF-8 编码，而中文 Windows 压缩包使用 GBK 编码。

## 已配置的解决方案

### 1. 命令行解压（推荐）

```bash
# 使用已配置的 unzip（自动使用 GBK 编码）
unzip 压缩文件.zip

# 或使用完整命令
unzip -O GBK 压缩文件.zip
```

### 2. 文件管理器右键菜单

**已添加右键菜单**: `Scripts` → `解压(GBK编码)`

使用方法：
1. 在文件管理器中选中压缩文件
2. 右键 → `Scripts` → `解压(GBK编码)`
3. 文件会解压到同名文件夹中

### 3. 智能解压脚本

```bash
# 使用 smart-unzip
smart-unzip 压缩文件.zip
# 或简写
uz 压缩文件.zip
```

## 手动修复已乱码的文件

如果已经用系统工具解压导致乱码，运行修复脚本：

```bash
python3 /home/l/rag-dashboard/fix_filenames.py
```

## 不同场景的使用建议

| 场景 | 推荐方法 |
|------|----------|
| 命令行解压 | `unzip 文件.zip` |
| 图形界面解压 | 右键 → `Scripts` → `解压(GBK编码)` |
| 批量解压 | `uz *.zip` |
| 已乱码修复 | `python3 fix_filenames.py` |

## 注意事项

1. **重启文件管理器**后右键菜单才会生效：
   ```bash
   nautilus -q
   ```

2. **命令行 unzip 已自动配置为 GBK**，直接使用即可

3. **如果压缩包是 UTF-8 编码**（少见），使用：
   ```bash
   /usr/bin/unzip -O UTF-8 文件.zip
   ```

## 配置文件位置

- unzip wrapper: `/home/l/.local/bin/unzip`
- 右键菜单脚本: `/home/l/.local/share/nautilus/scripts/解压(GBK编码)`
- 智能解压: `/home/l/.local/bin/smart-unzip`
- 修复脚本: `/home/l/rag-dashboard/fix_filenames.py`
