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
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
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

DATABASE_ROUTERS = ['caiwu.db_router.CaiwuRouter']

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

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
