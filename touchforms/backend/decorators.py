from __future__ import with_statement
from functools import wraps


def require_xform_session(fn):
    from xformplayer import GlobalStateManager

    @wraps(fn)
    def inner(session_id, *args, **kwargs):
        global_state = GlobalStateManager.get_globalstate()
        with global_state.get_lock(session_id):
            with global_state.get_session(session_id) as xform_session:
                result = fn(xform_session, *args, **kwargs)
                return result
    return inner
