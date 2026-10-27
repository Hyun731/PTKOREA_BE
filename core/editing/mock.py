"""Mock AI planner: keyword rules -> real edit commands, for running the editor without a model key.

It is deliberately simple and labelled as Mock in the UI. It produces the same command list a
model would, so the preview / apply / undo path is exercised end to end.
"""
from __future__ import annotations

import re
from typing import Optional

from core.editing.scope import Target
from core.editing.text import to_tokens
from core.schemas.slidespec import ImageBlock, ShapeBlock, SlideSpec, TableBlock, TextBlock

COLORS = [
    (("파란", "파랑", "블루"), "#1D4ED8", "파란색"),
    (("남색", "네이비"), "navy", "남색"),
    (("빨간", "빨강", "레드"), "#C0392B", "빨간색"),
    (("주황", "오렌지"), "red", "주황색"),
    (("초록", "녹색", "그린"), "green", "초록색"),
    (("검정", "검은", "블랙"), "text", "검정"),
    (("흰", "하얀", "화이트"), "white", "흰색"),
    (("회색", "그레이"), "muted", "회색"),
]
COUNTS = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5}
TITLE_ROLES = ("lead", "cover_title", "divider_title")  # the headline a person calls "제목"; role "title" is the breadcrumb
HELP = ("Mock 모드에서 처리할 수 있는 요청 예: '글씨 키워줘', '파란색으로 바꿔줘', '세 줄로 요약해 줘', "
        "'좌우로 바꿔줘', '가운데 정렬', '더 깔끔하게', '배경을 연하게', '제목 디자인 통일', '삭제해 줘', '여기에 텍스트 추가', '발표 대본 써줘'")


def _has(msg: str, *words: str) -> bool:
    return any(w in msg for w in words)


def _targets(slides: list[SlideSpec], target: Target) -> list[tuple[SlideSpec, object]]:
    out = []
    for s in slides:
        if s.slide_id not in target.slide_ids:
            continue
        ids = target.element_ids.get(s.slide_id)
        for b in s.blocks:
            if b.block_id == "bg":
                continue
            if not ids or b.block_id in ids:
                out.append((s, b))
    return out


def _texts(items, *, titles_first: bool = False):
    texts = [(s, b) for s, b in items if isinstance(b, TextBlock) and b.role not in ("page_no", "chip")]
    if titles_first:
        titles = [(s, b) for s, b in texts if b.role in TITLE_ROLES]
        return titles or [(s, b) for s, b in texts if b.role == "title"] or texts
    return texts


def _line_count(msg: str) -> Optional[int]:
    m = re.search(r"(\d)\s*(?:줄|개|문장|항목)", msg)
    if m:
        return int(m.group(1))
    for k, v in COUNTS.items():
        if re.search(k + r"\s*(?:줄|개|문장|항목|가지)", msg):
            return v
    return None


def script_for(slide: SlideSpec) -> str:
    """A plain presenter script: headline, up to three body points, closing line."""
    texts = {b.role: [p.plain().strip() for p in b.paragraphs if p.plain().strip()] for b in slide.blocks
             if isinstance(b, TextBlock) and b.role in ("lead", "cover_title", "divider_title", "takeaway")}
    paras = [p for b in slide.blocks if isinstance(b, TextBlock) and b.role in ("body", "insight") for p in b.paragraphs]
    # Bulleted lines are the slide's points; bare labels ("조회 수") are not worth saying aloud.
    cands = [p.plain().strip() for p in paras if p.bullet] + [p.plain().strip() for p in paras if not p.bullet]
    body: list[str] = []
    for t in cands:
        t = t.lstrip("·-▸▲┃ ").strip()
        if len(t) > 14 and not any(t in x or x in t for x in body):
            body.append(t)
    body = body[:3]
    head = " ".join(texts.get("lead") or texts.get("cover_title") or texts.get("divider_title") or [slide.title])
    lines = [f"이번 장은 '{head}'입니다."]
    lines += [f"- {t}" for t in body]
    if texts.get("takeaway"):
        lines.append(f"정리하면, {' '.join(texts['takeaway'])}.")
    return "\n".join(lines)


def plan(message: str, slides: list[SlideSpec], target: Target, current_slide_id: str) -> tuple[str, list[dict]]:
    msg = message.strip()
    items = _targets(slides, target)
    selected = bool(target.element_ids.get(current_slide_id) - {"__area_only__"}) if target.element_ids.get(current_slide_id) else False
    cmds: list[dict] = []
    said: list[str] = []

    def cmd(op: str, s: SlideSpec, reason: str, **kw):
        cmds.append({"op": op, "slide_id": s.slide_id, "reason": reason, **kw})

    whole_deck = len(target.slide_ids) > 1
    # 1) design unification across slides: copy the current slide's headline style
    if _has(msg, "통일", "일관"):
        cur = next((s for s in slides if s.slide_id == current_slide_id), None)
        ref = next((b for b in (cur.blocks if cur else []) if isinstance(b, TextBlock) and b.role == "lead"), None)
        if ref:
            for s, b in _texts(items, titles_first=True):
                if b.role == "lead" and b.block_id == ref.block_id and s.slide_id == current_slide_id:
                    continue
                same = (b.size, b.color, b.weight or "bold", b.align) == (ref.size, ref.color, ref.weight or "bold", ref.align)
                if b.role == "lead" and not same:
                    cmd("update_style", s, "현재 슬라이드의 헤드라인 스타일에 맞춤", element_id=b.block_id,
                        size=ref.size, color=ref.color, weight=ref.weight or "bold", align=ref.align)
            said.append("현재 슬라이드의 헤드라인 크기·색·굵기를 기준으로 다른 슬라이드의 헤드라인을 맞추겠습니다")

    # 2) colors
    for words, value, label in COLORS:
        if _has(msg, *words) and not _has(msg, "배경"):
            for s, b in (_texts(items, titles_first=not selected) or [(s, b) for s, b in items if isinstance(b, ShapeBlock)]):
                cmd("update_style", s, f"요청한 {label} 적용", element_id=b.block_id, color=value)
            said.append(f"{'선택한 요소를' if selected else '제목을'} {label}으로 바꾸겠습니다")
            break

    # 3) size
    bigger = _has(msg, "키워", "키우", "크게", "강렬", "강조")
    smaller = _has(msg, "작게", "줄여") and not _has(msg, "요약", "줄로")
    if bigger or smaller:
        factor = 1.2 if bigger else 0.85
        for s, b in _texts(items, titles_first=not selected):
            cmd("update_style", s, "글자 크기 " + ("키움" if bigger else "줄임"), element_id=b.block_id,
                size=round(b.size * factor, 1))
        said.append(f"글자 크기를 약 {int(abs(factor - 1) * 100)}% {'키우' if bigger else '줄이'}겠습니다")
    if _has(msg, "강렬", "굵게", "두껍게", "임팩트"):
        for s, b in _texts(items, titles_first=not selected):
            cmd("update_style", s, "굵기를 높여 강조", element_id=b.block_id, weight="heavy")
        said.append("굵기를 가장 굵게 바꾸겠습니다")

    # 4) summarise: keep the first N paragraphs (chips and names stay as they are)
    if _has(msg, "요약", "줄로", "핵심만", "간단히", "간결"):
        n = _line_count(msg) or 3
        done = False
        for s, b in _texts(items):
            if b.role in ("footnote", "page_no", "chip", "meta") or len(b.paragraphs) <= n:
                continue
            cmd("update_text", s, f"핵심 {n}개 문단만 남김", element_id=b.block_id, paragraphs=to_tokens(b)[:n])
            done = True
        said.append(f"문단이 많은 텍스트를 앞의 핵심 {n}개만 남기겠습니다" if done else
                    f"이미 {n}개 이하로 정리된 텍스트라 줄일 문단이 없습니다")

    # 5) swap left/right
    if _has(msg, "좌우", "자리 바꿔", "위치 바꿔", "바꿔 배치", "스왑"):
        cands = sorted([(s, b) for s, b in items if not isinstance(b, ShapeBlock) or b.shape != "line"],
                       key=lambda sb: -(sb[1].region.w * sb[1].region.h))[:2]
        if len(cands) == 2 and cands[0][0].slide_id == cands[1][0].slide_id:
            (s, a), (_, b) = cands
            ra, rb = a.region, b.region
            cmd("restructure_layout", s, "두 요소의 좌우 위치를 맞바꿈", items=[
                {"element_id": a.block_id, "x": rb.x + rb.w - ra.w if ra.x < rb.x else rb.x, "y": ra.y},
                {"element_id": b.block_id, "x": ra.x if ra.x < rb.x else ra.x + ra.w - rb.w, "y": rb.y}])
            said.append("가장 큰 두 요소의 좌우 위치를 맞바꾸겠습니다")
        else:
            said.append("좌우로 바꿀 두 요소를 함께 선택하거나 영역으로 지정해 주세요")

    # 6) alignment
    for word, al, label in (("가운데", "c", "가운데"), ("왼쪽", "l", "왼쪽"), ("오른쪽", "r", "오른쪽")):
        if word in msg and "정렬" in msg:
            for s, b in _texts(items):
                cmd("update_style", s, f"{label} 정렬", element_id=b.block_id, align=al)
            said.append(f"텍스트를 {label} 정렬하겠습니다")

    # 7) cleaner / more refined: more air between lines, calmer headline
    if _has(msg, "세련", "깔끔", "정리", "여백", "간격", "복잡"):
        for s, b in _texts(items):
            if b.role in ("page_no", "chip", "footnote"):
                continue
            cmd("update_style", s, "줄 간격을 넓혀 읽기 쉽게", element_id=b.block_id, line_spacing=round(b.line_spacing * 1.15, 1))
            if b.role in TITLE_ROLES:
                cmd("update_style", s, "제목을 차분한 남색 볼드로", element_id=b.block_id, color="navy", weight="bold")
        said.append("줄 간격을 15% 넓히고 제목을 남색 볼드로 정돈하겠습니다")

    # 8) background
    if "배경" in msg:
        value, label = "tint", "연한 회청색"
        for words, v, lb in COLORS:
            if _has(msg, *words):
                value, label = v, lb
        if _has(msg, "없애", "제거", "흰"):
            value, label = None, "흰색(배경 없음)"
        for sid in target.slide_ids:
            s = next(x for x in slides if x.slide_id == sid)
            cmd("update_background", s, f"배경을 {label}으로", color=value)
        said.append(f"배경을 {label}으로 바꾸겠습니다")

    # 9) delete
    if _has(msg, "삭제", "지워", "없애") and "배경" not in msg and selected:
        for s, b in items:
            cmd("delete_element", s, "요청에 따라 삭제", element_id=b.block_id)
        said.append(f"선택한 요소 {len(items)}개를 삭제하겠습니다")

    # 10) add text into an empty marked area
    if _has(msg, "추가", "넣어", "적어"):
        for sid, areas in target.areas.items():
            s = next(x for x in slides if x.slide_id == sid)
            for a in areas:
                cmd("add_element", s, "지정한 영역에 텍스트 상자 추가",
                    element={"kind": "text", "x": a.x, "y": a.y, "w": a.w, "h": a.h, "paragraphs": ["새 텍스트"],
                             "size": 14, "color": "text"})
        if target.areas:
            said.append("지정한 영역에 텍스트 상자를 추가하겠습니다")

    # 11) presenter script from what the slide shows
    if _has(msg, "대본", "발표 메모", "발표자 메모", "스크립트", "노트", "멘트"):
        for sid in target.slide_ids:
            s = next(x for x in slides if x.slide_id == sid)
            cmd("update_notes", s, "슬라이드에 보이는 내용으로 발표 대본 초안 작성", text=script_for(s))
        said.append("슬라이드에 보이는 헤드라인·본문·요약으로 발표자 메모 초안을 쓰겠습니다")

    if not cmds:
        if said:
            return ". ".join(dict.fromkeys(said)) + ". (바꿀 것이 없어 수정하지 않았습니다)", []
        return "요청을 편집 명령으로 바꾸지 못했습니다. " + HELP, []
    scope = "전체 슬라이드" if whole_deck else ("선택한 영역" if selected or target.areas else "현재 슬라이드")
    return f"[{scope}] " + ". ".join(dict.fromkeys(said)) + ".", cmds
