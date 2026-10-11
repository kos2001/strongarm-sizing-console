import type { Lang } from '../i18n'

export default function DraftStatus({ lang, status }: { lang: Lang; status: { savedAt: number | null; restored: boolean; saveError: boolean; saving?: boolean } }) {
  const ko = lang === 'ko'
  return <div className="draft-status" data-state={status.saveError ? 'error' : status.saving || !status.savedAt ? 'saving' : 'saved'} role="status" aria-live="polite">
    <span className="draft-mark" aria-hidden="true">{status.saveError ? '!' : '✓'}</span>
    <div>
      <span className="draft-title">{ko ? '설계 작업공간' : 'Design workspace'}</span>
      <span className="draft-detail">{status.saveError
        ? (ko ? '자동 저장 실패 · 브라우저 저장 공간을 확인하세요' : 'Autosave failed · check browser storage')
        : status.savedAt && !status.saving ? (ko ? '이 브라우저에 입력값 자동 저장됨' : 'Inputs saved in this browser')
        : (ko ? '저장 중…' : 'Saving…')}</span>
    </div>
    {status.restored && <span className="draft-restored">{ko ? '이전 입력 복원됨 · 결과는 다시 실행' : 'Previous inputs restored · rerun for results'}</span>}
  </div>
}
