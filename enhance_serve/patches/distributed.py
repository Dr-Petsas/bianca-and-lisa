"""Inference stub — no DeepSpeed."""

from functools import wraps


def is_global_leader():
    return True


def is_local_leader():
    return True


def global_leader_only(fn=None, **_kwargs):
    def deco(f):
        @wraps(f)
        def wrapped(*a, **k):
            return f(*a, **k)
        return wrapped
    return deco if fn is None else deco(fn)


def local_leader_only(fn=None, **_kwargs):
    return global_leader_only(fn, **_kwargs)
