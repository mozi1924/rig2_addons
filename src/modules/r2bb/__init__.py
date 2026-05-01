from . import ops, props, ui

modules = (
    props,
    ops,
    ui,
)


def register():
    for module in modules:
        module.register()


def unregister():
    for module in reversed(modules):
        module.unregister()
