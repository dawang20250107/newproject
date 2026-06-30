from django.urls import path, include
from django.http import JsonResponse, HttpResponse
from django.db import connections
from django.conf import settings


def index(request):
    return JsonResponse({'code': 0, 'msg': 'Paikuan API v1.0'})


def healthz(request):
    """Liveness：进程存活即 200（不碰 DB，供云托管/systemd watchdog 探活）。"""
    return HttpResponse('ok', content_type='text/plain')


def readyz(request):
    """Readiness：校验主数据库连接可用（SELECT 1），失败返回 503，
    供滚动发布/负载均衡在 DB 断连或死锁时把实例剔除流量。
    注：caiwu 为休眠次库、与 default 同一 MySQL 实例（同 _mysql_base），
    故校验 default 连通即可证明数据库服务可达，无需重复探 caiwu。"""
    try:
        with connections['default'].cursor() as cur:
            cur.execute('SELECT 1')
            cur.fetchone()
    except Exception as e:  # noqa: BLE001 — 探针需吞掉具体异常并归类为未就绪
        return JsonResponse({'status': 'unready', 'problem': e.__class__.__name__}, status=503)
    return JsonResponse({'status': 'ready'})


urlpatterns = [
    path('healthz', healthz),
    path('readyz', readyz),
    path('api/pk/', include('paikuan.urls')),
    path('api/pk/ar/', include('ar.urls')),
    path('api/cw/', include('caiwu.urls')),
    path('', index),
]

# Prometheus /metrics（仅当 django_prometheus 已安装时挂载）
if getattr(settings, 'PROMETHEUS_ENABLED', False):
    urlpatterns = [path('', include('django_prometheus.urls'))] + urlpatterns
