import os
from pathlib import Path

SOURCE_DIR = Path(os.environ.get("SOURCE_DIR", "/srv/nfs/hoerspiele"))
DEST_DIR = Path(os.environ.get("DEST_DIR", str(Path(__file__).parent.parent / "sd-card-complete")))
MAX_TRACKS = 255
