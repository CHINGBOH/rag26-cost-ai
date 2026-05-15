/**
 * 认证服务 - 安全强化版
 * 基础的用户认证和授权
 */

import * as crypto from 'crypto';
import { SignJWT, jwtVerify } from 'jose';

interface User {
  id: string;
  username: string;
  role: 'admin' | 'user';
  createdAt: number;
  passwordHash: string;
}

interface AuthToken {
  userId: string;
  username: string;
  role: string;
  iat: number;
  exp: number;
}

interface AuthConfig {
  secretKey: string;
  tokenExpiry: number; // 秒
  defaultAdminUsername: string;
  defaultAdminPassword: string;
}

export class AuthService {
  private config: AuthConfig;
  private users: Map<string, User> = new Map();
  private sessions: Map<string, string> = new Map(); // token -> userId
  private initialized: boolean = false;

  constructor(config: AuthConfig) {
    if (!config.secretKey) {
      throw new Error('AUTH_SECRET环境变量必须设置');
    }

    this.config = config;

    // 延迟初始化默认用户，避免在代码中保留硬编码默认密码
    this.initializeDefaultUser();
  }

  /**
   * 获取密钥字节
   */
  private getSecretKey(): Uint8Array {
    return new TextEncoder().encode(this.config.secretKey);
  }

  /**
   * 初始化默认管理员用户
   * 使用环境变量设置初始密码
   */
  private initializeDefaultUser(): void {
    const { defaultAdminUsername, defaultAdminPassword } = this.config;

    if (!defaultAdminPassword) {
      console.warn('[AuthService] 未配置默认管理员密码，跳过默认管理员引导');
      this.initialized = true;
      return;
    }

    this.createUser(defaultAdminUsername, defaultAdminPassword, 'admin');
    console.log(`[AuthService] 默认管理员用户已创建: ${defaultAdminUsername}`);

    this.initialized = true;
  }

  /**
   * 创建用户
   */
  createUser(username: string, password: string, role: 'admin' | 'user' = 'user'): User {
    // 验证密码强度
    if (password.length < 8) {
      throw new Error('密码长度不能少于8位');
    }

    const id = crypto.randomUUID();
    const passwordHash = this.hashPassword(password);

    const user: User = {
      id,
      username,
      role,
      createdAt: Date.now(),
      passwordHash
    };

    this.users.set(id, user);
    this.users.set(`username:${username}`, user); // 索引

    console.log(`[AuthService] 创建用户: ${username} (${role})`);
    return user;
  }

  /**
   * 用户登录
   */
  async login(username: string, password: string): Promise<{ token: string; user: Omit<User, 'passwordHash'> } | null> {
    const user = this.users.get(`username:${username}`);

    if (!user) {
      console.warn(`[AuthService] 登录失败: 用户不存在 ${username}`);
      return null;
    }

    // 验证密码
    if (!this.verifyPassword(password, user.passwordHash)) {
      console.warn(`[AuthService] 登录失败: 密码错误 ${username}`);
      return null;
    }

    const token = await this.generateToken(user);
    this.sessions.set(token, user.id);

    console.log(`[AuthService] 用户登录: ${username}`);

    // 返回用户信息（不含密码哈希）
    const { passwordHash, ...userWithoutPassword } = user;
    return { token, user: userWithoutPassword };
  }

  /**
   * 验证Token - 使用jose库
   */
  async verifyToken(token: string): Promise<AuthToken | null> {
    try {
      const secretKey = this.getSecretKey();
      const { payload } = await jwtVerify(token, secretKey);

      // 检查session
      if (!this.sessions.has(token)) {
        return null;
      }

      return {
        userId: payload.sub as string,
        username: payload.username as string,
        role: payload.role as string,
        iat: payload.iat!,
        exp: payload.exp!
      };
    } catch (error) {
      return null;
    }
  }

  /**
   * 登出
   */
  logout(token: string): void {
    this.sessions.delete(token);
    console.log('[AuthService] 用户登出');
  }

  /**
   * 获取用户信息（不含密码）
   */
  getUser(userId: string): Omit<User, 'passwordHash'> | undefined {
    const user = this.users.get(userId);
    if (!user) return undefined;

    const { passwordHash, ...userWithoutPassword } = user;
    return userWithoutPassword;
  }

  /**
   * 检查权限
   */
  async hasPermission(token: string, requiredRole: 'admin' | 'user'): Promise<boolean> {
    const payload = await this.verifyToken(token);
    if (!payload) return false;

    if (requiredRole === 'admin') {
      return payload.role === 'admin';
    }

    return true;
  }

  /**
   * 生成Token - 使用jose库实现真正的JWT
   */
  private async generateToken(user: User): Promise<string> {
    const secretKey = this.getSecretKey();

    return await new SignJWT({
      username: user.username,
      role: user.role
    })
      .setProtectedHeader({ alg: 'HS256' })
      .setSubject(user.id)
      .setIssuedAt()
      .setExpirationTime(`${this.config.tokenExpiry}s`)
      .sign(secretKey);
  }

  /**
   * 为外部模块（注册服务等）签发 token
   * Issue #156 — 让 RegistrationService 创建的用户也能拿到与 admin 同型的 JWT
   */
  async issueTokenForUser(input: { id: string; username: string; role: 'user' | 'admin' }): Promise<string> {
    const secretKey = this.getSecretKey();
    return await new SignJWT({ username: input.username, role: input.role })
      .setProtectedHeader({ alg: 'HS256' })
      .setSubject(input.id)
      .setIssuedAt()
      .setExpirationTime(`${this.config.tokenExpiry}s`)
      .sign(secretKey);
  }

  /**
   * 密码哈希 - 使用PBKDF2增强安全性
   */
  private hashPassword(password: string): string {
    // 生成随机盐值
    const salt = crypto.randomBytes(16).toString('hex');
    // 使用PBKDF2进行10000次迭代
    const hash = crypto.pbkdf2Sync(password, salt + this.config.secretKey, 10000, 64, 'sha256').toString('hex');
    // 返回格式: 盐值$哈希值
    return `${salt}$${hash}`;
  }

  /**
   * 验证密码
   */
  private verifyPassword(password: string, storedHash: string): boolean {
    const parts = storedHash.split('$');
    if (parts.length !== 2) return false;

    const [salt, hash] = parts;
    const computedHash = crypto.pbkdf2Sync(password, salt + this.config.secretKey, 10000, 64, 'sha256').toString('hex');

    try {
      return crypto.timingSafeEqual(Buffer.from(hash), Buffer.from(computedHash));
    } catch {
      return false;
    }
  }

  /**
   * 获取在线用户数量
   */
  getOnlineCount(): number {
    return this.sessions.size;
  }

  /**
   * 清理过期会话
   */
  async cleanupSessions(): Promise<void> {
    for (const [token, userId] of this.sessions) {
      const isValid = await this.verifyToken(token);
      if (!isValid) {
        this.sessions.delete(token);
      }
    }
    console.log(`[AuthService] 清理会话完成，当前在线: ${this.sessions.size}`);
  }
}
