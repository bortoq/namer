"""Durable rename journal in a standalone executable restoration script."""

import json
import os


_HEADER = '''#!/usr/bin/env python3
"""Restore names recorded by namer. Run from any working directory."""
import ctypes
import errno
import json
import os
import sys


def move_without_overwrite(source, destination):
    try:
        os.link(source, destination)
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP,
                             errno.ENOSYS, errno.EXDEV):
            raise
        libc = ctypes.CDLL(None, use_errno=True)
        try:
            rename = libc.renameat2
        except AttributeError:
            raise OSError(errno.ENOSYS, 'atomic no-replace rename unavailable')
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p,
                           ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(source), -100,
                  os.fsencode(destination), 1) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
        return
    try:
        os.unlink(source)
    except OSError:
        os.unlink(destination)
        raise


def matches(path, device, inode):
    try:
        info = os.lstat(path)
        return (info.st_dev, info.st_ino) == (device, inode)
    except FileNotFoundError:
        return False


def main():
    entries = []
    with open(__file__, encoding='utf-8') as script:
        for line in script:
            if line.startswith('# namer-restore: ') and line.endswith('\\n'):
                entries.append(json.loads(line[len('# namer-restore: '):]))
    errors = 0
    for source, destination, device, inode in reversed(entries):
        try:
            # An interrupted/failed rename, or an already restored entry.
            if matches(destination, device, inode):
                continue
            if not matches(source, device, inode):
                raise OSError('renamed file is missing or has been replaced')
            move_without_overwrite(source, destination)
            print(f'Restored: {destination!r}')
        except OSError as exc:
            errors += 1
            print(f'Cannot restore {destination!r}: {exc}', file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())

'''


class RestoreScript:
    """Write intent before moving a file; discard failed attempts.

    Entries identify the actual file by device/inode so a pending intent
    left by interruption never restores a different file at that path.
    """

    def __init__(self, directory: str, name: str = ''):
        directory = os.path.abspath(directory)
        explicit_path = os.path.abspath(name) if name else ''
        counter = 0
        while True:
            candidate = f'namer-restore_{counter}.py' if counter else 'namer-restore.py'
            self.path = explicit_path or os.path.join(directory, candidate)
            try:
                self._file = open(self.path, 'x', encoding='utf-8')
                break
            except FileExistsError:
                if explicit_path:
                    raise
                counter += 1
        try:
            self._file.write(_HEADER)
            self._sync()
            os.chmod(self.path, 0o755)
        except BaseException:
            self._file.close()
            os.unlink(self.path)
            raise

    def _sync(self):
        self._file.flush()
        os.fsync(self._file.fileno())

    def prepare(self, source: str, destination: str) -> int:
        info = os.lstat(source)
        offset = self._file.tell()
        entry = [os.path.abspath(destination), os.path.abspath(source),
                 info.st_dev, info.st_ino]
        try:
            self._file.write('# namer-restore: ' + json.dumps(entry) + '\n')
            self._sync()
        except OSError:
            self.cancel(offset)
            raise
        return offset

    def cancel(self, offset: int):
        self._file.seek(offset)
        self._file.truncate()
        self._sync()

    def close(self):
        self._file.close()
