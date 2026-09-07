export interface CoreAgentMode {
  title: string
  icon: string
  description: string
  highlight?: boolean
}

export interface TopologyChip {
  icon: string
  label: string
}

export interface TopologyPort {
  label: string
  tone: 'gold' | 'cyan' | 'error' | 'muted'
}

export interface AgentTopology {
  /** CSS animation class applied to the central node. */
  animation: string
  /** Upstream inputs shown on the left side. */
  inputs: TopologyChip[]
  /** Label for the downstream contract block. */
  outputTitle: string
  /** Downstream ports / deliverables shown on the right side. */
  outputs: TopologyPort[]
}

export interface CoreAgent {
  id: string
  name: string
  icon: string
  description: string
  tagline: string
  modes: string[]
  modeDetails: CoreAgentMode[]
  topology: AgentTopology
}

export const agents: CoreAgent[] = [
  {
    id: 'agent-1',
    name: 'Universal Multi-Doc Ingestor',
    icon: 'document_scanner',
    description:
      'Responsible for multi-format file extraction, OCR, and table structuring.',
    tagline: '(MCP Powered)',
    modes: ['Data Mode', 'Knowledge Mode'],
    modeDetails: [
      {
        title: 'Data Mode',
        icon: 'description',
        description:
          'Reads working files that contain actual records — invoices, purchase orders, bank statements, and transactions — and turns them into structured, typed tables.',
        highlight: true,
      },
      {
        title: 'Knowledge Mode',
        icon: 'find_in_page',
        description:
          'Reads knowledge documents — policy files, SOPs, rulebooks, contracts, and templates — and extracts structured rules, thresholds, and facts.',
      },
      {
        title: 'LLM-Driven Parsing',
        icon: 'psychology',
        description:
          'Uses the LLM as the primary engine to detect headers, types, and semantic meaning, so ingestion stays robust across any .xlsx, .csv, or .pdf layout.',
      },
    ],
    topology: {
      animation: 'anim-ingest-scan',
      inputs: [
        { icon: 'picture_as_pdf', label: 'Invoice.pdf' },
        { icon: 'table_view', label: 'Policy.xlsx' },
        { icon: 'dataset', label: 'Statement.csv' },
      ],
      outputTitle: 'TYPED TABLE',
      outputs: [
        { label: 'Headers + Types', tone: 'cyan' },
        { label: 'Schema Ref', tone: 'gold' },
        { label: 'Structured Facts', tone: 'muted' },
      ],
    },
  },
  {
    id: 'agent-2',
    name: 'Dynamic N-Way Matcher',
    icon: 'join_inner',
    description:
      'Responsible for relational joins, record alignment, and multi-source cross-referencing across disparate datasets.',
    tagline: '(Relational & Temporal Alignment)',
    modes: ['Dedupe Mode', 'Structural Mode', 'Semantic Mode'],
    modeDetails: [
      {
        title: 'Dedupe Mode',
        icon: 'filter_list',
        description:
          'One source. Finds exact and semantic near-duplicates and emits both a clean master table and an audit log with confidence scores.',
      },
      {
        title: 'Structural Mode',
        icon: 'key',
        description:
          'Two or more well-structured sources. Aligns on exact keys, composite keys, temporal windows, or multi-way joins.',
        highlight: true,
      },
      {
        title: 'Semantic Mode',
        icon: 'hub',
        description:
          'Two or more messy, real-world sources. Normalizes entities, matches fuzzy fields, and tolerates date drift.',
      },
    ],
    topology: {
      animation: 'anim-match-converge',
      inputs: [
        { icon: 'picture_as_pdf', label: 'PO.xlsx' },
        { icon: 'table_view', label: 'Receipts.csv' },
        { icon: 'dataset', label: 'Invoice.pdf' },
      ],
      outputTitle: 'UNIFIED RECORD',
      outputs: [
        { label: 'Matched', tone: 'gold' },
        { label: 'Residuals', tone: 'cyan' },
        { label: 'Exceptions', tone: 'error' },
      ],
    },
  },
  {
    id: 'agent-3',
    name: 'Deterministic Rule & Math Engine',
    icon: 'calculate',
    description:
      'Responsible for exact mathematical calculations, formula evaluation, and logic gating.',
    tagline: '(Exact Python AST Math & Policy Gating)',
    modes: ['Calculation Mode', 'Rule / Gate Mode', 'Hybrid Mode'],
    modeDetails: [
      {
        title: 'Calculation Mode',
        icon: 'functions',
        description:
          'Exact decimal arithmetic with four shapes: per-row, aggregate, sequential, and scalar. Never floating point.',
        highlight: true,
      },
      {
        title: 'Rule / Gate Mode',
        icon: 'rule',
        description:
          'Deterministic policy logic — nested AND/OR, thresholds, approval routing, deduplication, and filtering.',
      },
      {
        title: 'Hybrid Mode',
        icon: 'balance',
        description:
          'Compute a value, then apply a gate to that value in a single pass — e.g. calculate variance %, then approve or flag.',
      },
    ],
    topology: {
      animation: 'anim-math-calc',
      inputs: [
        { icon: 'functions', label: 'Input Table' },
        { icon: 'rule', label: 'Policy Rules' },
      ],
      outputTitle: 'CALCULATED TABLE',
      outputs: [
        { label: 'Computed Values', tone: 'gold' },
        { label: 'Passed', tone: 'cyan' },
        { label: 'Flagged', tone: 'error' },
      ],
    },
  },
  {
    id: 'agent-4',
    name: 'Semantic Policy & Fuzzy Judge',
    icon: 'psychology',
    description:
      'Responsible for fuzzy entity matching, contextual understanding, and qualitative policy interpretation.',
    tagline: '(LLM Cognitive Layer & Fuzzy Matching)',
    modes: ['Anomaly Classification', 'Policy Interpretation', 'Approval Gateway'],
    modeDetails: [
      {
        title: 'Anomaly & Risk Classification',
        icon: 'psychology',
        description:
          'Evaluates records for unusual transactions, suspicious outliers, and unexpected drivers, then assigns risk categories and severity scores.',
        highlight: true,
      },
      {
        title: 'Policy & Contract Interpretation',
        icon: 'find_in_page',
        description:
          'Reads policy documents and contracts and evaluates transactions against nuanced, context-dependent clauses.',
      },
      {
        title: 'Approval & Escalation Gateway',
        icon: 'verified_user',
        description:
          'Renders a formal verdict — Approved, Flagged for Review, or Escalated to Management — with plain-English rationale.',
      },
    ],
    topology: {
      animation: 'anim-decide-breathe',
      inputs: [
        { icon: 'table_view', label: 'Enriched Data' },
        { icon: 'find_in_page', label: 'Policy SOP' },
      ],
      outputTitle: 'VERDICT RECORD',
      outputs: [
        { label: 'Approved', tone: 'gold' },
        { label: 'Flagged', tone: 'cyan' },
        { label: 'Escalated', tone: 'error' },
      ],
    },
  },
  {
    id: 'agent-5',
    name: 'Smart Custom Output Exporter',
    icon: 'output',
    description:
      'Responsible for generating final user-defined deliverables across multiple formats.',
    tagline: '(User-Defined Excel, Styled PDFs, Webhooks)',
    modes: ['Styled Excel Workbook', 'Visual PDF Report', 'Alert Dispatcher'],
    modeDetails: [
      {
        title: 'Styled Excel Workbook',
        icon: 'table_view',
        description:
          'Generates fully formatted multi-tab workbooks with header styling, frozen panes, native formulas, and conditional formatting.',
        highlight: true,
      },
      {
        title: 'Visual PDF Report',
        icon: 'picture_as_pdf',
        description:
          'Produces paginated, publication-ready PDFs with KPI summary cards, data tables, and automated financial charts.',
      },
      {
        title: 'Alert & Notification Dispatcher',
        icon: 'notifications',
        description:
          'Dispatches immediate Slack, Teams, or Email notifications with KPI cards and download links.',
      },
    ],
    topology: {
      animation: 'anim-output-emit',
      inputs: [
        { icon: 'table_view', label: 'Matched' },
        { icon: 'functions', label: 'Calculated' },
        { icon: 'psychology', label: 'Judged' },
      ],
      outputTitle: 'DELIVERABLE',
      outputs: [
        { label: 'Excel Workbook', tone: 'gold' },
        { label: 'PDF Briefing', tone: 'cyan' },
        { label: 'Team Alert', tone: 'muted' },
      ],
    },
  },
]
