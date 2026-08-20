"""Apply final deterministic bullet and page-break fixes without extra packages."""

from __future__ import annotations

import argparse
import html
import os
import re
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


BULLET_TEXTS = {
    "합성 상담 원천의 중복 제거와 150건 필드 제안 데이터 파생",
    "간단한 EDA와 80:20 층화 분할",
    "Dummy, Logistic Regression, Random Forest 비교",
    "혼동행렬·Feature Importance·모델 비교 결과 생성",
    "선정 Pipeline 전체 joblib 저장과 재로드 추론 확인",
    "실제 사용자 데이터가 아닌 합성 상담 시나리오를 사용하였다.",
    "needs_review와 confidence가 실제 관측값이 아니라 규칙 기반 대리 값이다.",
    "데이터 150건, Test 30건으로 표본이 매우 작다.",
    "실제 F2 sLLM 오류 및 사용자 검토 분포와 다를 수 있다.",
    "현재 결과는 제출용 PoC이며 실서비스 환경에서 검증되지 않았다.",
    "향후 사용자 수락·수정·거절 이력을 Target으로 전환하고 시간·사용자 그룹 누수를 차단해 재학습해야 한다.",
    "딥러닝 모델은 이번 범위에서 학습하지 않았다.",
    "현재 모델은 제출용 오프라인 artifact로만 보관한다.",
    "F2 서비스 API나 사용자 승인·저장 흐름에는 연결하지 않는다.",
    "실제 승인 전후 데이터가 축적되면 대리 라벨을 폐기하고 실제 피드백 Target으로 재학습한다.",
    "새 데이터로 평가할 때 동일 그룹·동일 문장 파생본의 Train/Test 누수를 차단한다.",
    "세 원천 파일 총 1,250행 중 중복 제거 후 1,200개의 합성 상담만 후보로 사용하였다.",
    "학습 데이터는 150건, Test Set은 30건으로 작다.",
    "confidence와 needs_review가 실제 관측값이 아니다.",
    "실제 F2 sLLM 오류 분포 및 사용자의 검토 행동과 다를 수 있다.",
    "본 결과는 소규모 합성 Test Set 결과이며 실서비스 성능을 의미하지 않는다.",
    "향후 실제 사용자 수락·수정·거절 데이터와 시간 기반 평가셋으로 재검증해야 한다.",
    "딥러닝은 이번 PoC 범위에서 수행하지 않았다.",
}

PARAGRAPH_RE = re.compile(r"<w:p(?:\s[^>]*)?>.*?</w:p>", re.DOTALL)
TEXT_RE = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.DOTALL)
FIRST_TEXT_RE = re.compile(r"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)", re.DOTALL)
PAGE_BREAK = '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
LONG_SCOPE_EXCLUSION = "딥러닝, Transformer, XGBoost, Hyperparameter Search, SHAP, 외부 API 및 실제 서비스 연동은 수행하지 않았다."
SHORT_SCOPE_EXCLUSION = "딥러닝·Transformer·XGBoost·SHAP·외부 API·서비스 연동은 이번 범위에서 제외하였다."
OLD_SPLIT_DESCRIPTION = "field_type과 needs_review의 복합 층화를 사용해 Train 120건, Test 30건으로 분할하였다. 같은 source_group_id와 transcript hash의 Train/Test 교차는 모두 0건이다."
NEW_SPLIT_DESCRIPTION = "needs_review 기준 층화 분할을 사용해 Train 120건, Test 30건으로 나누고 Test에 10개 field_type이 모두 포함되는지 별도 검증하였다. 같은 source_group_id와 transcript hash의 Train/Test 교차는 모두 0건이다."


def visible_text(paragraph_xml: str) -> str:
    return html.unescape("".join(TEXT_RE.findall(paragraph_xml)))


def patch_xml(document_xml: str) -> tuple[str, int, bool]:
    document_xml = document_xml.replace(LONG_SCOPE_EXCLUSION, SHORT_SCOPE_EXCLUSION)
    document_xml = document_xml.replace(OLD_SPLIT_DESCRIPTION, NEW_SPLIT_DESCRIPTION)
    bullet_count = 0
    page_break_added = False

    def replace_paragraph(match: re.Match[str]) -> str:
        nonlocal bullet_count, page_break_added
        paragraph = match.group(0)
        text = visible_text(paragraph)
        plain = text[2:] if text.startswith("• ") else text

        if plain in BULLET_TEXTS and not text.startswith("• "):
            paragraph = FIRST_TEXT_RE.sub(
                lambda first: first.group(1) + "• " + first.group(2) + first.group(3),
                paragraph,
                count=1,
            )
            bullet_count += 1

        if text == "2. 데이터와 전처리":
            preceding = document_xml[max(0, match.start() - len(PAGE_BREAK)) : match.start()]
            if preceding != PAGE_BREAK:
                page_break_added = True
                return PAGE_BREAK + paragraph
        return paragraph

    return PARAGRAPH_RE.sub(replace_paragraph, document_xml), bullet_count, page_break_added


def patch_document(path: Path) -> tuple[int, bool]:
    with ZipFile(path, "r") as source:
        original = source.read("word/document.xml").decode("utf-8")
        patched, bullet_count, page_break_added = patch_xml(original)
        fd, temp_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".docx", dir=path.parent)
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            with ZipFile(temp_path, "w", ZIP_DEFLATED) as target:
                for item in source.infolist():
                    payload = patched.encode("utf-8") if item.filename == "word/document.xml" else source.read(item.filename)
                    target.writestr(item, payload)
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
    return bullet_count, page_break_added


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("documents", nargs="+", type=Path)
    args = parser.parse_args()
    for document in args.documents:
        count, added = patch_document(document)
        print(f"{document}: bullets={count}, page_break_added={added}")


if __name__ == "__main__":
    main()
