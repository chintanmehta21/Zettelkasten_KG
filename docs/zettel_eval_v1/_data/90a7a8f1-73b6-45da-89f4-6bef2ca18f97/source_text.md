## Introduction and Purpose
- `contextvars` module added in Python 3.7, detailed in PEP 567.
- Provides APIs to manage context-local state.
- Recommended over `threading.local()` for stateful context managers in concurrent code.
- Prevents state from bleeding across different execution contexts.

## `contextvars.ContextVar` Class
- Declares a context variable using `contextvars.ContextVar(name[, *, default])`.
- `name` is a required, read-only property (added in 3.7.1) for introspection.
- `default` is an optional, keyword-only fallback value.
- Context variables should be created at the top module level, not in closures, to prevent garbage collection issues.

### Methods
- `get([default])`: Returns a value by checking for a method-level default, then the variable's default, before raising a `LookupError`.
- `set(value)`: Sets a new value and returns a `Token` object.
- `reset(token)`: Restores the variable to its previous state using a `Token` that can only be used once.

## `Token` Object
- Returned by `set()`.
- Since Python 3.14, the `Token` object can be used as a context manager for automatic resets.
- Has read-only properties: `var` (the `ContextVar` that created it) and `old_value` (the value before `set()`, or `Token.MISSING` if unset).

## `contextvars.Context` Class
- `contextvars.copy_context()` returns a copy of the current `Context` object with O(1) complexity.
- The `contextvars.Context` class is a mapping of `ContextVars` to values.
- Each thread has its own stack of `Context` objects; the the current context is the one at the top.
- A context's `run(callable, *args, **kwargs)` method pushes it onto the stack, executes the callable, and then pops it off.
- Attempting to enter an already-entered context raises a `RuntimeError`.
- `Context` implements the `collections.abc.Mapping` interface.

### Mapping Interface Methods
- `copy()`
- `__getitem__`
- `get()`
- `keys()`
- `values()`
- `items()`

## `asyncio` Integration
- `contextvars` are natively supported in `asyncio`.
- Example: an echo server using a `ContextVar` to make a client's address available to handler functions without explicit passing.