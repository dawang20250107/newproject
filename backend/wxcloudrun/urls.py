from django.urls import re_path
from wxcloudrun import views

urlpatterns = [
    re_path(r'^$', views.index, name='index'),

    # 登录
    re_path(r'^api/login$', views.wx_login, name='wx_login'),

    # 用户档案
    re_path(r'^api/profile$', views.profile, name='profile'),

    # 日报
    re_path(r'^api/reports/dates$', views.report_dates, name='report_dates'),
    re_path(r'^api/reports/week$', views.report_week, name='report_week'),
    re_path(r'^api/reports/(?P<date>\d{4}-\d{2}-\d{2})$', views.report_detail, name='report_detail'),
]
