from rest_framework.routers import DefaultRouter

from .views import IssueViewSet

app_name = "issues"

router = DefaultRouter()
router.register(r"issues", IssueViewSet, basename="issues")

urlpatterns = router.urls