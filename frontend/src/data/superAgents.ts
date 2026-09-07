export type AgentStatus = 'published' | 'draft'

export interface SuperAgent {
  id: string
  name: string
  category: string
  description: string
  version: string
  runs: number
  status: AgentStatus
  icon: string
}

export const seedSuperAgents: SuperAgent[] = [
  {
    id: 'budget-actual',
    name: 'Budget vs Actual',
    category: 'FP&A',
    description:
      'Automates variance analysis by comparing actuals to budget, identifying key discrepancies and generating executive summaries.',
    version: 'v2.1',
    runs: 48,
    status: 'published',
    icon: 'bar_chart',
  },
  {
    id: 'bank-recon',
    name: 'Bank Reconciliation',
    category: 'R2R',
    description:
      'Matches daily bank statement transactions against ERP ledger entries and flags exceptions for manual review.',
    version: 'v1.4',
    runs: 31,
    status: 'published',
    icon: 'account_balance',
  },
  {
    id: 'invoice-processing',
    name: 'Invoice Processing',
    category: 'P2P',
    description:
      'Extracts data from incoming vendor invoices, performs 3-way matching, and queues for payment approval.',
    version: 'v3.0',
    runs: 22,
    status: 'published',
    icon: 'receipt_long',
  },
  {
    id: 'intercompany-recon',
    name: 'Intercompany Recon',
    category: 'R2R',
    description:
      'Reconciles balances between subsidiary ledgers, automatically netting corresponding receivables and payables.',
    version: 'v0.9',
    runs: 0,
    status: 'draft',
    icon: 'autorenew',
  },
  {
    id: 'cash-flow-forecast',
    name: 'Cash Flow Forecast',
    category: 'FP&A',
    description:
      'Predicts near-term liquidity by aggregating AP, AR, and historical treasury data models into a rolling forecast.',
    version: 'v1.1',
    runs: 15,
    status: 'published',
    icon: 'water_drop',
  },
  {
    id: 'vendor-onboarding',
    name: 'Vendor Onboarding',
    category: 'Procurement',
    description:
      'Collects W-9s, verifies banking details, and sets up new suppliers across connected ERP and compliance systems.',
    version: 'v0.5',
    runs: 2,
    status: 'draft',
    icon: 'group_add',
  },
]
