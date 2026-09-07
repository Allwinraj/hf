export type AgentKind = 'ingestion' | 'matcher' | 'math' | 'decision' | 'output'

export type SessionStatus =
  | 'welcome'
  | 'collecting'
  | 'interview'
  | 'ready_to_confirm'
  | 'confirmed'
  | 'handoff'

export interface ChatMessage {
  id: string
  role: 'assistant' | 'user' | 'system'
  content: string
  meta?: Record<string, unknown>
}

export interface Port {
  name: string
  direction?: 'in' | 'out'
}

export interface PipelineNode {
  id: string
  agent: AgentKind
  mode: string
  behavior_ref: string
  label: string
  config: Record<string, unknown>
  error_strategy?: string
  ports: Port[]
}

export interface PipelineEdge {
  id: string
  source: string
  source_port: string
  target: string
  target_port: string
  type?: string
  condition?: string | null
}

export interface Pipeline {
  id: string
  name: string
  version: string
  nodes: PipelineNode[]
  edges: PipelineEdge[]
  meta?: Record<string, unknown>
  file_slots?: FileSlot[]
  missing_files?: string[]
}

export interface ConfigPatch {
  node_id: string
  config: Record<string, unknown>
}

export interface ProgressiveReveal {
  upsert_nodes: PipelineNode[]
  remove_node_ids: string[]
  upsert_edges: PipelineEdge[]
  remove_edge_ids: string[]
  config_patches: ConfigPatch[]
}

export interface ChatResponse {
  session_id: string
  status: SessionStatus
  confirmed: boolean
  question_count: number
  ready_to_confirm: boolean
  summary: string | null
  upload_offer?: 'data' | 'knowledge' | null
  message: ChatMessage
  user_message?: ChatMessage | null
  reveal: ProgressiveReveal | null
  pipeline: Pipeline | null
  cannot_serve?: boolean
  suggest_handoff?: boolean
}

export interface AgentCatalogEntry {
  name: AgentKind
  label: string
  summary: string
  modes: string[]
  ports: { out: string[] }
  config_schema: Record<string, Record<string, unknown>>
}

export interface RunStepView {
  node_id: string
  agent: string
  behavior_version: string
  status: 'ok' | 'skipped' | 'error'
  duration_ms: number
  error: string | null
  skip_reason?: string | null
  summary?: string
  emitted_by: string[]
  output_ports: string[]
}

export interface RunStreamEvent {
  type: 'node_start' | 'node_finish' | 'done' | 'result' | 'error'
  run_id?: string
  node_id?: string
  agent?: string
  label?: string
  status?: string
  duration_ms?: number
  skip_reason?: string | null
  error?: string | null
  summary?: string
  message?: string
  artifacts?: string[]
  run?: RunView
}

export interface RunView {
  id: string
  pipeline_id: string
  pipeline_version: string
  status: string
  artifacts: string[]
  artifact_paths: string[]
  steps: RunStepView[]
  extra: Record<string, unknown>
}

export interface Envelope {
  run_id: string
  node_id: string
  port: string
  payload: Record<string, unknown>
  emitted_by: string
  knowledge_context?: Record<string, unknown> | null
  meta?: Record<string, unknown>
}

export interface RunStepFull {
  node_id: string
  agent: string
  behavior_version: string
  status: string
  duration_ms: number
  error: string | null
  inputs: Envelope[]
  outputs: Envelope[]
}

export interface RunSnapshot {
  run: {
    id: string
    pipeline_id: string
    pipeline_version: string
    status: string
    artifacts: string[]
    steps: RunStepFull[]
    started_at?: string | null
    finished_at?: string | null
    error?: string | null
    extra?: Record<string, unknown>
  }
  pipeline: Pipeline | null
}

export interface FileSlot {
  node_id: string
  kind: 'data' | 'knowledge' | string
  filename: string
  label: string
}

export interface DashboardWidget {
  catalog_id: string
  title: string
  source_node?: string | null
  source_port?: string | null
  value?: number
    data?: { name: string; value?: number; actual?: number; expected?: number; [key: string]: unknown }[]
    columns?: string[]
    rows?: Record<string, unknown>[]
    mail_rows?: Record<string, unknown>[]
    actions?: string[]
    subtitle?: string
    unit?: string
    delta?: number
    trend?: number[]
    series?: string[]
    text?: string
    explain?: {
      source_node?: string | null
      source_port?: string | null
      column?: string | null
      aggregation?: string
      why?: string
    }
}

export interface DashboardView {
  source: string
  widgets: DashboardWidget[]
  ports: Record<string, unknown>[]
  profile?: {
    name?: string
    purpose?: string
    brief?: string
    status?: string
    totals?: number
  }
}

export interface SheetCard {
  port: string
  sheet_name: string
  node_id: string
  agent: string
  row_count: number
  purpose: string
  columns: string[]
  key_columns?: string[]
  computed_columns?: string[]
  verdict_columns?: string[]
}

export interface ColumnCard {
  column: string
  origin?: string
  why?: string
  node_id?: string
  port?: string
  sheet_name?: string
  filename?: string
  catalog_id?: string | null
}

export interface DerivationCard {
  node_id: string
  agent: string
  label: string
  mode?: string
  status: string
  purpose?: string
  why?: string
  numbers?: { rows_in?: number; rows_out?: number; dropped?: number; matched_pct?: number | null }
  logic?: Record<string, unknown>
  outputs?: { port: string; row_count: number; columns: string[] }[]
}

export interface RowTraceStep {
  stage: string
  why?: string
  keys?: unknown
  evidence?: unknown
  confidence?: unknown
  expression?: string
  substituted?: string
  gate?: string
  verdict?: string
  explanation?: string
  citation?: unknown
  from?: { file_id: string; row: Record<string, unknown> }[]
  output_column?: string
  value?: unknown
}

export interface RowTrace {
  row: Record<string, unknown>
  row_index: number
  node_id: string
  port: string
  steps: RowTraceStep[]
  justification?: string[]
  error?: string
}

export interface ReportSection {
  catalog_id: string
  title?: string
  source_node?: string
  source_port?: string
}

export interface ReportSpec {
  source: string
  format: string
  title: string
  sections: ReportSection[]
  sheets?: SheetCard[]
}

export interface SheetPage {
  columns: string[]
  rows: Record<string, unknown>[]
  total: number
  offset: number
  limit: number
  node_id: string
  port: string
}

export interface LineageView {
  inputs: {
    node_id: string
    label: string
    filename?: string
    mode?: string
  }[]
  steps: {
    node_id: string
    agent: string
    label: string
    status: string
    summary: string
    skip_reason?: string | null
    catalog_id?: string | null
    formula_en?: string | null
    ast?: string | null
    keys?: unknown
    policy?: unknown
    formats?: unknown
    output_ports: string[]
    row_counts: Record<string, number>
  }[]
  outputs: { artifact: string; path: string }[]
  status: string
  cards?: DerivationCard[]
  sheets?: SheetCard[]
  columns?: ColumnCard[]
  profile?: DashboardView['profile']
}

export interface LibraryPipeline {
  id: string
  name: string
  version: string
  nodes: number
  brief?: string | null
  file_slots?: FileSlot[]
}
