import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-kxt-2026-dev-key-change-in-production'
)

DEBUG = os.environ.get('DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'wxcloudrun',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# CORS 配置 — 允许所有来源（内部使用，风险可控）
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = False

ROOT_URLCONF = 'wxcloudrun.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'wxcloudrun.wsgi.application'

# 数据库配置 — 优先使用云托管注入的环境变量
# 兼容两种模式：云托管内置MySQL 和 外部自建MySQL
_db_addr  = os.environ.get('MYSQL_ADDRESS', '')
_db_user  = os.environ.get('MYSQL_USERNAME', 'root')
_db_pass  = os.environ.get('MYSQL_PASSWORD', '')
_db_name  = os.environ.get('MYSQL_DATABASE', 'kxt')

# 解析地址：支持 "host" 或 "host:port" 两种格式
if _db_addr:
    if ':' in _db_addr:
        _db_host, _db_port = _db_addr.rsplit(':', 1)
    else:
        _db_host = _db_addr
        _db_port = '3306'
else:
    _db_host = '127.0.0.1'
    _db_port = '3306'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': _db_name,
        'USER': _db_user,
        'HOST': _db_host,
        'PORT': int(_db_port),
        'PASSWORD': _db_pass,
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_L10N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# JWT 配置
JWT_SECRET = os.environ.get('JWT_SECRET', 'kxt-jwt-dev-secret-change-in-production')
WX_APPID   = os.environ.get('WX_APPID', '')
WX_SECRET  = os.environ.get('WX_SECRET', '')

# AI 大模型 API（DeepSeek，OpenAI 兼容协议）
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', os.environ.get('CLAUDE_API_KEY', ''))
DEEPSEEK_BASE    = os.environ.get('DEEPSEEK_BASE', 'https://api.deepseek.com/v1')
DEEPSEEK_MODEL   = os.environ.get('DEEPSEEK_MODEL', 'deepseek-v4-flash')

# 日志配置
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] [{filename}:{lineno}] [{levelname}] - {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'wxcloudrun': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}
