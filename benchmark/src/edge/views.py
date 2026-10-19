import hmac
import json
import time
from functools import wraps

from django.contrib.auth import authenticate, login, logout
from django.http import Http404, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods

from demo.models import Post, User
from edge.config import setting
from edge.context import state


def json_body(request):
    body = json.loads(request.body or b"{}")
    if not isinstance(body, dict):
        raise ValueError("Expected a JSON object")
    return body


def authenticated(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        started = time.perf_counter()
        allowed = request.user.is_authenticated
        current = state.get()
        if current:
            current.segments["auth_ms"] = (time.perf_counter() - started) * 1000
        if not allowed:
            return JsonResponse({"error": "authentication required"}, status=401)
        started = time.perf_counter()
        try:
            return view(request, *args, **kwargs)
        except Http404:
            return JsonResponse({"error": "not found"}, status=404)
        except ValueError, KeyError, TypeError:
            return JsonResponse({"error": "invalid request"}, status=400)
        finally:
            if current:
                current.segments["content_ms"] = (time.perf_counter() - started) * 1000

    return wrapped


@ensure_csrf_cookie
@require_GET
def health(request):
    return JsonResponse({"service": "django-edge-reference", "csrf_token": get_token(request)})


@require_http_methods(["POST"])
def sign_in(request):
    try:
        body = json_body(request)
        user = authenticate(request, username=body["username"], password=body["password"])
    except ValueError, KeyError, TypeError:
        return JsonResponse({"error": "invalid request"}, status=400)
    if user is None:
        return JsonResponse({"error": "invalid credentials"}, status=401)
    login(request, user)
    return JsonResponse({"id": user.pk, "username": user.username})


@require_http_methods(["POST"])
def sign_out(request):
    logout(request)
    return JsonResponse({"logged_out": True})


def post_json(post):
    return {
        "id": post.pk,
        "title": post.title,
        "content": post.content,
        "pub_date": post.pub_date.isoformat(),
        "sync_version": post.sync_version,
    }


@require_http_methods(["GET", "POST"])
@authenticated
def posts(request):
    if request.method == "POST":
        body = json_body(request)
        title, content = body["title"], body["content"]
        if not isinstance(title, str) or not 1 <= len(title) <= 200 or not isinstance(content, str):
            raise ValueError("invalid post")
        post = Post.objects.create(title=title, content=content)
        post.refresh_from_db(using="default")
        return JsonResponse(post_json(post), status=201)
    page = max(1, min(int(request.GET.get("page", 1)), 10_000))
    query = Post.objects.all().eventually_consistent()
    count = query.count()
    rows = list(query[(page - 1) * 20 : page * 20])
    return JsonResponse({"count": count, "page": page, "posts": [post_json(p) for p in rows]})


@require_http_methods(["GET", "PATCH", "DELETE"])
@authenticated
def post_detail(request, pk):
    query = Post.objects.all()
    if request.method == "GET":
        query = query.eventually_consistent()
    post = get_object_or_404(query, pk=pk)
    if request.method == "DELETE":
        post.delete()
        return JsonResponse({"deleted": True, "id": pk})
    if request.method == "PATCH":
        body = json_body(request)
        updates = {key: body[key] for key in ("title", "content") if key in body}
        if not updates or any(not isinstance(v, str) for v in updates.values()):
            raise ValueError("invalid post")
        if "title" in updates and not 1 <= len(updates["title"]) <= 200:
            raise ValueError("invalid title")
        Post.objects.filter(pk=pk).update(**updates)
        post.refresh_from_db(using="default")
    return JsonResponse(post_json(post))


@require_GET
@authenticated
def whoami(request):
    return JsonResponse({"id": request.user.pk, "username": request.user.username})


@csrf_exempt
@require_http_methods(["POST"])
def control(request, action):
    expected = setting("CONTROL_TOKEN")
    if not expected or not hmac.compare_digest(
        request.headers.get("Authorization", ""), "Bearer " + expected
    ):
        return JsonResponse({"error": "unauthorized"}, status=401)
    try:
        body = json_body(request)
        if action == "deactivate":
            updated = User.objects.filter(username=body["username"]).update(is_active=False)
            return JsonResponse({"updated": updated})
        from pyodide.ffi import run_sync
        from workers import env

        if action == "cache_state":
            from django.apps import apps
            from django.conf import settings

            from edge.replication import quote

            if body["model"] not in settings.MIRRORED_MODELS:
                raise ValueError("Unknown mirrored model")
            model = apps.get_model(body["model"])
            columns = ["sync_version", "is_deleted"]
            if model is User:
                columns.append("is_active")
            sql = (
                f"SELECT {', '.join(map(quote, columns))} FROM {quote(model._meta.db_table)} "
                f"WHERE {quote(model._meta.pk.column)} = ?"
            )
            result = run_sync(
                env.CACHE.withSession("first-primary").prepare(sql).bind(body["pk"]).all()
            )
            return JsonResponse({"rows": result.get("results", []), "meta": result.get("meta", {})})
        if action == "probe_http":
            from edge.probe import runtime_probe

            return JsonResponse(runtime_probe(env.CACHE))
        allowed = {
            "start",
            "stop",
            "status",
            "probe",
            "migrate",
            "reset",
            "seed",
            "sync",
            "batch_probe",
        }
        if action not in allowed:
            return JsonResponse({"error": "unknown action"}, status=404)
        stub = env.SYNC.get(env.SYNC.idFromName("postgres-d1"), {"locationHint": "weur"})
        result = run_sync(stub.control(action, body))
        if "control_error" in result:
            return JsonResponse(result["control_error"], status=503)
        return JsonResponse(result)
    except ValueError, KeyError, TypeError:
        return JsonResponse({"error": "invalid control request"}, status=400)
    except Exception as error:
        from edge.diagnostics import error_details

        return JsonResponse(error_details(error), status=503)
