export {}
declare global {
  interface Window {
    desktop?: {
      appInfo():Promise<{version:string;program_directory:string;data_directory:string}>
      agentStatus(): Promise<import('./agentTypes').AIConfigStatus>
      getImportSource(sid:string):Promise<import('./importSource').SourceChoice|null>
      saveImportSource(sid:string,value:import('./importSource').SourceChoice):Promise<boolean>
      saveAgentKey(key: string, prices?: Record<string, number>): Promise<import('./agentTypes').AIConfigStatus>
      clearAgentKey(): Promise<import('./agentTypes').AIConfigStatus>
      onPrepareClose(handler: () => Promise<void>): () => void
      confirmDiscard(message: string): Promise<boolean>
      chooseLatex(): Promise<string | null>
      exportFile(kind: 'question' | 'solution', action: 'open' | 'save', collectionCode?: string): Promise<boolean>
      paperFile(kind: 'question' | 'solution', action: 'open' | 'save'): Promise<boolean>
      openFolder(kind: 'output' | 'papers' | 'logs' | 'data', collectionCode?: string): Promise<void>
      confirmDelete(message: string): Promise<boolean>
    }
  }
}
