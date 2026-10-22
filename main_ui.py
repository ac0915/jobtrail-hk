"""Local UI preview: python -m uvicorn main_ui:app --reload."""
from main import app, BASE_DIR, MULTI_USER_ENABLED
from app.ui import install_ui

install_ui(app, BASE_DIR / 'web', enabled=MULTI_USER_ENABLED)
