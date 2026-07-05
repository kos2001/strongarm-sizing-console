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
  const setDev = (dk: DeviceKey, field: 'w_um' | 'l_nm' | 'm', v: number) => {
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
        <span>W (µm)</span>
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
                step={f.step}
                min={0}
                disabled={disabled}
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
