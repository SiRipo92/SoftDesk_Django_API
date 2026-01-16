from rest_framework.permissions import BasePermission


class IsSelfOrAdmin(BasePermission):
    """
    Allow access if user is admin or accessing their own User object.
    """

    def has_object_permission(self, request, view, obj):
        return request.user.is_staff or obj == request.user
