import contextvars

_current_user = contextvars.ContextVar('current_user', default=None)


def set_current_user(user):
    """Store current user in context; return token for reset."""
    return _current_user.set(user)


def get_current_user():
    return _current_user.get()


def reset_current_user(token=None):
    try:
        if token is not None:
            _current_user.reset(token)
        else:
            _current_user.set(None)
    except Exception:
        _current_user.set(None)
