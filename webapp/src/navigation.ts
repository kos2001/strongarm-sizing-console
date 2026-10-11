import { NAV_LABELS, UI, type Bi } from './i18n'

export type VcoView = 'circuit' | 'main' | 'opt' | 'pvt' | 'pushing' | 'pareto' | 'layout' | 'flow' | 'pn' | 'yield'
export interface SearchDestination { id: Page; label: Bi; group: Bi; domain: Bi }

export type Page = 'sizing' | 'circuit' | 'resolution' | 'metastability' | 'maxfclk' | 'optimizer' | 'sensitivity' | 'pareto' | 'montecarlo' | 'ber' | 'pvt' | 'yield' | 'wicked' | 'layout' | 'flow'
  | 'vcocircuit' | 'vco' | 'vcoopt' | 'vcopareto' | 'vcopn' | 'vcopvt' | 'vcoyield' | 'vcopushing' | 'vcolayout' | 'vcoflow'
export type Domain = 'comparator' | 'vco'
// Each workspace owns related analyses; leaf views stay addressable for run history.
export type Workspace = { id: string; label: Bi; glyph: string; pages: Page[] }
export const NAV_COMPARATOR: Workspace[] = [
  { id: 'design', label: { ko: '설계 편집', en: 'Design editor' }, glyph: '⎓', pages: ['sizing', 'circuit'] },
  { id: 'characterization', label: { ko: '특성 분석', en: 'Characterization' }, glyph: '∿', pages: ['resolution', 'metastability', 'ber', 'maxfclk'] },
  { id: 'optimization', label: { ko: '최적화', en: 'Optimization' }, glyph: '◴', pages: ['optimizer', 'sensitivity', 'pareto'] },
  { id: 'variation', label: { ko: '변동성 검증', en: 'Variation' }, glyph: '◫', pages: ['pvt', 'montecarlo', 'yield', 'wicked'] },
  { id: 'implementation', label: { ko: '구현 · 검증', en: 'Implementation' }, glyph: '▧', pages: ['layout', 'flow'] },
]
export const NAV_VCO: Workspace[] = [
  { id: 'design', label: { ko: '설계 편집', en: 'Design editor' }, glyph: '⎓', pages: ['vco', 'vcocircuit'] },
  { id: 'optimization', label: { ko: '최적화', en: 'Optimization' }, glyph: '◴', pages: ['vcoopt', 'vcopareto'] },
  { id: 'characterization', label: { ko: '특성 분석', en: 'Characterization' }, glyph: '∿', pages: ['vcopn', 'vcopushing'] },
  { id: 'variation', label: { ko: '변동성 검증', en: 'Variation' }, glyph: '◫', pages: ['vcopvt', 'vcoyield'] },
  { id: 'implementation', label: { ko: '구현 · 검증', en: 'Implementation' }, glyph: '▧', pages: ['vcolayout', 'vcoflow'] },
]
export const DOMAIN_HOME: Record<Domain, Page> = { comparator: 'sizing', vco: 'vco' }
const VCO_PAGES = new Set<Page>(NAV_VCO.flatMap(workspace => workspace.pages))
export const VCO_VIEW: Partial<Record<Page, VcoView>> = { vcocircuit: 'circuit', vco: 'main', vcoopt: 'opt', vcopareto: 'pareto', vcopn: 'pn', vcopvt: 'pvt', vcoyield: 'yield', vcopushing: 'pushing', vcolayout: 'layout', vcoflow: 'flow' }
export const domainOf = (p: Page): Domain => VCO_PAGES.has(p) ? 'vco' : 'comparator'
export const PAGES = [...NAV_COMPARATOR, ...NAV_VCO].flatMap(workspace => workspace.pages)
export const SEARCH_DESTINATIONS: SearchDestination[] = [
  ...NAV_COMPARATOR.flatMap(workspace => workspace.pages.map(id => ({ id, label: NAV_LABELS[id], group: workspace.label, domain: UI.domainComparator }))),
  ...NAV_VCO.flatMap(workspace => workspace.pages.map(id => ({ id, label: NAV_LABELS[id], group: workspace.label, domain: UI.domainVco }))),
]

export function pageForVcoView(view: VcoView) {
  return PAGES.find(page => VCO_VIEW[page] === view)
}
