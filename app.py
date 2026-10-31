"""Vercel entrypoint: Vercel looks for a Flask object named `app` in app.py."""

from docdrift.web import create_app

app = create_app()
