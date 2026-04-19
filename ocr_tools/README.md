# OCR处理工具集使用指南

完整的一站式PDF OCR处理工具，支持从小文件到大文件的智能处理。

## 📋 目录结构

```
/home/l/rag-dashboard/
├── ocr_tools-master.sh          # 主控脚本
└── ocr_tools/                   # 工具目录
    ├── process_small_files.py   # 小文件处理 (<50MB)
    ├── process_medium_files.py  # 中等文件处理 (50-200MB)
    ├── process_large_files.py   # 大文件处理 (>200MB)
    ├── merge_results.py         # 结果合并工具
    ├── validate_results.py      # 质量验证工具
    └── generate_report.py       # 报告生成工具
```

## 🚀 快速开始

### 1. 启动OCR服务

```bash
# 检查服务状态
bash ocr_tools-master.sh check

# 或手动启动
docker run -d -p 8001:8001 --name ocr-gpu ocr-service:gpu
```

### 2. 交互式使用

```bash
bash ocr_tools-master.sh
```

选择菜单中的选项进行操作。

### 3. 命令行使用

```bash
# 分析文件
bash ocr_tools-master.sh analyze

# 处理小文件
bash ocr_tools-master.sh small

# 处理中等文件
bash ocr_tools-master.sh medium

# 处理大文件
bash ocr_tools-master.sh large

# 合并结果
bash ocr_tools-master.sh merge

# 验证质量
bash ocr_tools-master.sh validate

# 生成报告
bash ocr_tools-master.sh report

# 完整流程
bash ocr_tools-master.sh all
```

## 📊 文件分类策略

### 小文件 (<50MB)
- **处理方式**: 同步端点
- **适用场景**: 文档页数少，处理速度快
- **处理时间**: 通常几秒到几十秒

### 中等文件 (50-200MB)
- **处理方式**: 异步端点
- **适用场景**: 中型PDF，需要后台处理
- **处理时间**: 通常1-3分钟

### 大文件 (>200MB)
- **处理方式**: 拆分后处理
- **适用场景**: 超大PDF，需要分块处理
- **处理时间**: 取决于文件大小，可能需要更长时间
- **要求**: 需要安装 `poppler-utils`

## 🔧 环境要求

### 必需工具
- **Python 3.8+**
- **Docker** (用于OCR服务)
- **PaddleOCR Docker镜像**: `ocr-service:gpu`

### 可选工具 (用于大文件处理)
```bash
sudo apt-get install poppler-utils
```

### Python依赖
```bash
pip install requests
```

## 📝 输出文件说明

每个处理的PDF文件会生成以下输出：

### JSON格式文件
- **文件名**: `{原文件名}_ocr.json`
- **内容**: 完整的OCR结果，包含:
  - 文档元数据 (ID, 文件名, 总页数)
  - 每页的文本块 (文本、置信度、边界框坐标)
  - 表格数据 (HTML和Markdown格式)
  - 完整文本内容
  - 处理时间统计

### 文本格式文件
- **文件名**: `{原文件名}_text.txt`
- **内容**: 提取的纯文本内容

### 合并文件 (仅限大文件)
- **文件名**: `{原文件名}_merged_ocr.json`
- **内容**: 合并后的完整OCR结果

## 🎯 使用示例

### 处理单个目录

```bash
# 修改脚本中的SOURCE_DIRS变量
SOURCE_DIRS=["/path/to/your/pdfs"]

# 然后运行
bash ocr_tools-master.sh all
```

### 处理特定大小的文件

```bash
# 只处理小文件
bash ocr_tools-master.sh small

# 只处理中等文件
bash ocr_tools-master.sh medium
```

### 验证处理质量

```bash
# 运行质量验证
bash ocr_tools-master.sh validate

# 查看详细报告
cat /home/l/知识库测试资料/ocr_results/quality_report.json
```

### 生成处理报告

```bash
# 生成Markdown和JSON格式报告
bash ocr_tools-master.sh report

# 查看报告
cat /home/l/知识库测试资料/ocr_results/ocr_report.md
```

## 🔍 故障排查

### OCR服务无法启动
```bash
# 检查端口占用
netstat -tulpn | grep 8001

# 停止并重启容器
docker stop ocr-gpu
docker rm ocr-gpu
docker run -d -p 8001:8001 --name ocr-gpu ocr-service:gpu
```

### 处理大文件失败
```bash
# 安装必要工具
sudo apt-get update
sudo apt-get install poppler-utils

# 验证工具安装
pdfinfo --version
pdfseparate --version
pdfunite --version
```

### 内存不足
```bash
# 查看容器内存使用
docker stats ocr-gpu

# 增加容器内存限制
docker run -d -p 8001:8001 --memory=4g --name ocr-gpu ocr-service:gpu
```

## 📈 性能优化建议

### 1. 批量处理
```bash
# 按大小顺序处理，先处理小文件
bash ocr_tools-master.sh small
bash ocr_tools-master.sh medium
bash ocr_tools-master.sh large
```

### 2. 并行处理
对于小文件，可以修改脚本支持并行处理。

### 3. 缓存模型
OCR模型已预下载，首次启动后无需重新下载。

### 4. 磁盘空间
确保有足够的磁盘空间存储结果文件（通常为原文件的2-10倍）。

## 🛠️ 高级配置

### 自定义阈值
修改各脚本中的阈值变量：

```python
# 在 process_small_files.py 中
SMALL_FILE_THRESHOLD = 50  # MB

# 在 process_medium_files.py 中
MIN_FILE_SIZE = 50  # MB
MAX_FILE_SIZE = 200  # MB

# 在 process_large_files.py 中
LARGE_FILE_THRESHOLD = 200  # MB
PAGES_PER_CHUNK = 50  # 每个分块的页数
```

### 自定义输出目录
修改所有脚本中的OUTPUT_DIR变量：

```python
OUTPUT_DIR = "/your/custom/output/directory"
```

### OCR服务配置
如需修改OCR服务配置，可以修改Docker运行参数或OCR服务的配置文件。

## 📞 支持与反馈

如遇到问题，请检查：
1. OCR服务是否正常运行
2. 磁盘空间是否充足
3. 网络连接是否正常
4. 文件权限是否正确

## 📄 许可证

本工具集用于PDF文件的OCR处理，遵循相关法律法规使用。

## 🔄 版本历史

- **v1.0** - 初始版本，支持小文件、中等文件和大文件处理
- **v1.1** - 添加质量验证和报告生成功能
- **v1.2** - 优化大文件处理和结果合并功能