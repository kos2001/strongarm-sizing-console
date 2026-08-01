import { useState, type ReactNode } from 'react'

// 플로팅 에이전트 독 — 우하단 🤖 버튼을 누르면 슬라이드업 패널이 열린다.
// 모든 페이지에서 접근 가능(fixed), 내용물(children)은 도메인별 자연어
// 패널(AgentSizing / VcoAgentSizing). 패널 상태는 독이 열려도 유지된다.

export default function AgentDock({ ko, children }: { ko: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      {/* children 을 항상 마운트해 대화 상태를 유지하고, 표시만 토글 */}
      <div style={{
        position: 'fixed', right: 20, bottom: 76, zIndex: 60,
        width: 'min(430px, calc(100vw - 40px))', maxHeight: '72vh', overflowY: 'auto',
        display: open ? 'block' : 'none',
        boxShadow: '0 12px 40px rgba(0,0,0,0.45)', borderRadius: 16,
      }}>
        {children}
      </div>
      <button onClick={() => setOpen((v) => !v)}
        title={ko ? '자연어 에이전트 (실제 ngspice 로 시뮬·사이징)' : 'natural-language agent (real ngspice)'}
        style={{
          position: 'fixed', right: 20, bottom: 20, zIndex: 61,
          width: 48, height: 48, borderRadius: 24, fontSize: 22, lineHeight: 1,
          background: open ? 'var(--ag)' : 'var(--surface)', color: open ? 'var(--bg)' : 'var(--text)',
          border: '1px solid color-mix(in srgb, var(--ag) 55%, var(--line))',
          boxShadow: '0 6px 20px rgba(0,0,0,0.35)', cursor: 'pointer',
        }}>
        {open ? '×' : '🤖'}
      </button>
    </>
  )
}
