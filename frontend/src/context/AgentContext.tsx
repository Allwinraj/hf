import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { seedSuperAgents, type SuperAgent } from '../data/superAgents'
import { api } from '../lib/api'
import { emptyPipeline, mergePipeline, upsertNodeConfig } from '../lib/reveal'
import type {
  AgentCatalogEntry,
  ChatMessage,
  ChatResponse,
  Pipeline,
  RunView,
  SessionStatus,
} from '../types/nexus'

interface AgentContextValue {
  superAgents: SuperAgent[]
  createAgent: (agent: Omit<SuperAgent, 'id' | 'runs' | 'status'>) => SuperAgent
  sessionId: string | null
  status: SessionStatus
  confirmed: boolean
  readyToConfirm: boolean
  messages: ChatMessage[]
  pipeline: Pipeline
  questionCount: number
  summary: string | null
  selectedNodeId: string | null
  run: RunView | null
  busy: boolean
  error: string | null
  libraryPipelineId: string | null
  pipelineName: string
  pipelineVersion: string
  catalog: AgentCatalogEntry[]
  uploadOffer: 'data' | 'knowledge' | null
  cannotServe: boolean
  suggestHandoff: boolean
  startSession: () => Promise<void>
  loadLibrary: (pipelineId: string) => Promise<void>
  sendMessage: (content: string) => Promise<void>
  upload: (kind: 'data' | 'knowledge', files: FileList | File[]) => Promise<void>
  confirm: () => Promise<void>
  handoff: () => Promise<void>
  syncNode: (nodeId: string, config: Record<string, unknown>) => Promise<void>
  testRun: () => Promise<void>
  saveLibrary: () => Promise<Pipeline | null>
  selectNode: (id: string | null) => void
  setPipelineName: (name: string) => void
  setPipelineVersion: (version: string) => void
}

const AgentContext = createContext<AgentContextValue | null>(null)

const STORAGE_KEY = 'nexus.superAgents'

export function AgentProvider({ children }: { children: ReactNode }) {
  const [superAgents, setSuperAgents] = useState<SuperAgent[]>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) return JSON.parse(raw) as SuperAgent[]
    } catch {
      /* seed */
    }
    return seedSuperAgents
  })

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [status, setStatus] = useState<SessionStatus>('welcome')
  const [confirmed, setConfirmed] = useState(false)
  const [readyToConfirm, setReady] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pipeline, setPipeline] = useState<Pipeline>(emptyPipeline())
  const [questionCount, setQuestionCount] = useState(0)
  const [summary, setSummary] = useState<string | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [run, setRun] = useState<RunView | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [libraryPipelineId, setLibraryPipelineId] = useState<string | null>(null)
  const [pipelineName, setPipelineName] = useState('Untitled pipeline')
  const [pipelineVersion, setPipelineVersion] = useState('v1')
  const [catalog, setCatalog] = useState<AgentCatalogEntry[]>([])
  const [uploadOffer, setUploadOffer] = useState<'data' | 'knowledge' | null>(null)
  const [cannotServe, setCannotServe] = useState(false)
  const [suggestHandoff, setSuggestHandoff] = useState(false)

  const createAgent = useCallback((agent: Omit<SuperAgent, 'id' | 'runs' | 'status'>) => {
    const created: SuperAgent = {
      ...agent,
      id: `agent-${Date.now()}`,
      runs: 0,
      status: 'draft',
    }
    setSuperAgents((prev) => {
      const next = [created, ...prev]
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      } catch {
        /* ignore */
      }
      return next
    })
    return created
  }, [])

  const applyChat = useCallback((response: ChatResponse) => {
    setSessionId(response.session_id)
    setStatus(response.status)
    setConfirmed(response.confirmed)
    setReady(response.ready_to_confirm)
    setQuestionCount(response.question_count)
    setSummary(response.summary)
    setUploadOffer(response.upload_offer ?? null)
    setCannotServe(Boolean(response.cannot_serve))
    setSuggestHandoff(Boolean(response.suggest_handoff) || response.status === 'handoff')
    setMessages((prev) => {
      const next = [...prev]
      const incoming = [response.user_message, response.message].filter(Boolean) as ChatMessage[]
      for (const msg of incoming) {
        if (!next.some((m) => m.id === msg.id)) next.push(msg)
      }
      return next
    })
    setPipeline((prev) => mergePipeline(prev, response.pipeline, response.reveal))
  }, [])

  const startSession = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const [welcome, agents] = await Promise.all([api.createSession(), api.listAgents()])
      setCatalog(agents.agents)
      setMessages([welcome.message])
      setSessionId(welcome.session_id)
      setStatus(welcome.status)
      setConfirmed(false)
      setReady(false)
      setPipeline(emptyPipeline(welcome.session_id))
      setRun(null)
      setLibraryPipelineId(null)
      setSelectedNodeId(null)
      setUploadOffer(welcome.upload_offer ?? null)
      setCannotServe(false)
      setSuggestHandoff(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start session')
    } finally {
      setBusy(false)
    }
  }, [])

  const loadLibrary = useCallback(async (pipelineId: string) => {
    setBusy(true)
    setError(null)
    try {
      const [loaded, agents] = await Promise.all([api.getPipeline(pipelineId), api.listAgents()])
      setCatalog(agents.agents)
      setLibraryPipelineId(loaded.id)
      setPipeline(loaded)
      setPipelineName(loaded.name)
      setPipelineVersion(loaded.version)
      setSessionId(null)
      setMessages([])
      setStatus('confirmed')
      setConfirmed(true)
      setReady(true)
      setRun(null)
      setUploadOffer(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load pipeline')
    } finally {
      setBusy(false)
    }
  }, [])

  const sendMessage = useCallback(
    async (content: string) => {
      if (!sessionId) return
      const user: ChatMessage = { id: `local-${Date.now()}`, role: 'user', content }
      setMessages((prev) => [...prev, user])
      setBusy(true)
      setError(null)
      try {
        applyChat(await api.sendMessage(sessionId, content))
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Message failed')
      } finally {
        setBusy(false)
      }
    },
    [applyChat, sessionId],
  )

  const upload = useCallback(
    async (kind: 'data' | 'knowledge', files: FileList | File[]) => {
      if (!sessionId || !files.length) return
      setBusy(true)
      setError(null)
      try {
        applyChat(await api.upload(sessionId, kind, files))
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Upload failed')
      } finally {
        setBusy(false)
      }
    },
    [applyChat, sessionId],
  )

  const confirm = useCallback(async () => {
    if (!sessionId) return
    setBusy(true)
    setError(null)
    try {
      applyChat(await api.confirm(sessionId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Confirm failed')
    } finally {
      setBusy(false)
    }
  }, [applyChat, sessionId])

  const handoff = useCallback(async () => {
    if (!sessionId) return
    setBusy(true)
    setError(null)
    try {
      applyChat(await api.handoff(sessionId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Handoff failed')
    } finally {
      setBusy(false)
    }
  }, [applyChat, sessionId])

  const syncNode = useCallback(
    async (nodeId: string, config: Record<string, unknown>) => {
      setPipeline((prev) => upsertNodeConfig(prev, nodeId, config))
      if (!sessionId || libraryPipelineId) return
      setBusy(true)
      setError(null)
      try {
        applyChat(await api.syncNode(sessionId, nodeId, config))
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Sync failed')
      } finally {
        setBusy(false)
      }
    },
    [applyChat, libraryPipelineId, sessionId],
  )

  const testRun = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const body = libraryPipelineId
        ? { pipeline_id: libraryPipelineId }
        : sessionId
          ? { session_id: sessionId }
          : null
      if (!body) throw new Error('Nothing to run')
      setRun(await api.startRun(body))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Run failed')
    } finally {
      setBusy(false)
    }
  }, [libraryPipelineId, sessionId])

  const saveLibrary = useCallback(async () => {
    if (!sessionId) return null
    setBusy(true)
    setError(null)
    try {
      const saved = await api.savePipeline(sessionId, pipelineName, pipelineVersion)
      return saved
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
      return null
    } finally {
      setBusy(false)
    }
  }, [pipelineName, pipelineVersion, sessionId])

  const value = useMemo(
    () => ({
      superAgents,
      createAgent,
      sessionId,
      status,
      confirmed,
      readyToConfirm,
      messages,
      pipeline,
      questionCount,
      summary,
      selectedNodeId,
      run,
      busy,
      error,
      libraryPipelineId,
      pipelineName,
      pipelineVersion,
      catalog,
      uploadOffer,
      cannotServe,
      suggestHandoff,
      startSession,
      loadLibrary,
      sendMessage,
      upload,
      confirm,
      handoff,
      syncNode,
      testRun,
      saveLibrary,
      selectNode: setSelectedNodeId,
      setPipelineName,
      setPipelineVersion,
    }),
    [
      superAgents,
      createAgent,
      sessionId,
      status,
      confirmed,
      readyToConfirm,
      messages,
      pipeline,
      questionCount,
      summary,
      selectedNodeId,
      run,
      busy,
      error,
      libraryPipelineId,
      pipelineName,
      pipelineVersion,
      catalog,
      uploadOffer,
      cannotServe,
      suggestHandoff,
      startSession,
      loadLibrary,
      sendMessage,
      upload,
      confirm,
      handoff,
      syncNode,
      testRun,
      saveLibrary,
    ],
  )

  return <AgentContext.Provider value={value}>{children}</AgentContext.Provider>
}

export function useAgents() {
  const ctx = useContext(AgentContext)
  if (!ctx) throw new Error('useAgents must be used within AgentProvider')
  return ctx
}
