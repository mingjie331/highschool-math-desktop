const { contextBridge, ipcRenderer } = require('electron')
contextBridge.exposeInMainWorld('desktop', {
  getImportSource: sid => ipcRenderer.invoke('desktop:import-source-load', sid),
  saveImportSource: (sid, value) => ipcRenderer.invoke('desktop:import-source-save', sid, value),
  appInfo: () => ipcRenderer.invoke('desktop:app-info'),
  agentStatus: () => ipcRenderer.invoke('desktop:agent-status'),
  saveAgentKey: (key, prices) => ipcRenderer.invoke('desktop:agent-save', key, prices),
  clearAgentKey: () => ipcRenderer.invoke('desktop:agent-clear'),
  onPrepareClose: handler => {
    const listener = async (_event, requestId) => {
      try { await handler(); ipcRenderer.send('desktop:close-ready', requestId, true) }
      catch { ipcRenderer.send('desktop:close-ready', requestId, false) }
    }
    ipcRenderer.on('desktop:prepare-close', listener)
    return () => ipcRenderer.removeListener('desktop:prepare-close', listener)
  },
  confirmDiscard: message => ipcRenderer.invoke('desktop:confirm-discard', message),
  chooseLatex: () => ipcRenderer.invoke('desktop:choose-latex'),
  exportFile: (kind, action, collectionCode) => ipcRenderer.invoke('desktop:export-file', kind, action, collectionCode),
  paperFile: (kind, action) => ipcRenderer.invoke('desktop:paper-file', kind, action),
  openFolder: (kind, collectionCode) => ipcRenderer.invoke('desktop:open-folder', kind, collectionCode),
  confirmDelete: message => ipcRenderer.invoke('desktop:confirm-delete', message),
})
