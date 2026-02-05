"""Apps/Auth/views.py for logout function"""

from __future__ import annotations

from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import LogoutSerializer


class LoginView(TokenObtainPairView):
    """
    JWT login endpoint.

    Returns:
    - access: short-lived JWT access token
    - refresh: longer-lived refresh token
    """
    permission_classes = [AllowAny]
    serializer_class = TokenObtainPairSerializer

    @extend_schema(
        tags=["auth"],
        operation_id="auth_login",
        request=TokenObtainPairSerializer,
        responses={200: TokenObtainPairSerializer},
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class RefreshView(TokenRefreshView):
    """
    JWT refresh endpoint.

    Input:
    - refresh: refresh token
    Output:
    - access: new access token
    """
    permission_classes = [AllowAny]
    serializer_class = TokenRefreshSerializer

    @extend_schema(
        tags=["auth"],
        operation_id="auth_refresh",
        request=TokenRefreshSerializer,
        responses={200: TokenRefreshSerializer},
    )
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().post(request, *args, **kwargs)


class LogoutView(GenericAPIView):
    """
    JWT logout endpoint.

    Server-side "logout" is implemented by blacklisting the refresh token.
    Access tokens remain valid until they expire.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = LogoutSerializer

    @extend_schema(
        tags=["auth"],
        operation_id="auth_logout",
        request=LogoutSerializer,
        responses={
            204: OpenApiResponse(description="Refresh token blacklisted."),
            400: OpenApiResponse(description="Refresh token missing/invalid/expired."),
            401: OpenApiResponse(description="Not authenticated."),
        },
    )
    def post(self, request: Request) -> Response:
        """
        Expect JSON body:
            { "refresh": "<token>" }

        Returns:
            205 if blacklisted, 400 if missing, 401 if invalid token.
        """
        serializer = cast(LogoutSerializer, self.get_serializer(data=request.data))
        serializer.is_valid(raise_exception=True)

        # refresh_token typed as str, and cast only at the boundary
        # where we call RefreshToken(...)
        refresh_token: str = cast(str, serializer.validated_data["refresh"])

        try:
            token: RefreshToken = RefreshToken(cast(Any, refresh_token))
            token.blacklist()
        except TokenError:
            # Token is invalid/expired/already blacklisted
            return Response(
                {"refresh":
                     ["Invalid, expired, or already blacklisted refresh token."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)
