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
# 业财融合助手工具调用循环所用模型：默认走 PRO 模型（DeepSeek V3.1 起 reasoner/
# 思考模式已支持 function-calling），让助手以最强推理驱动多步取数与作答。
# 若某部署所连端点在该模型上不支持 tools，会自动降级到 DEEPSEEK_FALLBACK_MODEL。
DEEPSEEK_AGENT_MODEL = os.environ.get('DEEPSEEK_AGENT_MODEL', '') or DEEPSEEK_PRO_MODEL
# 主模型异常（超时/限流/不支持 tools）时的降级模型：默认退回支持 tools 的基础
# 对话模型，保证助手可用性。
DEEPSEEK_FALLBACK_MODEL = os.environ.get('DEEPSEEK_FALLBACK_MODEL', 'deepseek-chat')
DEEPSEEK_BASE_URL = 'https://api.deepseek.com/v1'

# 钉钉审批流对接：仅从环境变量读取，源码不内置任何密钥。
# 未配置时回调接口返回 503「未配置」，不影响其余功能。
DINGTALK_APP_KEY = os.environ.get('DINGTALK_APP_KEY', '')
DINGTALK_APP_SECRET = os.environ.get('DINGTALK_APP_SECRET', '')          # 敏感，仅环境变量
DINGTALK_CORP_ID = os.environ.get('DINGTALK_CORP_ID', '')
DINGTALK_PROCESS_CODE = os.environ.get('DINGTALK_PROCESS_CODE', '')       # 审批模板 process_code
# 事件订阅回调加解密（钉钉后台"事件订阅"里生成）：
DINGTALK_AES_KEY = os.environ.get('DINGTALK_AES_KEY', '')                 # 敏感，仅环境变量
DINGTALK_CALLBACK_TOKEN = os.environ.get('DINGTALK_CALLBACK_TOKEN', '')   # 敏感，仅环境变量
# 回调明文尾部校验用 key：企业内部应用事件订阅=AppKey；个别后台用 CorpId，则显式配此项覆盖。
DINGTALK_CALLBACK_KEY = os.environ.get('DINGTALK_CALLBACK_KEY', '') or DINGTALK_APP_KEY
DINGTALK_BASE_URL = 'https://oapi.dingtalk.com'
# 要纳入同步的审批模板：逗号分隔，支持 "code:名称,code:名称" 或纯 code。
# 财务口径通常纳入全部相关审批模板；留空时尝试用 DINGTALK_ADMIN_USERID 枚举其可见模板。
DINGTALK_PROCESS_CODES = os.environ.get('DINGTALK_PROCESS_CODES', '')
DINGTALK_ADMIN_USERID = os.environ.get('DINGTALK_ADMIN_USERID', '')

# 联网搜索（Agent 参考同行/行业研究用）：默认内置必应中国抓取（无需配置）；
# SEARCH_PROVIDER: 'bocha'（博查，国内直连）或 'serper'（Google via serper.dev）
SEARCH_PROVIDER = os.environ.get('SEARCH_PROVIDER', '')
SEARCH_API_KEY = os.environ.get('SEARCH_API_KEY', '')
# 联网检索：web_search / web_fetch 常开（内置必应中国抓取，无需 Key），用于行业趋势、
# 政策、同行财报等外部信息的即时查询——正常经营问答需要联网时开箱即用。
# 同行"一键调研"流水线（peer_research：搜索→读源→AI 提炼→查重→自动沉淀知识库）是
# 可选的重功能，默认关闭；需要时置 ENABLE_PEER_RESEARCH=1 开启。
ENABLE_PEER_RESEARCH = (os.environ.get('ENABLE_PEER_RESEARCH', '').strip().lower()
                        in ('1', 'true', 'yes', 'on'))

# ── AI Token 成本控制 ─────────────────────────────────────────────────────────
# 全组织每日 token 预算（输入+输出合计）：达到后当日 AI 功能暂停、次日自动恢复；
# 0 = 不限。默认 500 万 tokens/日（按 DeepSeek 定价上限约几十元/日）。
AI_DAILY_TOKEN_BUDGET = int(os.environ.get('AI_DAILY_TOKEN_BUDGET', 5_000_000))
# 成本估算单价（元/百万 tokens，仅用于用量页折算展示，不影响计量）
AI_PRICE_IN_PER_M = float(os.environ.get('AI_PRICE_IN_PER_M', 2.0))
AI_PRICE_OUT_PER_M = float(os.environ.get('AI_PRICE_OUT_PER_M', 8.0))

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
