"""Download exact model revisions once, inside a disposable image container."""

import json
import shutil
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

for item in json.loads(Path(sys.argv[1]).read_text()):
    path = Path(item["path"])
    marker = path / ".serving-revision"
    identity = item["model"] + "@" + item["revision"]
    if path.exists() and (not marker.exists() or marker.read_text() != identity):
        shutil.rmtree(path)
    snapshot_download(
        repo_id=item["model"], revision=item["revision"], local_dir=item["path"]
    )
    marker.write_text(identity)
