"""
Public authentication endpoints (no access token required).
"""

from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView

from .views import SignupView

urlpatterns = [
    path("signup/", SignupView.as_view(), name="signup"),
    path("login/", TokenObtainPairView.as_view(), name="login"),
]
