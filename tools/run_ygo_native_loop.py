from importlib import import_module as _import_module
_module = _import_module('ai_training.tools.run_ygo_native_loop')
globals().update(_module.__dict__)
