from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken, TokenError


class LogoutView(APIView):
    """
    Logout endpoint (server-side).

    Blacklists the provided refresh token, so it cannot be reused.

    Requires:
        - 'rest_framework_simplejwt.token_blacklist' in INSTALLED_APPS
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """
        Expect JSON body:
            { "refresh": "<token>" }

        Returns:
            205 if blacklisted, 400 if missing, 401 if invalid token.
        """
        refresh = request.data.get("refresh")
        if not refresh:
            return Response(
                {"detail": "refresh token requis"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = RefreshToken(refresh)
            token.blacklist()
        except TokenError:
            return Response(
                {"detail": "refresh token invalide"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response(status=status.HTTP_205_RESET_CONTENT)
