// Navigate the consolidated workspaces through the visible explorer and tabs.
export async function navigate(page, label) {
  const groups = {
    '소자 크기': '설계 편집', '회로 · 파형': '설계 편집', '사이징 · 튜닝': '설계 편집',
    'WiCkeD 강건성': '변동성 검증', 'PVT 코너': '변동성 검증',
    '자동 사이징': '최적화', '전체 흐름': '구현 · 검증',
  }
  const group = groups[label] ?? label
  const nav = page.getByRole('navigation', { name: '분석 화면' })
  if (!await nav.isVisible()) await page.getByRole('button', { name: '분석 메뉴', exact: true }).click()
  await nav.getByRole('button').filter({ hasText: group }).click()
  if (group !== '설계 편집') await page.getByRole('tab', { name: label, exact: true }).click()
  await page.locator('.panel-loading').waitFor({ state: 'hidden' })
}
