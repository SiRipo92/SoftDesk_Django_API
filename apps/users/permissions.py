from rest_framework.permissions import BasePermission


class IsSelfOrAdmin(BasePermission):
    """
    Allow any authenticated user through at the view level,
    then restrict object access to (self OR admin).
    """

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated)

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        return bool(user and (user.is_staff or obj.pk == user.pk))
