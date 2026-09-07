import type {
  AgentCatalogEntry,
  ChatResponse,
  FileSlot,
  LibraryPipeline,
  LineageView,
  DashboardView,
  ReportSpec,
  RowTrace,
  SheetPage,
  Pipeline,
  RunSnapshot,
  RunStreamEvent,
  RunView,
} from '../types/nexus'

const CLOUD_API_BASE = 'https://nexus-api.cfapps.eu10-004.hana.ondemand.com'

function apiUrl(path: string): string {
  if (import.meta.env.DEV) return `/api${path}`
  return `${CLOUD_API_BASE.replace(/\/$/, '')}${path}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), { ...init, mode: 'cors', credentials: 'omit' })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail) detail = JSON.stringify(body.detail)
    } catch {
      /* keep statusText */
    }
    throw new Error(detail)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  createSession: () => request<ChatResponse>('/chat/session', { method: 'POST' }),

  sendMessage: (session_id: string, content: string) =>
    request<ChatResponse>('/chat/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id, content }),
    }),

  upload: (session_id: string, kind: 'data' | 'knowledge', files: FileList | File[]) => {
    const form = new FormData()
    form.append('session_id', session_id)
    form.append('kind', kind)
    for (const file of Array.from(files)) form.append('files', file)
    return request<ChatResponse>('/chat/upload', { method: 'POST', body: form })
  },

  confirm: (session_id: string) =>
    request<ChatResponse>('/chat/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id }),
    }),

  handoff: (session_id: string) =>
    request<ChatResponse>('/chat/handoff', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id }),
    }),

  syncNode: (session_id: string, node_id: string, config: Record<string, unknown>) =>
    request<ChatResponse>('/chat/sync-node', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id, node_id, config }),
    }),

  listAgents: () => request<{ agents: AgentCatalogEntry[] }>('/agents'),

  listPipelines: () => request<{ pipelines: LibraryPipeline[] }>('/pipelines'),

  getPipeline: (id: string) => request<Pipeline>(`/pipelines/${id}`),

  savePipeline: (session_id: string, name: string, version: string) =>
    request<Pipeline>('/pipelines', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id, name, version }),
    }),

  startRun: (body: { session_id?: string; pipeline_id?: string }) =>
    request<RunView>('/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  uploadLibraryFiles: (pipelineId: string, files: FileList | File[]) => {
    const form = new FormData()
    for (const file of Array.from(files)) form.append('files', file)
    return request<{ written: string[]; file_slots: FileSlot[]; missing_files: string[] }>(
      `/pipelines/${pipelineId}/files`,
      { method: 'POST', body: form },
    )
  },

  runLibrary: (pipelineId: string) => request<RunView>(`/pipelines/${pipelineId}/run`, { method: 'POST' }),

  runLibraryStream: async (pipelineId: string, onEvent: (event: RunStreamEvent) => void): Promise<RunView> => {
    const response = await fetch(apiUrl(`/pipelines/${pipelineId}/run/stream`), {
      method: 'POST',
      mode: 'cors',
      credentials: 'omit',
    })
    if (!response.ok) {
      let detail = response.statusText
      try {
        const body = (await response.json()) as { detail?: unknown }
        if (typeof body.detail === 'string') detail = body.detail
        else if (body.detail) detail = JSON.stringify(body.detail)
      } catch {
        /* keep statusText */
      }
      throw new Error(detail)
    }
    if (!response.body) throw new Error('Run stream is empty')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let result: RunView | null = null
    let errorMessage: string | null = null
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() || ''
      for (const chunk of chunks) {
        const line = chunk.split('\n').find((item) => item.startsWith('data: '))
        if (!line) continue
        const event = JSON.parse(line.slice(6)) as RunStreamEvent
        onEvent(event)
        if (event.type === 'result' && event.run) result = event.run
        if (event.type === 'error' && event.message) errorMessage = event.message
      }
    }
    if (errorMessage) throw new Error(errorMessage)
    if (!result) throw new Error('Run stream ended without a result')
    return result
  },

  askLibrary: (
    pipelineId: string,
    runId: string,
    question: string,
    view?: string,
    extra?: { node_id?: string; port?: string; row_index?: number },
  ) =>
    request<{ answer: string; run_id: string }>(`/pipelines/${pipelineId}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_id: runId, question, view, ...extra }),
    }),

  artifactUrl: (runId: string, name: string) =>
    apiUrl(`/runs/${runId}/artifacts/${encodeURIComponent(name)}`),

  getSnapshot: (runId: string) => request<RunSnapshot>(`/runs/${runId}/snapshot`),

  getDashboard: (pipelineId: string, runId: string) =>
    request<DashboardView>(`/pipelines/${pipelineId}/runs/${runId}/dashboard`),

  getLineage: (pipelineId: string, runId: string) =>
    request<LineageView>(`/pipelines/${pipelineId}/runs/${runId}/lineage`),

  getSheetRows: (
    pipelineId: string,
    runId: string,
    nodeId: string,
    port: string,
    params?: { offset?: number; limit?: number; only_exceptions?: boolean },
  ) => {
    const query = new URLSearchParams()
    if (params?.offset != null) query.set('offset', String(params.offset))
    if (params?.limit != null) query.set('limit', String(params.limit))
    if (params?.only_exceptions) query.set('only_exceptions', 'true')
    const suffix = query.toString() ? `?${query}` : ''
    return request<SheetPage>(
      `/pipelines/${pipelineId}/runs/${runId}/sheets/${encodeURIComponent(nodeId)}/${encodeURIComponent(port)}/rows${suffix}`,
    )
  },

  explainRow: (pipelineId: string, runId: string, nodeId: string, port: string, rowIndex: number) =>
    request<RowTrace>(`/pipelines/${pipelineId}/runs/${runId}/explain/row`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ node_id: nodeId, port, row_index: rowIndex }),
    }),

  getReportSpec: (pipelineId: string, runId: string, fmt = 'xlsx') =>
    request<ReportSpec>(`/pipelines/${pipelineId}/runs/${runId}/report/spec?fmt=${encodeURIComponent(fmt)}`),

  generateReport: (pipelineId: string, runId: string, format: 'xlsx' | 'pdf', sections?: ReportSpec['sections']) =>
    request<{ artifact: string; path: string; format: string }>(
      `/pipelines/${pipelineId}/runs/${runId}/report`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ format, sections }),
      },
    ),

  sendMail: (runId: string, action: 'send' | 'skip' | 'send_all', mail_ids: string[] = []) =>
    request<{ ok: boolean; action: string; rows: Record<string, unknown>[] }>(`/runs/${runId}/mail/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, mail_ids }),
    }),

  saveMailDraft: (
    runId: string,
    body: { mail_id: string; to_address?: string; draft_subject?: string; draft_body?: string },
  ) =>
    request<{ ok: boolean; row: Record<string, unknown> }>(`/runs/${runId}/mail/draft`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
}
