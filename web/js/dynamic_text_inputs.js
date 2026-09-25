import { app } from "/scripts/app.js";

const NODE_TYPE = "MmuuAIMultiStringMergeNodeV001";
const PREFIX = "字符串";
const INPUT_TYPE = "STRING";
const MAX_INPUTS = 16;

function inputNumber(name) {
  const text = String(name || "");
  if (!text.startsWith(PREFIX)) return 0;
  const value = Number(text.slice(PREFIX.length));
  return Number.isInteger(value) && value >= 1 && value <= MAX_INPUTS ? value : 0;
}

function hasLink(input) {
  return input?.link != null || (Array.isArray(input?.links) && input.links.length > 0);
}

function refreshInputs(node) {
  if (!Array.isArray(node.inputs)) return;
  const connected = node.inputs
    .filter((input) => inputNumber(input?.name) && hasLink(input))
    .map((input) => inputNumber(input.name));
  const lastConnected = connected.length ? Math.max(...connected) : 0;
  const visibleCount = Math.min(MAX_INPUTS, Math.max(1, lastConnected + 1));

  for (let number = 1; number <= visibleCount; number += 1) {
    const name = `${PREFIX}${number}`;
    if (!node.inputs.some((input) => input.name === name)) {
      node.addInput(name, INPUT_TYPE);
    }
  }
  for (let index = node.inputs.length - 1; index >= 0; index -= 1) {
    const number = inputNumber(node.inputs[index]?.name);
    if (number > visibleCount && !hasLink(node.inputs[index])) {
      node.removeInput(index);
    }
  }

  const computed = node.computeSize();
  const currentWidth = Number(node.size?.[0]) || computed[0];
  node.setSize([Math.max(currentWidth, computed[0]), computed[1]]);
  node.graph?.setDirtyCanvas?.(true, true);
}

function scheduleRefresh(node) {
  for (const delay of [0, 100, 500]) {
    setTimeout(() => refreshInputs(node), delay);
  }
}

app.registerExtension({
  name: "mmuuai.dynamic-text-inputs.v001",
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE_TYPE) return;
    const originalCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      const result = originalCreated?.apply(this, args);
      scheduleRefresh(this);
      return result;
    };
    const originalConnectionsChange = nodeType.prototype.onConnectionsChange;
    nodeType.prototype.onConnectionsChange = function (...args) {
      const result = originalConnectionsChange?.apply(this, args);
      scheduleRefresh(this);
      return result;
    };
  },
  nodeCreated(node) {
    if (node.comfyClass === NODE_TYPE) scheduleRefresh(node);
  },
  loadedGraphNode(node) {
    if (node.comfyClass === NODE_TYPE) scheduleRefresh(node);
  },
});
