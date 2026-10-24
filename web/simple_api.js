import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

app.registerExtension({
  name: "SimpleAPI.TextPreview",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "SAShowText") return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      created?.apply(this, arguments);
      const widget = ComfyWidgets.STRING(
        this, "preview", ["STRING", { multiline: true }], app,
      ).widget;
      widget.inputEl.readOnly = true;
      widget.inputEl.style.opacity = "0.95";
      widget.options ??= {};
      widget.options.serialize = false;
      this._simpleAPIPreview = widget;
      this.setSize([360, 240]);
    };
    const executed = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      executed?.apply(this, arguments);
      if (this._simpleAPIPreview) {
        this._simpleAPIPreview.value = (message.text ?? []).join("\n");
        this.setDirtyCanvas(true, true);
      }
    };
  },
});
