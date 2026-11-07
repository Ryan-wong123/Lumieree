"""WSGI entrypoint: ``gunicorn wsgi:app``."""

from lumieree import create_app

app = create_app()
