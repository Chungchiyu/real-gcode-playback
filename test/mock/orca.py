"""Minimal stand-in for OrcaSlicer's embedded `orca` module (shapes taken from the C++ bindings)."""
import json, types, enum
_registered = []
_pkg = None
class ExecutionResult:
    def __init__(self, status, message="", data=""): self.status, self.message, self.data = status, message, data
    @staticmethod
    def success(message="", data=""): return ExecutionResult("Success", message, data)
class _Base:
    _configs = {}
    def get_config(self): return json.dumps(_Base._configs.get(self.get_name(), {}))
    def save_config(self, s): _Base._configs[self.get_name()] = json.loads(s); return True
    def on_load(self): pass
    def on_unload(self): pass
    def on_lifecycle_event(self, e, c): pass
pages = types.SimpleNamespace()
class PagesPluginCapabilityBase(_Base):
    sender = None
    def __init__(self): pass
    def post_message(self, data):
        if PagesPluginCapabilityBase.sender: PagesPluginCapabilityBase.sender(json.dumps(data))
pages.PagesPluginCapabilityBase = PagesPluginCapabilityBase
class Step(enum.Enum):
    posSlice = 1; psGCodePostProcess = 99
slicing = types.SimpleNamespace(SlicingPipelineCapabilityBase=type("SlicingPipelineCapabilityBase", (_Base,), {"__init__": lambda self: None}), Step=Step)
class LifecycleEvent(enum.Enum):
    SliceStarted = 1; SlicingJobComplete = 2
class LifecycleEvtCode(enum.Enum):
    Ok = 0; Error = 1; Warn = 2
class base: pass
def plugin(cls):
    global _pkg; _pkg = cls; return cls
def register_capability(cls): _registered.append(cls)
