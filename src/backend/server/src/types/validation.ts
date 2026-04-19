/**
 * 输入验证
 * 使用 Zod 进行类型验证和消毒
 */

import { z } from 'zod';

// 会话创建请求验证
export const CreateSessionSchema = z.object({
  query: z.string()
    .min(1, '查询不能为空')
    .max(1000, '查询长度不能超过1000字符')
    .trim()
});

export type CreateSessionRequest = z.infer<typeof CreateSessionSchema>;

// 活动记录请求验证
export const RecordActivitySchema = z.object({
  sessionId: z.string()
    .uuid('无效的会话ID')
});

export type RecordActivityRequest = z.infer<typeof RecordActivitySchema>;

// 登录请求验证
export const LoginSchema = z.object({
  username: z.string()
    .min(1, '用户名不能为空')
    .max(50, '用户名长度不能超过50字符')
    .regex(/^[a-zA-Z0-9_]+$/, '用户名只能包含字母、数字和下划线'),
  password: z.string()
    .min(6, '密码长度不能少于6位')
    .max(100, '密码长度不能超过100字符')
});

export type LoginRequest = z.infer<typeof LoginSchema>;

// 分页查询验证
export const PaginationSchema = z.object({
  page: z.coerce.number()
    .int()
    .min(1, '页码必须大于0')
    .default(1),
  pageSize: z.coerce.number()
    .int()
    .min(1, '每页数量必须大于0')
    .max(100, '每页数量不能超过100')
    .default(10)
});

export type PaginationParams = z.infer<typeof PaginationSchema>;

// OCR任务提交验证
export const OCRJobSchema = z.object({
  filePath: z.string()
    .min(1, '文件路径不能为空')
    .regex(/\.(pdf|png|jpg|jpeg)$/i, '只支持PDF和图片文件')
    .refine(path => !path.includes('..'), '非法路径'),
  config: z.object({
    language: z.enum(['ch', 'en', 'ch_en']).optional(),
    enhanceImage: z.boolean().optional()
  }).optional()
});

export type OCRJobRequest = z.infer<typeof OCRJobSchema>;

// 查询参数验证辅助函数
export function validate<T>(schema: z.ZodSchema<T>, data: unknown): { success: true; data: T } | { success: false; errors: string[] } {
  const result = schema.safeParse(data);
  
  if (result.success) {
    return { success: true, data: result.data };
  }
  
  const errors = result.error.errors.map(e => `${e.path.join('.')}: ${e.message}`);
  return { success: false, errors };
}
