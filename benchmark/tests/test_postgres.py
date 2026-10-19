"""Run explicitly against the disposable source after installing dependencies."""

import os
import unittest


@unittest.skipUnless(os.environ.get("EDGE_POSTGRES_TESTS") == "1", "requires disposable PostgreSQL")
class PostgreSQLTriggerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from edge.config import load_local_env

        load_local_env()
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "edge.settings")
        import django

        django.setup()
        from django.core.management import call_command

        call_command("migrate", database="default", verbosity=0, interactive=False)

    def setUp(self):
        from django.db import transaction

        self.transaction = transaction.atomic()
        self.transaction.__enter__()
        self.addCleanup(
            self.transaction.__exit__, RuntimeError, RuntimeError("test rollback"), None
        )

    def test_insert_bulk_update_ack_and_soft_delete(self):
        from demo.models import Post
        from edge.sync import PostgresSource, table_for

        post = Post.objects.create(title="test", content="original")
        post.refresh_from_db()
        self.assertEqual(post.sync_version, 1)
        self.assertTrue(post.needs_sync)
        table = table_for(Post)
        source = PostgresSource()
        copied = {"id": post.pk, "sync_version": 1}
        self.assertEqual(source.acknowledge(table, [copied]), 1)
        post.refresh_from_db()
        self.assertFalse(post.needs_sync)
        self.assertEqual(post.sync_version, 1)
        Post.objects.filter(pk=post.pk).update(title="changed")
        post.refresh_from_db()
        self.assertEqual(post.sync_version, 2)
        self.assertTrue(post.needs_sync)
        self.assertEqual(source.acknowledge(table, [copied]), 0)
        post.delete()
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())
        self.assertEqual(Post.all_objects.get(pk=post.pk).sync_version, 3)

    def test_stale_model_save_cannot_clear_pending_metadata(self):
        from demo.models import Post
        from edge.sync import PostgresSource, table_for

        post = Post.objects.create(title="test", content="original")
        PostgresSource().acknowledge(table_for(Post), [{"id": post.pk, "sync_version": 1}])
        post.refresh_from_db()
        stale = Post.objects.get(pk=post.pk)
        Post.objects.filter(pk=post.pk).update(content="pending")
        stale.save(update_fields=["title"])
        post.refresh_from_db()
        self.assertTrue(post.needs_sync)
        self.assertEqual(post.sync_version, 2)

    def test_bulk_create_bulk_update_and_raw_sql_are_tracked(self):
        from django.db import connections

        from demo.models import Post

        posts = Post.objects.bulk_create(
            [Post(title="a", content="a"), Post(title="b", content="b")]
        )
        for post in posts:
            post.content = "changed"
        Post.objects.bulk_update(posts, ["content"])
        with connections["default"].cursor() as cursor:
            cursor.execute("UPDATE demo_post SET title=%s WHERE id=%s", ["raw", posts[0].pk])
        self.assertEqual(Post.objects.get(pk=posts[0].pk).sync_version, 3)
        self.assertEqual(Post.objects.get(pk=posts[1].pk).sync_version, 2)

    def test_domain_transaction_rolls_back_with_tracking(self):
        from django.db import transaction

        from demo.models import Post

        post = Post.objects.create(title="original", content="test")
        with self.assertRaises(ValueError), transaction.atomic():
            Post.objects.filter(pk=post.pk).update(title="rolled back")
            raise ValueError("rollback")
        post.refresh_from_db()
        self.assertEqual((post.title, post.sync_version), ("original", 1))

    def test_physical_delete_is_rejected(self):
        from django.db import DatabaseError, connections, transaction

        from demo.models import Post

        post = Post.objects.create(title="test", content="test")
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connections["default"].cursor() as cursor:
                cursor.execute("DELETE FROM demo_post WHERE id=%s", [post.pk])
