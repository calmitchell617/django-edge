from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.sessions.base_session import AbstractBaseSession, BaseSessionManager
from django.db import models
from django.utils import timezone

from edge.models import SyncedModel, SyncQuerySet
from edge.triggers import sync_triggers


class UserManager(BaseUserManager.from_queryset(SyncQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

    def create_user(self, username, password=None, **extra):
        user = self.model(username=username, **extra)
        user.set_password(password)
        user.save(using="default")
        return user


class User(SyncedModel, AbstractBaseUser):
    username = models.CharField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)
    objects = UserManager()
    USERNAME_FIELD = "username"

    class Meta(SyncedModel.Meta):
        abstract = False
        triggers = sync_triggers()


class SessionManager(BaseSessionManager.from_queryset(SyncQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Session(SyncedModel, AbstractBaseSession):
    objects = SessionManager()

    class Meta(SyncedModel.Meta):
        abstract = False
        triggers = sync_triggers()

    @classmethod
    def get_session_store_class(cls):
        from edge.sessions import SessionStore

        return SessionStore


class Post(SyncedModel):
    title = models.CharField(max_length=200)
    content = models.TextField()
    pub_date = models.DateTimeField(default=timezone.now)

    class Meta(SyncedModel.Meta):
        abstract = False
        ordering = ["-pub_date", "-pk"]
        triggers = sync_triggers()
