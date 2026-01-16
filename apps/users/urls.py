"""
Point d'entrée URL de l'app users.

On découpe les routes par "surface" :
- Public : signup / login
- Auth  : refresh / logout (gestion des tokens)
- Users : endpoints de compte (me)
"""

from rest_framework.routers import DefaultRouter

from .views import UserViewSet

app_name = "users"

router = DefaultRouter()
router.register("users", UserViewSet, basename="users")

urlpatterns = router.urls
