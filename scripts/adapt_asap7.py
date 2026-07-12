#!/usr/bin/env python3
"""ASAP7 HSPICE 모델 카드(BSIM-CMG 107, level=72) → ngspice-OSDI 형식 변환.

바꾸는 것: `.model <name> nmos|pmos level = 72` → `.model <name> bsimcmg`
+ `type=1/-1` 주입, hspice 전용 `version=107` 파라미터 제거.
나머지 파라미터는 BSIM-CMG 107 Verilog-A 와 이름이 같아 그대로 통과한다.
"""
import re
import sys

def adapt(src: str) -> str:
    out = []
    for line in src.splitlines():
        m = re.match(r"^\.model\s+(\S+)\s+(nmos|pmos)\s+level\s*=\s*72\s*$", line.strip(), re.I)
        if m:
            name, pol = m.group(1), m.group(2).lower()
            out.append(f".model {name} bsimcmg")
            out.append(f"+devtype = {1 if pol == 'nmos' else 0}")   # `ntype=1, `ptype=0
            continue
        # hspice 버전 선택자 제거(va 에는 없는 파라미터)
        line = re.sub(r"version\s*=\s*107\s*", "", line)
        if line.strip() == "+":
            continue
        out.append(line)
    return "\n".join(out) + "\n"

if __name__ == "__main__":
    for corner in ("TT", "SS", "FF"):
        with open(f"third_party/asap7_models/7nm_{corner}.pm") as f:
            adapted = adapt(f.read())
        dst = f"models/asap7/7nm_{corner}.sp"
        with open(dst, "w") as f:
            f.write(adapted)
        print(dst, len(adapted.splitlines()), "lines")
