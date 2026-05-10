from .core.utils import tag_context_redraw


def reconcile_feature_modules():
    """
    Compatibility shim.

    Feature modules are registered by src.__init__ in a deterministic order.
    Keep this function so existing runtime refresh callsites remain valid.
    """
    try:
        tag_context_redraw()
    except Exception:
        pass


def register():
    reconcile_feature_modules()


def unregister():
    reconcile_feature_modules()
