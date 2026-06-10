import logging
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

_DEV_SECRET_KEY = 'paikuan-dev-key-change-in-prod-xK9mL2nP'
_DEV_JWT_SECRET = 'paikuan-jwt-secret-change-in-prod-Qr8sT1uV'

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', _DEV_SECRET_KEY)
JWT_SECRET = os.environ.get('JWT_SECRET', _DEV_JWT_SECRET)

# DeepSeek AI API (stored via env var; fallback for dev only)
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', 'sk-d7721aa1a60b4a7c9b93181e9cfe7cfc')
DEEPSEEK_MODEL = os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')
# 更强的模型，用于「财务驾驶舱」全集团高度的综合分析（推理量更大）。
# 生产可经环境变量切到 V4 Pro 等更强模型，如 DEEPSEEK_PRO_MODEL=deepseek-reasoner。
DEEPSEEK_PRO_MODEL = os.environ.get('DEEPSEEK_PRO_MODEL', 'deepseek-reasoner')
DEEPSEEK_BASE_URL = 'https://api.deepseek.com/v1'

if SECRET_KEY == _DEV_SECRET_KEY or JWT_SECRET == _DEV_JWT_SECRET:
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
