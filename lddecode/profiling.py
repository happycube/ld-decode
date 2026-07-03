"""Shared no-op `profile` decorator shim.

kernprof/line_profiler injects `profile` into builtins when active; the
assignment below rebinds it into this module so it can be re-exported.
Otherwise a pass-through decorator is defined.
"""

try:
    profile = profile  # noqa: F821 -- resolves to the kernprof builtin if present
except NameError:
    def profile(fn):
        return fn
