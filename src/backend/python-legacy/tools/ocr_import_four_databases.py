#!/usr/bin/env python3
"""
完整的四库导入流程脚本
同时执行PostgreSQL、Qdrant、Neo4j和知识库的导入
"""

import os
import sys
import logging
import subprocess
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class FourDatabaseImporter:
    """四库导入协调器"""

    def __init__(self):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.conda_env = "py310"

    def run_command(self, command, description):
        """运行命令并记录日志"""
        logger.info(f"开始{description}...")
        logger.info(f"执行命令: {command}")

        try:
            # 使用bash作为shell
            result = subprocess.run(
                command,
                shell=True,
                executable='/bin/bash',
                capture_output=True,
                text=True,
                cwd=os.path.dirname(self.base_dir)
            )

            if result.returncode == 0:
                logger.info(f"{description}成功完成")
                # 输出最后几行日志
                output_lines = result.stdout.strip().split('\n')
                if output_lines:
                    for line in output_lines[-10:]:
                        logger.info(f"  {line}")
                return True
            else:
                logger.error(f"{description}失败")
                logger.error(f"退出码: {result.returncode}")
                logger.error(f"错误输出: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"{description}执行异常: {e}")
            return False

    def import_postgres(self):
        """导入PostgreSQL"""
        command = f"source ~/miniconda3/bin/activate {self.conda_env} && python {self.base_dir}/ocr_import_postgres.py"
        return self.run_command(command, "PostgreSQL导入")

    def import_qdrant(self):
        """导入Qdrant"""
        command = f"source ~/miniconda3/bin/activate {self.conda_env} && python {self.base_dir}/ocr_embed_import.py"
        return self.run_command(command, "Qdrant向量数据库导入")

    def import_neo4j(self):
        """导入Neo4j"""
        command = f"source ~/miniconda3/bin/activate {self.conda_env} && python {self.base_dir}/ocr_import_neo4j.py"
        return self.run_command(command, "Neo4j知识图谱导入")

    def import_knowledge_base(self):
        """导入知识库"""
        command = f"source ~/miniconda3/bin/activate {self.conda_env} && python {self.base_dir}/ocr_import_knowledge_base.py"
        return self.run_command(command, "知识库文档存储导入")

    def run(self):
        """运行完整的四库导入流程"""
        start_time = datetime.now()
        logger.info("=" * 80)
        logger.info("开始四库导入流程")
        logger.info(f"开始时间: {start_time}")
        logger.info("=" * 80)

        # 执行各个导入
        results = {
            "PostgreSQL": self.import_postgres(),
            "Qdrant": self.import_qdrant(),
            "Neo4j": self.import_neo4j(),
            "知识库": self.import_knowledge_base()
        }

        # 统计结果
        success_count = sum(1 for success in results.values() if success)
        total_count = len(results)

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        logger.info("=" * 80)
        logger.info("四库导入流程完成")
        logger.info(f"结束时间: {end_time}")
        logger.info(f"总耗时: {duration:.2f} 秒")
        logger.info(f"成功导入: {success_count}/{total_count}")
        
        for db, success in results.items():
            status = "成功" if success else "失败"
            logger.info(f"{db}: {status}")

        logger.info("=" * 80)

        return success_count == total_count

def main():
    """主函数"""
    importer = FourDatabaseImporter()
    importer.run()

if __name__ == "__main__":
    main()
