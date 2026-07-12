#!/usr/bin/env python3
"""자기개선 루프 — 에이전트 골든 과제 셀프테스트 + 교훈 축적.

한 바퀴:
  ① 골든 과제(진단/edit × comparator/VCO)를 /api/agent/ask 로 실행
  ② 자동 채점 — 문자열 정답요소가 아니라 '독립 교차검증'이 기준:
     · 진단: 답의 수치가 백엔드 실측(brief)과 일치하는가
     · edit: 반환 덱이 실제로 돌아가고, 에이전트가 주장한 측정값과 일치하는가
  ③ 결과를 hermes/selftest/<UTC시각>.json 에 기록
  ④ 실패 사례를 hermes/skills/strongarm-lessons/SKILL.md 에 교훈 초안으로
     append 하고, 프로파일 스킬 디렉토리에 재설치 → 다음 에이전트 턴이 학습

사용:
  python3 scripts/agent_selftest.py            # 전체 (4과제, ~10분)
  python3 scripts/agent_selftest.py --quick    # 진단 2과제만 (~2분)

콘솔 서버(:8770)와 hermes strong-arm 게이트웨이가 떠 있어야 한다.
크론 예: 매일 새벽  0 3 * * *  cd <repo> && python3 scripts/agent_selftest.py
"""
import json
import os
import re
import shutil
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
API = os.environ.get("STRONGARM_API", "http://127.0.0.1:8770")

CTX_COMP = {"topology": "strongarm", "model": "ptm", "vdd": 0.7, "cload_ff": 15,
            "devices": {"input": {"w_um": 8, "l_nm": 80, "m": 4}, "tail": {"w_um": 12, "l_nm": 45, "m": 6},
                        "ncc": {"w_um": 4, "l_nm": 45, "m": 2}, "pcc": {"w_um": 9, "l_nm": 45, "m": 4},
                        "pre": {"w_um": 4, "l_nm": 45, "m": 2}, "prei": {"w_um": 4, "l_nm": 45, "m": 2}},
            "spec_targets": {"decision_time_ps": 400, "power_uw": 100, "offset_sigma_mv": 5}}
CTX_VCO = {"topology": "xcpl", "model": "ptm", "vdd": 1.0, "vctrl": 0.6, "n_stages": 3, "cload_ff": 3.0,
           "devices": {"invp": {"w_um": 2, "l_nm": 45, "m": 2}, "invn": {"w_um": 1, "l_nm": 45, "m": 2},
                       "starvep": {"w_um": 2, "l_nm": 45, "m": 2}, "starven": {"w_um": 1, "l_nm": 45, "m": 1},
                       "xcplp": {"w_um": 0.4, "l_nm": 45, "m": 1}, "rstp": {"w_um": 2, "l_nm": 45, "m": 2}}}


def _post(path, body, timeout=900):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _ask(question, ctx, domain):
    t0 = time.time()
    d = _post("/api/agent/ask", {"question": question, "context": ctx, "domain": domain})
    return time.time() - t0, d.get("answer", d.get("error", "")), d.get("role")


def _nums(text):
    return [float(x) for x in re.findall(r"[-+]?\d+\.?\d*", text)]


# ── 채점기 — 기준은 독립 교차검증 ───────────────────────────────────────────

def grade_diagnose_comp(ans):
    ref = _post("/api/brief", {"params": CTX_COMP, "targets": CTX_COMP["spec_targets"]})
    dec = ref["nominal"]["decision_time_ps"]
    ok = any(abs(v - dec) < 1.5 for v in _nums(ans))
    return ok, f"답에 실측 판정시간 {dec}ps 부재" if not ok else ""


def grade_diagnose_vco(ans):
    ref = _post("/api/vco/brief", {"params": CTX_VCO})
    f = ref["nominal"]["f_osc_ghz"]
    ok = any(abs(v - f) < 0.05 for v in _nums(ans))
    return ok, f"답에 실측 주파수 {f}GHz 부재(5/per 오해석 의심)" if not ok else ""


def _deck_of(ans):
    m = re.search(r"```spice\s*([\s\S]*?)```", ans)
    return m.group(1) if m else None


def grade_edit_comp(ans):
    deck = _deck_of(ans)
    if not deck:
        return False, "```spice 덱 미포함"
    if "Ccoup" not in deck and "2.0f" not in deck and "2f" not in deck:
        return False, "요청한 2fF 커패시터가 덱에 없음"
    import run_sim
    tdec = run_sim._parse(run_sim._run(deck), "tdec")
    if tdec is None:
        return False, "반환 덱이 ngspice 에서 tdec 측정 실패"
    ok = any(abs(v - tdec * 1e12) < 2.0 for v in _nums(ans))
    return ok, f"덱 실측 {tdec*1e12:.1f}ps 가 답의 수치와 불일치" if not ok else ""


def grade_edit_vco(ans):
    deck = _deck_of(ans)
    if not deck:
        return False, "```spice 덱 미포함"
    import run_sim
    per = run_sim._parse(run_sim._run(deck), "per")
    if per is None:
        return False, "반환 덱이 ngspice 에서 per 측정 실패"
    f = 5.0 / per / 1e9
    ok = any(abs(v - f) < 0.05 for v in _nums(ans))
    return ok, f"덱 실측 f=5/per={f:.3f}GHz 가 답에 없음(5주기 오해석 의심)" if not ok else ""


TASKS = [
    {"id": "comp-diagnose", "domain": "comparator", "ctx": CTX_COMP, "quick": True,
     "q": "지금 스펙 대비 각 항목 마진이 어떤지만 알려줘", "grade": grade_diagnose_comp,
     "expect_role": "diagnose", "budget_s": 120},
    {"id": "vco-diagnose", "domain": "vco", "ctx": CTX_VCO, "quick": True,
     "q": "지금 발진 주파수랑 상태 알려줘", "grade": grade_diagnose_vco,
     "expect_role": "diagnose", "budget_s": 150},
    {"id": "comp-edit", "domain": "comparator", "ctx": CTX_COMP, "quick": False,
     "q": "넷리스트에서 outp와 outn 사이에 2fF 커플링 커패시터를 추가하고 판정시간 변화를 확인해줘",
     "grade": grade_edit_comp, "expect_role": "edit", "budget_s": 300},
    {"id": "vco-edit", "domain": "vco", "ctx": CTX_VCO, "quick": False,
     "q": "넷리스트에서 o1 노드에 2fF 커패시터를 추가해서 주파수가 얼마나 떨어지는지 확인해줘",
     "grade": grade_edit_vco, "expect_role": "edit", "budget_s": 300},
]

LESSONS = os.path.join(REPO, "hermes", "skills", "strongarm-lessons", "SKILL.md")
PROFILE_SKILLS = os.path.expanduser("~/.hermes/profiles/strong-arm/skills/semiconductor-eda")


def append_lesson(task, why, took, ans_head):
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    entry = (f"\n## L-auto · {task['id']} 실패 ({stamp}, selftest)\n\n"
             f"- **증상**: {why} (소요 {took:.0f}s, 예산 {task['budget_s']}s)\n"
             f"- **응답 앞부분**: {ans_head[:160]!r}\n"
             f"- **조치 필요**: 역할 규칙/레시피에서 원인 확인 후 이 항목을 정식 규칙으로 승격하라.\n")
    with open(LESSONS, "a") as f:
        f.write(entry)


def install_skills():
    if os.path.isdir(PROFILE_SKILLS):
        for name in ("strongarm-lessons", "strongarm-console", "strongarm-design-recipes"):
            src = os.path.join(REPO, "hermes", "skills", name)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(PROFILE_SKILLS, name), dirs_exist_ok=True)
        return True
    return False


def main():
    quick = "--quick" in sys.argv
    results, n_lessons = [], 0
    for t in TASKS:
        if quick and not t["quick"]:
            continue
        took, ans, role = _ask(t["q"], t["ctx"], t["domain"])
        ok, why = (False, "빈 응답/에러") if not ans or ans.startswith("에이전트 호출 실패") else t["grade"](ans)
        over = took > t["budget_s"]
        role_ok = role == t["expect_role"]
        verdict = ok and role_ok and not over
        if not verdict:
            why = why or ("예산 초과" if over else f"역할 오라우팅({role})")
            append_lesson(t, why, took, ans)
            n_lessons += 1
        results.append({"id": t["id"], "pass": verdict, "took_s": round(took), "role": role,
                        "why": why, "over_budget": over, "answer": ans})
        print(f"[{'PASS' if verdict else 'FAIL'}] {t['id']}: {took:.0f}s role={role} {why}")
    out = os.path.join(REPO, "hermes", "selftest",
                       time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".json")
    json.dump({"quick": quick, "results": results}, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"결과: {out}")
    if n_lessons:
        installed = install_skills()
        print(f"교훈 {n_lessons}건 추가 → lessons 스킬 {'프로파일 재설치 완료' if installed else '(프로파일 미발견 — 수동 설치 필요)'}")
    npass = sum(r["pass"] for r in results)
    print(f"셀프테스트: {npass}/{len(results)} 통과")
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
