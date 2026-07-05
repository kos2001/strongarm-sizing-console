// Lightweight bilingual (Korean / English) strings — no i18n library, just a
// dictionary keyed by string id with a `ko`/`en` pair. `t(lang, bi)` picks one.
export type Lang = 'ko' | 'en'
export interface Bi { ko: string; en: string }
export const t = (lang: Lang, b: Bi) => b[lang]

// Sidebar nav: label + one-line subtitle per page id.
export const NAV_LABELS: Record<string, Bi> = {
  sizing: { ko: '소자 크기', en: 'Sizing' },
  circuit: { ko: '회로 · 파형', en: 'Circuit' },
  metastability: { ko: '메타안정성', en: 'Metastability' },
  maxfclk: { ko: '최대 클럭', en: 'Max f_clk' },
  optimizer: { ko: '자동 최적화', en: 'Optimizer' },
  sensitivity: { ko: '민감도', en: 'Sensitivity' },
  pareto: { ko: '파레토', en: 'Pareto' },
  montecarlo: { ko: '몬테카를로', en: 'Monte-Carlo' },
  ber: { ko: '노이즈 / BER', en: 'Noise / BER' },
  pvt: { ko: 'PVT 코너', en: 'PVT corners' },
  yield: { ko: '수율', en: 'Yield' },
  layout: { ko: '레이아웃', en: 'Layout' },
  flow: { ko: '전체 흐름', en: 'Full flow' },
  vco: { ko: 'VCO (링)', en: 'VCO (ring)' },
}
export const NAV_SUBS: Record<string, Bi> = {
  sizing: { ko: '소자 · 실행 · 스펙', en: 'devices · run · spec' },
  circuit: { ko: '회로도 · 트랜지언트', en: 'schematic · transient' },
  metastability: { ko: '판정시간 vs 입력 · τ', en: 'resolve time vs Vin · τ' },
  maxfclk: { ko: '클럭 속도 · 변환당 에너지', en: 'clock rate · energy/conv' },
  optimizer: { ko: '차분진화 + 대리모델', en: 'DE + GP surrogate' },
  sensitivity: { ko: '어느 소자가 지렛대인가', en: 'device levers' },
  pareto: { ko: '전력 ↔ 속도 (NSGA-II)', en: 'power ↔ speed (NSGA-II)' },
  montecarlo: { ko: '오프셋 분포', en: 'offset distribution' },
  ber: { ko: '입력 대비 에러율', en: 'error rate vs Vin' },
  pvt: { ko: '공정 · 전압 · 온도', en: 'process · voltage · temp' },
  yield: { ko: '미스매치 × PVT', en: 'mismatch × PVT' },
  layout: { ko: 'GDS + DRC', en: 'GDS + DRC' },
  flow: { ko: '크기→PVT→GDS', en: 'size → PVT → GDS' },
  vco: { ko: '발진 · 튜닝 · 자동사이징', en: 'oscillate · tune · auto-size' },
}

// Beginner-friendly "what does this page do?" explanation. `what` = plain-language
// purpose; `read` = how to read the result / why it matters.
export const HELP: Record<string, { what: Bi; read: Bi }> = {
  sizing: {
    what: {
      ko: '트랜지스터의 크기 — 폭(W), 길이(L), 병렬 개수(M) — 를 정하고 SPICE 시뮬레이션을 돌립니다. StrongARM 비교기는 두 입력 전압 중 어느 쪽이 큰지 판정하는 회로예요.',
      en: 'Set the transistor sizes — width (W), length (L), and parallel count (M) — and run a SPICE simulation. A StrongARM comparator is the circuit that decides which of two input voltages is larger.',
    },
    read: {
      ko: '오른쪽 게이지가 측정값을 목표(스펙)와 비교합니다: 판정시간(빠를수록 좋음), 전력(작을수록 좋음), 오프셋 σ·입력 노이즈(작을수록 정확). 위의 P1/P2/P3 버튼으로 응용별 목표를 고르거나 숫자를 직접 바꿀 수 있어요.',
      en: 'The gauges on the right compare measured values to your targets: decision time (lower is faster), power (lower is better), offset σ and input noise (lower is more accurate). Pick an application preset (P1/P2/P3) above, or type your own limits.',
    },
  },
  circuit: {
    what: {
      ko: '회로 구조도(schematic)와 실제 시뮬레이션 파형을 나란히 보여줍니다. 각 트랜지스터에 현재 크기가 표시됩니다.',
      en: 'Shows the circuit diagram (schematic) next to the real simulated waveform, with each transistor annotated with its current size.',
    },
    read: {
      ko: '클럭(clk)이 올라가면 두 출력(outp/outn)이 전원 양쪽으로 갈라집니다 — 이 갈라짐이 "판정"이에요. "⚡ 기생" 버튼은 레이아웃 배선 용량을 더해 실제로 얼마나 느려지는지 보여줍니다.',
      en: 'When the clock (clk) rises, the two outputs (outp/outn) split toward opposite rails — that split is the "decision". The "⚡ parasitics" button adds layout wiring capacitance to show how much slower the real chip is.',
    },
  },
  metastability: {
    what: {
      ko: '두 입력의 전압 차이를 아주 작게 줄여가며 판정에 걸리는 시간을 측정합니다.',
      en: 'Sweeps the voltage difference between the two inputs down to very small values and measures how long the decision takes.',
    },
    read: {
      ko: '입력 차이가 작아질수록 판정이 느려집니다(로그 곡선). 그 기울기가 재생 시상수 τ예요 — 작을수록 회로가 빠르게 결론냅니다. 입력이 0에 가까우면 판정이 끝없이 느려질 수 있는데, 이것이 "메타안정성"입니다.',
      en: 'The smaller the input difference, the slower the decision (a logarithmic curve). Its slope is the regeneration time constant τ — smaller means the circuit makes up its mind faster. Near zero input the decision can take arbitrarily long: that is "metastability".',
    },
  },
  maxfclk: {
    what: {
      ko: '클럭 주기를 점점 짧게 바꿔가며, 이 비교기가 안정적으로 동작하는 가장 빠른 클럭 주파수를 찾습니다.',
      en: 'Shortens the clock period step by step to find the fastest clock frequency at which this comparator still works reliably.',
    },
    read: {
      ko: '초록 점은 정상 동작(판정도 끝나고 리셋도 됨), 빨강 점은 시간이 모자라 실패한 경우입니다. 세로 점선이 최대 클럭이에요. "변환당 에너지(fJ)"는 한 번 판정에 드는 에너지로, 낮을수록 효율적입니다.',
      en: 'Teal dots work (decision finishes and the circuit resets in time); red dots run out of time. The dashed line is the max clock. "Energy per conversion (fJ)" is the energy for one decision — lower is more efficient.',
    },
  },
  optimizer: {
    what: {
      ko: '목표(스펙)를 만족하면서 전력을 가장 작게 만드는 소자 크기를 자동으로 찾아줍니다(차분진화 + 대리모델 알고리즘).',
      en: 'Automatically searches for the device sizes that meet your targets while using the least power (differential-evolution search + a surrogate model).',
    },
    read: {
      ko: '탐색 과정이 회로도 위에서 단계별로 재생됩니다 — 어떤 소자의 폭이 바뀌는지 강조됩니다. 끝나면 최적 크기가 자동으로 적용돼요.',
      en: 'The search replays step by step on the schematic, highlighting which device width changed. When it finishes, the best sizing is applied automatically.',
    },
  },
  sensitivity: {
    what: {
      ko: '각 소자의 폭을 ±10% 바꿔보고, 그때 속도·전력·오프셋이 얼마나 달라지는지 측정합니다.',
      en: 'Perturbs each device width by ±10% and measures how much the speed, power, and offset change.',
    },
    read: {
      ko: '막대가 길수록 그 소자가 해당 지표에 미치는 영향이 큽니다("지렛대"). 예를 들어 입력 쌍이 속도와 오프셋 모두를 가장 크게 좌우해요. 수동으로 튜닝할 때 어디를 건드릴지 알려줍니다.',
      en: 'The longer the bar, the stronger that device is as a "lever" for that metric. For example, the input pair dominates both speed and offset. It tells you what to adjust when tuning by hand.',
    },
  },
  pareto: {
    what: {
      ko: '전력과 속도는 보통 서로 상충합니다(하나를 좋게 하면 다른 하나가 나빠짐). 그 최선의 절충 곡선을 그립니다(NSGA-II 다목적 최적화).',
      en: 'Power and speed usually trade off against each other. This plots the best trade-off curve between them (NSGA-II multi-objective search).',
    },
    read: {
      ko: '곡선(front) 위의 점들이 "더 낫게 만들 수 없는" 설계들입니다. 왼쪽 아래일수록 좋아요(저전력·고속). 점을 클릭하면 그 설계를 불러옵니다.',
      en: 'Points on the front are designs you cannot improve without giving something up. Lower-left is better (low power + fast). Click a point to load that design.',
    },
  },
  montecarlo: {
    what: {
      ko: '제조 편차 때문에 트랜지스터마다 문턱전압이 조금씩 다릅니다. 이를 무작위로 여러 번 뽑아 오프셋(0 입력에서 한쪽으로 치우치는 정도)의 분포를 보여줍니다.',
      en: 'Manufacturing variation makes each transistor’s threshold voltage slightly different. This draws many random samples to show the distribution of offset (the bias at zero input).',
    },
    read: {
      ko: '분포가 좁을수록(σ가 작을수록) 비교기가 정확합니다. 빨간 선(±스펙) 밖으로 나가는 샘플이 불량이에요. n_MC를 키우면 분포가 촘촘해집니다.',
      en: 'A narrower distribution (smaller σ) means a more accurate comparator. Samples outside the red ±spec lines are failures. Raising n_MC gives a denser distribution.',
    },
  },
  ber: {
    what: {
      ko: '노이즈와 오프셋 때문에 비교기가 판정을 "틀릴" 확률(에러율)을 입력 크기에 따라 보여줍니다.',
      en: 'Shows the probability the comparator makes a wrong decision (error rate) as a function of input size, due to noise and offset.',
    },
    read: {
      ko: '입력이 클수록 에러율이 뚝 떨어집니다. 파란선은 노이즈만, 빨간선은 오프셋까지 더한 경우예요. 목표 에러율(점선)을 만족하는 최소 입력이 "감지 가능한 가장 작은 신호"입니다.',
      en: 'The bigger the input, the sharply lower the error rate. The blue line is noise only; the red line adds offset. The smallest input that meets the target error rate (dashed) is the "minimum detectable signal".',
    },
  },
  pvt: {
    what: {
      ko: '공정(Process)·전압(Voltage)·온도(Temperature)가 변해도 동작하는지, 27개 조합(코너)에서 최악의 성능을 확인합니다.',
      en: 'Checks that the circuit still works as process, voltage, and temperature vary — the worst case across 27 combinations (corners).',
    },
    read: {
      ko: '표의 각 칸이 한 코너에서의 판정시간입니다(청록=통과, 빨강=실패). 상온에서 통과해도 느리고 차갑고 저전압인 코너에서 실패하는 경우가 많아요 — 그래서 코너 검증이 중요합니다.',
      en: 'Each cell is the decision time at one corner (teal = pass, red = fail). A design that passes at room temperature often fails at the slow-cold-low-voltage corner — which is why corner sign-off matters.',
    },
  },
  yield: {
    what: {
      ko: '제조 편차(미스매치)와 공정·전압·온도 변동을 동시에 무작위로 뽑아, 스펙을 통과하는 칩의 비율(수율)을 계산합니다.',
      en: 'Draws chips randomly from both manufacturing mismatch and process/voltage/temperature variation, and computes the fraction that meet spec (yield).',
    },
    read: {
      ko: '큰 숫자가 수율(%)입니다 — 생산에서 실제로 쓸 수 있는 칩 비율이에요. 아래 막대는 어떤 이유로 떨어졌는지(오프셋/속도/오판정) 보여줍니다. 점 그래프에서 초록 상자 안이 합격입니다.',
      en: 'The big number is the yield (%) — the share of chips usable in production. The bars show why chips failed (offset / too slow / wrong decision). In the scatter, inside the green box = pass.',
    },
  },
  layout: {
    what: {
      ko: '소자 크기 정보로부터 실제 물리 레이아웃(GDS 파일)을 자동 생성하고, 간단한 설계 규칙 검사(DRC)를 돌립니다.',
      en: 'Automatically generates a real physical layout (GDS file) from the device sizes and runs a light design-rule check (DRC).',
    },
    read: {
      ko: '색깔은 각 레이어(확산층·폴리·금속 등)입니다. 셀 면적과 DRC 결과(위반 없으면 clean)를 보여줘요. 이것은 개념 증명(PoC) 레이아웃이지 양산 사인오프는 아닙니다.',
      en: 'Colors are the layers (diffusion, poly, metal, …). It reports the cell area and the DRC result (clean if no violations). This is a proof-of-concept layout, not sign-off DRC.',
    },
  },
  flow: {
    what: {
      ko: '크기 최적화 → 기생 재시뮬 → PVT 코너 사인오프 → 레이아웃/DRC 까지 전체 설계 흐름을 버튼 하나로 한 번에 실행합니다.',
      en: 'Runs the whole design flow — size optimization → parasitic re-sim → PVT corner sign-off → layout/DRC — end to end with a single button.',
    },
    read: {
      ko: '각 단계마다 통과/실패가 표시되고, 마지막에 전체 사인오프 여부와 생성된 레이아웃이 나옵니다. 초보자가 "설계가 어떤 단계를 거치는지" 한눈에 보기 좋아요.',
      en: 'Each stage shows a pass/fail, and the end shows the overall sign-off verdict plus the generated layout. A good way for a beginner to see the stages a design goes through.',
    },
  },
  vco: {
    what: {
      ko: '순수 MOSFET로 만든 전압제어발진기(VCO) — current-starved 링 오실레이터입니다. 홀수 개 인버터를 고리로 연결해 계속 발진하고, 제어전압 V_ctrl이 전류를 조절해 주파수를 바꿉니다. 비교기와 똑같은 SPICE·최적화 흐름을 씁니다.',
      en: 'A voltage-controlled oscillator built from pure MOSFETs — a current-starved ring oscillator. An odd number of inverters in a loop oscillates continuously, and the control voltage V_ctrl adjusts the current to change frequency. Same SPICE + optimization loop as the comparator.',
    },
    read: {
      ko: '실행하면 발진 주파수·전력과 튜닝 곡선(f vs V_ctrl)이 나옵니다. 곡선의 기울기가 Kvco. "자동 최적화"는 목표 주파수를 만족하면서 전력을 최소화하도록 소자 크기를 차분진화로 찾습니다. × 표시는 그 전압에서 발진하지 않음.',
      en: 'Running shows the oscillation frequency, power, and the tuning curve (f vs V_ctrl) — the curve slope is Kvco. "Auto-size" runs Differential Evolution to size the devices to hit a target frequency at minimum power. An × marks a voltage where it does not oscillate.',
    },
  },
}

// What each transistor does (device editor / schematic).
export const DEVICE_ROLES: Record<string, Bi> = {
  input: { ko: '입력 쌍 — 오프셋 & 노이즈', en: 'input pair — offset & noise' },
  tail: { ko: '테일 스위치 — 속도', en: 'tail switch — speed' },
  ncc: { ko: 'NMOS 래치 — 재생', en: 'latch NMOS — regeneration' },
  pcc: { ko: 'PMOS 래치 — 재생', en: 'latch PMOS — regeneration' },
  pre: { ko: '프리차지 — 리셋', en: 'precharge — reset' },
}

// Small bits of shared UI chrome.
export const UI = {
  device: { ko: '소자', en: 'Device' },
  appSub: { ko: '사이징 콘솔', en: 'Sizing Console' },
  backendLive: { ko: '백엔드 연결됨', en: 'backend live' },
  backendOff: { ko: '백엔드 꺼짐', en: 'backend offline' },
  connecting: { ko: '연결 중…', en: 'connecting…' },
  theme: { ko: '테마', en: 'theme' },
  report: { ko: '리포트', en: 'report' },
  whatIsThis: { ko: '이 페이지는?', en: 'What is this?' },
  howToRead: { ko: '읽는 법', en: 'How to read it' },
}
