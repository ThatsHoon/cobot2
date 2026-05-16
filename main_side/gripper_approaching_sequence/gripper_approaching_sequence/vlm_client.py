"""vlm_client.py — OpenAI Chat Completions vision 으로 의미론적 파지 ROI 추론.

입력: 객체 크롭 이미지 (BGR ndarray) + 객체 라벨
출력: 크롭 좌표계의 grasp ROI bbox [x1, y1, x2, y2] (픽셀)

OPENAI_API_KEY 환경변수 필수 (~/.bashrc 의 export 값을 그대로 사용).
JSON 모드(response_format=json_object) 로 응답을 강제하여 파싱 안정성 확보.
"""
from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np


DEFAULT_MODEL = "gpt-4o"

GRASP_PROMPT_TEMPLATE = (
    "You annotate images for a tabletop pick-and-place research experiment.\n"
    "The image is a crop showing a '{label}' on a workbench. The crop "
    "INTENTIONALLY shows surrounding workbench area for visual context, "
    "but you MUST NOT include workbench in the output bbox.\n"
    "\n"
    "Mark a rectangular region for the LOCAL GRASPABLE SURFACE — the "
    "area on the OBJECT itself where a two-finger parallel gripper makes "
    "contact. The region's depth points feed PCA for the grasp pose, so "
    "it must contain enough OBJECT pixels — never a thin sliver and "
    "never overlapping the workbench around the object.\n"
    "\n"
    "Sizing rules (mandatory):\n"
    "- The rectangle must lie ENTIRELY on the object's surface. "
    "  Workbench / floor / table is for visual context only and must be "
    "  EXCLUDED from the bbox.\n"
    "- Width AND height each >= max(30 px, 15% of the crop's smaller "
    "  side).\n"
    "- Region area should be roughly 10%–60% of the crop area "
    "  (tight on the object, NOT the whole crop).\n"
    "- Stay on ONE visible surface — do NOT cross obvious depth or "
    "  material transitions (e.g., a pot handle joining its body).\n"
    "- ★ AVOID concave / curved interiors. The region must be a "
    "  FLAT or NEARLY-FLAT patch. If the object has a bowl-shaped or "
    "  deeply curved interior (cup, deep dish, bowl, plate well), pick "
    "  a FLAT region only — typically a strip on the outer rim's TOP "
    "  edge — and do NOT include the inner concave surface.\n"
    "- Axis-aligned only (no rotation).\n"
    "\n"
    "Selection priority by object shape:\n"
    "(1) Handled objects (pot, mug, pan, kettle): a rectangle ALONG the "
    "    handle's main length, covering its full thickness — keep the "
    "    box entirely on the handle, not on the body.\n"
    "(2a) FLAT objects with no bowl (smartphone, remote, book, lid, "
    "    glasses, flat plate): a square-ish patch on one flat face. "
    "    Inner surface OK if it is flat.\n"
    "(2b) Concave / bowl-shaped objects (cup, mug bowl, deep plate, "
    "    soup bowl): place the box as a NARROW STRIP across the FLAT "
    "    RIM (the top circular edge), tangent to the rim, NOT crossing "
    "    into the curved interior. Width may be narrow if needed.\n"
    "(3) Long / waisted objects (banana, dumbbell, bottle, shaker, jar "
    "    with neck): the narrow waist segment near the centroid, "
    "    oriented along the long axis.\n"
    "(4) Other: the flattest, most accessible patch near the centroid.\n"
    "\n"
    "Note: workbench plane (floor) is detected separately by another "
    "module from raw depth — you do NOT need to include workbench in "
    "the bbox for that purpose.\n"
    "\n"
    "Respond with a SINGLE JSON object only (no markdown, no extra text):\n"
    '{{"bbox":[x1,y1,x2,y2],"reason":"<10-15 words>"}}\n'
    "Coordinates are pixel integers from top-left (0,0); x2>x1, y2>y1.\n"
    "Image size: {w} x {h}."
)


def make_grasp_prompt(label: str, w: int, h: int) -> str:
    """프롬프트 미리보기/로깅용 — 외부에서 동일 텍스트를 얻을 수 있도록 노출."""
    return GRASP_PROMPT_TEMPLATE.format(label=label, w=w, h=h)


@dataclass
class GraspROI:
    bbox: Tuple[int, int, int, int]
    reason: str
    raw_response: str
    prompt: str = ""


def _encode_jpeg_b64(image_bgr: np.ndarray, quality: int = 85) -> str:
    ok, buf = cv2.imencode(".jpg", image_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG 인코딩 실패")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _extract_first_json(text: str) -> Optional[dict]:
    fence = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        m = re.search(r"\{[\s\S]*?\}", text)
        candidate = m.group(0) if m else None
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


class VLMClient:
    """OpenAI Chat Completions vision 클라이언트 (JSON 모드)."""

    def __init__(self, model: str = DEFAULT_MODEL,
                 max_tokens: int = 256,
                 timeout: float = 30.0):
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "openai SDK 미설치 — 'pip install openai' 필요"
            ) from e
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY 미설정 — ~/.bashrc 를 source 한 셸에서 실행하세요"
            )
        self.client = OpenAI(api_key=api_key, timeout=timeout)
        self.model = model
        self.max_tokens = max_tokens

    def query_grasp_roi(self, crop_bgr: np.ndarray, label: str) -> GraspROI:
        h, w = crop_bgr.shape[:2]
        if min(h, w) < 16:
            raise ValueError(f"크롭 너무 작음: {w}x{h}")

        prompt = make_grasp_prompt(label, w, h)
        b64 = _encode_jpeg_b64(crop_bgr)
        data_url = f"data:image/jpeg;base64,{b64}"

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url",
                         "image_url": {"url": data_url, "detail": "high"}},
                    ],
                }],
            )
        except Exception as e:
            raise RuntimeError(f"OpenAI API 호출 실패: {type(e).__name__}: {e}") from e

        if not resp.choices:
            raise RuntimeError(f"choices 비어 있음: {resp}")
        choice = resp.choices[0]
        msg = choice.message
        text = (msg.content or "").strip()
        finish = getattr(choice, "finish_reason", "?")
        refusal = getattr(msg, "refusal", None)

        if not text:
            raise RuntimeError(
                f"VLM 빈 응답  finish_reason={finish}  refusal={refusal!r}  "
                f"prompt 길이={len(prompt)}  image={w}x{h}  "
                "(content_filter / max_tokens 부족 / 모델 거부 등)"
            )

        data = _extract_first_json(text)
        if data is None or "bbox" not in data:
            raise RuntimeError(
                f"VLM 응답 파싱 실패  finish_reason={finish}  "
                f"text={text[:200]!r}"
            )
        bbox = data["bbox"]
        if not (isinstance(bbox, list) and len(bbox) == 4):
            raise RuntimeError(f"bbox 형식 오류: {bbox}")
        x1, y1, x2, y2 = (int(v) for v in bbox)
        x1 = max(0, min(w - 1, x1))
        y1 = max(0, min(h - 1, y1))
        x2 = max(0, min(w, x2))
        y2 = max(0, min(h, y2))
        if x2 <= x1 or y2 <= y1:
            raise RuntimeError(f"VLM bbox 무효: {bbox} (이미지 {w}x{h})")
        return GraspROI(
            bbox=(x1, y1, x2, y2),
            reason=str(data.get("reason", "")),
            raw_response=text,
            prompt=prompt,
        )


def to_global_bbox(crop_bbox: Tuple[int, int, int, int],
                   crop_origin_xy: Tuple[int, int]
                   ) -> Tuple[int, int, int, int]:
    ox, oy = crop_origin_xy
    x1, y1, x2, y2 = crop_bbox
    return (x1 + ox, y1 + oy, x2 + ox, y2 + oy)
