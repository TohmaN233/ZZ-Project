from importlib import import_module as _import_module
_module = _import_module('ai_training.tools.hidden_multiprocessing_spawn')
globals().update(_module.__dict__)
