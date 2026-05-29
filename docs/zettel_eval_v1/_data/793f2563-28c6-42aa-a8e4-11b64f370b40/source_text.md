## Introduction and Overview
- Python's `zoneinfo` module, added in version 3.9 and specified in PEP 615, provides `zoneinfo.ZoneInfo`.
- `ZoneInfo` is a concrete `datetime.tzinfo` implementation for the IANA time zone database.
- It is not available on WebAssembly (WASI).
- By default, `zoneinfo` uses the system's time zone data, falling back to the `tzdata` PyPI package if system data is unavailable.
- If neither source is found, `ZoneInfoNotFoundError` is raised.
- For cross-platform compatibility, especially on systems like Windows without a system IANA database, a dependency on `tzdata` is recommended.

## `ZoneInfo` Object Integration
- `ZoneInfo` objects can be attached to `datetime` objects via the constructor, `replace()`, or `astimezone()`.
- They automatically handle daylight saving time transitions in datetime arithmetic.
- They support the `fold` attribute from PEP 495 for ambiguous times.

### Fold Attribute Behavior
- `fold=0` uses the pre-transition offset.
- `fold=1` uses the post-transition offset.

## Time Zone Data Source Configuration (`TZPATH`)
- The data source search path, `TZPATH`, is configured by searching specified directories first, then the `tzdata` package.
- Configuration can be done at compile-time, via an environment variable, or at runtime.

### Configuration Methods
- Compile-time: via the `TZPATH` option or `--with-tzpath` flag on POSIX.
- Environment variable: `PYTHONTZPATH` (an `os.pathsep`-separated string of absolute paths); an empty string forces `tzdata` use.
- Runtime: with `zoneinfo.reset_tzpath(to=...)`.

### Warnings
- `PYTHONTZPATH` with relative paths raises `InvalidTZPathWarning` in CPython.

## `ZoneInfo` Constructors and Caching
- The `ZoneInfo(key)` constructor takes a relative, normalized POSIX path string `key` and raises `ValueError` for non-conforming keys or `ZoneInfoNotFoundError` if the key is not found.
- `ZoneInfo(key)` returns cached, identical objects for the same key.
- Alternate constructor `ZoneInfo.from_file(file_obj, key=None)` always creates a new, unpicklable object from a file-like object.
- Alternate constructor `ZoneInfo.no_cache(key)` bypasses the cache to always return a new object.
- The cache can be invalidated with `ZoneInfo.clear_cache(only_keys=None)`.

## `ZoneInfo.key` and String Representation
- The read-only `ZoneInfo.key` attribute stores the lookup key.
- The `key` is intended as a primary key, not a user-facing string; CLDR is recommended for user-friendly names.
- `str(zone)` returns `zone.key`.

## Pickling Behavior
- When pickling, `ZoneInfo` objects are serialized by key.
- Objects from the primary constructor deserialize to the same cached instance.
- Objects from `no_cache` deserialize to new instances.
- Objects from `from_file` cannot be pickled.
- Pickling requires the key's data to be available in the deserializing environment.
- There are no consistency guarantees across different time zone data versions during deserialization.

## Module-Level Functions and Globals
- `zoneinfo.available_timezones()` returns a set of all canonical IANA keys found on the `TZPATH` (excluding special directories like `posix/`).
- `zoneinfo.reset_tzpath(to=None)` modifies the search path using a sequence of absolute paths.
- The module global `zoneinfo.TZPATH` is a read-only sequence representing the current search path.