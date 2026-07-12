import { useState } from 'react'
import type { Device, DeviceKey, Params } from '../types'

type Targets = Record<'decision_time_ps' | 'power_uw' | 'offset_sigma_mv', number>

// 자연어 사이징 에이전트 — hermes strong-arm 프로파일(MCP: 실제 ngspice)로
// 프록시(/api/agent/chat). 매 턴 현재 파라미터·스펙을 컨텍스트로 보내고,
// 에이전트가 제안하는 변경은 답변 끝의 ```json 블록으로 받아 ↧ 적용한다.
// 세션(X-Hermes-Session-Id)이 유지돼 이어지는 질문은 맥락을 기억한다.

interface Proposal {
  devices?: Partial<Record<DeviceKey, Partial<Device>>>
  targets?: Partial<Targets>
  vdd?: number
  cload_ff?: number
  topology?: 'strongarm' | 'doubletail'
}
interface Msg { role: 'user' | 'assistant'; text: string; proposal?: Proposal | null; deck?: string | null }

function extractDeck(answer: string): string | null {
  const m = answer.match(/```spice\s*([\s\S]*?)```/)
  return m ? m[1].trim() : null
}

function downloadDeck(text: string, filename: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

const DEV_KEYS: DeviceKey[] = ['input', 'tail', 'ncc', 'pcc', 'pre']

function extractProposal(answer: string): Proposal | null {
  const m = answer.match(/```json\s*([\s\S]*?)```/)
  if (!m) return null
  try {
    const j = JSON.parse(m[1])
    const out: Proposal = {}
    if (j.devices && typeof j.devices === 'object') {
      out.devices = {}
      for (const k of DEV_KEYS) if (j.devices[k]) out.devices[k] = j.devices[k]
    }
    if (j.targets && typeof j.targets === 'object') out.targets = j.targets
    if (typeof j.vdd === 'number') out.vdd = j.vdd
    if (typeof j.cload_ff === 'number') out.cload_ff = j.cload_ff
    if (j.topology === 'strongarm' || j.topology === 'doubletail') out.topology = j.topology
    return Object.keys(out).length ? out : null
  } catch { return null }
}

export default function AgentSizing({ params, targets, onApply, ko, disabled }: {
  params: Params
  targets: Targets
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
        topology: params.topology ?? 'strongarm', vdd: params.vdd, cload_ff: params.cload_ff,
        devices: params.devices, spec_targets: targets,
      }
      const message =
        `현재 comparator 설계 상태(JSON):\n${JSON.stringify(ctx)}\n\n` +
        `규칙: 아래 사용자의 요청을 처리하라. 시뮬레이션이 필요하면 오직 strongarm MCP 도구(strongarm_run_sim/strongarm_optimize)만 사용하고, params 인자에 위 설계 상태(및 변경분)를 그대로 넣어 한 번에 호출하라. terminal·파일 등 다른 도구는 절대 사용하지 말고, 도구 호출은 최대 2회, 탐색·검증 반복 없이 결과를 바로 보고하라. 회로 구조 자체를 바꾸는 요청(소자 추가/삭제/결선 변경)이면: ① strongarm_netlist 도구로 현재 덱(.sp)을 받고 ② 텍스트로 수정한 뒤 ③ spice_run_netlist 도구로 실행해 측정값을 확인하고 ④ 수정된 덱 전체를 답변에 \`\`\`spice 코드블록으로 포함하라(이때는 도구 3회까지 허용). ` +
        `소자 크기(w_um/l_nm/m)·스펙(decision_time_ps/power_uw/offset_sigma_mv)·vdd·cload_ff·topology 변경을 제안/적용할 때는 답변 마지막에 \`\`\`json {"devices":{...변경 소자만...},"targets":{...},"vdd":...,"topology":"..."} \`\`\` 블록을 포함하라(변경 없으면 생략). 간결한 한국어로 답하라.\n\n` +
        `사용자 요청: ${q}`
      const r = await fetch('/api/agent/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message, sessionId }) })
      const d = await r.json()
      if (d.error) { setMsgs((m) => [...m, { role: 'assistant', text: '⚠ ' + d.error }]); return }
      setSessionId(d.sessionId)
      setMsgs((m) => [...m, { role: 'assistant', text: d.answer, proposal: extractProposal(d.answer), deck: extractDeck(d.answer) }])
    } catch (e) {
      setMsgs((m) => [...m, { role: 'assistant', text: '⚠ ' + String(e) }])
    } finally { setBusy(false) }
  }

  return (
    <div className="rounded-2xl p-4" style={{ background: 'var(--surface)', border: '1px solid color-mix(in srgb, var(--ag) 30%, var(--line))' }}>
      <div className="flex items-center justify-between mb-2">
        <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--ag)' }}>
          🤖 {T('자연어 사이징 · 스펙 (hermes agent)', 'natural-language sizing · spec (hermes agent)')}
        </div>
        {msgs.length > 0 && (
          <button onClick={() => { setMsgs([]); setSessionId(null) }} className="mono text-[10.5px] px-2 py-0.5 rounded-full" style={{ color: 'var(--muted)', border: '1px solid var(--line)' }}>
            {T('새 대화', 'new chat')}
          </button>
        )}
      </div>
      {msgs.length === 0 && (
        <p className="text-xs mb-2 leading-relaxed" style={{ color: 'var(--muted)' }}>
          {T('예: "입력쌍 W를 10µ으로 키우고 시뮬 돌려서 판정시간 알려줘" · "스펙을 300ps/80µW로 바꿔" · "0.7V에서 350ps 안에 들어오게 사이징해줘" — 에이전트가 실제 ngspice(MCP)로 확인하고, 변경안은 ↧ 적용 버튼으로 에디터에 반영됩니다.',
            'e.g. "widen the input pair to 10µ and simulate" · "set spec to 300ps/80µW" · "size it to meet 350ps at 0.7V" — the agent verifies with real ngspice (MCP); proposals apply to the editor.')}
        </p>
      )}
      <div className="flex flex-col gap-2 mb-2" style={{ maxHeight: 300, overflowY: 'auto' }}>
        {msgs.map((m, i) => m.role === 'user' ? (
          <div key={i} className="self-end rounded-lg px-2.5 py-1.5 text-xs" style={{ background: 'color-mix(in srgb, var(--ag) 14%, transparent)', color: 'var(--text)' }}>{m.text}</div>
        ) : (
          <div key={i} className="rounded-lg px-2.5 py-1.5" style={{ background: 'var(--surface-2)', border: '1px solid var(--line-soft)' }}>
            <div className="text-xs whitespace-pre-wrap leading-relaxed" style={{ color: 'var(--text)' }}>{m.text.replace(/```json[\s\S]*?```/, '').replace(/```spice[\s\S]*?```/, '(수정된 넷리스트 — 아래 버튼으로 저장)').trim()}</div>
            {m.deck && (
              <div className="flex items-center gap-2 mt-2">
                <button onClick={() => downloadDeck(m.deck!, 'modified_circuit.sp')} className="mono text-[10.5px] px-2.5 py-1 rounded-full" style={{ color: 'var(--si)', border: '1px solid color-mix(in srgb, var(--si) 40%, var(--line))' }}>
                  ⤓ 수정된 넷리스트(.sp) 저장
                </button>
                <span className="mono text-[10px]" style={{ color: 'var(--faint)' }}>회로 화면의 ⇪ 넷리스트 불러오기에 붙여넣으면 소자 표로 확인 가능</span>
              </div>
            )}
            {m.proposal && (
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <span className="mono text-[10.5px]" style={{ color: 'var(--prop, var(--muted))' }}>
                  {[m.proposal.devices && `소자 ${Object.keys(m.proposal.devices).length}개`, m.proposal.targets && '스펙', m.proposal.vdd != null && `vdd ${m.proposal.vdd}V`, m.proposal.topology].filter(Boolean).join(' · ')}
                </span>
                <button onClick={() => onApply(m.proposal!)} disabled={disabled} className="mono text-[10.5px] px-2.5 py-1 rounded-full disabled:opacity-40" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
                  ↧ {T('에디터에 적용', 'apply to editor')}
                </button>
              </div>
            )}
          </div>
        ))}
        {busy && <div className="mono text-[11px]" style={{ color: 'var(--muted)' }}>{T('에이전트가 작업 중… (시뮬 포함 시 수십 초)', 'agent working… (tens of seconds with sims)')}</div>}
      </div>
      <div className="flex gap-2">
        <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !busy) send() }}
          placeholder={T('소자 크기·스펙을 자연어로…', 'sizing/spec in natural language…')} disabled={disabled}
          className="flex-1 mono text-xs rounded-lg px-2.5 py-2" style={{ background: 'var(--surface-2)', border: '1px solid var(--line)', color: 'var(--text)' }} />
        <button onClick={send} disabled={busy || disabled || !input.trim()} className="mono text-xs px-3 py-1.5 rounded-full disabled:opacity-40" style={{ color: 'var(--bg)', background: 'var(--ag)' }}>
          {busy ? '…' : T('보내기', 'send')}
        </button>
      </div>
    </div>
  )
}
