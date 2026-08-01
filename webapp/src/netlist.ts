// SPICE 넷리스트(.sp) 내보내기 — 백엔드가 생성한 덱을 파일로 다운로드한다.
// path: '/api/netlist'(comparator) | '/api/vco/netlist'(VCO)

export async function downloadNetlist(path: string, params: unknown, filename: string) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params }),
  })
  if (!r.ok) throw new Error(`netlist ${r.status}`)
  const text = await r.text()
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
