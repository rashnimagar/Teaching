import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestCoreViews:
    """Test core landing page and system health check views."""

    def test_home_page_returns_200(self, client):
        url = reverse("core:home")
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Teaching" in content
        assert "Platform" in content
        assert "Phase 1 Foundation Ready" in content
        assert "core/home.html" in [t.name for t in response.templates]
        assert "base.html" in [t.name for t in response.templates]

    def test_healthz_endpoint_returns_200_and_json(self, client):
        url = reverse("core:healthz")
        response = client.get(url)
        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        data = response.json()
        assert data["status"] == "ok"
        assert data["database"] == "healthy"
        assert "timestamp" in data
