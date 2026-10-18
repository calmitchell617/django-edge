"""ASGI R2 tests executed inside workerd.

The view goes through the configured ``STORAGES["default"]`` backend and a model
``FileField`` instead of instantiating ``R2Storage`` directly. ``test_wsgi_r2``
drives the same lifecycle through the WSGI adapter.
"""

# pyright: reportMissingImports=false

import pytest
from _asgi_client import get_json
from _django_app import R2_LOCATION
from _r2_document_app import (
    R2_CONTENT,
    R2_UPLOAD_TO,
    async_document_view,
    create_r2_table,
    drop_r2_table,
)
from django.core.handlers.asgi import ASGIHandler
from django.test import override_settings
from django.urls import path

urlpatterns = [path("asgi/r2/document/", async_document_view)]


async def _run_r2_request(path_name):
    create_r2_table()
    try:
        with override_settings(ROOT_URLCONF=__name__):
            return await get_json(ASGIHandler(), path_name)
    finally:
        drop_r2_table()


@pytest.mark.asyncio
async def test_asgi_r2_filefield_save_read_and_delete():
    response, payload = await _run_r2_request("/asgi/r2/document/")

    assert response.status == 200
    assert payload is not None
    assert payload["name"].startswith(f"{R2_UPLOAD_TO}/payload-")
    assert payload["content"] == R2_CONTENT.decode()
    assert payload["size"] == len(R2_CONTENT)
    assert payload["url"] == f"/media/{R2_LOCATION}/{payload['name']}"
    assert payload["exists_before_delete"] is True
    assert payload["exists_after_delete"] is False
    assert payload["rows_after_delete"] == 0
