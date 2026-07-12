import { useState } from 'react'
import type { Device, VcoDeviceKey, VcoParams } from '../types'

// VCO 자연어 설정 — comparator 의 AgentSizing 과 같은 패턴(/api/agent/chat →
// hermes strong-arm, MCP vco_simulate/vco_optimize/vco_wicked = 실제 ngspice).
// 제안은 ```json 블록으로 받아 ↧ 적용: devices(6키)/vdd/vctrl/n_stages(홀수)/
// cload_ff/target_f_ghz.

interface Proposal {
  devices?: Partial<Record<VcoDeviceKey, Partial<Device>>>
  vdd?: number
  vctrl?: number
  n_stages?: number
  cload_ff?: number
  target_f_ghz?: number
}
interface Msg { role: 'user' | 'assistant'; text: string; proposal?: Proposal | null }

const KEYS: VcoDeviceKey[] = ['invp', 'invn', 'starvep', 'starven', 'xcplp', 'rstp']

function extractProposal(answer: string): Proposal | null {
  const m = answer.match(/```json\s*([\s\S]*?)```/)
  if (!m) return null
  try {
    const j = JSON.parse(m[1])
    const out: Proposal = {}
    if (j.devices && typeof j.devices === 'object') {
      out.devices = {}
      for (const k of KEYS) if (j.devices[k]) out.devices[k] = j.devices[k]
    }
    for (const f of ['vdd', 'vctrl', 'n_stages', 'cload_ff', 'target_f_ghz'] as const) {
      if (typeof j[f] === 'number') out[f] = j[f]
    }
    if (out.n_stages != null) out.n_stages = Math.max(3, out.n_stages % 2 === 0 ? out.n_stages + 1 : out.n_stages)
    return Object.keys(out).length ? out : null
  } catch { return null }
}

export default function VcoAgentSizing({ params, targetF, onApply, ko, disabled }: {
  params: VcoParams
  targetF: number
  onApply: (p: Proposal) => void
  ko: boolean
  disabled?: boolean
}) {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const T = (k: string, e: string) => (ko ? k : e)

  const send = async () => {
    const q = input.trim()
    if (!q || busy) return
    setMsgs((m) => [...m, { role: 'user', text: q }])
    setInput('')
    setBusy(true)
    try {
      const ctx = {
        topology: 'xcpl', vdd: params.vdd, vctrl: params.vctrl, n_stages: params.n_stages,
        cload_ff: params.cload_ff, devices: params.devices, target_f_ghz: targetF,
      }
      const message =
        `현재 ring VCO(xcpl) 설계 상태(JSON):\n${JSON.stringify(ctx)}\n\n` +
        `규칙: 아래 사용자의 요청을 처리하라. 시뮬레이션·사이징이 필요하면 오직 vco MCP 도구(vco_simulate/vco_optimize/vco_wicked)만 사용하고, params 인자에 위 설계 상태(및 변경분)를 그대로 넣어 한 번에 호출하라. terminal·파일 등 다른 도구는 절대 사용하지 말고, 도구 호출은 최대 2회, 탐색·검증 반복 없이 결과를 바로 보고하라. ` +
        `n_stages 는 반드시 홀수(≥3). 변경을 제안/적용할 때는 답변 마지막에 \`\`\`json {"devices":{...변경 소자만...},"vdd":...,"vctrl":...,"n_stages":...,"cload_ff":...,"target_f_ghz":...} \`\`\` 블록을 포함하라(변경 없으면 생략). 간결한 한국어로 답하라.\n\n` +
        `사용자 요청: ${q}`
      const r = await fetch('/api/agent/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message, sessionId }) })
      const d = await r.json()
      if (d.error) { setMsgs((m) => [...m, { role: 'assistant', text: '⚠ ' + d.error }]); return }
      setSessionId(d.sessionId)
      setMsgs((m) => [...m, { role: 'assistant', text: d.answer, proposal: extractProposal(d.answer) }])
    } catch (e) {
      setMsgs((m) => [...m, { role: 'assistant', text: '⚠ ' + String(e) }])
    } finally { setBusy(false) }
  }

  return (
    <div className="rounded-2xl p-4" style={{ background: 'var(--surface)', border: '1px solid color-mix(in srgb, var(--ag) 30%, var(--line))' }}>
      <div className="flex items-center justify-between mb-2">
        <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--ag)' }}>
          🤖 {T('자연어 설정 (hermes agent)', 'natural-language setup (hermes agent)')}
        </div>
        {msgs.length > 0 && (
          <button onClick={() => { setMsgs([]); setSessionId(null) }} className="mono text-[10.5px] px-2 py-0.5 rounded-full" style={{ color: 'var(--muted)', border: '1px solid var(--line)' }}>
            {T('새 대화', 'new chat')}
          </button>
        )}
      </div>
      {msgs.length === 0 && (
        <p className="text-xs mb-2 leading-relaxed" style={{ color: 'var(--muted)' }}>
          {T('예: "N을 5단으로 바꾸고 시뮬해서 주파수 알려줘" · "V_ctrl 0.5V에서 튜닝 곡선 확인해줘" · "2 GHz를 최저 전력으로 사이징해줘" — 에이전트가 실제 ngspice(MCP)로 확인하고, 변경안은 ↧ 적용으로 반영됩니다.',
            'e.g. "set N=5 and simulate" · "check the tuning at V_ctrl 0.5V" · "size it for 2 GHz at min power" — verified with real ngspice (MCP); proposals apply to the editor.')}
        </p>
      )}
      <div className="flex flex-col gap-2 mb-2" style={{ maxHeight: 300, overflowY: 'auto' }}>
        {msgs.map((m, i) => m.role === 'user' ? (
          <div key={i} className="self-end rounded-lg px-2.5 py-1.5 text-xs" style={{ background: 'color-mix(in srgb, var(--ag) 14%, transparent)', color: 'var(--text)' }}>{m.text}</div>
        ) : (
          <div key={i} className="rounded-lg px-2.5 py-1.5" style={{ background: 'var(--surface-2)', border: '1px solid var(--line-soft)' }}>
            <div className="text-xs whitespace-pre-wrap leading-relaxed" style={{ color: 'var(--text)' }}>{m.text.replace(/```json[\s\S]*?```/, '').trim()}</div>
            {m.proposal && (
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <span className="mono text-[10.5px]" style={{ color: 'var(--muted)' }}>
                  {[m.proposal.devices && `${T('소자', 'devices')} ${Object.keys(m.proposal.devices).length}`, m.proposal.n_stages != null && `N=${m.proposal.n_stages}`, m.proposal.vdd != null && `vdd ${m.proposal.vdd}V`, m.proposal.vctrl != null && `V_ctrl ${m.proposal.vctrl}V`, m.proposal.target_f_ghz != null && `${m.proposal.target_f_ghz} GHz`].filter(Boolean).join(' · ')}
                </span>
                <button onClick={() => onApply(m.proposal!)} disabled={disabled} className="mono text-[10.5px] px-2.5 py-1 rounded-full disabled:opacity-40" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
                  ↧ {T('에디터에 적용', 'apply to editor')}
                </button>
              </div>
            )}
          </div>
        ))}
        {busy && <div className="mono text-[11px]" style={{ color: 'var(--muted)' }}>{T('에이전트가 작업 중… (시뮬 포함 시 수십 초)', 'agent working…')}</div>}
      </div>
      <div className="flex gap-2">
        <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !busy) send() }}
          placeholder={T('소자 크기·N·V_ctrl·목표 f를 자연어로…', 'sizing/N/V_ctrl/target f in natural language…')} disabled={disabled}
          className="flex-1 mono text-xs rounded-lg px-2.5 py-2" style={{ background: 'var(--surface-2)', border: '1px solid var(--line)', color: 'var(--text)' }} />
        <button onClick={send} disabled={busy || disabled || !input.trim()} className="mono text-xs px-3 py-1.5 rounded-full disabled:opacity-40" style={{ color: 'var(--bg)', background: 'var(--ag)' }}>
          {busy ? '…' : T('보내기', 'send')}
        </button>
      </div>
    </div>
  )
}
