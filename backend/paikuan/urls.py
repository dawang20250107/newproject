from django.urls import path
from paikuan import views

urlpatterns = [
    path('register', views.register),
    path('login', views.login),
    path('registration-status', views.registration_status),
    path('me', views.me),
    path('payments', views.payments),
    path('payments/<int:pk>', views.payment_detail),
    path('dashboard', views.dashboard),
    path('stats', views.stats),
    path('users', views.users),
    path('users/<int:pk>', views.user_detail),
    path('users/<int:pk>/approve', views.approve_user),
    path('users/<int:pk>/reject', views.reject_user),
    path('permissions', views.permissions),
    path('permissions/<str:job>', views.permission_detail),
    path('departments', views.departments),
]
