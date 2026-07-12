import { useState } from 'react'

// SPICE 넷리스트 입력(붙여넣기/파일) → /api/netlist/parse → 소자 표 + 파라미터 반영.
// 이 콘솔이 내보내는 덱(⤓ 넷리스트)과 그 수정본을 인식한다. 파라미터로 매핑되면
// onApply 로 회로도가 그 크기·토폴로지로 다시 그려진다(= 입력 넷리스트 시각화).

export interface ParsedDevice { name: string; type: string; w_um: number; l_nm: number; m: number; nodes: Record<string, string> }
export interface ParsedNetlist {
  kind: 'comparator' | 'vco' | 'unknown'
  n_mos: number
  devices: ParsedDevice[]
  params?: { devices: Record<string, { w_um: number; l_nm: number; m: number }>; vdd?: number; vctrl?: number; n_stages?: number; cload_ff?: number; topology?: string }
  error?: string
}

export default function NetlistImport({ kind, ko, onApply }: {
  kind: 'comparator' | 'vco'
  ko: boolean
  onApply: (p: NonNullable<ParsedNetlist['params']>) => void
}) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [parsed, setParsed] = useState<ParsedNetlist | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const T = (k: string, e: string) => (ko ? k : e)

  const parse = async () => {
    setMsg(null)
    try {
      const r = await fetch('/api/netlist/parse', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ netlist: text }) })
      const d: ParsedNetlist = await r.json()
      setParsed(d)
      if (!d.n_mos) { setMsg({ ok: false, text: T('MOS 소자를 찾지 못했습니다 — SPICE 덱인지 확인하세요.', 'No MOS devices found — is this a SPICE deck?') }); return }
      if (d.kind === kind && d.params) {
        onApply(d.params)
        setMsg({ ok: true, text: T(`인식됨(${d.kind}) — 소자 ${d.n_mos}개, 회로도에 반영했습니다.`, `Recognized (${d.kind}) — ${d.n_mos} devices, applied to the schematic.`) })
      } else if (d.kind !== 'unknown') {
        setMsg({ ok: false, text: T(`이 덱은 ${d.kind} 넷리스트입니다 — 해당 도메인 화면에서 불러오세요.`, `This deck is a ${d.kind} netlist — import it on that domain's page.`) })
      } else {
        setMsg({ ok: false, text: T('알 수 없는 토폴로지 — 파라미터 매핑 없이 소자 표만 표시합니다.', 'Unknown topology — showing the device table only.') })
      }
    } catch (e) {
      setMsg({ ok: false, text: String(e) })
    }
  }

  const onFile = (f: File | null) => {
    if (!f) return
    const rd = new FileReader()
    rd.onload = () => { setText(String(rd.result ?? '')) }
    rd.readAsText(f)
  }

  return (
    <div className="rounded-2xl p-4 mt-4" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
      <div className="flex items-center justify-between">
        <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>
          ⇪ {T('넷리스트 불러오기 (.sp) → 회로도 시각화', 'import netlist (.sp) → visualize')}
        </div>
        <button onClick={() => setOpen((v) => !v)} className="mono text-[11px] px-2.5 py-1 rounded-full" style={{ color: 'var(--muted)', border: '1px solid var(--line)' }}>
          {open ? T('접기', 'collapse') : T('펼치기', 'expand')}
        </button>
      </div>
      {open && (
        <div className="mt-3 flex flex-col gap-2">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={7} spellCheck={false}
            placeholder={T('⤓ 넷리스트로 내보낸 .sp 덱(또는 W/L/M·V 값을 수정한 버전)을 붙여넣으세요…', 'Paste a .sp deck exported by ⤓ netlist (or an edited copy)…')}
            className="mono text-[11px] rounded-lg p-2.5 w-full" style={{ background: 'var(--surface-2)', border: '1px solid var(--line)', color: 'var(--text)', resize: 'vertical' }} />
          <div className="flex items-center gap-2 flex-wrap">
            <label className="mono text-[11px] px-2.5 py-1 rounded-full cursor-pointer" style={{ color: 'var(--muted)', border: '1px solid var(--line)' }}>
              {T('파일 선택…', 'choose file…')}
              <input type="file" accept=".sp,.cir,.net,.txt" style={{ display: 'none' }} onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
            </label>
            <button onClick={parse} disabled={!text.trim()} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-40" style={{ color: 'var(--si)', border: '1px solid color-mix(in srgb, var(--si) 40%, var(--line))' }}>
              {T('파싱 → 회로도 반영', 'parse → apply')}
            </button>
            {msg && <span className="mono text-[11px]" style={{ color: msg.ok ? 'var(--good)' : 'var(--warn)' }}>{msg.text}</span>}
          </div>
          {parsed && parsed.n_mos > 0 && (
            <div className="overflow-x-auto mt-1">
              <table className="mono text-[10.5px] tnum" style={{ borderCollapse: 'collapse', width: '100%' }}>
                <thead>
                  <tr style={{ color: 'var(--faint)' }}>
                    {[T('소자', 'device'), T('종류', 'type'), 'W (µm)', 'L (nm)', 'M', 'D', 'G', 'S'].map((h) => (
                      <th key={h} style={{ textAlign: 'left', padding: '3px 8px', borderBottom: '1px solid var(--line)' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {parsed.devices.map((d) => (
                    <tr key={d.name} style={{ color: 'var(--muted)' }}>
                      <td style={{ padding: '2.5px 8px', color: 'var(--si)' }}>{d.name}</td>
                      <td style={{ padding: '2.5px 8px' }}>{d.type}</td>
                      <td style={{ padding: '2.5px 8px' }}>{d.w_um}</td>
                      <td style={{ padding: '2.5px 8px' }}>{d.l_nm}</td>
                      <td style={{ padding: '2.5px 8px' }}>{d.m}</td>
                      <td style={{ padding: '2.5px 8px' }}>{d.nodes.d}</td>
                      <td style={{ padding: '2.5px 8px' }}>{d.nodes.g}</td>
                      <td style={{ padding: '2.5px 8px' }}>{d.nodes.s}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
