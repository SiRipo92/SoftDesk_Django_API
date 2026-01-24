"""
Users app URL entrypoint.

Exposes user CRUD endpoints via DRF router:
- /users/        (POST public signup, GET admin list)
- /users/{id}/   (self or admin)
"""

from rest_framework.routers import DefaultRouter

from .views import UserViewSet

app_name = "users"

router = DefaultRouter()
router.register("users", UserViewSet, basename="users")

urlpatterns = router.urls
