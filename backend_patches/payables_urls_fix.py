from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register('', views.PayableViewSet, basename='payables')

urlpatterns = [
    path('registrations/', views.PaymentRegistrationView.as_view(), name='payment-registrations'),
    path('registrations/summary/', views.PaymentRegistrationSummaryView.as_view(), name='payment-registrations-summary'),
    path('', include(router.urls)),
]
