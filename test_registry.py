import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "mu_nodes_runninghub",
    ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)],
)
assert spec and spec.loader
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)

EXPECTED = {
    "MmuuAIMediaParserNodeV001",
    "MmuuAILinkListSplitterNodeV001",
    "MmuuAIH3SystemPromptLanguageNodeV001",
    "MmuuAIVideoCompressNodeV001",
    "MmuuAILLMModelNodeV001",
    "MmuuAIImageModelNodeV001",
    "MmuuAIGoogleImageModelNodeV001",
    "MmuuAIGeminiVideoUploadNodeV001",
    "MmuuAIGeminiVideoLLMNodeV001",
}

assert set(plugin.NODE_CLASS_MAPPINGS) == EXPECTED
assert set(plugin.NODE_DISPLAY_NAME_MAPPINGS) == EXPECTED
assert all(node.CATEGORY == "MU" for node in plugin.NODE_CLASS_MAPPINGS.values())
print(f"validated {len(EXPECTED)} nodes")


