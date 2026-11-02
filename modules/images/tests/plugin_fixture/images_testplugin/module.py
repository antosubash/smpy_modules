"""The plugin's framework module: only its metadata and its dependency on images."""

from __future__ import annotations

from simple_module_core.module import ModuleBase, ModuleMeta


class TestPluginModule(ModuleBase):
    meta = ModuleMeta(name="TestPlugin", depends_on=["Images"])
