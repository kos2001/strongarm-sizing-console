import type { DeviceKey, Params } from '../types'
import { DEVICE_META } from '../types'
import { DEVICE_ROLES, t, UI, type Lang } from '../i18n'

interface Props {
  params: Params
  onChange: (p: Params) => void
  disabled: boolean
  lang: Lang
}

const KEYS: DeviceKey[] = ['input', 'tail', 'ncc', 'pcc', 'pre']
const FIELDS: { k: 'w_um' | 'l_nm' | 'm'; label: string; step: number }[] = [
  { k: 'w_um', label: 'W (µm)', step: 0.5 },
  { k: 'l_nm', label: 'L (nm)', step: 5 },
  { k: 'm', label: 'M', step: 1 },
]

export default function DeviceEditor({ params, onChange, disabled, lang }: Props) {
  // W 그리드 모델: gaa2nm = 나노시트 스택 0.2µ, asap7 = 핀 0.07µ — 입력을 그리드에 스냅
  const unit = params.model === 'gaa2nm' ? 0.2 : params.model === 'asap7' ? 0.07 : null
  const unitName = params.model === 'asap7' ? { ko: '핀', en: 'fin' } : { ko: '스택', en: 'stack' }
  const setDev = (dk: DeviceKey, field: 'w_um' | 'l_nm' | 'm', v: number) => {
    if (unit && field === 'w_um') v = Math.max(unit, Math.round(Math.round(v / unit) * unit * 1000) / 1000)
    onChange({
      ...params,
      devices: { ...params.devices, [dk]: { ...params.devices[dk], [field]: v } },
    })
  }

  return (
    <div className="flex flex-col gap-2.5">
      <div
        className="grid gap-2 mono text-[11px] uppercase tracking-wider px-1"
        style={{ gridTemplateColumns: '1.6fr 1fr 1fr 0.7fr', color: 'var(--faint)' }}
      >
        <span>{t(lang, UI.device)}</span>
        <span>{unit ? `W (${unit}µ×${lang === 'ko' ? unitName.ko : unitName.en})` : 'W (µm)'}</span>
        <span>L (nm)</span>
        <span>M</span>
      </div>
      {KEYS.map((dk) => {
        const meta = DEVICE_META[dk]
        return (
          <div
            key={dk}
            className="grid gap-2 items-center rounded-xl p-2.5"
            style={{
              gridTemplateColumns: '1.6fr 1fr 1fr 0.7fr',
              background: 'var(--surface)',
              border: '1px solid var(--line)',
              borderLeft: `3px solid var(--si)`,
            }}
          >
            <div className="min-w-0">
              <div className="mono text-sm" style={{ color: 'var(--text)' }}>
                {meta.name}
              </div>
              <div className="text-xs truncate" style={{ color: 'var(--muted)' }}>
                {t(lang, DEVICE_ROLES[dk])}
              </div>
            </div>
            {FIELDS.map((f) => (
              <input
                key={f.k}
                type="number"
                step={unit && f.k === 'w_um' ? unit : f.step}
                min={0}
                disabled={disabled}
                title={unit && f.k === 'w_um' ? (lang === 'ko' ? `${unit}µ(${unitName.ko} 1개) 단위로 스냅 — 현재 ${Math.round(params.devices[dk].w_um / unit)}${unitName.ko} × M${params.devices[dk].m}` : `snaps to ${unit}µ (1 ${unitName.en}) — ${Math.round(params.devices[dk].w_um / unit)} ${unitName.en}s × M${params.devices[dk].m}`) : undefined}
                value={params.devices[dk][f.k]}
                onChange={(e) => setDev(dk, f.k, parseFloat(e.target.value) || 0)}
                aria-label={`${meta.name} ${f.label}`}
              />
            ))}
          </div>
        )
      })}
    </div>
  )
}
