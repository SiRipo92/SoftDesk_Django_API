from rest_framework.routers import DefaultRouter

from .views import ProjectViewSet

app_name = "projects"

router = DefaultRouter()
router.register(r"projects", ProjectViewSet, basename="projects")

urlpatterns = router.urls
