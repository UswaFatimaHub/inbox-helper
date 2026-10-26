"""ASGI entry point: .venv\Scripts\python -m uvicorn inbox_helper.server:app --port 8000"""
from .api import create_app

app = create_app()
