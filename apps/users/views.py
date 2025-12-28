"""
Users app API views.

Contains endpoints for:
- Signup (public)
- Current user account management (/users/me/)
- Logout (server-side refresh token blacklisting)
"""

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from .serializers import UserMeSerializer, UserSignupSerializer


class SignupView(generics.CreateAPIView):
    """
    Public endpoint to create a user account.

    Uses UserSignupSerializer which enforces business rules such as:
    - birth_date required
    - age >= 15
    """
    serializer_class = UserSignupSerializer
    permission_classes = [permissions.AllowAny]


class MeView(generics.RetrieveUpdateDestroyAPIView):
    """
    Authenticated endpoint to manage the current user's account.

    Supports:
    - GET: retrieve profile
    - PATCH/PUT: update profile fields + consents
    - DELETE: delete account (requires confirm=true)
    """
    serializer_class = UserMeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        """Return the authenticated user instance."""
        return self.request.user

    def destroy(self, request, *args, **kwargs):
        """
        Delete the authenticated user.

        Requires query parameter:
            ?confirm=true

        This prevents accidental deletions.
        """
        confirm = request.query_params.get("confirm")
        if confirm != "true":
            return Response(
                {"detail": "Confirmation requise : ajoute ?confirm=true"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = self.get_object()
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LogoutView(APIView):
    """
    Logout endpoint (server-side).

    Blacklists the provided refresh token, so it cannot be reused.

    Requirements:
        - 'rest_framework_simplejwt.token_blacklist' in INSTALLED_APPS
        - SIMPLE_JWT settings include rotation/blacklist if you want full effect
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
                status=status.HTTP_401_UNAUTHORIZED)

        return Response(status=status.HTTP_205_RESET_CONTENT)
