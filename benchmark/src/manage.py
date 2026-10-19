import os
import sys

from edge.config import load_local_env

load_local_env()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "edge.settings")

from django.core.management import execute_from_command_line  # noqa: E402

execute_from_command_line(sys.argv)
