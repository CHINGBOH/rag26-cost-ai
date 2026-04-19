# 解压工具配置说明

## 已安装的工具

### 1. smart-unzip (智能解压脚本)
**位置**: `/home/l/.local/bin/smart-unzip`

**功能**:
- 自动检测压缩格式 (zip, 7z, rar, tar)
- 自动尝试 UTF-8 和 GBK 编码
- 自动修复解压后的乱码文件名

**用法**:
```bash
# 基本用法
smart-unzip archive.zip

# 指定输出目录
smart-unzip archive.zip ./output

# 简写
uz archive.zip
```

### 2. unzip 编码配置
**配置位置**: `~/.bashrc`

**设置**:
```bash
export UNZIP="-O UTF-8"
export ZIPINFO="-O UTF-8"
alias unzip='unzip -O UTF-8'
```

**效果**:
- 所有 `unzip` 命令自动使用 UTF-8 编码
- 避免中文文件名乱码

## 使用示例

### 解压 ZIP 文件
```bash
# 方法1: 使用 smart-unzip (推荐)
smart-unzip 知识库.zip
uz 知识库.zip

# 方法2: 使用配置后的 unzip
unzip 知识库.zip  # 自动使用 UTF-8

# 方法3: 手动指定编码
unzip -O UTF-8 知识库.zip
unzip -O GBK 知识库.zip
```

### 解压其他格式
```bash
# 7z 格式
7z x archive.7z

# RAR 格式
unrar x archive.rar

# tar.gz 格式
tar -xzf archive.tar.gz
```

## 如果已经乱码了

使用修复脚本:
```bash
python3 /home/l/rag-dashboard/fix_filenames.py
```

## 跨平台建议

### Windows → Linux 传输文件
1. **压缩时使用 UTF-8**
   - 7-Zip: 选择 "utf-8" 编码
   - WinRAR: 勾选 "UTF-8 文件名"

2. **使用 tar 格式**
   ```bash
   # Linux 上压缩
   tar -czvf archive.tar.gz 文件夹/
   
   # 解压
   tar -xzvf archive.tar.gz
   ```

3. **避免使用 Windows 自带压缩工具**
   - 使用 7-Zip 或 Bandizip
   - 确保编码设置为 UTF-8

## 验证配置

```bash
# 检查环境变量
echo $UNZIP
# 输出: -O UTF-8

# 检查别名
alias unzip
# 输出: alias unzip='unzip -O UTF-8'

# 检查 smart-unzip
which smart-unzip
# 输出: /home/l/.local/bin/smart-unzip
```
