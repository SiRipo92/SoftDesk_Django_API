"""Apps/Auth/views.py for logout function"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from .serializers import LogoutSerializer


class LogoutView(GenericAPIView):
    """
    Logout endpoint (server-side).

    Blacklists the provided refresh token, so it cannot be reused.

    Requires:
        - 'rest_framework_simplejwt.token_blacklist' in INSTALLED_APPS
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LogoutSerializer

    @extend_schema(
        request=LogoutSerializer,
        responses={
            205: OpenApiResponse(description="Refresh token blacklisté."),
            400: OpenApiResponse(description="Refresh token manquant."),
            401: OpenApiResponse(description="Refresh token invalide."),
        },
        description="Blackliste le refresh token fourni afin qu'il "
                    "ne puisse plus être réutilisé.",
    )
    def post(self, request, *args, **kwargs):
        """
        Expect JSON body:
            { "refresh": "<token>" }

        Returns:
            205 if blacklisted, 400 if missing, 401 if invalid token.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        refresh = serializer.validated_data["refresh"]

        try:
            token = RefreshToken(refresh)
            token.blacklist()
        except TokenError:
            return Response(
                {"detail": "refresh token invalide"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response(status=status.HTTP_205_RESET_CONTENT)
