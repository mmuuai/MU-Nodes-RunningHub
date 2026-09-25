import re


SEPARATOR_MODES = ["换行", "空格", "无分隔符", "自定义"]
MAX_PROMPT_SEGMENTS = 80
H3_OUTPUT_LANGUAGES = ("英文", "中文")
SEGMENT_HEADING = re.compile(
    r"(?m)^#{1,6}\s*分段\s*(\d+)\s*[，,]\s*时长[^\r\n]*"
)


def separator_value(mode, custom):
    if mode == "换行":
        return "\n"
    if mode == "空格":
        return " "
    if mode == "无分隔符":
        return ""
    return custom


class MmuuAIMultiStringMergeNode:
    CATEGORY = "MU/文本"
    FUNCTION = "merge"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("合并字符串",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "字符串1": ("STRING", {"forceInput": True}),
                "分隔方式": (SEPARATOR_MODES, {"default": "换行"}),
                "自定义分隔符": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": {
                f"字符串{index}": ("STRING", {"forceInput": True})
                for index in range(2, 17)
            },
        }

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    def merge(self, **kwargs):
        values = []
        for index in range(1, 17):
            value = kwargs.get(f"字符串{index}")
            if value is not None and value != "":
                values.append(str(value))
        separator = separator_value(kwargs["分隔方式"], kwargs["自定义分隔符"])
        return (separator.join(values),)


class MmuuAIH3SystemPromptLanguageNode:
    CATEGORY = "MU/文本"
    FUNCTION = "select"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("H3系统提示词",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "核心系统预设": ("STRING", {"forceInput": True}),
                "中文输出覆盖层": ("STRING", {"forceInput": True}),
                "输出语言": (H3_OUTPUT_LANGUAGES, {"default": "中文"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    def select(self, 核心系统预设, 中文输出覆盖层, 输出语言):
        core = str(核心系统预设 or "").strip()
        if 输出语言 == "英文":
            return (core,)
        overlay = str(中文输出覆盖层 or "").strip()
        return (f"{core}\n\n{overlay}" if overlay else core,)


def split_segment_prompts(text):
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    matches = list(SEGMENT_HEADING.finditer(normalized))
    if not matches:
        raise ValueError("没有找到“## 分段N，时长：...”格式的分段标题")

    segments = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        if number < 1:
            raise ValueError(f"分段编号必须从1开始，实际为 {number}")
        if number in segments:
            raise ValueError(f"检测到重复的分段编号：{number}")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        segments[number] = normalized[match.start():end].strip()
    return segments


class MmuuAISegmentPromptSplitterNode:
    CATEGORY = "MU/工具"
    FUNCTION = "split"
    RETURN_TYPES = ("INT",) + ("STRING",) * MAX_PROMPT_SEGMENTS
    RETURN_NAMES = ("实际分段数",) + tuple(
        f"分段{index}" for index in range(1, MAX_PROMPT_SEGMENTS + 1)
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "分段提示词": ("STRING", {"forceInput": True}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    def split(self, 分段提示词):
        segments = split_segment_prompts(分段提示词)
        outputs = tuple(segments.get(index, "") for index in range(1, MAX_PROMPT_SEGMENTS + 1))
        return (len(segments),) + outputs
