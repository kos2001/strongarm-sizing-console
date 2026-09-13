import { Component, type ReactNode } from 'react'
import type { Lang } from '../i18n'

/** Keep navigation and saved inputs accessible if a panel fails to load/render. */
export default class AnalysisBoundary extends Component<{ children: ReactNode; page: string; lang: Lang }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidUpdate(previous: Readonly<{ page: string }>) {
    if (previous.page !== this.props.page && this.state.failed) this.setState({ failed: false })
  }
  render() {
    if (!this.state.failed) return this.props.children
    const ko = this.props.lang === 'ko'
    return <div className="analysis-notice" role="alert">
      <p>{ko ? '분석 화면을 표시하지 못했습니다. 다른 화면으로 이동하거나 새로고침해 다시 불러올 수 있습니다.' : 'This analysis panel could not be displayed. Open another workspace or reload to try again.'}</p>
      <button className="execution-open" onClick={() => window.location.reload()}>{ko ? '화면 새로고침' : 'Reload workspace'}</button>
    </div>
  }
}
