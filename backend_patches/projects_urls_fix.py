from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register('', views.ProjectViewSet, basename='projects')

urlpatterns = [
    path('summary/', views.ProjectSummaryView.as_view(), name='project-summary'),
    path('unpaid/', views.UnpaidRecordsView.as_view(), name='unpaid-records'),
    path('', include(router.urls)),
]
