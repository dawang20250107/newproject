"""请求级审计中间件 — 自动记录所有 API 写操作（POST/PUT/PATCH/DELETE）。

设计原则：
- 永不阻断业务：记录失败只打日志，不影响原请求；
- 自动脱敏：password/token/secret 等敏感键统一掩码；
- 体积可控：multipart（文件导入）只记文件名不记内容，JSON 截断到上限；
- 身份来自视图：pk_required 装饰器在视图里给 request 挂 pk_user，
  中间件在响应阶段读取（视图执行后），无需重复解析 JWT。
"""
import json
import logging

logger = logging.getLogger('paikuan')

_AUDIT_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}
_SENSITIVE_KEYS = ('password', 'token', 'secret', 'api_key')
_MAX_PAYLOAD_CHARS = 4000

# 高频且无审计价值的写接口（none 目前；登录保留——失败登录也是审计事件）
_SKIP_PATHS = ()


def _module_of(path):
    if path.startswith('/api/pk/ar/'):
        return 'ar'
    if path.startswith('/api/cw/'):
        return 'caiwu'
    if path.startswith('/api/pk/'):
        return 'paikuan'
    return ''


def _sanitize(obj, depth=0):
    """递归脱敏 + 限深。"""
    if depth > 6:
        return '…'
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if any(s in str(k).lower() for s in _SENSITIVE_KEYS):
                out[k] = '***'
            else:
                out[k] = _sanitize(v, depth + 1)
        return out
    if isinstance(obj, list):
        if len(obj) > 50:
            return [_sanitize(x, depth + 1) for x in obj[:50]] + [f'…共{len(obj)}项']
        return [_sanitize(x, depth + 1) for x in obj]
    if isinstance(obj, str) and len(obj) > 500:
        return obj[:500] + '…'
    return obj


def _extract_payload(request):
    ctype = request.META.get('CONTENT_TYPE', '') or ''
    if ctype.startswith('multipart/'):
        # 文件导入：只记文件名，不碰内容（避免大文件/二进制入库）
        try:
            names = [f.name for f in request.FILES.values()]
        except Exception:
            names = []
        return {'_multipart': True, 'files': names}
    try:
        body = request.body
        if not body:
            return {}
        data = json.loads(body)
    except Exception:
        return {'_raw': (request.body[:200].decode('utf-8', 'replace') + '…') if request.body else ''}
    data = _sanitize(data)
    # 总量兜底截断：超限时只保留键名清单
    try:
        if len(json.dumps(data, ensure_ascii=False)) > _MAX_PAYLOAD_CHARS:
            keys = list(data.keys()) if isinstance(data, dict) else []
            return {'_truncated': True, 'keys': keys}
    except Exception:
        return {'_truncated': True}
    return data


def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()[:64]
    return (request.META.get('REMOTE_ADDR') or '')[:64]


def _resolve_user(request, payload):
    """操作人归因（按可靠度递降三层兜底）：
    1) 视图装饰器挂的 request.pk_user（pk_required / cw_required）；
    2) 自行解析 Authorization JWT —— 覆盖 404/405、视图早退、未走标准装饰器的请求；
    3) 登录接口按请求体手机号归因（成功失败都记到对应账号，便于审计异常登录）。
    """
    user = getattr(request, 'pk_user', None)
    if user is not None:
        return user
    from paikuan.models import PaikuanUser
    token = (request.headers.get('Authorization', '') or '').replace('Bearer ', '').strip()
    if token:
        try:
            import jwt
            from django.conf import settings
            data = jwt.decode(token, settings.JWT_SECRET, algorithms=['HS256'])
            return PaikuanUser.objects.only('id', 'name').filter(id=data.get('uid')).first()
        except Exception:
            pass
    if request.path.endswith('/login') and isinstance(payload, dict):
        phone = str(payload.get('phone') or '').strip()
        if phone:
            return PaikuanUser.objects.only('id', 'name').filter(phone=phone).first()
    return None


class AuditLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        capture = (request.method in _AUDIT_METHODS
                   and request.path.startswith('/api/')
                   and request.path not in _SKIP_PATHS)
        # body 必须在视图前读取并缓存（multipart 除外，交给视图解析 FILES）
        payload = _extract_payload(request) if capture else None

        response = self.get_response(request)

        if capture:
            try:
                from paikuan.models import AuditLog
                user = _resolve_user(request, payload)
                AuditLog.objects.create(
                    user=user,
                    user_name=(user.name if user else ''),
                    method=request.method,
                    path=request.path[:300],
                    module=_module_of(request.path),
                    status_code=getattr(response, 'status_code', 0) or 0,
                    payload=payload or {},
                    ip=_client_ip(request),
                )
            except Exception:
                logger.exception('audit log write failed (request unaffected)')
        return response
