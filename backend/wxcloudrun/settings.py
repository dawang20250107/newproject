import logging
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

_DEV_SECRET_KEY = 'paikuan-dev-key-change-in-prod-xK9mL2nP'
_DEV_JWT_SECRET = 'paikuan-jwt-secret-change-in-prod-Qr8sT1uV'

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', _DEV_SECRET_KEY)
JWT_SECRET = os.environ.get('JWT_SECRET', _DEV_JWT_SECRET)

# DeepSeek AI API：仅从环境变量读取，源码不内置任何密钥。
# 未设置时 AI 相关接口会优雅返回「未配置」(503)，不影响其余功能。
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
DEEPSEEK_MODEL = os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')
# 更强的模型，用于「财务驾驶舱」全集团高度的综合分析（推理量更大）。
# 生产可经环境变量切到 V4 Pro 等更强模型，如 DEEPSEEK_PRO_MODEL=deepseek-reasoner。
DEEPSEEK_PRO_MODEL = os.environ.get('DEEPSEEK_PRO_MODEL', 'deepseek-reasoner')
DEEPSEEK_BASE_URL = 'https://api.deepseek.com/v1'

# 生产判定：设置了 MYSQL_ADDRESS 即视为生产（与下方 DATABASES 选择同一信号）。
_IS_PROD = bool(os.environ.get('MYSQL_ADDRESS'))
_USING_DEV_SECRET = SECRET_KEY == _DEV_SECRET_KEY or JWT_SECRET == _DEV_JWT_SECRET
if _USING_DEV_SECRET:
    if _IS_PROD:
        # 生产仍用入库默认密钥 = 攻击者可离线伪造任意审批人/管理员 JWT。
        # 直接拒绝启动，迫使运维设置环境变量（最常见的是迁移/重装时漏配）。
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(
            'SECURITY: 生产环境（已设置 MYSQL_ADDRESS）检测到默认密钥，拒绝启动。'
            '请先设置 DJANGO_SECRET_KEY 与 JWT_SECRET 环境变量再启动。'
        )
    logging.warning(
        'SECURITY: Using insecure dev secrets. '
        'Set DJANGO_SECRET_KEY and JWT_SECRET environment variables in production.'
    )

DEBUG = os.environ.get('DEBUG', 'False').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [
    'kxtshare.cloud',
    'localhost',
    '127.0.0.1',
]
# 允许经环境变量追加 Host（云托管/k8s 健康探针常按 Pod IP 或内网域名直连，
# 否则 CommonMiddleware 会以 400 拒绝探针 → 实例被误判不健康）。
_EXTRA_HOSTS = os.environ.get('EXTRA_ALLOWED_HOSTS', '')
if _EXTRA_HOSTS:
    ALLOWED_HOSTS += [h.strip() for h in _EXTRA_HOSTS.split(',') if h.strip()]

INSTALLED_APPS = [
    'corsheaders',
    'wxcloudrun',
    'paikuan',
    'caiwu',
    'ar.apps.ArConfig',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
    # 全系统操作审计：自动记录所有 API 写操作（谁/何时/何接口/何参数/结果）
    'paikuan.middleware.AuditLogMiddleware',
]

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [
    'https://kxtshare.cloud',
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'http://localhost:5174',
    'http://127.0.0.1:5174',
    'http://localhost:8080',
]
CORS_ALLOW_CREDENTIALS = False

ROOT_URLCONF = 'wxcloudrun.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {},
}]

WSGI_APPLICATION = 'wxcloudrun.wsgi.application'

# SQLite for dev; set MYSQL_ADDRESS for prod
if os.environ.get('MYSQL_ADDRESS'):
    addr = os.environ.get('MYSQL_ADDRESS', '127.0.0.1:3306')
    host, port = addr.rsplit(':', 1) if ':' in addr else (addr, '3306')
    _mysql_base = {
        'ENGINE': 'django.db.backends.mysql',
        'USER': os.environ.get('MYSQL_USERNAME', 'root'),
        'PASSWORD': os.environ.get('MYSQL_PASSWORD', ''),
        'HOST': host,
        'PORT': port,
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
        'CONN_MAX_AGE': 60,
    }
    DATABASES = {
        'default': {**_mysql_base, 'NAME': os.environ.get('MYSQL_DATABASE', 'paikuan')},
        'caiwu':   {**_mysql_base, 'NAME': os.environ.get('CAIWU_DB', 'caiwu')},
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        },
        'caiwu': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'caiwu.sqlite3',
        },
    }

# ── caiwu 已并入 default 库（平台整合阶段1）。保留 'caiwu' 连接仅作为历史
# 数据搬运源（manage.py migrate_caiwu_to_default 使用），不再通过 router 路由。
# 待数据确认无误、生产搬运完成后，可移除 'caiwu' 连接与旧库文件。
DATABASE_ROUTERS = []

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_ROOT = BASE_DIR / 'uploads'
UPLOAD_MAX_MB = int(os.environ.get('UPLOAD_MAX_MB', '20'))
# X-Accel-Redirect: set to '/protected-media/' in nginx production config
X_ACCEL_REDIRECT_BASE = os.environ.get('X_ACCEL_REDIRECT_BASE', '')

# W039: MySQL 不支持条件唯一约束 (UniqueConstraint(condition=...))。
# 我们已知 paikuan.Payment.uniq_payment_business_key 在 MySQL 上不会真正建出，
# 业务唯一性由应用层 _find_duplicate_payment + select_for_update 兜底；
# SQLite/PostgreSQL 仍按条件唯一索引正常工作。
SILENCED_SYSTEM_CHECKS = ['models.W039']

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'paikuan': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': False},
        'caiwu': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': False},
    },
}


# ── 可观测性：Sentry 错误追踪 + Prometheus 指标 ─────────────────────────────────
# 均为「可选依赖」：未安装或未配置时静默跳过，绝不影响启动（开发/CI 无需安装）。
def _has_module(name):
    import importlib.util
    return importlib.util.find_spec(name) is not None


# Prometheus RED 指标：装了 django_prometheus 即自动启用，/metrics 暴露
# 请求量/延迟/状态码（按视图维度），供 Prometheus 抓取与告警。
PROMETHEUS_ENABLED = _has_module('django_prometheus')
if PROMETHEUS_ENABLED:
    if 'django_prometheus' not in INSTALLED_APPS:
        INSTALLED_APPS = INSTALLED_APPS + ['django_prometheus']
    # Before 必须首位、After 必须末位（包裹整条中间件链以测全程耗时）。
    MIDDLEWARE = (
        ['django_prometheus.middleware.PrometheusBeforeMiddleware']
        + MIDDLEWARE
        + ['django_prometheus.middleware.PrometheusAfterMiddleware']
    )

# Sentry：仅当装了 sentry-sdk 且设置了 SENTRY_DSN 才初始化。
SENTRY_DSN = os.environ.get('SENTRY_DSN', '')
if SENTRY_DSN and _has_module('sentry_sdk'):
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=float(os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0.0')),
        send_default_pii=False,   # 财务系统：默认不上送 PII（手机号/姓名）
        environment=os.environ.get('SENTRY_ENV', 'production' if _IS_PROD else 'dev'),
        release=os.environ.get('SENTRY_RELEASE', ''),
    )
