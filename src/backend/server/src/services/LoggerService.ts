/**
 * 结构化日志服务
 * 统一日志格式，支持结构化输出
 */

import * as fs from 'fs/promises';
import * as path from 'path';

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

interface LogEntry {
  timestamp: string;
  level: LogLevel;
  message: string;
  context?: Record<string, any>;
  service?: string;
  sessionId?: string;
}

interface LoggerConfig {
  level: LogLevel;
  outputFile?: string;
  enableConsole: boolean;
  enableFile: boolean;
  prettyPrint: boolean;
}

class Logger {
  private config: LoggerConfig;
  private logBuffer: LogEntry[] = [];
  private flushTimer: NodeJS.Timeout | null = null;

  constructor(config?: Partial<LoggerConfig>) {
    this.config = {
      level: config?.level || 'info',
      outputFile: config?.outputFile || './logs/app.log',
      enableConsole: config?.enableConsole ?? true,
      enableFile: config?.enableFile ?? false,
      prettyPrint: config?.prettyPrint ?? false
    };

    if (this.config.enableFile) {
      this.ensureLogDir();
      this.startFlushTimer();
    }
  }

  /**
   * 确保日志目录存在
   */
  private async ensureLogDir(): Promise<void> {
    if (this.config.outputFile) {
      const dir = path.dirname(this.config.outputFile);
      try {
        await fs.mkdir(dir, { recursive: true });
      } catch (error) {
        console.error('创建日志目录失败:', error);
      }
    }
  }

  /**
   * 启动定时刷新
   */
  private startFlushTimer(): void {
    this.flushTimer = setInterval(() => {
      this.flush();
    }, 5000); // 5秒刷新一次
  }

  /**
   * 检查日志级别
   */
  private shouldLog(level: LogLevel): boolean {
    const levels: LogLevel[] = ['debug', 'info', 'warn', 'error'];
    return levels.indexOf(level) >= levels.indexOf(this.config.level);
  }

  /**
   * 记录日志
   */
  private log(level: LogLevel, message: string, context?: Record<string, any>): void {
    if (!this.shouldLog(level)) return;

    const entry: LogEntry = {
      timestamp: new Date().toISOString(),
      level,
      message,
      context,
      service: context?.service,
      sessionId: context?.sessionId
    };

    // 输出到控制台
    if (this.config.enableConsole) {
      this.printToConsole(entry);
    }

    // 添加到缓冲区
    if (this.config.enableFile) {
      this.logBuffer.push(entry);
    }
  }

  /**
   * 打印到控制台
   */
  private printToConsole(entry: LogEntry): void {
    const colors = {
      debug: '\x1b[36m', // 青色
      info: '\x1b[32m',  // 绿色
      warn: '\x1b[33m',  // 黄色
      error: '\x1b[31m', // 红色
      reset: '\x1b[0m'
    };

    const color = colors[entry.level];
    const reset = colors.reset;

    if (this.config.prettyPrint) {
      console.log(
        `${color}[${entry.level.toUpperCase()}]${reset} ${entry.timestamp} - ${entry.message}`
      );
      if (entry.context) {
        console.log('  Context:', JSON.stringify(entry.context, null, 2));
      }
    } else {
      const output = this.config.prettyPrint 
        ? `[${entry.level.toUpperCase()}] ${entry.timestamp} - ${entry.message}`
        : JSON.stringify(entry);
      console.log(output);
    }
  }

  /**
   * 刷新缓冲区到文件
   */
  private async flush(): Promise<void> {
    if (this.logBuffer.length === 0 || !this.config.outputFile) return;

    try {
      const lines = this.logBuffer.map(entry => JSON.stringify(entry)).join('\n') + '\n';
      await fs.appendFile(this.config.outputFile, lines, 'utf-8');
      this.logBuffer = [];
    } catch (error) {
      console.error('写入日志文件失败:', error);
    }
  }

  // ==================== 公共方法 ====================

  debug(message: string, context?: Record<string, any>): void {
    this.log('debug', message, context);
  }

  info(message: string, context?: Record<string, any>): void {
    this.log('info', message, context);
  }

  warn(message: string, context?: Record<string, any>): void {
    this.log('warn', message, context);
  }

  error(message: string, context?: Record<string, any>): void {
    this.log('error', message, context);
  }

  /**
   * 创建带上下文的子logger
   */
  child(defaultContext: Record<string, any>) {
    return {
      debug: (msg: string, ctx?: Record<string, any>) => 
        this.debug(msg, { ...defaultContext, ...ctx }),
      info: (msg: string, ctx?: Record<string, any>) => 
        this.info(msg, { ...defaultContext, ...ctx }),
      warn: (msg: string, ctx?: Record<string, any>) => 
        this.warn(msg, { ...defaultContext, ...ctx }),
      error: (msg: string, ctx?: Record<string, any>) => 
        this.error(msg, { ...defaultContext, ...ctx })
    };
  }

  /**
   * 关闭logger
   */
  async close(): Promise<void> {
    if (this.flushTimer) {
      clearInterval(this.flushTimer);
    }
    await this.flush();
  }
}

// 创建全局logger实例
export const logger = new Logger({
  level: (process.env.LOG_LEVEL as LogLevel) || 'info',
  enableConsole: true,
  enableFile: process.env.ENABLE_FILE_LOG === 'true',
  prettyPrint: process.env.NODE_ENV === 'development'
});

export { Logger };
