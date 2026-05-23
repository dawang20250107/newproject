from django.urls import path, include
from django.http import JsonResponse


def index(request):
    return JsonResponse({'code': 0, 'msg': 'Paikuan API v1.0'})


urlpatterns = [
    path('api/pk/', include('paikuan.urls')),
    path('', index),
]
