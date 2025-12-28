"""
Token lifecycle endpoints (refresh/logout).
"""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import LogoutView

urlpatterns = [
    path("refresh/", TokenRefreshView.as_view(), name="refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
]