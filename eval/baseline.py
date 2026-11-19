"""기준선 — 같은 생성 모델에 같은 채널 프로필·협찬 정보를 주고, 프롬프트 한 번으로 같은 JSON(PlanOutput)을 뽑는다.

사전 점검·RAG·계획·코드 보정·검증·수정 루프가 없다. Agent 와의 점수 차이가 '구조'에서 나왔는지 보기 위한 비교군.
    python -m eval.baseline eval/cases/N01_CH1.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app import config
from app.llm import gen_structured
from app.schemas import ChannelProfile, EvalCase, PlanOutput, Sponsorship, load_case, load_channel

RESULTS_DIR = config.EVAL_DIR / "results" / "baseline"

PROMPT = """너는 인플루언서 채널의 협찬 숏폼(9:16, {length_sec}초) 기획자다.
아래 채널 프로필과 협찬 정보로, 채널 톤을 지키면서 광고주 홍보 포인트를 반영하고 광고 규정을 지키는 숏폼 기획을 한 번에 만든다.

요구 사항:
- concept: 콘셉트 1개 (concept_no=1, 훅 유형, 첫 대사, 요약).
- storyboard: 영문 style_sheet 와 씬 목록. 씬마다 정수 seconds, 화면 설명, 대사·자막(한국어, 채널 말투), product_visible, 영문 image_prompt.
  씬 seconds 합은 {length_sec}초. 첫 씬은 3초 이하의 훅이고 제품이 나오지 않는다. 제품이 나오는 시간은 전체의 30% 이하.
  채널의 시그니처 오프닝·엔딩 멘트를 넣는다.
- upload_package: 제목, 설명란, 해시태그, 광고 표시. 광고 규정에 맞게 광고임을 표시한다.
- 영상에 다 못 넣은 포인트는 설명란에 넣는다. 과장·금지 표현과 채널 avoid 표현을 쓰지 않는다.

[채널 프로필]
{channel}

[협찬 정보]
{sponsorship}
"""


def run_baseline(ch: ChannelProfile, sp: Sponsorship) -> PlanOutput:
    prompt = PROMPT.format(
        length_sec=sp.length_sec,
        channel=ch.model_dump_json(indent=1),
        sponsorship=sp.model_dump_json(indent=1),
    )
    return gen_structured(PlanOutput, temperature=0.7, max_tokens=8000).invoke(prompt)


def run_case(case: EvalCase, out_dir: Path = RESULTS_DIR) -> Path:
    out = run_baseline(load_channel(case.channel_id), case.sponsorship)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{case.case_id}.json"
    path.write_text(out.model_dump_json(indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    for arg in sys.argv[1:] or ["eval/cases/N01_CH1.json"]:
        p = run_case(load_case(arg))
        data = json.loads(p.read_text(encoding="utf-8"))
        scenes = data["storyboard"]["scenes"]
        print(f"기준선 저장: {p}  (씬 {len(scenes)}개, 합 {sum(s['seconds'] for s in scenes)}초)")
