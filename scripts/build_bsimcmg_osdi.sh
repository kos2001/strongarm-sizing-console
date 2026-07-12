#!/bin/sh
# BSIM-CMG 107 Verilog-A → bsimcmg107.osdi (ngspice OSDI 용) 재컴파일.
# openvaf-r 이 필요하다 (github.com/arpadbuermen/OpenVAF, macOS 는 소스 빌드:
#   brew install rust llvm@21
#   LLVM_SYS_211_PREFIX=$(brew --prefix llvm@21) cargo build --release --features llvm21 --bin openvaf-r).
# third_party/bsimcmg107 은 CMC BSIM-CMG 107.0.0 에 두 가지 패치를 얹은 것:
#   1) 인스턴스 파라미터(L/NFIN/DELVTRAND 등 28개)에 (* type="instance" *) 속성
#   2) EOTACC 하한 0.1n→0.01n (0.1n 의 이진 표현이 1e-10 보다 1ulp 커서
#      ASAP7 카드의 경계값 eotacc=1e-10 이 포함 검사에 실패하는 문제)
set -e
cd "$(dirname "$0")/.."
OPENVAF=${OPENVAF:-third_party/OpenVAF/target/release/openvaf-r}
"$OPENVAF" third_party/bsimcmg107/bsimcmg.va -o models/asap7/bsimcmg107.osdi
echo "built models/asap7/bsimcmg107.osdi"
