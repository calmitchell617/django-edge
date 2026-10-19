"""Native Django integration checks; SQLite is not a substitute for trigger tests."""

import os
import unittest


@unittest.skipUnless(
    os.environ.get("EDGE_SQLITE_TEST") == "1", "requires installed Django; enable EDGE_SQLITE_TEST"
)
class DjangoIntegrationTests(unittest.TestCase):
    def test_database_error_metrics_exclude_exception_messages(self):
        from edge.backends.postgres.base import record_error
        from edge.context import request_state

        class DriverError(Exception):
            sqlstate = "53300"

        with request_state() as current:
            record_error(DriverError("sensitive connection details"))
            self.assertEqual(
                current.database_errors, [{"type": "DriverError", "sqlstate": "53300"}]
            )

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "edge.settings")
        os.environ.setdefault("EDGE_LOCAL", "1")
        import django

        django.setup()
        from django.core.management import call_command
        from django.db import connections

        from demo.models import Post, Session, User

        call_command("migrate", database="default", verbosity=0, interactive=False)
        with connections["cache"].schema_editor() as editor:
            for model in (User, Session, Post):
                editor.create_model(model)

    def test_policy_routes_only_opted_in_reads(self):
        from django.db import router

        from demo.models import Post, User
        from edge.context import request_state

        with request_state("auth_cache"):
            self.assertEqual(router.db_for_read(User), "cache")
            self.assertEqual(Post.objects.eventually_consistent().db, "default")
        with request_state("all_cache"):
            self.assertEqual(Post.objects.eventually_consistent().db, "cache")
            self.assertEqual(Post.objects.eventually_consistent().select_for_update().db, "default")
            self.assertEqual(router.db_for_write(User), "default")

    def test_api_login_and_post_mutations_with_csrf(self):
        from django.test import Client

        from demo.models import Post, User

        User.objects.create_user("integration-user", "test-password")
        client = Client(enforce_csrf_checks=True)
        token = client.get("/api/health/").json()["csrf_token"]
        response = client.post(
            "/api/login/",
            {"username": "integration-user", "password": "test-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get("/api/me/").status_code, 200)
        csrf = client.cookies["csrftoken"].value
        response = client.post(
            "/api/posts/",
            {"title": "test", "content": "body"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_READ_POLICY="all_cache",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        pk = response.json()["id"]
        self.assertTrue(Post.objects.using("default").filter(pk=pk).exists())
        response = client.delete(f"/api/posts/{pk}/", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Post.objects.filter(pk=pk).exists())
        self.assertTrue(Post.all_objects.get(pk=pk).is_deleted)

    def test_cached_query_writes_still_go_to_source(self):
        from demo.models import Post
        from edge.context import request_state

        post = Post.objects.create(title="write routing", content="before")
        with request_state("all_cache"):
            Post.objects.eventually_consistent().filter(pk=post.pk).update(content="after")
        self.assertEqual(Post.objects.get(pk=post.pk).content, "after")

    def test_cache_miss_does_not_fall_back_to_postgres(self):
        from demo.models import Post
        from edge.context import request_state

        post = Post.objects.create(title="source only", content="body")
        with request_state("all_cache"):
            self.assertFalse(Post.objects.eventually_consistent().filter(pk=post.pk).exists())

    def test_replica_session_miss_does_not_destroy_client_cookie(self):
        from django.test import Client

        from demo.models import User

        user = User.objects.create_user("replica-session-test", "test-password")
        client = Client()
        client.force_login(user)
        original = client.cookies["sessionid"].value
        response = client.get("/api/me/", HTTP_X_READ_POLICY="auth_cache")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(client.cookies["sessionid"].value, original)
        self.assertEqual(client.get("/api/me/").status_code, 200)
