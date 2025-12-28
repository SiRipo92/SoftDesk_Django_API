"""
Point d'entrée URL de l'app users.

On découpe les routes par "surface" :
- Public : signup / login
- Auth  : refresh / logout (gestion des tokens)
- Users : endpoints de compte (me)
"""

from django.urls import include, path

app_name = "users"

urlpatterns = [
    # Public auth routes (pas de préfixe /auth)
    path("", include("apps.users.urls_public")),

    # Token management / logout côté serveur
    path("auth/", include("apps.users.urls_auth")),

    # Endpoints "compte"
    path("users/", include("apps.users.urls_users")),
]