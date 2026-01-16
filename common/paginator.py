"""
Common DRF pagination configuration.

Using pagination prevents large responses and improves API performance
(especially on list endpoints).
"""

from __future__ import annotations

from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """
    Default pagination class.

    Query params:
        - ?page=1
        - ?page_size=20 (optional, capped)
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
