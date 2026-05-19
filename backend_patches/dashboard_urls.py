from django.urls import path
from . import views
from .monthly_view import MonthlyReceivedPaidView

urlpatterns = [
    path('kpi/', views.KPIView.as_view()),
    path('project-monthly/', views.ProjectMonthlyView.as_view()),
    path('alert-ranking/', views.AlertRankingView.as_view()),
    path('unpaid-distribution/', views.UnpaidDistributionView.as_view()),
    path('manager-comparison/', views.ManagerComparisonView.as_view()),
    path('manager-detail/', views.ManagerDetailView.as_view()),
    path('monthly-received-paid/', MonthlyReceivedPaidView.as_view()),
]
