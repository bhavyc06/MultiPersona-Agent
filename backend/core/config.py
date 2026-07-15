# Re-export from backend.config so both import paths work:
#   from backend.config import settings
#   from backend.core.config import settings
from backend.config import settings, Settings

__all__ = ["settings", "Settings"]
