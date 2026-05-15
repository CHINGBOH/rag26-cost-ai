-- Issue #156 — 普通用户注册/登录基础表
-- 兼容现有 admin (来自 config) 在内存 Map 中的默认登录，DB 是普通用户的持久化层

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS app_users (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone             TEXT,
  email             TEXT,
  password_hash     TEXT,
  display_name      TEXT,
  role              TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
  status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled','pending')),
  registered_ip     INET,
  registered_ua     TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at     TIMESTAMPTZ,
  last_login_ip     INET,
  CONSTRAINT app_users_at_least_one_identifier CHECK (phone IS NOT NULL OR email IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_app_users_phone ON app_users(phone) WHERE phone IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_app_users_email ON app_users(email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_app_users_created_at ON app_users(created_at DESC);

-- 验证码（短信/邮箱）— 一次性消费，发码后 5 分钟内有效
CREATE TABLE IF NOT EXISTS verification_codes (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  channel           TEXT NOT NULL CHECK (channel IN ('sms','email')),
  recipient         TEXT NOT NULL,
  code_hash         TEXT NOT NULL,
  purpose           TEXT NOT NULL CHECK (purpose IN ('register','login','reset','bind')),
  expires_at        TIMESTAMPTZ NOT NULL,
  consumed_at       TIMESTAMPTZ,
  attempt_count     INT NOT NULL DEFAULT 0,
  client_ip         INET,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vc_recipient_purpose ON verification_codes(recipient, purpose, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_vc_expires ON verification_codes(expires_at) WHERE consumed_at IS NULL;

-- 注册/发码审计：用于反机器人和事后追责
CREATE TABLE IF NOT EXISTS auth_audit_log (
  id                BIGSERIAL PRIMARY KEY,
  event_type        TEXT NOT NULL,   -- send_code|register|login_password|login_code|logout|captcha_fail|rate_limited
  recipient         TEXT,
  user_id           UUID REFERENCES app_users(id),
  client_ip         INET,
  client_ua         TEXT,
  success           BOOLEAN NOT NULL,
  detail            JSONB,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_aal_event_time ON auth_audit_log(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_aal_ip_time ON auth_audit_log(client_ip, created_at DESC);
