"""Cloud entrypoint. Secrets are read from the host environment, never printed."""
from app import create_app
from settings import Settings
app = create_app(Settings.from_env())
