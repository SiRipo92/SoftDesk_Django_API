"""
Short apps/auth/serializers.py to facilitate Swagger OpenAPI
"""

from __future__ import annotations

from rest_framework import serializers


class LogoutSerializer(serializers.Serializer):
    """
    Serializer for logout payload.

    Expected payload:
        { "refresh": "<refresh_token>" }
    """

    refresh = serializers.CharField(
        help_text="Refresh token JWT à blacklister.",
        write_only=True,
        trim_whitespace=True,
    )