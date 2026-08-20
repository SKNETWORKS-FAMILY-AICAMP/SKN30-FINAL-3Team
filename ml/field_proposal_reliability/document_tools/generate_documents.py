#!/usr/bin/env python3
"""Create the two temporary submission DOCX files from actual PoC results.

The previous cohort documents are used as retained visual references. Their
body contents are replaced, while section geometry, styles, headers, footers,
theme relationships, and embedded branding remain source-derived.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from docx import Document
from docx.document import Document as DocumentObject
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor


NAVY = "17365D"
BLUE = "2F5597"
LIGHT_BLUE = "D9EAF7"
PALE_BLUE = "EDF4FB"
LIGHT_GRAY = "E7E6E6"
MID_GRAY = "B4C6E7"
WHITE = "FFFFFF"
TEXT = "222222"

FONT_KO = "맑은 고딕"
FONT_EN = "Arial"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poc-root", type=Path, required=True)
    parser.add_argument("--training-template", type=Path, required=True)
    parser.add_argument("--model-template", type=Path, required=True)
    parser.add_argument("--submission-date", default="2026. 08. 20.")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_comparison(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        return list(csv.DictReader(file_obj))


def set_run_font(run: Any, name: str = FONT_KO) -> None:
    run.font.name = name
    if run._element.rPr is None:
        run._element.get_or_add_rPr()
    rfonts = run._element.rPr.get_or_add_rFonts()
    rfonts.set(qn("w:ascii"), FONT_EN)
    rfonts.set(qn("w:hAnsi"), FONT_EN)
    rfonts.set(qn("w:eastAsia"), name)


def configure_style(style: Any, size: float, bold: bool = False, color: str = TEXT) -> None:
    style.font.name = FONT_KO
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = RGBColor.from_string(color)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:ascii"), FONT_EN)
    rfonts.set(qn("w:hAnsi"), FONT_EN)
    rfonts.set(qn("w:eastAsia"), FONT_KO)


def configure_document(doc: DocumentObject, title: str) -> None:
    doc.core_properties.title = title
    doc.core_properties.subject = "F2 Field Proposal Review Risk Model synthetic PoC"
    doc.core_properties.author = "SK 네트웍스 Family AI 30기 3팀"
    doc.core_properties.comments = (
        "Synthetic proxy-label PoC. Not production or real-user performance."
    )

    configure_style(doc.styles["Normal"], 10.5, False, TEXT)
    normal_format = doc.styles["Normal"].paragraph_format
    normal_format.space_after = Pt(5)
    normal_format.line_spacing = 1.25

    if "Title" in doc.styles:
        configure_style(doc.styles["Title"], 24, True, NAVY)
    if "Subtitle" in doc.styles:
        configure_style(doc.styles["Subtitle"], 12, False, BLUE)
    if "Heading 1" in doc.styles:
        configure_style(doc.styles["Heading 1"], 15, True, NAVY)
        doc.styles["Heading 1"].paragraph_format.space_before = Pt(14)
        doc.styles["Heading 1"].paragraph_format.space_after = Pt(7)
        doc.styles["Heading 1"].paragraph_format.keep_with_next = True
    if "Heading 2" in doc.styles:
        configure_style(doc.styles["Heading 2"], 12, True, BLUE)
        doc.styles["Heading 2"].paragraph_format.space_before = Pt(10)
        doc.styles["Heading 2"].paragraph_format.space_after = Pt(5)
        doc.styles["Heading 2"].paragraph_format.keep_with_next = True
    if "Heading 3" in doc.styles:
        configure_style(doc.styles["Heading 3"], 10.5, True, NAVY)


def clear_body(doc: DocumentObject) -> None:
    body = doc._element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def set_cell_shading(cell: Any, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell: Any, top: int = 100, start: int = 120, bottom: int = 100, end: int = 120) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin_name, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin_name}"))
        if node is None:
            node = OxmlElement(f"w:{margin_name}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_repeat_table_header(row: Any) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_table_fixed(table: Any, widths_cm: Sequence[float] | None = None) -> None:
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")
    if widths_cm:
        for row in table.rows:
            for index, width in enumerate(widths_cm):
                if index < len(row.cells):
                    row.cells[index].width = Cm(width)


def set_table_borders(table: Any, color: str = "B7C5D8", size: str = "6") -> None:
    """Apply explicit grid borders without depending on a localized table style."""
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = qn(f"w:{edge}")
        element = borders.find(tag)
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), size)
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), color)


def format_table(table: Any, widths_cm: Sequence[float] | None = None) -> None:
    set_table_fixed(table, widths_cm)
    set_table_borders(table)
    set_repeat_table_header(table.rows[0])
    for row_index, row in enumerate(table.rows):
        for cell in row.cells:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(cell)
            if row_index == 0:
                set_cell_shading(cell, NAVY)
            elif row_index % 2 == 0:
                set_cell_shading(cell, PALE_BLUE)
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = 1.1
                for run in paragraph.runs:
                    set_run_font(run)
                    run.font.size = Pt(8.8)
                    if row_index == 0:
                        run.font.bold = True
                        run.font.color.rgb = RGBColor.from_string(WHITE)


def add_table(
    doc: DocumentObject,
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]],
    widths_cm: Sequence[float] | None = None,
) -> Any:
    materialized = [["" if value is None else str(value) for value in row] for row in rows]
    table = doc.add_table(rows=1, cols=len(headers))
    for index, header in enumerate(headers):
        table.rows[0].cells[index].text = header
    for row_values in materialized:
        cells = table.add_row().cells
        for index, value in enumerate(row_values):
            cells[index].text = value
    format_table(table, widths_cm)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return table


def add_heading(doc: DocumentObject, text: str, level: int = 1) -> Any:
    paragraph = doc.add_paragraph(style=f"Heading {level}")
    run = paragraph.add_run(text)
    set_run_font(run)
    return paragraph


def add_body(doc: DocumentObject, text: str, bold_prefix: str | None = None) -> Any:
    paragraph = doc.add_paragraph()
    if bold_prefix and text.startswith(bold_prefix):
        prefix = paragraph.add_run(bold_prefix)
        prefix.font.bold = True
        set_run_font(prefix)
        rest = paragraph.add_run(text[len(bold_prefix) :])
        set_run_font(rest)
    else:
        run = paragraph.add_run(text)
        set_run_font(run)
    return paragraph


def add_bullet(doc: DocumentObject, text: str) -> Any:
    # The supplied Korean templates do not expose Word's localized bullet style
    # through the English name, so use an explicit bullet for deterministic output.
    paragraph = doc.add_paragraph(style="Normal")
    paragraph.paragraph_format.left_indent = Cm(0.55)
    paragraph.paragraph_format.first_line_indent = Cm(-0.35)
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.paragraph_format.line_spacing = 1.1
    run = paragraph.add_run(f"• {text}")
    set_run_font(run)
    return paragraph


def add_numbered(doc: DocumentObject, text: str) -> Any:
    style = "List Number" if "List Number" in doc.styles else "Normal"
    paragraph = doc.add_paragraph(style=style)
    run = paragraph.add_run(text)
    set_run_font(run)
    return paragraph


def add_callout(doc: DocumentObject, title: str, text: str) -> None:
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(table, color=BLUE, size="8")
    cell = table.cell(0, 0)
    set_cell_shading(cell, LIGHT_BLUE)
    set_cell_margins(cell, top=150, start=180, bottom=150, end=180)
    paragraph = cell.paragraphs[0]
    title_run = paragraph.add_run(f"{title}  ")
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor.from_string(NAVY)
    set_run_font(title_run)
    body_run = paragraph.add_run(text)
    set_run_font(body_run)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_figure(doc: DocumentObject, image_path: Path, caption: str, width_inches: float = 5.7) -> None:
    if not image_path.is_file():
        return
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    run.add_picture(str(image_path), width=Inches(width_inches))
    caption_paragraph = doc.add_paragraph()
    caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption_run = caption_paragraph.add_run(caption)
    caption_run.font.size = Pt(9)
    caption_run.font.italic = True
    caption_run.font.color.rgb = RGBColor.from_string(BLUE)
    set_run_font(caption_run)


def add_cover(
    doc: DocumentObject,
    title: str,
    subtitle: str,
    submission_date: str,
) -> None:
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after = Pt(22)
    cohort = doc.add_paragraph()
    cohort.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = cohort.add_run("SK 네트웍스 Family AI 30기 : 3팀")
    run.font.size = Pt(14)
    run.font.bold = True
    run.font.color.rgb = RGBColor.from_string(BLUE)
    set_run_font(run)

    title_paragraph = doc.add_paragraph()
    title_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_paragraph.paragraph_format.space_before = Pt(26)
    title_paragraph.paragraph_format.space_after = Pt(8)
    title_run = title_paragraph.add_run(title)
    title_run.font.size = Pt(24)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor.from_string(NAVY)
    set_run_font(title_run)

    subtitle_paragraph = doc.add_paragraph()
    subtitle_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle_run = subtitle_paragraph.add_run(subtitle)
    subtitle_run.font.size = Pt(12)
    subtitle_run.font.color.rgb = RGBColor.from_string(BLUE)
    set_run_font(subtitle_run)

    doc.add_paragraph().paragraph_format.space_after = Pt(18)
    add_table(
        doc,
        ["항목", "내용"],
        [
            ["산출물 단계", "데이터 전처리"],
            ["제출 일자", submission_date],
            ["깃허브 경로", "https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team"],
            ["작성 팀원", "3팀 전체"],
            ["기능명", "Field Proposal Review Risk Model"],
        ],
        [4.2, 12.0],
    )
    add_callout(
        doc,
        "제출 범위",
        "기존 프로젝트의 합성 상담 시나리오에서 규칙 기반 대리 라벨을 파생한 소규모 ML PoC이다. 실제 사용자 데이터나 실서비스 성능을 의미하지 않는다.",
    )
    doc.add_page_break()


def metric_rows(comparison: list[dict[str, str]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in comparison:
        rows.append(
            [
                row["Model"],
                f"{float(row['Train Accuracy']):.4f}",
                f"{float(row['Test Accuracy']):.4f}",
                f"{float(row['Precision']):.4f}",
                f"{float(row['Recall']):.4f}",
                f"{float(row['F1']):.4f}",
            ]
        )
    return rows


def format_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def create_training_result_document(
    template: Path,
    output: Path,
    poc_root: Path,
    metrics: dict[str, Any],
    metadata: dict[str, Any],
    inventory: dict[str, Any],
    eda: dict[str, Any],
    comparison: list[dict[str, str]],
    submission_date: str,
) -> None:
    doc = Document(str(template))
    clear_body(doc)
    configure_document(doc, "머신러닝 / 딥러닝 학습 결과서")
    add_cover(
        doc,
        "머신러닝 / 딥러닝 학습 결과서",
        "F2 Field Proposal Review Risk Model - 합성 대리 라벨 기반 ML PoC",
        submission_date,
    )

    add_heading(doc, "1. 개요", 1)
    add_heading(doc, "1.1 실험 목적", 2)
    add_body(
        doc,
        "F2의 sLLM이 만든 장부 필드 제안 중 사용자의 추가 검토가 필요한 제안을 정형 Feature 기반 이진 분류 문제로 구분할 수 있는지 확인하였다. 본 실험은 sLLM을 대체하거나 자동 저장을 수행하지 않으며, 제출을 위한 최소 ML 적용 가능성 확인에 한정한다.",
    )
    add_table(
        doc,
        ["구분", "정의"],
        [
            ["Task", "Binary Classification"],
            ["Target 0", "LOW_RISK - 제안값을 그대로 사용할 가능성이 높은 항목"],
            ["Target 1", "NEEDS_REVIEW - 충돌·부정·낮은 confidence·파싱 실패 등으로 검토가 필요한 항목"],
            ["Positive class", "needs_review=1"],
            ["주요 선정 지표", "Recall → F1 → Train/Test 차이 → 단순성"],
        ],
        [4.0, 12.2],
    )
    add_callout(
        doc,
        "중요 해석",
        "Target과 confidence는 실제 운영 로그가 아니라 규칙과 고정 난수로 만든 대리 값이다. 따라서 결과는 생성 규칙을 학습할 수 있는지에 대한 초기 확인이며 실제 중개 상담 성능이 아니다.",
    )

    add_heading(doc, "1.2 작업 범위", 2)
    for item in (
        "합성 상담 원천의 중복 제거와 150건 필드 제안 데이터 파생",
        "간단한 EDA와 80:20 층화 분할",
        "Dummy, Logistic Regression, Random Forest 비교",
        "혼동행렬·Feature Importance·모델 비교 결과 생성",
        "선정 Pipeline 전체 joblib 저장과 재로드 추론 확인",
    ):
        add_bullet(doc, item)
    add_body(doc, "딥러닝·Transformer·XGBoost·SHAP·외부 API·서비스 연동은 이번 범위에서 제외하였다.")

    doc.add_page_break()
    add_heading(doc, "2. 데이터와 전처리", 1)
    add_heading(doc, "2.1 원천 데이터", 2)
    add_body(
        doc,
        f"세 원천 파일에는 총 {inventory['raw_row_count']:,}행이 있으며, 파일 간 완전 중복 {inventory['duplicate_row_count']:,}건을 제거한 뒤 {inventory['deduplicated_row_count']:,}개의 고유 합성 상담을 후보 풀로 사용하였다.",
    )
    source_rows = []
    for source in inventory["sources"]:
        source_rows.append(
            [
                Path(source["path"]).name,
                source["raw_rows"],
                source["retained_rows_after_cross_file_deduplication"],
                ", ".join(f"{key} {value}" for key, value in source["raw_label_distribution"].items()),
            ]
        )
    add_table(
        doc,
        ["원천 파일", "원본 행", "중복 제거 후", "라벨 분포"],
        source_rows,
        [6.6, 2.0, 2.3, 5.5],
    )
    add_body(
        doc,
        "모든 원천 레코드는 contains_real_personal_data=false로 표시된 합성 문장이다. 다만 사람 검수된 운영 데이터가 아니므로 실제 상담 분포를 대표한다고 가정하지 않았다.",
    )

    add_heading(doc, "2.2 필드 제안 단위 데이터 생성", 2)
    for index, step in enumerate(
        (
            "상담 문장에서 금액·거래유형·동·호·평형·날짜·명도 관련 후보 근거를 정규식과 키워드로 탐지한다.",
            "각 field_type마다 서로 다른 상담 15건을 선택하고 같은 원천 그룹과 같은 transcript hash를 중복 사용하지 않는다.",
            "근거 길이, 후보 수, 충돌·부정 여부, 파싱 성공 여부와 모사 confidence를 산출한다.",
            "필드별 proxy risk score 상위 7건을 NEEDS_REVIEW로 지정하여 총 70건의 positive class를 구성한다.",
        ),
        start=1,
    ):
        add_numbered(doc, f"{index}. {step}")

    add_table(
        doc,
        ["Feature", "형식", "정의"],
        [
            ["field_type", "범주형", "10개 장부 필드 유형"],
            ["confidence", "0~1 실수", "파싱·충돌·부정·후보 수와 seed 42로 모사한 신뢰도"],
            ["evidence_length", "5~80 정수", "근거 문장 길이"],
            ["mention_count", "1~4 정수", "해당 필드 후보 언급 수"],
            ["has_conflict", "0/1", "복수 값 또는 정정·변경·대조 표현 존재"],
            ["has_negation", "0/1", "부정·거부·보류 표현 존재"],
            ["parse_success", "0/1", "필드별 정규화기가 구체 값을 생성했는지"],
            ["needs_review", "0/1", "규칙 기반 대리 Target"],
        ],
        [4.2, 3.0, 9.2],
    )

    add_heading(doc, "2.3 데이터 품질과 분포", 2)
    add_table(
        doc,
        ["검사 항목", "결과"],
        [
            ["전체 행", eda["row_count"]],
            ["필드별 행", "10개 field_type 각각 15건"],
            ["LOW_RISK", eda["target_distribution"]["0"]],
            ["NEEDS_REVIEW", eda["target_distribution"]["1"]],
            ["Positive 비율", format_pct(float(eda["target_positive_ratio"]))],
            ["결측치", sum(int(value) for value in eda["missing_values"].values())],
            ["원천 그룹/문장 중복", "선택 데이터 0건"],
        ],
        [6.2, 10.2],
    )
    add_callout(doc, "재현성", f"random_state={metadata['random_state']}를 고정하고 데이터·생성기·원천 파일 SHA-256을 함께 기록하였다.")

    doc.add_page_break()
    add_heading(doc, "3. 실험 설계", 1)
    add_heading(doc, "3.1 전처리와 분할", 2)
    add_body(
        doc,
        f"needs_review 기준 층화 분할을 사용해 Train {metrics['split']['train_rows']}건, Test {metrics['split']['test_rows']}건으로 나누고 Test에 10개 field_type이 모두 포함되는지 별도 검증하였다. 같은 source_group_id와 transcript hash의 Train/Test 교차는 모두 {metrics['split']['source_group_overlap']}건이다.",
    )
    add_table(
        doc,
        ["구분", "처리"],
        [
            ["field_type", "OneHotEncoder(handle_unknown='ignore')"],
            ["Logistic 숫자 Feature", "SimpleImputer(median) + StandardScaler"],
            ["Random Forest 숫자 Feature", "SimpleImputer(median), 원 스케일 유지"],
            ["분할", "Train 80% / Test 20%, random_state=42"],
        ],
        [5.5, 10.9],
    )

    add_heading(doc, "3.2 모델 후보", 2)
    add_table(
        doc,
        ["모델", "주요 설정", "역할"],
        [
            ["Dummy", "most_frequent", "다수 클래스 기준선"],
            ["Logistic Regression", "max_iter=1000, random_state=42", "단순하고 영향 방향을 설명하기 쉬운 선형 분류"],
            ["Random Forest", "n_estimators=200, max_depth=6, random_state=42", "비선형 상호작용 비교 후보"],
        ],
        [4.4, 6.1, 5.9],
    )
    add_heading(doc, "3.3 평가 지표", 2)
    add_table(
        doc,
        ["지표", "해석", "사용 목적"],
        [
            ["Accuracy", "전체 예측 중 정답 비율", "전반적 성능 확인"],
            ["Precision", "검토 필요 예측 중 실제 대리 positive 비율", "불필요 검토 부담 확인"],
            ["Recall", "대리 검토 필요 항목 중 탐지 비율", "위험 항목 누락 최소화, 1순위"],
            ["F1", "Precision과 Recall의 조화 평균", "균형 성능, 2순위"],
        ],
        [3.2, 8.0, 5.2],
    )

    add_heading(doc, "4. 실험 결과", 1)
    add_heading(doc, "4.1 모델 비교", 2)
    add_table(
        doc,
        ["Model", "Train Acc.", "Test Acc.", "Precision", "Recall", "F1"],
        metric_rows(comparison),
        [4.0, 2.5, 2.5, 2.4, 2.2, 2.2],
    )
    add_body(doc, "모든 수치는 고정된 30건 합성 Test Set에서 실제 실행한 결과이며, 일반화된 실서비스 성능이 아니다.")

    add_heading(doc, "4.2 혼동행렬", 2)
    add_figure(
        doc,
        poc_root / "reports/confusion_matrix_logistic_regression.png",
        "그림 1. Logistic Regression confusion matrix",
        4.8,
    )
    add_figure(
        doc,
        poc_root / "reports/confusion_matrix_random_forest.png",
        "그림 2. Random Forest confusion matrix",
        4.8,
    )

    add_heading(doc, "4.3 Random Forest Feature Importance", 2)
    add_figure(
        doc,
        poc_root / "reports/random_forest_feature_importance.png",
        "그림 3. 변환된 Feature 기준 Random Forest 중요도",
        5.8,
    )
    importance_rows = []
    for item in metrics.get("random_forest_feature_importance", [])[:8]:
        importance_rows.append([item["feature"], f"{float(item['importance']):.4f}"])
    if importance_rows:
        add_table(doc, ["상위 Feature", "Importance"], importance_rows, [11.0, 5.2])
    add_body(
        doc,
        "Feature Importance는 이 규칙 기반 합성 데이터 안에서의 분할 기여도이며 인과관계나 실제 업무 중요도를 의미하지 않는다.",
    )

    add_heading(doc, "5. 최종 모델 선정", 1)
    final_name = metrics["final_model"]["name"]
    final_result = metrics["models"][final_name]
    add_callout(doc, "선정 모델", final_name)
    add_body(doc, metrics["final_model"]["selection_reason"])
    add_table(
        doc,
        ["선정 모델 Test 지표", "값"],
        [
            ["Accuracy", f"{final_result['test_accuracy']:.4f}"],
            ["Precision", f"{final_result['precision']:.4f}"],
            ["Recall", f"{final_result['recall']:.4f}"],
            ["F1", f"{final_result['f1']:.4f}"],
            ["Train/Test Accuracy 차이", f"{final_result['train_test_accuracy_gap']:.4f}"],
        ],
        [9.0, 7.2],
    )
    add_body(doc, "선정된 전처리·모델 Pipeline 전체는 field_proposal_review_risk_model.joblib로 저장했으며 재로드 후 알려진 입력과 미지 field_type 입력 모두에서 0/1 예측을 확인하였다.")

    add_heading(doc, "6. 한계 및 향후 개선", 1)
    for limitation in (
        "실제 사용자 데이터가 아닌 합성 상담 시나리오를 사용하였다.",
        "needs_review와 confidence가 실제 관측값이 아니라 규칙 기반 대리 값이다.",
        "데이터 150건, Test 30건으로 표본이 매우 작다.",
        "실제 F2 sLLM 오류 및 사용자 검토 분포와 다를 수 있다.",
        "현재 결과는 제출용 PoC이며 실서비스 환경에서 검증되지 않았다.",
        "향후 사용자 수락·수정·거절 이력을 Target으로 전환하고 시간·사용자 그룹 누수를 차단해 재학습해야 한다.",
        "딥러닝 모델은 이번 범위에서 학습하지 않았다.",
    ):
        add_bullet(doc, limitation)

    add_heading(doc, "7. 주요 산출물", 1)
    add_table(
        doc,
        ["분류", "파일"],
        [
            ["데이터", "data/synthetic_field_proposals.csv"],
            ["Notebook", "notebooks/field_proposal_review_risk_poc_output.ipynb"],
            ["모델", "artifacts/field_proposal_review_risk_model.joblib"],
            ["메타데이터", "artifacts/model_metadata.json"],
            ["지표", "reports/model_comparison.csv, reports/metrics.json"],
            ["요약", "reports/experiment_summary.md"],
        ],
        [4.0, 12.2],
    )
    add_heading(doc, "8. 변경 이력", 1)
    add_table(
        doc,
        ["변경일", "변경자", "변경내용", "버전"],
        [[submission_date.rstrip("."), "3팀 전체", "합성 대리 라벨 기반 제출용 ML PoC 결과서 작성", "v1.0"]],
        [3.1, 3.2, 7.8, 2.1],
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output))


def create_model_document(
    template: Path,
    output: Path,
    poc_root: Path,
    metrics: dict[str, Any],
    metadata: dict[str, Any],
    inventory: dict[str, Any],
    comparison: list[dict[str, str]],
    submission_date: str,
) -> None:
    doc = Document(str(template))
    clear_body(doc)
    configure_document(doc, "학습한 ML / DL 모델")
    add_cover(
        doc,
        "학습한 ML / DL 모델",
        "Field Proposal Review Risk Model - 최종 모델 설명서",
        submission_date,
    )

    final_name = metrics["final_model"]["name"]
    final_result = metrics["models"][final_name]
    add_heading(doc, "1. 모델 개요", 1)
    add_table(
        doc,
        ["항목", "내용"],
        [
            ["모델명", final_name],
            ["기능명", "Field Proposal Review Risk Model"],
            ["목적", "F2 sLLM 필드 제안 중 추가 검토가 필요한 항목을 구분하는 제출용 PoC"],
            ["문제 유형", "Binary Classification"],
            ["Positive class", "needs_review=1 (NEEDS_REVIEW)"],
            ["데이터", "기존 합성 상담에서 파생한 규칙 기반 대리 라벨 150건"],
        ],
        [4.2, 12.0],
    )

    add_heading(doc, "2. 모델 구조", 1)
    add_body(doc, "합성 상담 → 필드 후보 탐지 → 정형 Feature 생성 → 80:20 층화 분할 → 모델 비교 → Recall/F1 기반 최종 선택 → Pipeline joblib 저장")

    add_heading(doc, "3. 입력 / 출력 정의", 1)
    add_table(
        doc,
        ["구분", "항목", "설명"],
        [
            ["입력", "field_type", "10개 장부 필드 유형"],
            ["입력", "confidence", "0~1 모사 신뢰도"],
            ["입력", "evidence_length", "근거 문장 길이"],
            ["입력", "mention_count", "후보 언급 수"],
            ["입력", "has_conflict / has_negation", "충돌·부정 표현 여부"],
            ["입력", "parse_success", "구조화 파싱 성공 여부"],
            ["출력", "0", "LOW_RISK"],
            ["출력", "1", "NEEDS_REVIEW"],
        ],
        [2.6, 5.2, 8.4],
    )

    add_heading(doc, "4. Target 정의", 1)
    add_body(doc, "needs_review는 실제 사용자 피드백이 아니라 충돌·부정·낮은 confidence·복수 후보·파싱 실패 및 공동중개/단순문의 문맥을 조합한 proxy risk score로 생성하였다.")
    add_callout(doc, "라벨 한계", "실제 사용자 수락·수정·거절 데이터가 아니며 모델 성능을 실서비스에 일반화할 수 없다.")

    add_heading(doc, "5. 전처리와 사용 프레임워크", 1)
    add_table(
        doc,
        ["항목", "내용"],
        [
            ["범주형", "OneHotEncoder(handle_unknown='ignore')"],
            ["숫자형", "median imputation; Logistic Regression은 StandardScaler 적용"],
            ["Train/Test", f"{metrics['split']['train_rows']} / {metrics['split']['test_rows']}"],
            ["라이브러리", "pandas, NumPy, scikit-learn, Matplotlib, joblib"],
            ["난수 시드", str(metadata["random_state"])],
        ],
        [5.0, 11.2],
    )

    add_heading(doc, "6. 학습 모델과 평가", 1)
    add_table(
        doc,
        ["Model", "Train Acc.", "Test Acc.", "Precision", "Recall", "F1"],
        metric_rows(comparison),
        [4.0, 2.5, 2.5, 2.4, 2.2, 2.2],
    )
    add_body(doc, f"검토 필요 항목 누락을 줄이기 위해 Recall을 우선했고, 실제 실행 결과에 따라 {final_name}을 최종 선택하였다.")
    add_figure(
        doc,
        poc_root
        / (
            "reports/confusion_matrix_logistic_regression.png"
            if final_name == "Logistic Regression"
            else "reports/confusion_matrix_random_forest.png"
        ),
        f"그림 1. 최종 모델({final_name}) confusion matrix",
        4.6,
    )

    add_heading(doc, "7. 최종 모델", 1)
    add_callout(doc, "선정 모델", final_name)
    add_body(doc, metrics["final_model"]["selection_reason"])
    add_table(
        doc,
        ["Test 지표", "값"],
        [
            ["Accuracy", f"{final_result['test_accuracy']:.4f}"],
            ["Precision", f"{final_result['precision']:.4f}"],
            ["Recall", f"{final_result['recall']:.4f}"],
            ["F1", f"{final_result['f1']:.4f}"],
        ],
        [8.2, 8.0],
    )
    add_body(doc, "전체 전처리 Pipeline과 분류기를 field_proposal_review_risk_model.joblib로 저장하였다. 입력은 정의된 7개 Feature를 가진 pandas DataFrame이며 출력은 0 또는 1이다.")

    add_heading(doc, "8. 적용 전략", 1)
    for item in (
        "현재 모델은 제출용 오프라인 artifact로만 보관한다.",
        "F2 서비스 API나 사용자 승인·저장 흐름에는 연결하지 않는다.",
        "실제 승인 전후 데이터가 축적되면 대리 라벨을 폐기하고 실제 피드백 Target으로 재학습한다.",
        "새 데이터로 평가할 때 동일 그룹·동일 문장 파생본의 Train/Test 누수를 차단한다.",
    ):
        add_bullet(doc, item)

    add_heading(doc, "9. 한계 및 향후 개선", 1)
    for item in (
        "세 원천 파일 총 1,250행 중 중복 제거 후 1,200개의 합성 상담만 후보로 사용하였다.",
        "학습 데이터는 150건, Test Set은 30건으로 작다.",
        "confidence와 needs_review가 실제 관측값이 아니다.",
        "실제 F2 sLLM 오류 분포 및 사용자의 검토 행동과 다를 수 있다.",
        "본 결과는 소규모 합성 Test Set 결과이며 실서비스 성능을 의미하지 않는다.",
        "향후 실제 사용자 수락·수정·거절 데이터와 시간 기반 평가셋으로 재검증해야 한다.",
        "딥러닝은 이번 PoC 범위에서 수행하지 않았다.",
    ):
        add_bullet(doc, item)

    add_heading(doc, "10. 모델 Artifact", 1)
    add_table(
        doc,
        ["파일", "설명"],
        [
            ["field_proposal_review_risk_model.joblib", "최종 전처리·분류 Pipeline"],
            ["model_metadata.json", "Feature·데이터 해시·선정 사유·라이브러리 버전"],
            ["metrics.json", "모델별 실제 평가 지표와 혼동행렬"],
        ],
        [9.0, 7.2],
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output))


def main() -> None:
    args = parse_args()
    poc_root = args.poc_root.resolve()
    metrics = load_json(poc_root / "reports/metrics.json")
    metadata = load_json(poc_root / "artifacts/model_metadata.json")
    inventory = load_json(poc_root / "data/source_inventory.json")
    eda = load_json(poc_root / "reports/eda_summary.json")
    comparison = load_comparison(poc_root / "reports/model_comparison.csv")

    documents_dir = poc_root / "documents"
    detailed_output = documents_dir / "[데이터 전처리] 머신러닝_딥러닝 학습 결과서_30기_3팀.docx"
    model_output = documents_dir / "[데이터 전처리] 학습한 ML_DL 모델_30기_3팀.docx"

    create_training_result_document(
        args.training_template.resolve(),
        detailed_output,
        poc_root,
        metrics,
        metadata,
        inventory,
        eda,
        comparison,
        args.submission_date,
    )
    create_model_document(
        args.model_template.resolve(),
        model_output,
        poc_root,
        metrics,
        metadata,
        inventory,
        comparison,
        args.submission_date,
    )
    print(detailed_output)
    print(model_output)


if __name__ == "__main__":
    main()
