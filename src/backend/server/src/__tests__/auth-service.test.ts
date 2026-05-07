import { describe, expect, it } from 'vitest';

import { AuthService } from '../services/AuthService';

const authServiceConfig = {
  secretKey: 'test-auth-secret',
  tokenExpiry: 24 * 60 * 60,
  defaultAdminUsername: 'admin',
  defaultAdminPassword: 'admin123',
};

describe('AuthService', () => {
  it('authenticates the bootstrapped admin when a password is configured', async () => {
    const authService = new AuthService(authServiceConfig);

    const result = await authService.login('admin', 'admin123');

    expect(result?.user.username).toBe('admin');
    expect(result?.token).toBeDefined();
  });

  it('skips admin bootstrap when no password is configured', async () => {
    const authService = new AuthService({
      ...authServiceConfig,
      defaultAdminPassword: '',
    });

    const result = await authService.login('admin', 'admin123');

    expect(result).toBeNull();
  });

  it('requires a non-empty auth secret', () => {
    expect(
      () =>
        new AuthService({
          ...authServiceConfig,
          secretKey: '',
        }),
    ).toThrow('AUTH_SECRET环境变量必须设置');
  });
});
