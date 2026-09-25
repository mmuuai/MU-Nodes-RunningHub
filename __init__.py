from .media_tools.node import MmuuAIMediaParserNode
from .media_tools.text_nodes import MmuuAIH3SystemPromptLanguageNode
from .media_tools.utility_nodes import MmuuAILinkListSplitterNode
from .media_tools.video_compress import MmuuAIVideoCompressNode
from .model_nodes import (
    MmuuAIImageModelNode,
    MmuuAIGoogleImageModelNode,
    MmuuAILLMModelNode,
    MmuuAIGeminiVideoUploadNode,
    MmuuAIGeminiVideoLLMNode,
)

_INCLUDED_NODE_TYPES = (
    MmuuAIMediaParserNode,
    MmuuAIH3SystemPromptLanguageNode,
    MmuuAILinkListSplitterNode,
    MmuuAIVideoCompressNode,
    MmuuAIImageModelNode,
    MmuuAIGoogleImageModelNode,
    MmuuAILLMModelNode,
    MmuuAIGeminiVideoUploadNode,
    MmuuAIGeminiVideoLLMNode,
)
for _node_type in _INCLUDED_NODE_TYPES:
    _node_type.CATEGORY = "MU"

NODE_CLASS_MAPPINGS = {
    "MmuuAIMediaParserNodeV001": MmuuAIMediaParserNode,
    "MmuuAILinkListSplitterNodeV001": MmuuAILinkListSplitterNode,
    "MmuuAIH3SystemPromptLanguageNodeV001": MmuuAIH3SystemPromptLanguageNode,
    "MmuuAIVideoCompressNodeV001": MmuuAIVideoCompressNode,
    "MmuuAILLMModelNodeV001": MmuuAILLMModelNode,
    "MmuuAIImageModelNodeV001": MmuuAIImageModelNode,
    "MmuuAIGoogleImageModelNodeV001": MmuuAIGoogleImageModelNode,
    "MmuuAIGeminiVideoUploadNodeV001": MmuuAIGeminiVideoUploadNode,
    "MmuuAIGeminiVideoLLMNodeV001": MmuuAIGeminiVideoLLMNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MmuuAIMediaParserNodeV001": "MU｜媒体分析",
    "MmuuAILinkListSplitterNodeV001": "MU｜链接列表拆分",
    "MmuuAIH3SystemPromptLanguageNodeV001": "MU｜H3系统提示词语言选择",
    "MmuuAIVideoCompressNodeV001": "MU｜视频流式压缩",
    "MmuuAILLMModelNodeV001": "MU｜LLM处理",
    "MmuuAIImageModelNodeV001": "MU｜图片处理",
    "MmuuAIGoogleImageModelNodeV001": "MU｜G图片处理",
    "MmuuAIGeminiVideoUploadNodeV001": "MU｜G视频上传",
    "MmuuAIGeminiVideoLLMNodeV001": "MU｜G视频LLM处理",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]



