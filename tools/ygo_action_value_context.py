from importlib import import_module as _import_module
_module = _import_module('ai_training.tools.ygo_action_value_context')
globals().update(_module.__dict__)
