from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import StaffViewSet, AuthViewSet

router = DefaultRouter()
router.register(r'staff', StaffViewSet, basename='staff')

urlpatterns = [
    path('', include(router.urls)),
    path('auth/token/', AuthViewSet.as_view({'post': 'token'}), name='auth-token'),
]