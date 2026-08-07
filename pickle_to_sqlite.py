import argparse
import json
import os
import pickle
import pickletools
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path


UNSAFE_OPCODES = {
    "BUILD",
    "EXT1",
    "EXT2",
    "EXT4",
    "GLOBAL",
    "INST",
    "NEWOBJ",
    "NEWOBJ_EX",
    "OBJ",
    "PERSID",
    "BINPERSID",
    "REDUCE",
    "STACK_GLOBAL",
}
GET_OPCODES = {"GET", "BINGET", "LONG_BINGET"}
EXPLICIT_PUT_OPCODES = {"PUT", "BINPUT", "LONG_BINPUT"}


def format_bytes(value):
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024


class Progress:
    def __init__(self, path, label):
        self.path = path
        self.label = label
        self.total = os.path.getsize(path)
        self.started = time.monotonic()
        self.last_report = 0.0

    def report(self, position, count=None, force=False):
        now = time.monotonic()
        if not force and now - self.last_report < 2:
            return
        elapsed = max(now - self.started, 0.001)
        percent = min(position / self.total * 100, 100.0)
        speed = position / elapsed
        eta = (self.total - position) / speed if speed else 0
        count_text = f" | records={count:,}" if count is not None else ""
        print(
            f"\r{self.label}: {percent:6.2f}% | {format_bytes(speed)}/s"
            f" | ETA={eta / 60:.1f}m{count_text}",
            end="",
            flush=True,
        )
        self.last_report = now
        if force:
            print()


def cache_path_for(db_path):
    return Path(str(db_path) + ".memo_refs.json")


def load_memo_cache(pickle_path, db_path):
    cache_path = cache_path_for(db_path)
    if not cache_path.exists():
        return None
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        stat = os.stat(pickle_path)
        if (
            cache.get("pickle_size") == stat.st_size
            and cache.get("pickle_mtime_ns") == stat.st_mtime_ns
        ):
            return set(cache["referenced_memo_ids"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def scan_referenced_memo_ids(pickle_path, db_path):
    cached = load_memo_cache(pickle_path, db_path)
    if cached is not None:
        print(f"Using cached memo analysis ({len(cached):,} referenced IDs).")
        return cached

    referenced = set()
    unsafe = Counter()
    explicit_puts = Counter()
    progress = Progress(pickle_path, "Memo analysis")

    with open(pickle_path, "rb") as source:
        for opcode, argument, position in pickletools.genops(source):
            name = opcode.name
            if name in GET_OPCODES:
                referenced.add(int(argument))
            elif name in UNSAFE_OPCODES:
                unsafe[name] += 1
            elif name in EXPLICIT_PUT_OPCODES:
                explicit_puts[name] += 1
            progress.report(position)
        progress.report(os.path.getsize(pickle_path), force=True)

    if unsafe:
        details = ", ".join(f"{name}={count}" for name, count in unsafe.items())
        raise pickle.UnpicklingError(
            f"Refusing object-capable pickle opcodes: {details}"
        )
    if explicit_puts:
        details = ", ".join(
            f"{name}={count}" for name, count in explicit_puts.items()
        )
        raise pickle.UnpicklingError(
            "Sparse memo currently requires protocol MEMOIZE opcodes only; " + details
        )

    stat = os.stat(pickle_path)
    cache = {
        "pickle_size": stat.st_size,
        "pickle_mtime_ns": stat.st_mtime_ns,
        "referenced_memo_ids": sorted(referenced),
    }
    cache_path_for(db_path).write_text(
        json.dumps(cache, ensure_ascii=True), encoding="utf-8"
    )
    print(f"Referenced memo IDs: {len(referenced):,}")
    return referenced


class SparseMemo:
    """Emulate a sequential pickle memo while retaining only future GET targets."""

    def __init__(self, retained_ids):
        self.retained_ids = retained_ids
        self.retained = {}
        self.next_index = 0

    def __len__(self):
        return self.next_index

    def __setitem__(self, key, value):
        if key != self.next_index:
            raise pickle.UnpicklingError(
                f"Non-sequential memo index {key}; expected {self.next_index}"
            )
        if key in self.retained_ids:
            self.retained[key] = value
        self.next_index += 1

    def __getitem__(self, key):
        try:
            return self.retained[key]
        except KeyError as error:
            raise pickle.UnpicklingError(
                f"Memo ID {key} was referenced but not retained"
            ) from error

    def copy(self):
        return dict(self.retained)

    def clear(self):
        self.retained.clear()
        self.next_index = 0


class RecordStreamingUnpickler(pickle._Unpickler):
    def __init__(self, source, callback, retained_memo_ids, progress):
        super().__init__(source)
        self.source = source
        self.callback = callback
        self.memo = SparseMemo(retained_memo_ids)
        self.progress = progress
        self.record_count = 0
        self.root = None

    def find_class(self, module, name):
        raise pickle.UnpicklingError(
            f"Class loading is disabled: {module}.{name}"
        )

    def persistent_load(self, pid):
        raise pickle.UnpicklingError("Persistent pickle IDs are disabled")

    @staticmethod
    def is_application_number(value):
        return (
            isinstance(value, str)
            and len(value) == 13
            and value.startswith("10")
            and value.isascii()
            and value.isdigit()
        )

    def emit(self, key, value):
        if not self.is_application_number(key):
            raise pickle.UnpicklingError(
                f"Unexpected top-level key: {key!r}"
            )
        self.callback(key, value)
        self.record_count += 1
        self.progress.report(self.source.tell(), self.record_count)

    def emit_pending_mark_items(self):
        if len(self.stack) % 2:
            raise pickle.UnpicklingError("Odd top-level key/value stack")
        for index in range(0, len(self.stack), 2):
            value_index = index + 1
            if self.stack[value_index] is not None:
                self.emit(self.stack[index], self.stack[value_index])
                self.stack[value_index] = None

    def load(self):
        self._unframer = pickle._Unframer(self._file_read, self._file_readline)
        self.read = self._unframer.read
        self.readinto = self._unframer.readinto
        self.readline = self._unframer.readline
        self.metastack = []
        self.stack = []
        self.append = self.stack.append
        self.proto = 0

        while True:
            opcode_bytes = self.read(1)
            if not opcode_bytes:
                raise EOFError
            opcode = opcode_bytes[0]

            if opcode == pickle.SETITEMS[0] and len(self.metastack) == 1:
                if self.root is None:
                    self.root = self.metastack[0][-1]
                self.emit_pending_mark_items()
            elif (
                opcode == pickle.SETITEM[0]
                and not self.metastack
                and len(self.stack) >= 3
                and self.stack[-3] is self.root
            ):
                self.emit(self.stack[-2], self.stack[-1])
                self.stack[-1] = None

            try:
                self.dispatch[opcode](self)
            except pickle._Stop as stop:
                self.progress.report(
                    os.path.getsize(self.progress.path),
                    self.record_count,
                    force=True,
                )
                return stop.value

            if self.root is None and len(self.stack) == 1 and isinstance(self.stack[0], dict):
                self.root = self.stack[0]

            if (
                len(self.metastack) == 1
                and len(self.stack) > 2
                and len(self.stack) % 2 == 1
                and self.stack[-2] is not None
                and self.is_application_number(self.stack[-1])
            ):
                self.emit(self.stack[-3], self.stack[-2])
                self.stack[-2] = None

            if (
                self.root is not None
                and not self.metastack
                and len(self.stack) == 1
                and self.stack[0] is self.root
                and self.root
            ):
                self.root.clear()


class SQLiteWriter:
    def __init__(self, db_path, commit_every):
        self.db_path = db_path
        self.commit_every = commit_every
        self.pending = 0
        self.total = 0
        self.connection = sqlite3.connect(db_path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute("PRAGMA temp_store=MEMORY")
        self.connection.execute("PRAGMA wal_autocheckpoint=2000")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS parsing_data (
                application_number TEXT PRIMARY KEY,
                data_json TEXT NOT NULL
            ) WITHOUT ROWID
            """
        )
        self.connection.execute("BEGIN")

    def write(self, application_number, value):
        data_json = json.dumps(
            value, ensure_ascii=False, separators=(",", ":")
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO parsing_data VALUES (?, ?)",
            (application_number, data_json),
        )
        self.total += 1
        self.pending += 1
        if self.pending >= self.commit_every:
            self.connection.commit()
            self.connection.execute("BEGIN")
            self.pending = 0

    def close(self, completed):
        if completed:
            self.connection.commit()
            self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversion_metadata (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )
            self.connection.execute(
                "INSERT OR REPLACE INTO conversion_metadata VALUES ('complete', 'true')"
            )
            self.connection.execute(
                "INSERT OR REPLACE INTO conversion_metadata VALUES ('record_count', ?)",
                (str(self.total),),
            )
            self.connection.commit()
        else:
            self.connection.commit()
        self.connection.close()


def convert(pickle_path, db_path, commit_every):
    referenced_ids = scan_referenced_memo_ids(pickle_path, db_path)
    writer = SQLiteWriter(db_path, commit_every)
    progress = Progress(pickle_path, "SQLite conversion")
    completed = False
    try:
        with open(pickle_path, "rb") as source:
            RecordStreamingUnpickler(
                source, writer.write, referenced_ids, progress
            ).load()
        completed = True
    finally:
        writer.close(completed)
    print(f"SQLite rows written: {writer.total:,}")
    print(f"Database: {db_path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert the known application-number pickle dictionary to SQLite."
    )
    parser.add_argument("pickle_path", type=Path)
    parser.add_argument("db_path", type=Path)
    parser.add_argument("--commit-every", type=int, default=250)
    return parser.parse_args()


def main():
    args = parse_args()
    pickle_path = args.pickle_path.resolve()
    db_path = args.db_path.resolve()
    if not pickle_path.is_file():
        raise SystemExit(f"Pickle file not found: {pickle_path}")
    if pickle_path == db_path:
        raise SystemExit("Input and output paths must differ")
    if args.commit_every < 1:
        raise SystemExit("--commit-every must be positive")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    convert(pickle_path, db_path, args.commit_every)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nConversion interrupted; committed rows remain in the database.")
        sys.exit(130)
