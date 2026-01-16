from django.contrib.auth import get_user_model
from rest_framework import permissions, viewsets

from .permissions import IsSelfOrAdmin
from .serializers import UserSerializer

User = get_user_model()


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    queryset = User.objects.all()

    def get_permissions(self):
        if self.action == "create":
            return [permissions.AllowAny()]
        if self.action == "list":
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated(), IsSelfOrAdmin()]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return User.objects.all()
        return User.objects.filter(id=user.id)
