from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CustomerViewSet, AuthViewSet

router = DefaultRouter()
router.register(r'customers', CustomerViewSet)
router.register(r'auth', AuthViewSet, basename='auth')

urlpatterns = [
    path('', include(router.urls)),
]