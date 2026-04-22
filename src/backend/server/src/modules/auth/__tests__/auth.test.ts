/**
 * 认证模块测试
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  authenticate,
  createToken,
  verifyToken,
  authorize,
  hasRole,
  refreshToken,
  revokeToken,
  createAuthPipeline
} from '../src'
import { User } from '../../common/types'

describe('Auth 模块', () => {
  describe('Token 创建与验证', () => {
    it('应该创建 Token', async () => {
      const user: User = {
        id: '1',
        username: 'admin',
        roles: ['admin'],
        permissions: ['*:*'],
        createdAt: Date.now()
      }
      
      const tokenFn = createToken()
      const authToken = await tokenFn(user)
      
      expect(authToken.token).toBeDefined()
      expect(authToken.refreshToken).toBeDefined()
      expect(authToken.user).toEqual(user)
    })

    it('应该验证 Token 并返回用户', async () => {
      const user: User = {
        id: '1',
        username: 'admin',
        roles: ['admin'],
        permissions: ['*:*'],
        createdAt: Date.now()
      }
      
      const tokenFn = createToken()
      const authToken = await tokenFn(user)
      
      const verifyFn = verifyToken()
      const verifiedUser = await verifyFn(authToken.token)
      
      expect(verifiedUser.id).toBe(user.id)
      expect(verifiedUser.username).toBe(user.username)
    })

    it('应该拒绝无效 Token', async () => {
      const verifyFn = verifyToken()
      
      await expect(verifyFn('invalid-token')).rejects.toThrow('Invalid token')
    })
  })

  describe('用户认证', () => {
    it('应该成功认证有效用户', async () => {
      const auth = authenticate()
      
      const user = await auth({
        username: 'admin',
        password: 'admin123'
      })
      
      expect(user.username).toBe('admin')
      expect(user.roles).toContain('admin')
    })

    it('应该拒绝无效凭据', async () => {
      const auth = authenticate()
      
      await expect(auth({
        username: 'admin',
        password: 'wrong-password'
      })).rejects.toThrow('Invalid credentials')
    })

    it('应该拒绝未知用户', async () => {
      const auth = authenticate()
      
      await expect(auth({
        username: 'unknown',
        password: 'password'
      })).rejects.toThrow('Invalid credentials')
    })
  })

  describe('权限检查', () => {
    it('应该检查通过有效权限', () => {
      const user: User = {
        id: '1',
        username: 'admin',
        roles: ['admin'],
        permissions: ['read:*', 'write:docs'],
        createdAt: Date.now()
      }
      
      const check = authorize('read:docs')
      const result = check(user)
      
      expect(result).toEqual(user)
    })

    it('应该检查通过通配符权限', () => {
      const user: User = {
        id: '1',
        username: 'admin',
        roles: ['admin'],
        permissions: ['*:*'],
        createdAt: Date.now()
      }
      
      const check = authorize('delete:all')
      const result = check(user)
      
      expect(result).toEqual(user)
    })

    it('应该拒绝无权限用户', () => {
      const user: User = {
        id: '1',
        username: 'user',
        roles: ['user'],
        permissions: ['read:docs'],
        createdAt: Date.now()
      }
      
      const check = authorize('write:docs')
      
      expect(() => check(user)).toThrow('Unauthorized')
    })
  })

  describe('角色检查', () => {
    it('应该检查通过有效角色', () => {
      const user: User = {
        id: '1',
        username: 'admin',
        roles: ['admin', 'user'],
        permissions: [],
        createdAt: Date.now()
      }
      
      const check = hasRole('admin')
      const result = check(user)
      
      expect(result).toEqual(user)
    })

    it('应该拒绝无角色用户', () => {
      const user: User = {
        id: '1',
        username: 'user',
        roles: ['user'],
        permissions: [],
        createdAt: Date.now()
      }
      
      const check = hasRole('admin')
      
      expect(() => check(user)).toThrow('Required role')
    })
  })

  describe('Token 刷新与撤销', () => {
    it('应该刷新 Token', async () => {
      const user: User = {
        id: '1',
        username: 'admin',
        roles: ['admin'],
        permissions: ['*:*'],
        createdAt: Date.now()
      }
      
      const createTokenFn = createToken()
      const authToken = await createTokenFn(user)
      
      const refreshFn = refreshToken()
      const newToken = await refreshFn(authToken.refreshToken!)
      
      expect(newToken.token).toBeDefined()
      // 验证新 Token 有效即可
      const verifyFn = verifyToken()
      const verifiedUser = await verifyFn(newToken.token)
      expect(verifiedUser.id).toBe(user.id)
      expect(verifiedUser.username).toBe(user.username)
    })

    it('应该拒绝无效 Refresh Token', async () => {
      const refreshFn = refreshToken()
      
      await expect(refreshFn('invalid-refresh-token')).rejects.toThrow('Invalid refresh token')
    })

    it('应该撤销 Token', async () => {
      const user: User = {
        id: '1',
        username: 'admin',
        roles: ['admin'],
        permissions: ['*:*'],
        createdAt: Date.now()
      }
      
      const createTokenFn = createToken()
      const authToken = await createTokenFn(user)
      
      const revokeFn = revokeToken()
      const result = revokeFn(authToken.token)
      
      expect(result).toBe(true)
      
      // 验证 Token 已失效
      const verifyFn = verifyToken()
      await expect(verifyFn(authToken.token)).rejects.toThrow('Invalid token')
    })
  })

  describe('管道工厂', () => {
    it('应该创建认证管道', () => {
      const pipeline = createAuthPipeline()
      
      expect(pipeline.authenticate).toBeDefined()
      expect(pipeline.createToken).toBeDefined()
      expect(pipeline.verifyToken).toBeDefined()
      expect(pipeline.authorize).toBeDefined()
      expect(pipeline.hasRole).toBeDefined()
      expect(pipeline.refreshToken).toBeDefined()
      expect(pipeline.revokeToken).toBeDefined()
    })

    it('应该使用管道进行认证流程', async () => {
      const pipeline = createAuthPipeline()
      
      // 认证用户
      const user = await pipeline.authenticate({
        username: 'admin',
        password: 'admin123'
      })
      
      // 创建 Token
      const authToken = await pipeline.createToken(user)
      expect(authToken.token).toBeDefined()
      
      // 验证 Token
      const verifiedUser = await pipeline.verifyToken(authToken.token)
      expect(verifiedUser.username).toBe('admin')
    })
  })
})
