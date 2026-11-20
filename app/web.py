"""웹 화면 (실험) — 터미널 대신 브라우저에서 입력하고 질문에 답한다.

    streamlit run app/web.py

Agent 본체(app/graph.py 와 노드)는 그대로 쓴다. app/main.py 가 터미널에서 하던 일
(입력 → 그래프 실행 → 멈춘 곳에서 질문 → 답을 넘겨 이어서 실행)을 화면으로 옮긴 것뿐이다.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # streamlit 은 app/ 폴더를 기준으로 실행하므로 프로젝트 폴더를 추가
    sys.path.insert(0, str(ROOT))

import streamlit as st
from langgraph.types import Command
from pydantic import ValidationError

from app import config
from app.graph import build_graph
from app.main import STEP_NAMES
from app.product_extract import categories, extract_from_text
from app.rules import find_forbidden, max_points
from app.schemas import ChannelProfile, PlanOutput, Sponsorship, load_channel
from app.tracing import trace_config

st.set_page_config(page_title="협찬 숏폼 기획 Agent", page_icon="🎬", layout="wide")

LENGTHS = [15, 30, 45, 60]
PRESET_CHANNELS = ["CH1", "CH2", "CH3", "CH4"]
CUSTOM = "직접 입력"


# --- 상태 -----------------------------------------------------------------------
def init_state() -> None:
    defaults = {
        "phase": "input",  # input → waiting(질문 대기) → done
        "graph": None,
        "cfg": None,
        "pending": None,  # 그래프가 멈추며 보낸 질문
        "steps": [],  # 끝난 단계 이름
        "trace_where": "",
        "error": "",
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def reset() -> None:
    for k in ("phase", "graph", "cfg", "pending", "steps", "trace_where", "error"):
        st.session_state.pop(k, None)
    init_state()


def advance(payload) -> None:
    """그래프를 다음 질문(또는 끝)까지 실행한다."""
    graph, cfg = st.session_state.graph, st.session_state.cfg
    pending = None
    with st.status("Agent 가 작업 중입니다… (1~2분 걸릴 수 있어요)", expanded=True) as status:
        try:
            for chunk in graph.stream(payload, cfg, stream_mode="updates"):
                for node in chunk:
                    if node == "__interrupt__":
                        pending = chunk[node][0].value
                    else:
                        name = STEP_NAMES.get(node, node)
                        st.session_state.steps.append(name)
                        st.write(f"✅ {name} 완료")
        except Exception as e:  # 모델 한도·네트워크 오류 등
            st.session_state.error = f"{type(e).__name__}: {e}"
            st.session_state.phase = "done"
            status.update(label="오류로 멈췄습니다", state="error")
            return
        status.update(label="질문이 있어요" if pending else "완료", state="complete", expanded=False)
    st.session_state.pending = pending
    st.session_state.phase = "waiting" if pending else "done"


def answer(value) -> None:
    advance(Command(resume=value))
    st.rerun()


# --- 입력 화면 -------------------------------------------------------------------
def channel_input() -> ChannelProfile | None:
    st.subheader("① 내 채널")
    choice = st.selectbox(
        "채널 프로필", PRESET_CHANNELS + [CUSTOM],
        format_func=lambda c: c if c == CUSTOM else f"{c} · {load_channel(c).channel_name}",
    )
    if choice != CUSTOM:
        ch = load_channel(choice)
        with st.expander("프로필 보기"):
            st.markdown(
                f"- **콘셉트**: {ch.concept}\n- **말투**: {ch.speech_style} · 톤: {', '.join(ch.tone_keywords)}\n"
                f"- **오프닝**: {ch.signature_opening}\n- **엔딩**: {ch.signature_ending}\n"
                f"- **대표 포맷**: {ch.representative_format}\n- **안 쓰는 말**: {', '.join(ch.avoid) or '없음'}"
            )
        return ch

    c1, c2 = st.columns(2)
    name = c1.text_input("채널 이름", placeholder="예: 오늘도 자취중")
    speech = c2.radio("말투", ["반말", "존댓말"], horizontal=True)
    concept = st.text_input("채널 콘셉트", placeholder="예: 자취 5년 차의 돈 안 드는 현실 살림 꿀팁")
    tone = st.text_input("톤 키워드 (쉼표로 구분)", placeholder="예: 솔직함, 현실적, 가벼운 자조 개그")
    c3, c4 = st.columns(2)
    opening = c3.text_input("오프닝 멘트", placeholder="예: 자취 5년 차 꿀팁 들어간다")
    ending = c4.text_input("엔딩 멘트", placeholder="예: 다음 꿀팁에서 보자")
    fmt = st.text_input("평소 영상 구성", placeholder="예: 문제 상황 → 꿀팁 → 비용 비교")
    avoid = st.text_input("절대 안 쓰는 말 (쉼표로 구분, 선택)", placeholder="예: 무조건 사세요, 플렉스")
    split = lambda t: [x.strip() for x in t.split(",") if x.strip()]
    try:
        return ChannelProfile(
            channel_id="CUSTOM", channel_name=name, concept=concept, speech_style=speech,
            tone_keywords=split(tone), signature_opening=opening, signature_ending=ending,
            representative_format=fmt, avoid=split(avoid),
        )
    except ValidationError:
        return None


def paste_to_fill() -> None:
    """쇼핑몰 상세페이지 글을 붙여 넣으면 아래 입력 칸을 AI 가 채운다 (사람이 확인·수정)."""
    with st.expander("🛒 쇼핑몰 상품 설명을 붙여 넣어 자동으로 채우기", expanded=not st.session_state.get("sp_product")):
        st.caption("쿠팡·스마트스토어 등 상품 페이지에서 상품명과 상세 설명 글을 드래그해 복사한 뒤 붙여 넣으세요. "
                   "이미지 속 글자는 읽지 못해요.")
        source = st.text_area("상품 페이지 글", height=160, key="paste_source",
                              placeholder="여기에 붙여 넣기 (Ctrl + V)")
        if st.button("AI로 정리하기", disabled=not source.strip()):
            if not (config.AWS_ACCESS_KEY_ID and config.AWS_SECRET_ACCESS_KEY):
                st.error("AWS 키가 없습니다. .env 파일에 AWS_ACCESS_KEY_ID 와 AWS_SECRET_ACCESS_KEY 를 넣어 주세요.")
                return
            try:
                with st.spinner("상품 설명을 정리하는 중…"):
                    r = extract_from_text(source)
            except Exception as e:
                st.error(f"정리하지 못했어요: {e}")
                return
            # 아래 입력 칸(아직 그리기 전)에 값을 넣는다
            st.session_state.sp_product = r.product_name
            if r.category:
                st.session_state.sp_category = r.category
            st.session_state.sp_desc = r.product_desc
            st.session_state.sp_points = "\n".join(r.points)
            st.session_state.extract_result = r
        r = st.session_state.get("extract_result")
        if r is not None:
            st.success("아래 칸을 채웠어요. 광고주가 따로 요청한 포인트가 있으면 꼭 고쳐 주세요.")
            for n in r.notes:
                st.info(n)
            if r.points:
                st.markdown("**포인트별 원문 근거**")
                for p, q in zip(r.points, r.quotes):
                    st.markdown(f"- {p}  \n  <small>원문: “{q}”</small>", unsafe_allow_html=True)
            if r.dropped:
                st.markdown("**근거를 찾지 못해 뺀 포인트**\n" + "\n".join(f"- ~~{d}~~" for d in r.dropped))


def sponsorship_input() -> tuple[dict, list[str]]:
    st.subheader("② 이번 협찬")
    paste_to_fill()
    c1, c2, c3 = st.columns([2, 2, 1])
    product = c1.text_input("제품 이름", placeholder="예: 포근 보풀 제거기", key="sp_product")
    category = c2.selectbox("카테고리", categories(), key="sp_category")
    length = c3.selectbox("영상 길이(초)", LENGTHS, index=1)
    desc = st.text_area(
        "제품 설명 (스펙·가격 등 사실 정보)", height=90, key="sp_desc",
        placeholder="예: 충전식 보풀 제거기. USB-C 충전 1회 약 60분 사용, 날 높이 3단 조절, 무게 180g. 정가 15,900원.",
    )
    points_text = st.text_area(
        "광고주 홍보 포인트 (한 줄에 하나씩)", height=110, key="sp_points",
        placeholder="USB-C 충전식이라 건전지 필요 없음\n3단 높이 조절로 니트도 안전하게\n보풀 통이 커서 비우기 편함",
    )
    points = [p.strip() for p in points_text.splitlines() if p.strip()]
    st.caption(f"{length}초 영상에는 포인트를 최대 {max_points(length)}개까지 넣을 수 있어요. 넘치면 설명란으로 보내도록 제안합니다.")
    data = {"product_name": product.strip(), "category": category, "promo_points": points,
            "length_sec": length, "product_desc": desc.strip()}
    missing = [label for label, v in (("제품 이름", product.strip()), ("제품 설명", desc.strip()),
                                      ("홍보 포인트", points)) if not v]
    return data, missing


def input_screen() -> None:
    st.title("🎬 협찬 숏폼 기획 Agent")
    st.write("채널 정보와 협찬 내용을 넣으면 채널 톤을 지키고 광고 규정에 맞는 숏폼 기획안을 만들어요.")
    left, right = st.columns(2, gap="large")
    with left:
        ch = channel_input()
    with right:
        data, missing = sponsorship_input()

    st.divider()
    if ch is None:
        st.info("채널 정보를 모두 채워 주세요 (안 쓰는 말은 비워도 돼요).")
    if missing:
        st.info("아직 비어 있어요: " + ", ".join(missing))
    if st.button("기획 시작", type="primary", disabled=ch is None or bool(missing)):
        if not (config.AWS_ACCESS_KEY_ID and config.AWS_SECRET_ACCESS_KEY):
            st.error("AWS 키가 없습니다. .env 파일에 AWS_ACCESS_KEY_ID 와 AWS_SECRET_ACCESS_KEY 를 넣어 주세요.")
            return
        sp = Sponsorship.model_validate(data)
        cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
        cfg, where = trace_config(cfg, name=sp.product_name, tags=[ch.channel_id, "web"])
        st.session_state.update(graph=build_graph(), cfg=cfg, trace_where=where, steps=[])
        advance({"channel": ch, "sponsorship": sp, "confirm_points": True})
        st.rerun()


# --- 질문 화면 -------------------------------------------------------------------
def show_storyboard(out: PlanOutput) -> None:
    sb, pkg = out.storyboard, out.upload_package
    st.markdown(f"#### {out.concept.concept_no}안 · {out.concept.title}  \n총 {sb.total_seconds}초 · 씬 {len(sb.scenes)}개")
    st.dataframe(
        [{"#": s.scene_no, "초": s.seconds, "제품": "📦" if s.product_visible else "",
          "화면": s.visual, "대사": s.dialogue, "자막": s.caption} for s in sb.scenes],
        hide_index=True, width="stretch",
    )
    st.markdown("#### 업로드 패키지")
    st.markdown(f"**제목**: {pkg.title}")
    st.code(pkg.description, language=None)
    st.markdown("**해시태그**: " + " ".join(pkg.hashtags))


def precheck_question(p: dict) -> None:
    has_issues = bool(p["issues"])
    (st.warning if has_issues else st.info)(p["question"])
    for it in p["issues"]:
        st.markdown(f"- **[{it['type']}]** {it['detail']}  \n  → 제안: {it['suggestion']}")
    prop = p["proposal"]
    c1, c2 = st.columns(2)
    c1.markdown("**🎬 영상에 넣을 포인트**\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(prop["video_points"], 1)))
    c2.markdown("**📝 설명란으로 보낼 포인트**\n" + ("\n".join(f"- {x}" for x in prop["description_points"]) or "(없음)"))

    b = st.columns(3 if has_issues else 2)
    if b[0].button("제안대로" if has_issues else "이대로 진행", type="primary", width="stretch"):
        answer("accept_suggestion")
    if has_issues and b[1].button("원래 포인트 그대로", width="stretch"):
        answer("proceed")
    if b[-1].button("중단", width="stretch"):
        answer("cancel")

    # --- 직접 고치기 ---------------------------------------------------------------
    # 질문에 빠진 값이 있으면(예: 예전 코드가 만든 질문) 실행 상태에서 직접 계산한다
    sp = st.session_state.graph.get_state(st.session_state.cfg).values["sponsorship"]
    cap = p.get("max_video_points") or max_points(sp.length_sec)
    category = p.get("category") or sp.category
    with st.expander("✏️ 직접 고치기 — 포인트를 바꾸거나 영상 ↔ 설명란으로 옮기기"):
        st.caption(f"한 줄에 포인트 하나. 위에 있을수록 중요하게 다뤄요. 이 영상 길이에는 영상 포인트를 최대 {cap}개까지 넣을 수 있어요.")
        if p.get("original_points"):
            st.markdown("<small>광고주 원래 포인트: " + " / ".join(p["original_points"]) + "</small>",
                        unsafe_allow_html=True)
        e1, e2 = st.columns(2)
        video_text = e1.text_area("🎬 영상에 넣을 포인트", "\n".join(prop["video_points"]), height=150)
        desc_text = e2.text_area("📝 설명란으로 보낼 포인트", "\n".join(prop["description_points"]), height=150)
        video = [x.strip() for x in video_text.splitlines() if x.strip()]
        desc = [x.strip() for x in desc_text.splitlines() if x.strip()]
        if len(video) > cap:
            st.warning(f"영상 포인트가 {len(video)}개예요. 진행하면 뒤쪽 {len(video) - cap}개는 설명란으로 옮겨져요.")
        hits = sorted({h["word"] for x in video + desc for h in find_forbidden(x, category)})
        if hits:
            st.warning(f"광고 규정 금지 표현이 있어요: {', '.join(hits)}. 그대로 두면 생성·검증 단계에서 걸러지지만, 지금 고치는 게 좋아요.")
        if st.button("고친 대로 진행", disabled=not video, width="stretch"):
            answer({"action": "edit", "video_points": video, "description_points": desc})
        if not video:
            st.caption("영상 포인트가 최소 1개는 있어야 해요.")


def concept_question(p: dict) -> None:
    st.info(p["question"])
    cols = st.columns(len(p["concepts"]))
    for col, c in zip(cols, p["concepts"]):
        with col.container(border=True):
            st.markdown(f"### {c['concept_no']}안 · {c['title']}")
            st.caption(f"훅: {c['hook_type']}")
            st.markdown(f"> {c['hook_line']}")
            st.write(c["summary"])
            if st.button(f"{c['concept_no']}안 선택", key=f"concept_{c['concept_no']}", width="stretch"):
                answer(c["concept_no"])


def final_question(p: dict) -> None:
    show_storyboard(PlanOutput.model_validate(p["output"]))
    st.markdown("#### 자동 검증 결과")
    if p["passed"]:
        st.success("모든 항목 통과")
    else:
        st.error(f"미통과 항목이 있어요 (자동 수정 {p['revision']}회 후)")
    st.dataframe(
        [{"결과": "✅" if it["passed"] else "❌", "항목": f"{it['code']} {it['name']}", "근거": it["detail"]}
         for it in p["items"]],
        hide_index=True, width="stretch",
    )
    if p.get("human_feedback"):
        st.markdown("**지금까지 반영한 수정 요청**\n" + "\n".join(f"- {f}" for f in p["human_feedback"]))

    st.divider()
    st.info(p["question"])
    b1, b2 = st.columns(2)
    if b1.button("승인하고 저장", type="primary", width="stretch"):
        answer("approve")
    if b2.button("반려 (미승인으로 저장)", width="stretch"):
        answer("reject")
    if p.get("can_revise", True):
        with st.form("revise"):
            fb = st.text_area("고칠 내용을 적어 주세요", placeholder="예: 3번 씬 대사를 더 짧게, 제목에 가격 넣기")
            if st.form_submit_button("수정 요청 (계획부터 다시 만들어요)") and fb.strip():
                answer({"action": "revise", "feedback": fb.strip()})
    else:
        st.caption("수정 요청 한도에 도달했어요. 승인 또는 반려를 골라 주세요.")


def waiting_screen() -> None:
    st.title("🎬 협찬 숏폼 기획 Agent")
    st.caption(" → ".join(st.session_state.steps))
    p = st.session_state.pending
    if p["stage"] != "precheck":
        state = st.session_state.graph.get_state(st.session_state.cfg).values
        for n in state.get("edit_notes", []):
            st.info("✏️ " + n)
    {"precheck": precheck_question, "concept": concept_question, "final": final_question}[p["stage"]](p)


# --- 결과 화면 -------------------------------------------------------------------
def done_screen() -> None:
    st.title("🎬 협찬 숏폼 기획 Agent")
    if st.session_state.error:
        st.error("실행 중 오류가 났어요: " + st.session_state.error)
    else:
        state = st.session_state.graph.get_state(st.session_state.cfg).values
        if state.get("stopped"):
            st.error("⛔ 중단: " + state.get("stop_reason", ""))
        elif state.get("output"):
            rep = state.get("check_report")
            ok = rep is not None and rep.passed
            approved = state.get("approved")
            (st.success if ok and approved else st.warning)(
                f"{'✅ 검증 통과' if ok else '⚠️ 미통과 표시'} · 수정 {state.get('revision', 0)}회 · "
                f"최종 승인: {'예' if approved else '아니오'}"
            )
            show_storyboard(state["output"])
            if state.get("output_dir"):
                folder = Path(state["output_dir"])
                st.markdown(f"#### 결과 파일\n`{folder}`")
                cols = st.columns(3)
                for col, name in zip(cols, ("기획안.md", "storyboard.json", "check_report.json")):
                    f = folder / name
                    if f.exists():
                        col.download_button(f"⬇️ {name}", f.read_bytes(), file_name=name, width="stretch")
    if st.session_state.trace_where:
        st.caption(f"🧭 실행 기록(Trace): {st.session_state.trace_where}")
    if st.button("새 기획 시작", type="primary"):
        reset()
        st.rerun()


# --- 시작 ------------------------------------------------------------------------
init_state()
{"input": input_screen, "waiting": waiting_screen, "done": done_screen}[st.session_state.phase]()
