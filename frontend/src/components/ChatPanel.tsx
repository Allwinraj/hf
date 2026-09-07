import { useEffect, useRef, useState, type FormEvent } from 'react'
import Icon from './Icon'
import MarkdownBody from './MarkdownBody'
import TypingDots from './TypingDots'
import { useAgents } from '../context/AgentContext'
import type { ChatMessage } from '../types/nexus'

export default function ChatPanel() {
  const {
    messages,
    sendMessage,
    upload,
    confirm,
    handoff,
    busy,
    status,
    readyToConfirm,
    confirmed,
    questionCount,
    summary,
    libraryPipelineId,
    uploadOffer,
    cannotServe,
    suggestHandoff,
  } = useAgents()
  const [draft, setDraft] = useState('')
  const scroller = useRef<HTMLDivElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const showConfirm = !libraryPipelineId && (readyToConfirm || status === 'ready_to_confirm') && !confirmed
  const showHandoff =
    !libraryPipelineId &&
    status !== 'confirmed' &&
    (cannotServe || suggestHandoff || questionCount >= 12 || status === 'handoff')

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }, [messages, uploadOffer, busy])

  if (libraryPipelineId) {
    return (
      <aside className="flex h-full w-full flex-col border-r border-[var(--ey-line)] bg-surface-container">
        <div className="flex h-14 shrink-0 items-center gap-2 border-b border-[var(--ey-line)] px-6">
          <Icon name="account_tree" className="text-tertiary-fixed-dim" />
          <h2 className="font-label-md tracking-wider text-on-surface">Library pipeline</h2>
        </div>
        <div className="p-6 font-body-md text-on-surface-variant">
          Loaded from Super Agents. Use Run in chat to execute with named files.
        </div>
      </aside>
    )
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    const text = draft.trim()
    if (!text || busy) return
    setDraft('')
    void sendMessage(text)
  }

  const uploadLabel =
    uploadOffer === 'data'
      ? 'Attach your input files'
      : uploadOffer === 'knowledge'
        ? 'Attach reference documents'
        : null

  return (
    <aside className="flex h-full w-full flex-col border-r border-[var(--ey-line)] bg-surface-container">
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-[var(--ey-line)] bg-[color-mix(in_srgb,var(--ey-accent)_7%,transparent)] px-6">
        <div className="flex items-center gap-2">
          <Icon name="smart_toy" className={`text-tertiary-fixed-dim ${busy ? 'animate-pulse' : ''}`} />
          <h2 className="font-label-md tracking-wider text-on-surface">Nexus</h2>
          {busy ? <span className="chip chip-accent font-mono-label">thinking…</span> : null}
        </div>
        {questionCount > 0 && status === 'interview' && (
          <span className="chip font-mono-label">Q {questionCount}/15</span>
        )}
      </div>

      <div ref={scroller} className="min-h-0 flex-1 space-y-6 overflow-y-auto p-6">
        {messages.map((message) => (
          <ChatBubble key={message.id} message={message} />
        ))}
        {busy && (
          <div className="rise flex gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[var(--ey-line)] bg-surface-container-highest">
              <Icon name="auto_awesome" className="animate-pulse text-[16px] text-tertiary-fixed-dim" />
            </div>
            <div className="rounded-2xl rounded-tl-sm border border-[var(--ey-line)] bg-surface-container-high p-4">
              <TypingDots label="Nexus is thinking" />
            </div>
          </div>
        )}
        {summary && (readyToConfirm || confirmed || status === 'handoff') && (
          <div className="rise rail rounded-xl border border-primary-fixed-dim/30 bg-surface-container-high p-4 pl-5 font-body-md text-on-surface">
            <div className="mb-1 flex items-center gap-2 font-label-md text-primary-fixed-dim">
              <Icon name="fact_check" className="text-[18px]" />
              Pipeline summary
            </div>
            <MarkdownBody text={summary} />
          </div>
        )}
      </div>

      <div className="shrink-0 space-y-3 border-t border-[var(--ey-line)] bg-surface-container p-4">
        {uploadLabel && (
          <div className="space-y-2">
            <button
              type="button"
              className="hover-tint flex w-full items-center justify-center gap-2 rounded-xl border border-primary-fixed-dim/30 bg-surface-container-high py-2.5 font-label-md text-primary-fixed-dim disabled:opacity-40"
              onClick={() => fileInput.current?.click()}
              disabled={busy}
            >
              <Icon name="upload_file" className="text-[18px]" />
              {uploadLabel}
            </button>
            <input
              ref={fileInput}
              type="file"
              className="hidden"
              multiple
              accept={uploadOffer === 'knowledge' ? '.csv,.xlsx,.pdf,.txt,.md' : '.csv,.xlsx,.pdf'}
              onChange={(e) => {
                if (e.target.files?.length && uploadOffer) {
                  void upload(uploadOffer, e.target.files)
                }
                e.target.value = ''
              }}
            />
          </div>
        )}
        {showConfirm && (
          <button
            type="button"
            onClick={() => void confirm()}
            disabled={busy}
            className="cta-sheen w-full rounded-xl bg-primary-container py-2 font-label-md text-on-primary-container"
          >
            Confirm pipeline
          </button>
        )}
        {showHandoff && status !== 'handoff' && (
          <button
            type="button"
            onClick={() => void handoff()}
            disabled={busy}
            className="w-full rounded-lg border border-[var(--ey-line)] py-2 font-label-md text-on-surface"
          >
            Connect to a Nexus expert
          </button>
        )}
        <form onSubmit={onSubmit} className="relative flex items-center">
          <input
            className="w-full rounded-xl border border-[var(--ey-line)] bg-surface py-3 pl-4 pr-12 font-body-md text-body-md text-on-surface transition-all placeholder:text-on-surface-variant/50 focus:border-primary-fixed-dim focus:ring-1 focus:ring-primary-fixed-dim"
            placeholder={confirmed ? 'Confirmed — Save to the library to run' : 'Reply to Nexus…'}
            aria-label="Reply to Nexus"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={busy || confirmed}
          />
          <button
            type="submit"
            className="hover-tint absolute right-3 rounded-lg p-1.5 text-primary-fixed-dim"
            disabled={busy || confirmed}
            aria-label="Send"
          >
            <Icon name="send" />
          </button>
        </form>
        <span className="px-1 font-mono-label text-on-surface-variant/60">Enter to send</span>
      </div>
    </aside>
  )
}

function fileNames(message: ChatMessage): string[] {
  const files = message.meta?.files
  if (!Array.isArray(files)) return []
  return files.map((item) => {
    if (typeof item === 'string') return item
    if (item && typeof item === 'object' && 'name' in item) return String((item as { name: string }).name)
    return ''
  }).filter(Boolean)
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const ai = message.role === 'assistant'
  const attachments = fileNames(message)
  const isUpload = message.meta?.kind === 'upload' || attachments.length > 0
  return (
    <div className={`rise flex gap-3 ${ai ? '' : 'flex-row-reverse'}`}>
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border ${
          ai ? 'border-[var(--ey-line)] bg-surface-container-highest' : 'border-[var(--ey-line)] bg-surface-variant'
        }`}
      >
        <Icon
          name={ai ? 'auto_awesome' : isUpload ? 'attach_file' : 'person'}
          className={`text-[16px] ${ai ? 'text-tertiary-fixed-dim' : 'text-on-surface'}`}
        />
      </div>
      <div
        className={`max-w-[92%] rounded-2xl border p-4 font-body-md text-body-md shadow-sm ${
          ai
            ? 'rounded-tl-sm border-[var(--ey-line)] bg-surface-container-high text-on-surface-variant'
            : 'whitespace-pre-wrap rounded-tr-sm border-[var(--ey-line)] bg-surface-variant text-on-surface'
        }`}
      >
        {ai ? <MarkdownBody text={message.content} /> : message.content}
        {attachments.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {attachments.map((name) => (
              <span
                key={name}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--ey-line)] bg-surface-container-high px-2.5 py-1 font-label-md text-primary-fixed-dim"
              >
                <Icon name="description" className="text-[16px]" />
                {name}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
