import { app } from "/scripts/app.js";

const CONFIGS = {
  MmuuAILLMModelNodeV001: [
    ["图片", "IMAGE", 16],
    ["视频", "VIDEO", 6],
  ],
  MmuuAIImageModelNodeV001: [["图片", "IMAGE", 16]],
  MmuuAILLMModelNodeV002: [
    ["图片", "IMAGE", 16],
    ["视频", "VIDEO", 6],
  ],
  MmuuAIImageModelNodeV002: [["图片", "IMAGE", 16]],
  MmuuAIGoogleImageModelNodeV001: [["图片", "IMAGE", 14]],
};
const LEGACY_PLATFORMS = new Set(["GPT", "Gemini", "Claude", "Grok"]);
const REQUEST_PROTOCOLS = [
  "自动（按模型）",
  "OpenAI Responses",
  "Google Gemini",
  "Anthropic Claude",
  "xAI Grok",
];
const URL_OPTIONS = ["https://api.mmuu.uk", "https://api.mmuu.ai", "自定义"];
const MODEL_FIELD_FALLBACKS = {
  MmuuAILLMModelNodeV001: "gpt-5.6-luna",
  MmuuAIImageModelNodeV001: "gpt-image-2",
};
const GENERIC_WIDGET_VALUES = new Set([
  "", "key", "模型", "系统提示词", "提示词", "标准", "专业",
  "自动", "自动（模型默认）", "自动（上游默认）", "获取key：https://mmuu.ai",
]);
const IMAGE_RESOLUTIONS = new Set(["自动", "1K", "2K", "4K"]);
const IMAGE_SIZES = new Set([
  "自动", "1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5",
  "16:9", "9:16", "2:1", "1:2", "3:1", "1:3", "21:9", "9:21",
]);
const IMAGE_QUALITIES = new Set(["自动", "low", "medium", "high"]);
const IMAGE_MODERATION = new Set(["自动（上游默认）", "低"]);
const IMAGE_REQUEST_MODES = new Set(["账号模式（OAuth）", "API模式（尺寸参数）"]);

function widget(node, name) {
  return node.widgets?.find((item) => item.name === name);
}

function setWidgetValue(node, name, value) {
  const item = widget(node, name);
  if (!item || item.value === value) return;
  item.value = value;
  item.callback?.(value);
}

function hideLegacyWidget(widget) {
  if (!widget || widget._muLegacyHidden) return;
  widget._muLegacyHidden = true;
  Object.defineProperty(widget, "hidden", {
    configurable: true,
    get: () => true,
    set: () => {},
  });
  Object.defineProperty(widget, "type", {
    configurable: true,
    get: () => "hidden",
    set: () => {},
  });
  widget.computeSize = () => [0, 0];
  const hideTimer = setInterval(() => {
    const container = widget.element?.closest?.(".lg-node-widget") || widget.element;
    if (container) container.style.display = "none";
  }, 50);
  setTimeout(() => clearInterval(hideTimer), 1200);
}

function removeLegacyWidgets(node) {
  const legacyNames = new Set(["模型", "base地址", "自定义模型名称或ID"]);
  if (!Array.isArray(node.widgets)) return;
  node.widgets = node.widgets.filter((item) => !legacyNames.has(item.name));
}

function migrateShiftedImageValues(node, rawValues, oldValues) {
  if (node.comfyClass !== "MmuuAIImageModelNodeV001") return;
  const values = rawValues.map((value) => String(value ?? "").trim()).filter(Boolean);
  const find = (predicate) => values.find(predicate);
  const isHttps = (value) => /^https:\/\//i.test(value);
  const isModel = (value) => /^(?:gpt-|mdl_)/i.test(value);
  const isKey = (value) => /^(?:sk-|AQ[\w-]{8,})/i.test(value) || value === "获取key：https://mmuu.ai";
  const customUrl = find((value) => isHttps(value) && !["https://api.mmuu.uk", "https://api.mmuu.ai"].includes(value));
  const model = find(isModel);
  const key = find(isKey);
  const requestMode = find((value) => IMAGE_REQUEST_MODES.has(value));
  const resolution = find((value) => IMAGE_RESOLUTIONS.has(value));
  const size = find((value) => IMAGE_SIZES.has(value));
  const quality = find((value) => IMAGE_QUALITIES.has(value));
  const moderation = find((value) => IMAGE_MODERATION.has(value));
  const timeout = find((value) => /^\d+$/.test(value));
  const currentPrompt = String(oldValues.get("提示词") ?? "").trim();
  const prompt = currentPrompt && !IMAGE_RESOLUTIONS.has(currentPrompt) && !IMAGE_SIZES.has(currentPrompt) &&
    !IMAGE_QUALITIES.has(currentPrompt) && !IMAGE_MODERATION.has(currentPrompt) &&
    !IMAGE_REQUEST_MODES.has(currentPrompt) && !isHttps(currentPrompt) && !isModel(currentPrompt) && !isKey(currentPrompt)
    ? currentPrompt
    : find((value) => value !== "自定义" && !isHttps(value) && !isModel(value) && !isKey(value) &&
      !IMAGE_RESOLUTIONS.has(value) && !IMAGE_SIZES.has(value) && !IMAGE_QUALITIES.has(value) &&
      !IMAGE_MODERATION.has(value) && !IMAGE_REQUEST_MODES.has(value) && !/^\d+$/.test(value));

  if (customUrl) setWidgetValue(node, "自定义URL", customUrl);
  if (model) setWidgetValue(node, "模型名称", model);
  if (key) setWidgetValue(node, "key", key);
  if (requestMode) setWidgetValue(node, "图片请求模式", requestMode);
  if (prompt) setWidgetValue(node, "提示词", prompt);
  if (resolution) setWidgetValue(node, "分辨率", resolution);
  if (size) setWidgetValue(node, "尺寸", size);
  if (quality) setWidgetValue(node, "质量", quality);
  if (moderation) setWidgetValue(node, "审核强度", moderation);
  if (timeout) setWidgetValue(node, "超时时间（秒，0不限）", Number(timeout));
}

function migrateShiftedLLMValues(node, rawValues, oldValues) {
  if (node.comfyClass !== "MmuuAILLMModelNodeV001") return;
  const values = rawValues.map((value) => String(value ?? "").trim()).filter(Boolean);
  const find = (predicate) => values.find(predicate);
  const isHttps = (value) => /^https:\/\//i.test(value);
  const isModel = (value) => /^(?:gpt-|gemini-|claude-|grok-|mdl_)/i.test(value);
  const isKey = (value) => /^(?:sk-|AQ[\w-]{8,})/i.test(value) || value === "获取key：https://mmuu.ai";
  const isNumber = (value) => /^-?\d+(?:\.\d+)?$/.test(value);
  const thinkingValues = new Set(["自动（模型默认）", "最少", "低", "中", "高", "极高", "最高"]);
  const verbosityValues = new Set(["自动（模型默认）", "简洁", "标准", "详细"]);
  const reasoningValues = new Set(["标准", "专业"]);
  const model = find(isModel);
  const key = find(isKey);
  const protocol = find((value) => REQUEST_PROTOCOLS.includes(value));
  const presetUrl = find((value) => ["https://api.mmuu.uk", "https://api.mmuu.ai"].includes(value));
  const customUrl = find((value) => isHttps(value) && !["https://api.mmuu.uk", "https://api.mmuu.ai"].includes(value));
  const temperature = find((value) => isNumber(value) && Number(value) >= 0 && Number(value) <= 2);
  const maxTokens = find((value) => /^\d+$/.test(value) && Number(value) >= 1024);
  const timeout = find((value) => /^\d+$/.test(value) && Number(value) > 2 && value !== maxTokens);
  const thinking = find((value) => thinkingValues.has(value));
  const verbosity = find((value) => verbosityValues.has(value));
  const reasoning = find((value) => reasoningValues.has(value));
  const currentModel = String(oldValues.get("模型名称") ?? "").trim();
  const currentTemperature = oldValues.get("温度");
  const currentMaxTokens = oldValues.get("最大令牌数");
  const shifted = Boolean(model) && (!isModel(currentModel) || !isNumber(String(currentTemperature)) ||
    !/^\d+$/.test(String(currentMaxTokens)));
  if (!shifted) return;

  if (model) setWidgetValue(node, "模型名称", model);
  if (key) setWidgetValue(node, "key", key);
  if (protocol) setWidgetValue(node, "请求协议", protocol);
  if (presetUrl) setWidgetValue(node, "URL", presetUrl);
  else if (customUrl) {
    setWidgetValue(node, "URL", "自定义");
    setWidgetValue(node, "自定义URL", customUrl);
  }
  if (temperature) setWidgetValue(node, "温度", Number(temperature));
  if (maxTokens) setWidgetValue(node, "最大令牌数", Number(maxTokens));
  if (timeout) setWidgetValue(node, "超时时间（秒，0不限）", Number(timeout));
  if (thinking) setWidgetValue(node, "思考强度", thinking);
  if (verbosity) setWidgetValue(node, "回答详细度（GPT）", verbosity);
  if (reasoning) setWidgetValue(node, "推理模式（统一响应）", reasoning);

  const excluded = new Set([model, key, protocol, presetUrl, customUrl, temperature, maxTokens, timeout, thinking, verbosity, reasoning]);
  const textCandidates = values.filter((value) => !excluded.has(value) && !isHttps(value) && !isNumber(value));
  const currentSystem = String(oldValues.get("系统提示词") ?? "").trim();
  const currentPrompt = String(oldValues.get("提示词") ?? "").trim();
  const validText = (value) => value && !isModel(value) && !isKey(value) && !REQUEST_PROTOCOLS.includes(value) &&
    !thinkingValues.has(value) && !verbosityValues.has(value) && !reasoningValues.has(value);
  if (!validText(currentSystem) && textCandidates[0]) setWidgetValue(node, "系统提示词", textCandidates[0]);
  if (!validText(currentPrompt) && textCandidates[1]) setWidgetValue(node, "提示词", textCandidates[1]);
}

function ensureModelCustomizationWidgets(node) {
  if (node.comfyClass !== "MmuuAILLMModelNodeV001" && node.comfyClass !== "MmuuAIImageModelNodeV001") return;
  if (!node.widgets) node.widgets = [];
  if (node._muModelWidgetSchemaPrepared) {
    const url = widget(node, "URL");
    const customUrl = widget(node, "自定义URL");
    if (url && customUrl) {
      customUrl.hidden = url.value !== "自定义";
      customUrl.computeSize = () => customUrl.hidden ? [0, 0] : [Math.max(240, node.size?.[0] - 40 || 360), 30];
    }
    return;
  }
  node._muModelWidgetSchemaPrepared = true;
  const oldModel = widget(node, "模型");
  const oldCustom = widget(node, "自定义模型名称或ID");
  const oldBase = widget(node, "base地址");
  const oldValues = node._muInitialWidgetValuesByName || new Map(node.widgets.map((item) => [item.name, item.value]));
  const modelName = widget(node, "模型名称") || node.addWidget(
    "text", "模型名称", oldCustom?.value || oldModel?.value || "", () => node.graph?.setDirtyCanvas?.(true, true),
  );
  const url = widget(node, "URL") || node.addWidget(
    "combo", "URL", oldBase?.value || "https://api.mmuu.uk", (value) => {
      const custom = widget(node, "自定义URL");
      if (custom) {
        custom.hidden = value !== "自定义";
        custom.computeSize = () => custom.hidden ? [0, 0] : [Math.max(240, node.size?.[0] - 40 || 360), 30];
      }
      node.graph?.setDirtyCanvas?.(true, true);
    },
    { values: URL_OPTIONS },
  );
  const customUrl = widget(node, "自定义URL") || node.addWidget(
    "text", "自定义URL", oldValues.get("自定义URL") || "", () => node.graph?.setDirtyCanvas?.(true, true),
  );
  const imageRequestMode = widget(node, "图片请求模式");
  const protocol = widget(node, "请求协议") || node.addWidget(
    "combo", "请求协议", oldModel ? "自动（按模型）" : "自动（按模型）", () => node.graph?.setDirtyCanvas?.(true, true),
    { values: REQUEST_PROTOCOLS },
  );
  if (oldBase && !url.value) url.value = oldBase.value;
  if (oldCustom && !modelName.value) modelName.value = oldCustom.value;
  if (oldModel && !modelName.value) modelName.value = oldModel.value;

  // Do not reorder node.widgets here. ComfyUI stores widgets_values as a
  // positional array. The Python node schema is the single source of truth for
  // both display and persistence order; client-side reordering corrupts saved
  // workflows when they are opened again.
  setWidgetValue(node, "请求协议", REQUEST_PROTOCOLS.includes(oldValues.get("请求协议")) ? oldValues.get("请求协议") : "自动（按模型）");
  const requestedUrl = oldValues.get("URL") || oldValues.get("base地址");
  const isPresetUrl = ["https://api.mmuu.uk", "https://api.mmuu.ai"].includes(requestedUrl);
  setWidgetValue(node, "URL", isPresetUrl ? requestedUrl : (requestedUrl ? "自定义" : "https://api.mmuu.uk"));
  setWidgetValue(node, "自定义URL", isPresetUrl ? (oldValues.get("自定义URL") || "") : (oldValues.get("自定义URL") || requestedUrl || ""));
  customUrl.hidden = url.value !== "自定义";
  customUrl.computeSize = () => customUrl.hidden ? [0, 0] : [Math.max(240, node.size?.[0] - 40 || 360), 30];
  const requestedModel = oldValues.get("模型名称") || oldValues.get("自定义模型名称或ID") || oldValues.get("模型");
  setWidgetValue(node, "模型名称", GENERIC_WIDGET_VALUES.has(String(requestedModel || "")) ? MODEL_FIELD_FALLBACKS[node.comfyClass] : requestedModel);
  const requestedKey = oldValues.get("key");
  setWidgetValue(node, "key", GENERIC_WIDGET_VALUES.has(String(requestedKey || "")) ? "获取key：https://mmuu.ai" : requestedKey);
  [oldModel, oldBase, oldCustom].forEach(hideLegacyWidget);
}

function migrateLoadedModelValues(node) {
  if (node._muModelValuesMigrated || !node._muInitialWidgetValues) return;
  const oldValues = node._muInitialWidgetValuesByName || new Map();
  migrateShiftedLLMValues(node, node._muInitialWidgetValues, oldValues);
  migrateShiftedImageValues(node, node._muInitialWidgetValues, oldValues);
  removeLegacyWidgets(node);
  node._muModelValuesMigrated = true;
}

function migrateLegacyWidgets(node) {
  const modelWidget = widget(node, "模型");
  if (!modelWidget || !LEGACY_PLATFORMS.has(modelWidget.value)) return;
  const values = node.widgets.map((item) => item.value);
  setWidgetValue(node, "模型", values[2]);
  setWidgetValue(node, "key", values[1]);
  if (node.comfyClass === "MmuuAILLMModelNodeV001") {
    setWidgetValue(node, "系统提示词", values[3]);
    setWidgetValue(node, "提示词", values[4]);
    setWidgetValue(node, "温度", values[5]);
    setWidgetValue(node, "思考强度", "自动（模型默认）");
    setWidgetValue(node, "最大令牌数", values[6]);
    setWidgetValue(node, "回答详细度（GPT）", "自动（模型默认）");
    setWidgetValue(node, "推理模式（统一响应）", "标准");
    setWidgetValue(node, "超时时间（秒，0不限）", values[7]);
  } else {
    setWidgetValue(node, "提示词", values[3]);
    setWidgetValue(node, "分辨率", values[4]);
    setWidgetValue(node, "尺寸", values[5]);
    setWidgetValue(node, "质量", values[6]);
    setWidgetValue(node, "超时时间（秒，0不限）", values[7]);
  }
}

function normalizeModelParameters(node) {
  if (!["MmuuAILLMModelNodeV001", "MmuuAILLMModelNodeV002"].includes(node.comfyClass)) return;
  const thinking = widget(node, "思考强度");
  const verbosity = widget(node, "回答详细度（GPT）");
  const reasoning = widget(node, "推理模式（统一响应）");
  const thinkingValues = new Set(["自动（模型默认）", "最少", "低", "中", "高", "极高", "最高"]);
  const verbosityValues = new Set(["自动（模型默认）", "简洁", "标准", "详细"]);
  if (!thinkingValues.has(thinking?.value)) setWidgetValue(node, "思考强度", "自动（模型默认）");
  if (!verbosityValues.has(verbosity?.value)) setWidgetValue(node, "回答详细度（GPT）", "自动（模型默认）");
  if (!new Set(["标准", "专业"]).has(reasoning?.value)) {
    setWidgetValue(node, "推理模式（统一响应）", "标准");
  }
}

function inputNumber(name, prefix, maximum) {
  const text = String(name || "");
  if (!text.startsWith(prefix)) return 0;
  const value = Number(text.slice(prefix.length));
  return Number.isInteger(value) && value >= 1 && value <= maximum ? value : 0;
}

function seriesNumber(name, prefix) {
  const text = String(name || "");
  if (!text.startsWith(prefix)) return 0;
  const value = Number(text.slice(prefix.length));
  return Number.isInteger(value) && value >= 1 ? value : 0;
}

function hasLink(input) {
  return input?.link != null || (Array.isArray(input?.links) && input.links.length > 0);
}

function refreshSeries(node, prefix, type, maximum) {
  const connected = node.inputs
    .filter((input) => inputNumber(input?.name, prefix, maximum) && hasLink(input))
    .map((input) => inputNumber(input.name, prefix, maximum));
  const lastConnected = connected.length ? Math.max(...connected) : 0;
  const visibleCount = Math.min(maximum, Math.max(1, lastConnected + 1));
  for (let number = 1; number <= visibleCount; number += 1) {
    const name = `${prefix}${number}`;
    if (!node.inputs.some((input) => input.name === name)) node.addInput(name, type);
  }
  for (let index = node.inputs.length - 1; index >= 0; index -= 1) {
    const number = seriesNumber(node.inputs[index]?.name, prefix);
    if (number > maximum) {
      // A legacy graph can retain ports beyond this node's supported maximum.
      // Remove their dangling links as well so the obsolete port cannot survive.
      node.disconnectInput?.(index);
      node.removeInput(index);
    } else if (number > visibleCount && !hasLink(node.inputs[index])) {
      node.removeInput(index);
    }
  }
}

function refresh(node, migrateValues = false) {
  const config = CONFIGS[node.comfyClass];
  if (!config || !Array.isArray(node.inputs)) return;
  if (migrateValues && !node._muInitialWidgetValues) {
    node._muInitialWidgetValues = node.widgets.map((item) => item.value);
    node._muInitialWidgetValuesByName = new Map(node.widgets.map((item) => [item.name, item.value]));
  }
  migrateLegacyWidgets(node);
  ensureModelCustomizationWidgets(node);
  if (migrateValues) migrateLoadedModelValues(node);
  else removeLegacyWidgets(node);
  normalizeModelParameters(node);
  for (const args of config) refreshSeries(node, ...args);
  const computed = node.computeSize();
  node.setSize([Math.max(Number(node.size?.[0]) || computed[0], 420, computed[0]), computed[1]]);
  node.graph?.setDirtyCanvas?.(true, true);
}

function schedule(node, migrateValues = false) {
  for (const delay of [0, 100, 500, 1000]) setTimeout(() => refresh(node, migrateValues), delay);
}

app.registerExtension({
  name: "mu.model-nodes.dynamic-inputs",
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (!CONFIGS[nodeData?.name]) return;
    const originalCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      const result = originalCreated?.apply(this, args);
      schedule(this);
      return result;
    };
    const originalConfigured = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (...args) {
      const result = originalConfigured?.apply(this, args);
      // ComfyUI applies saved widgets_values during configuration. Capture the
      // post-load values, not the defaults created in onNodeCreated.
      this._muInitialWidgetValues = undefined;
      this._muInitialWidgetValuesByName = undefined;
      this._muModelValuesMigrated = false;
      schedule(this, true);
      return result;
    };
    const originalConnectionsChange = nodeType.prototype.onConnectionsChange;
    nodeType.prototype.onConnectionsChange = function (...args) {
      const result = originalConnectionsChange?.apply(this, args);
      setTimeout(() => refresh(this), 0);
      return result;
    };
  },
  nodeCreated(node) {
    if (CONFIGS[node.comfyClass]) schedule(node);
  },
  loadedGraphNode(node) {
    if (CONFIGS[node.comfyClass]) {
      // The graph loader has now applied the positional widgets_values array.
      // Re-capture it once and repair legacy workflows by semantic value.
      node._muInitialWidgetValues = undefined;
      node._muInitialWidgetValuesByName = undefined;
      node._muModelValuesMigrated = false;
      migrateLegacyWidgets(node);
      normalizeModelParameters(node);
      schedule(node, true);
    }
  },
});
