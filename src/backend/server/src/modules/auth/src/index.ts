/**
 * 认证模块 - 身份验证与权限控制
 * 提供管道式认证接口
 */

import { User, AuthCredentials, AuthToken } from '../../common/types'
import { SignJWT, jwtVerify } from 'jose'

export interface AuthConfig {
  secret: string
  expiresIn: number
  refreshExpiresIn: number
}

export interface Permission {
  resource: string
  action: string
}

const defaultConfig: AuthConfig = {
  secret: process.env.JWT_SECRET || '',
  expiresIn: 3600, // 1小时
  refreshExpiresIn: 7 * 24 * 3600 // 7天
}

// 验证JWT_SECRET必须设置
if (!defaultConfig.secret) {
  throw new Error('JWT_SECRET environment variable must be set')
}

// 获取密钥字节
function getSecretKey(secret: string): Uint8Array {
  return new TextEncoder().encode(secret)
}

// 模拟用户数据库 - 生产环境应使用真实数据库
const users: Map<string, User & { password: string }> = new Map([
  ['admin', {
    id: '1',
    username: 'admin',
    password: process.env.DEFAULT_ADMIN_PASSWORD || 'admin123', // 从环境变量读取
    roles: ['admin'],
    permissions: ['*:*'],
    createdAt: Date.now()
  }]
])

// 会话存储
const sessions: Map<string, AuthToken> = new Map()

/**
 * 认证用户
 */
export function authenticate(config?: Partial<AuthConfig>) {
  return async function auth(credentials: AuthCredentials): Promise<User> {
    const user = users.get(credentials.username)

    if (!user || user.password !== credentials.password) {
      throw new Error('Invalid credentials')
    }

    const { password, ...userWithoutPassword } = user
    return userWithoutPassword
  }
}

/**
 * 创建Token - 使用jose库实现真正的JWT
 */
export function createToken(config?: Partial<AuthConfig>) {
  const cfg = { ...defaultConfig, ...config }

  return async function generate(user: User): Promise<AuthToken> {
    const secretKey = getSecretKey(cfg.secret)

    // 创建访问令牌
    const token = await new SignJWT({
      sub: user.id,
      username: user.username,
      roles: user.roles
    })
      .setProtectedHeader({ alg: 'HS256' })
      .setIssuedAt()
      .setExpirationTime(`${cfg.expiresIn}s`)
      .sign(secretKey)

    // 创建刷新令牌
    const refreshToken = await new SignJWT({
      sub: user.id,
      type: 'refresh'
    })
      .setProtectedHeader({ alg: 'HS256' })
      .setIssuedAt()
      .setExpirationTime(`${cfg.refreshExpiresIn}s`)
      .sign(secretKey)

    const authToken: AuthToken = {
      token,
      refreshToken,
      expiresAt: Date.now() + cfg.expiresIn * 1000,
      user
    }

    sessions.set(token, authToken)
    return authToken
  }
}

/**
 * 验证Token
 */
export function verifyToken(config?: Partial<AuthConfig>) {
  const cfg = { ...defaultConfig, ...config }

  return async function verify(token: string): Promise<User> {
    const session = sessions.get(token)

    if (!session) {
      throw new Error('Invalid token')
    }

    if (Date.now() > session.expiresAt) {
      sessions.delete(token)
      throw new Error('Token expired')
    }

    return session.user
  }
}

/**
 * 解码并验证JWT（不验证session，用于外部验证）
 */
export async function decodeAndVerifyJWT(token: string, secret: string): Promise<User> {
  const secretKey = getSecretKey(secret)
  const { payload } = await jwtVerify(token, secretKey)

  return {
    id: payload.sub as string,
    username: payload.username as string,
    roles: payload.roles as string[],
    permissions: ['*:*'],
    createdAt: Date.now()
  }
}

/**
 * 授权检查
 */
export function authorize(permission: string) {
  return function check(user: User): User {
    const [resource, action] = permission.split(':')

    const hasPermission = user.permissions.some(p => {
      if (p === '*:*') return true
      const [userResource, userAction] = p.split(':')
      return (userResource === '*' || userResource === resource) &&
             (userAction === '*' || userAction === action)
    })

    if (!hasPermission) {
      throw new Error(`Unauthorized: ${permission}`)
    }

    return user
  }
}

/**
 * 检查角色
 */
export function hasRole(role: string) {
  return function check(user: User): User {
    if (!user.roles.includes(role)) {
      throw new Error(`Required role: ${role}`)
    }
    return user
  }
}

/**
 * 刷新Token
 */
export function refreshToken(config?: Partial<AuthConfig>) {
  return async function refresh(refreshTokenValue: string): Promise<AuthToken> {
    const secretKey = getSecretKey(defaultConfig.secret)

    // 验证刷新令牌
    try {
      const { payload } = await jwtVerify(refreshTokenValue, secretKey)
      if (payload.type !== 'refresh') {
        throw new Error('Invalid refresh token type')
      }

      // 查找原会话
      for (const [token, session] of sessions) {
        if (session.refreshToken === refreshTokenValue) {
          return createToken(config)(session.user)
        }
      }
    } catch (e) {
      throw new Error('Invalid refresh token')
    }

    throw new Error('Refresh token not found')
  }
}

/**
 * 注销
 */
export function revokeToken() {
  return function revoke(token: string): boolean {
    return sessions.delete(token)
  }
}

/**
 * 创建认证管道
 */
export function createAuthPipeline(config?: Partial<AuthConfig>) {
  return {
    authenticate: authenticate(config),
    createToken: createToken(config),
    verifyToken: verifyToken(config),
    authorize: (permission: string) => authorize(permission),
    hasRole: (role: string) => hasRole(role),
    refreshToken: refreshToken(config),
    revokeToken: revokeToken()
  }
}
