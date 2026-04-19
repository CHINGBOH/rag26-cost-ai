/**
 * OCR 服务 - FastAPI 实现
 * 独立的 OCR 微服务
 */

import { spawn } from 'child_process';
import * as path from 'path';

export interface OCRServiceConfig {
  host: string;
  port: number;
  useDocker?: boolean;
}

export class OCRServiceClient {
  private config: OCRServiceConfig;
  private dockerProcess?: any;

  constructor(config: Partial<OCRServiceConfig> = {}) {
    this.config = {
      host: config.host || 'localhost',
      port: config.port || 8000,
      useDocker: config.useDocker ?? true
    };
  }

  /**
   * 启动 OCR 服务
   */
  async start(): Promise<void> {
    if (this.config.useDocker) {
      await this.startDockerService();
    } else {
      await this.startLocalService();
    }
  }

  /**
   * 使用 Docker 启动服务
   */
  private async startDockerService(): Promise<void> {
    const dockerfilePath = path.resolve(__dirname, '../../ocr-service');

    // 1. 构建镜像
    console.log('[OCR] Building Docker image...');
    await this.runCommand('docker', [
      'build', '-t', 'rag-ocr-service', dockerfilePath
    ]);

    // 2. 启动容器
    console.log('[OCR] Starting Docker container...');
    this.dockerProcess = spawn('docker', [
      'run',
      '-d',
      '--name', 'rag-ocr',
      '-p', `${this.config.port}:8000`,
      '-v', '/tmp/rag-ocr:/app/temp',
      '--rm',
      'rag-ocr-service'
    ]);

    // 等待服务启动
    await this.waitForService(30000);
    console.log('[OCR] Service started successfully');
  }

  /**
   * 启动本地服务
   */
  private async startLocalService(): Promise<void> {
    // 检查 Python 和 PaddleOCR 是否可用
    const checkResult = await this.checkPythonEnvironment();
    if (!checkResult.available) {
      throw new Error(`OCR environment not available: ${checkResult.reason}`);
    }

    // 启动 Python 服务
    const servicePath = path.resolve(__dirname, '../../ocr-service/ocr_service.py');
    this.dockerProcess = spawn('python3', [
      '-m', 'uvicorn',
      `ocr_service:app`,
      '--host', this.config.host,
      '--port', String(this.config.port)
    ], {
      cwd: path.dirname(servicePath)
    });

    await this.waitForService(30000);
  }

  /**
   * 检查 Python 环境
   */
  private async checkPythonEnvironment(): Promise<{
    available: boolean;
    reason?: string;
  }> {
    return new Promise((resolve) => {
      const check = spawn('python3', ['-c', `
import sys
try:
    from paddleocr import PaddleOCR
    print("OK")
    sys.exit(0)
except ImportError as e:
    print(f"Missing: {e}")
    sys.exit(1)
      `]);

      let output = '';
      check.stdout.on('data', (data) => {
        output += data.toString();
      });

      check.on('close', (code) => {
        if (code === 0 && output.includes('OK')) {
          resolve({ available: true });
        } else {
          resolve({
            available: false,
            reason: 'PaddleOCR not installed. Run: pip install paddlepaddle paddleocr'
          });
        }
      });
    });
  }

  /**
   * 等待服务启动
   */
  private async waitForService(timeout: number): Promise<void> {
    const startTime = Date.now();
    
    while (Date.now() - startTime < timeout) {
      try {
        const response = await fetch(`http://${this.config.host}:${this.config.port}/health`);
        if (response.ok) {
          return;
        }
      } catch {
        // 服务还未启动
      }
      await new Promise(r => setTimeout(r, 500));
    }

    throw new Error('OCR service failed to start within timeout');
  }

  /**
   * 执行命令
   */
  private runCommand(cmd: string, args: string[]): Promise<void> {
    return new Promise((resolve, reject) => {
      const proc = spawn(cmd, args);
      
      proc.on('close', (code) => {
        if (code === 0) {
          resolve();
        } else {
          reject(new Error(`Command failed: ${cmd} ${args.join(' ')}`));
        }
      });

      proc.on('error', reject);
    });
  }

  /**
   * 处理 PDF
   */
  async processPDF(filePath: string): Promise<any> {
    const formData = new FormData();
    
    // 读取文件并创建 blob
    const fs = await import('fs');
    const fileBuffer = fs.readFileSync(filePath);
    const blob = new Blob([fileBuffer]);
    
    formData.append('file', blob, path.basename(filePath));

    const response = await fetch(`http://${this.config.host}:${this.config.port}/ocr/pdf`, {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      throw new Error(`OCR request failed: ${response.statusText}`);
    }

    return response.json();
  }

  /**
   * 停止服务
   */
  async stop(): Promise<void> {
    if (this.config.useDocker) {
      await this.runCommand('docker', ['stop', 'rag-ocr']);
    } else if (this.dockerProcess) {
      this.dockerProcess.kill();
    }
  }
}
