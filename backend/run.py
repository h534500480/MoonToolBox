import os
import sys
from pathlib import Path

import uvicorn


if __name__ == "__main__":
    backend_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(backend_dir))
    reload_enabled = os.environ.get("ROS_TOOL_RELOAD", "0").lower() in {"1", "true", "yes", "on"}
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=reload_enabled)
