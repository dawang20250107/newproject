import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'paikuan-dev-key-change-in-prod-xK9mL2nP')
JWT_SECRET = os.environ.get('JWT_SECRET', 'paikuan-jwt-secret-change-in-prod-Qr8sT1uV')

DEBUG = os.environ.get('DEBUG', 'True').lower() in ('true', '1', 'yes')
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'corsheaders',
    'wxcloudrun',
    'paikuan',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
]

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = False

ROOT_URLCONF = 'wxcloudrun.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {},
}]

WSGI_APPLICATION = 'wxcloudrun.wsgi.application'

# SQLite for dev; set DB_ENGINE=django.db.backends.mysql + env vars for prod
if os.environ.get('MYSQL_ADDRESS'):
    addr = os.environ.get('MYSQL_ADDRESS', '127.0.0.1:3306')
    host, port = addr.rsplit(':', 1) if ':' in addr else (addr, '3306')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ.get('MYSQL_DATABASE', 'paikuan'),
            'USER': os.environ.get('MYSQL_USERNAME', 'root'),
            'PASSWORD': os.environ.get('MYSQL_PASSWORD', ''),
            'HOST': host,
            'PORT': port,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

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
    },
}
