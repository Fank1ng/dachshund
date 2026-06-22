const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("dachshund", {
  snapshot: () => ipcRenderer.invoke("app:snapshot"),
  action: (name, payload = {}) => ipcRenderer.invoke("app:action", name, payload),
  api: (method, path, body = null) => ipcRenderer.invoke("app:api", method, path, body),
  asset: (name) => ipcRenderer.invoke("app:asset", name),
  openExternal: (url) => ipcRenderer.invoke("app:open-external", url),
  openPath: (key) => ipcRenderer.invoke("app:open-path", key),
  onStatus: (callback) => {
    ipcRenderer.on("status:changed", (_event, status) => callback(status));
  },
});
