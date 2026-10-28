import json
import os
import time
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class SingleRunLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            if os.name == "nt":
                if self.path.stat().st_size == 0:
                    self.handle.write(" ")
                    self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            if os.name == "nt":
                owner = "another process"
            else:
                self.handle.seek(0)
                owner = self.handle.read().strip() or "another process"
            self.handle.close()
            self.handle = None
            raise RuntimeError(f"Another Anaplan backup is already running ({owner}).") from None
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(json.dumps({"pid": os.getpid(), "started": time.time()}))
        self.handle.flush()

    def release(self):
        if self.handle:
            if os.name == "nt":
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None


def remove_old_files(directory: Path, pattern: str, retention_days: int):
    return len(cleanup_old_files(directory, pattern, retention_days)['removed'])


def cleanup_old_files(directory: Path, pattern: str, retention_days: int,
                      keep_latest=0, preview=False, now=None):
    result = {'directory': str(directory), 'pattern': pattern,
              'retention_days': retention_days, 'keep_latest': keep_latest,
              'preview': preview, 'candidates': [], 'removed': [], 'errors': []}
    if retention_days < 0 or not directory.exists():
        return result
    cutoff = (time.time() if now is None else now) - retention_days * 86400
    files = []
    for path in directory.glob(pattern):
        try:
            if path.is_file() and not path.is_symlink():
                files.append((path.stat().st_mtime, path))
        except OSError as exc:
            result['errors'].append({'path': str(path), 'error': str(exc)})
    files.sort(key=lambda item: item[0], reverse=True)
    protected = {path for _, path in files[:max(0, keep_latest)]}
    expired = [path for modified, path in files
               if modified < cutoff and path not in protected]
    result['candidates'] = [str(path) for path in expired]
    if preview:
        return result
    for path in expired:
        try:
            path.unlink()
            result['removed'].append(str(path))
        except OSError as exc:
            result['errors'].append({'path': str(path), 'error': str(exc)})
    return result
