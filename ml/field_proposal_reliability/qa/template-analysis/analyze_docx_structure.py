#!/usr/bin/env python3
"""Read-only OOXML audit for the two retained DOCX references.

The script intentionally uses only Python's standard library so the audit can
still run when the bundled Windows document runtime cannot execute under WSL.
It never writes to, re-zips, or otherwise mutates the source DOCX.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import Counter
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import xml.etree.ElementTree as ET


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}
W = "{" + NS["w"] + "}"
R = "{" + NS["r"] + "}"


def local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def clean_attrs(element: ET.Element | None) -> dict[str, str]:
    if element is None:
        return {}
    return {local_name(key): value for key, value in element.attrib.items()}


def child_value(element: ET.Element | None, path: str) -> str | None:
    if element is None:
        return None
    child = element.find(path, NS)
    if child is None:
        return None
    return child.get(W + "val")


def paragraph_text(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.findall(".//w:t", NS)).strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def part_policy(name: str) -> str:
    if name == "word/document.xml":
        return "editable_content_slots"
    if name in {"word/styles.xml", "word/numbering.xml"}:
        return "preserve_design_authority; extend only for new semantic roles"
    if name.startswith("word/media/"):
        return "preserve_design_asset"
    if name.startswith("word/header") or name.startswith("word/footer"):
        return "preserve_page_furniture"
    if name.startswith("customXML/") or name.startswith("word/fonts/"):
        return "preserve_opaque_part"
    if name.endswith(".rels") or name == "[Content_Types].xml":
        return "preserve_relationship_contract; update only with linked edits"
    return "preserve_package_infrastructure"


def parse_png_dimensions(data: bytes) -> dict[str, int] | None:
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", data[16:24])
        return {"width_px": width, "height_px": height}
    return None


def xml_or_none(archive: ZipFile, name: str) -> ET.Element | None:
    try:
        return ET.fromstring(archive.read(name))
    except KeyError:
        return None


def paragraph_properties(paragraph: ET.Element) -> dict:
    ppr = paragraph.find("w:pPr", NS)
    num_pr = ppr.find("w:numPr", NS) if ppr is not None else None
    spacing = ppr.find("w:spacing", NS) if ppr is not None else None
    indent = ppr.find("w:ind", NS) if ppr is not None else None
    tabs = []
    if ppr is not None:
        tabs = [clean_attrs(tab) for tab in ppr.findall("./w:tabs/w:tab", NS)]
    return {
        "style_id": child_value(ppr, "w:pStyle"),
        "num_id": child_value(num_pr, "w:numId"),
        "ilvl": child_value(num_pr, "w:ilvl"),
        "alignment": child_value(ppr, "w:jc"),
        "spacing": clean_attrs(spacing),
        "indent": clean_attrs(indent),
        "tabs": tabs,
        "keep_next": ppr is not None and ppr.find("w:keepNext", NS) is not None,
        "keep_lines": ppr is not None and ppr.find("w:keepLines", NS) is not None,
        "page_break_before": ppr is not None and ppr.find("w:pageBreakBefore", NS) is not None,
        "borders": clean_attrs(ppr.find("./w:pBdr/w:bottom", NS)) if ppr is not None else {},
    }


def run_format_signature(run: ET.Element) -> dict:
    rpr = run.find("w:rPr", NS)
    fonts = rpr.find("w:rFonts", NS) if rpr is not None else None
    result = {
        "fonts": clean_attrs(fonts),
        "size_half_points": child_value(rpr, "w:sz"),
        "bold": child_value(rpr, "w:b"),
        "italic": child_value(rpr, "w:i"),
        "underline": child_value(rpr, "w:u"),
        "color": child_value(rpr, "w:color"),
        "highlight": child_value(rpr, "w:highlight"),
    }
    return {key: value for key, value in result.items() if value not in (None, {})}


def run_format_histogram(root: ET.Element) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for run in root.findall(".//w:r", NS):
        signature = run_format_signature(run)
        if signature:
            counts[json.dumps(signature, ensure_ascii=False, sort_keys=True)] += 1
        else:
            counts["inherited"] += 1
    return dict(counts.most_common())


def extract_styles(root: ET.Element | None) -> dict:
    if root is None:
        return {}
    defaults = root.find("w:docDefaults", NS)
    default_rpr = defaults.find("./w:rPrDefault/w:rPr", NS) if defaults is not None else None
    default_ppr = defaults.find("./w:pPrDefault/w:pPr", NS) if defaults is not None else None
    styles = []
    for style in root.findall("w:style", NS):
        ppr = style.find("w:pPr", NS)
        rpr = style.find("w:rPr", NS)
        styles.append(
            {
                "style_id": style.get(W + "styleId"),
                "type": style.get(W + "type"),
                "default": style.get(W + "default"),
                "name": child_value(style, "w:name"),
                "based_on": child_value(style, "w:basedOn"),
                "next": child_value(style, "w:next"),
                "paragraph": {
                    "spacing": clean_attrs(ppr.find("w:spacing", NS)) if ppr is not None else {},
                    "indent": clean_attrs(ppr.find("w:ind", NS)) if ppr is not None else {},
                    "alignment": child_value(ppr, "w:jc"),
                    "keep_next": ppr is not None and ppr.find("w:keepNext", NS) is not None,
                    "keep_lines": ppr is not None and ppr.find("w:keepLines", NS) is not None,
                },
                "run": {
                    "fonts": clean_attrs(rpr.find("w:rFonts", NS)) if rpr is not None else {},
                    "size_half_points": child_value(rpr, "w:sz"),
                    "bold": child_value(rpr, "w:b"),
                    "italic": child_value(rpr, "w:i"),
                    "color": child_value(rpr, "w:color"),
                },
                "table_cell_margins": {
                    local_name(node.tag): clean_attrs(node)
                    for node in style.findall("./w:tblPr/w:tblCellMar/*", NS)
                },
            }
        )
    return {
        "document_defaults": {
            "run": {
                "fonts": clean_attrs(default_rpr.find("w:rFonts", NS)) if default_rpr is not None else {},
                "size_half_points": child_value(default_rpr, "w:sz"),
                "bold": child_value(default_rpr, "w:b"),
                "language": child_value(default_rpr, "w:lang"),
            },
            "paragraph": {
                "spacing": clean_attrs(default_ppr.find("w:spacing", NS)) if default_ppr is not None else {}
            },
        },
        "styles": styles,
    }


def extract_numbering(root: ET.Element | None) -> dict:
    if root is None:
        return {}
    abstract: dict[str, list[dict]] = {}
    for item in root.findall("w:abstractNum", NS):
        aid = item.get(W + "abstractNumId")
        levels = []
        for level in item.findall("w:lvl", NS):
            ppr = level.find("w:pPr", NS)
            rpr = level.find("w:rPr", NS)
            levels.append(
                {
                    "level": level.get(W + "ilvl"),
                    "start": child_value(level, "w:start"),
                    "format": child_value(level, "w:numFmt"),
                    "text": child_value(level, "w:lvlText"),
                    "justification": child_value(level, "w:lvlJc"),
                    "indent": clean_attrs(ppr.find("w:ind", NS)) if ppr is not None else {},
                    "fonts": clean_attrs(rpr.find("w:rFonts", NS)) if rpr is not None else {},
                }
            )
        abstract[aid or ""] = levels
    instances = []
    for item in root.findall("w:num", NS):
        instances.append(
            {
                "num_id": item.get(W + "numId"),
                "abstract_num_id": child_value(item, "w:abstractNumId"),
            }
        )
    return {"abstract_definitions": abstract, "instances": instances}


def extract_sections(document: ET.Element) -> list[dict]:
    sections = []
    for index, section in enumerate(document.findall(".//w:sectPr", NS), start=1):
        refs = []
        for ref in list(section.findall("w:headerReference", NS)) + list(section.findall("w:footerReference", NS)):
            refs.append(
                {
                    "kind": local_name(ref.tag).replace("Reference", ""),
                    "type": ref.get(W + "type"),
                    "relationship_id": ref.get(R + "id"),
                }
            )
        page_size = section.find("w:pgSz", NS)
        margins = section.find("w:pgMar", NS)
        section_type = section.find("w:type", NS)
        page_num = section.find("w:pgNumType", NS)
        cols = section.find("w:cols", NS)
        sections.append(
            {
                "index": index,
                "type": section_type.get(W + "val") if section_type is not None else "continuous/default",
                "page_size_twips": clean_attrs(page_size),
                "margins_twips": clean_attrs(margins),
                "columns": clean_attrs(cols),
                "page_numbering": clean_attrs(page_num),
                "different_first_page": section.find("w:titlePg", NS) is not None,
                "references": refs,
            }
        )
    return sections


def extract_relationships(root: ET.Element | None) -> list[dict]:
    if root is None:
        return []
    return [dict(item.attrib) for item in root]


def rel_target_map(relationships: list[dict]) -> dict[str, str]:
    return {item.get("Id", ""): item.get("Target", "") for item in relationships}


def extract_table(table: ET.Element, locator: str, page: int) -> dict:
    table_pr = table.find("w:tblPr", NS)
    grid = [node.get(W + "w") for node in table.findall("./w:tblGrid/w:gridCol", NS)]
    rows = table.findall("./w:tr", NS)
    column_count = max((len(row.findall("./w:tc", NS)) for row in rows), default=0)
    fills: Counter[str] = Counter()
    widths: Counter[str] = Counter()
    borders: Counter[str] = Counter()
    vertical_alignments: Counter[str] = Counter()
    merged_cells = []
    for row_index, row in enumerate(rows):
        for cell_index, cell in enumerate(row.findall("./w:tc", NS)):
            tcpr = cell.find("w:tcPr", NS)
            if tcpr is None:
                continue
            shade = tcpr.find("w:shd", NS)
            if shade is not None and shade.get(W + "fill"):
                fills[shade.get(W + "fill")] += 1
            width = tcpr.find("w:tcW", NS)
            if width is not None:
                widths[json.dumps(clean_attrs(width), sort_keys=True)] += 1
            valign = tcpr.find("w:vAlign", NS)
            if valign is not None:
                vertical_alignments[valign.get(W + "val", "")] += 1
            for border in tcpr.findall("./w:tcBorders/*", NS):
                borders[local_name(border.tag) + ":" + json.dumps(clean_attrs(border), sort_keys=True)] += 1
            grid_span = tcpr.find("w:gridSpan", NS)
            vmerge = tcpr.find("w:vMerge", NS)
            if grid_span is not None or vmerge is not None:
                merged_cells.append(
                    {
                        "row": row_index,
                        "cell": cell_index,
                        "grid_span": clean_attrs(grid_span),
                        "vertical_merge": clean_attrs(vmerge),
                    }
                )
    first_row = []
    if rows:
        first_row = [paragraph_text(cell)[:160] for cell in rows[0].findall("./w:tc", NS)]
    cell_margins = {}
    if table_pr is not None:
        for margin in table_pr.findall("./w:tblCellMar/*", NS):
            cell_margins[local_name(margin.tag)] = clean_attrs(margin)
    return {
        "locator": locator,
        "page_by_explicit_breaks": page,
        "rows": len(rows),
        "max_columns": column_count,
        "style_id": child_value(table_pr, "w:tblStyle"),
        "table_width": clean_attrs(table_pr.find("w:tblW", NS)) if table_pr is not None else {},
        "table_indent": clean_attrs(table_pr.find("w:tblInd", NS)) if table_pr is not None else {},
        "alignment": child_value(table_pr, "w:jc"),
        "layout": clean_attrs(table_pr.find("w:tblLayout", NS)) if table_pr is not None else {},
        "grid_widths_twips": grid,
        "cell_width_signatures": dict(widths),
        "cell_margins": cell_margins,
        "fill_histogram": dict(fills),
        "border_histogram": dict(borders),
        "vertical_alignment_histogram": dict(vertical_alignments),
        "repeat_header_rows": [
            index for index, row in enumerate(rows) if row.find("./w:trPr/w:tblHeader", NS) is not None
        ],
        "cant_split_rows": [
            index for index, row in enumerate(rows) if row.find("./w:trPr/w:cantSplit", NS) is not None
        ],
        "merged_cells": merged_cells,
        "first_row_labels": first_row,
        "character_count": len(paragraph_text(table)),
    }


def extract_body(document: ET.Element) -> dict:
    body = document.find("w:body", NS)
    if body is None:
        return {}
    page = 1
    paragraphs = []
    tables = []
    outline = []
    page_break_locations = []
    for body_index, child in enumerate(body):
        breaks = [node for node in child.findall(".//w:br", NS) if node.get(W + "type") == "page"]
        if child.tag == W + "p":
            text = paragraph_text(child)
            props = paragraph_properties(child)
            if text:
                entry = {
                    "locator": f"word/document.xml/body/p[{body_index}]",
                    "page_by_explicit_breaks": page,
                    "text": text,
                    "properties": props,
                    "run_formats": [
                        {"text": paragraph_text(run), "format": run_format_signature(run)}
                        for run in child.findall("w:r", NS)
                        if paragraph_text(run)
                    ],
                }
                paragraphs.append(entry)
                if props["style_id"] and props["style_id"].lower().startswith("heading"):
                    outline.append({"kind": "heading", "page": page, "locator": entry["locator"], "label": text})
                elif props["ilvl"] == "0":
                    outline.append({"kind": "numbered_level_0", "page": page, "locator": entry["locator"], "label": text})
        elif child.tag == W + "tbl":
            table = extract_table(child, f"word/document.xml/body/tbl[{body_index}]", page)
            tables.append(table)
            labels = table["first_row_labels"]
            if labels:
                outline.append(
                    {
                        "kind": "table",
                        "page": page,
                        "locator": table["locator"],
                        "label": " | ".join(labels),
                    }
                )
        elif child.tag == W + "sdt":
            for nested_index, nested_table in enumerate(child.findall(".//w:tbl", NS)):
                locator = f"word/document.xml/body/sdt[{body_index}]/tbl[{nested_index}]"
                table = extract_table(nested_table, locator, page)
                tables.append(table)
                labels = table["first_row_labels"]
                if labels:
                    outline.append(
                        {
                            "kind": "content_control_table",
                            "page": page,
                            "locator": locator,
                            "label": " | ".join(labels),
                        }
                    )
        if breaks:
            page_break_locations.append({"body_index": body_index, "count": len(breaks), "page_before": page})
            page += len(breaks)
    return {
        "body_child_count": len(body),
        "nonempty_body_paragraphs": len(paragraphs),
        "tables": tables,
        "table_count": len(tables),
        "paragraphs": paragraphs,
        "outline": outline,
        "explicit_page_break_count": sum(item["count"] for item in page_break_locations),
        "page_break_locations": page_break_locations,
        "page_count_inferred_from_explicit_breaks": page,
    }


def extract_content_controls(document: ET.Element) -> list[dict]:
    controls = []
    for index, control in enumerate(document.findall(".//w:sdt", NS), start=1):
        properties = control.find("w:sdtPr", NS)
        content = control.find("w:sdtContent", NS)
        controls.append(
            {
                "index": index,
                "stable_locator": f"word/document.xml//w:sdt[{index}]",
                "tag": child_value(properties, "w:tag"),
                "alias": child_value(properties, "w:alias"),
                "id": child_value(properties, "w:id"),
                "lock": child_value(properties, "w:lock"),
                "text_preview": paragraph_text(content)[:240] if content is not None else "",
                "paragraph_count": len(content.findall(".//w:p", NS)) if content is not None else 0,
                "table_count": len(content.findall(".//w:tbl", NS)) if content is not None else 0,
            }
        )
    return controls


def extract_header_footer(archive: ZipFile, names: list[str]) -> list[dict]:
    output = []
    for name in sorted(names):
        root = xml_or_none(archive, name)
        output.append(
            {
                "part": name,
                "text": paragraph_text(root) if root is not None else "",
                "paragraph_count": len(root.findall(".//w:p", NS)) if root is not None else 0,
                "field_instruction_count": len(root.findall(".//w:instrText", NS)) if root is not None else 0,
                "drawing_count": len(root.findall(".//w:drawing", NS)) if root is not None else 0,
            }
        )
    return output


def extract_drawings(document: ET.Element, relationships: dict[str, str], archive: ZipFile) -> list[dict]:
    drawings = []
    for index, drawing in enumerate(document.findall(".//w:drawing", NS), start=1):
        position = drawing.find("wp:anchor", NS)
        mode = "anchor" if position is not None else "inline"
        if position is None:
            position = drawing.find("wp:inline", NS)
        extent = position.find("wp:extent", NS) if position is not None else None
        doc_pr = position.find("wp:docPr", NS) if position is not None else None
        embeds = [node.get(R + "embed") for node in drawing.findall(".//a:blip", NS) if node.get(R + "embed")]
        targets = [relationships.get(embed or "", "") for embed in embeds]
        image_metadata = []
        for target in targets:
            part = str(PurePosixPath("word") / target)
            try:
                data = archive.read(part)
            except KeyError:
                continue
            image_metadata.append(
                {
                    "part": part,
                    "sha256": sha256_bytes(data),
                    "byte_size": len(data),
                    "dimensions": parse_png_dimensions(data),
                }
            )
        horizontal = position.find("wp:positionH", NS) if position is not None else None
        vertical = position.find("wp:positionV", NS) if position is not None else None
        drawings.append(
            {
                "index": index,
                "mode": mode,
                "anchor_attributes": clean_attrs(position) if mode == "anchor" else {},
                "horizontal_position": {
                    "relative_from": horizontal.get("relativeFrom") if horizontal is not None else None,
                    "offset_emu": horizontal.findtext("wp:posOffset", default=None, namespaces=NS) if horizontal is not None else None,
                },
                "vertical_position": {
                    "relative_from": vertical.get("relativeFrom") if vertical is not None else None,
                    "offset_emu": vertical.findtext("wp:posOffset", default=None, namespaces=NS) if vertical is not None else None,
                },
                "extent_emu": clean_attrs(extent),
                "extent_inches": {
                    "width": round(int(extent.get("cx")) / 914400, 4),
                    "height": round(int(extent.get("cy")) / 914400, 4),
                }
                if extent is not None
                else {},
                "doc_properties": clean_attrs(doc_pr),
                "relationship_ids": embeds,
                "targets": targets,
                "images": image_metadata,
            }
        )
    return drawings


def audit(source: Path) -> dict:
    with ZipFile(source) as archive:
        names = archive.namelist()
        document = ET.fromstring(archive.read("word/document.xml"))
        styles = xml_or_none(archive, "word/styles.xml")
        numbering = xml_or_none(archive, "word/numbering.xml")
        settings = xml_or_none(archive, "word/settings.xml")
        document_relationships = extract_relationships(xml_or_none(archive, "word/_rels/document.xml.rels"))
        rel_targets = rel_target_map(document_relationships)
        package = []
        for info in archive.infolist():
            data = archive.read(info.filename)
            package.append(
                {
                    "path": info.filename,
                    "uncompressed_bytes": info.file_size,
                    "compressed_bytes": info.compress_size,
                    "sha256": sha256_bytes(data),
                    "policy": part_policy(info.filename),
                }
            )
        header_footer_names = [
            name for name in names if name.startswith("word/header") or name.startswith("word/footer")
        ]
        body = extract_body(document)
        all_xml = b"\n".join(
            archive.read(name) for name in names if name.endswith(".xml") and not name.startswith("word/fonts/")
        )
        return {
            "audit_version": "1.0",
            "source": {
                "path": str(source.resolve()),
                "byte_size": source.stat().st_size,
                "sha256": sha256_file(source),
            },
            "render_status": {
                "status": "not_rendered",
                "reason": "Bundled Windows Python cannot execute under WSL; Linux Python lacks pdf2image/Pillow; soffice/libreoffice and pdftoppm are unavailable.",
                "page_count_status": "inferred from explicit page breaks; not visually verified",
            },
            "package": package,
            "relationships": document_relationships,
            "page_system": {
                "sections": extract_sections(document),
                "even_and_odd_headers_enabled": settings is not None and settings.find("w:evenAndOddHeaders", NS) is not None,
                "body_explicit_page_break_count": body["explicit_page_break_count"],
                "page_count_inferred_from_explicit_breaks": body["page_count_inferred_from_explicit_breaks"],
            },
            "styles": extract_styles(styles),
            "numbering": extract_numbering(numbering),
            "body": body,
            "content_controls": extract_content_controls(document),
            "headers_and_footers": extract_header_footer(archive, header_footer_names),
            "drawings": extract_drawings(document, rel_targets, archive),
            "direct_run_format_histogram": run_format_histogram(document),
            "feature_counts": {
                "drawings": len(document.findall(".//w:drawing", NS)),
                "tables_total_including_nested": len(document.findall(".//w:tbl", NS)),
                "hyperlinks": len(document.findall(".//w:hyperlink", NS)),
                "fields": len(document.findall(".//w:instrText", NS)),
                "bookmarks": len(document.findall(".//w:bookmarkStart", NS)),
                "content_controls": len(document.findall(".//w:sdt", NS)),
                "tracked_insertions": len(document.findall(".//w:ins", NS)),
                "tracked_deletions": len(document.findall(".//w:del", NS)),
                "comments_parts": sum(1 for name in names if "comments" in name.lower()),
                "footnotes_part": int("word/footnotes.xml" in names),
                "endnotes_part": int("word/endnotes.xml" in names),
                "embedded_fonts": sum(1 for name in names if name.startswith("word/fonts/")),
                "custom_xml_parts": sum(1 for name in names if name.startswith("customXML/") and name.endswith(".xml")),
                "alt_text_tokens": all_xml.count(b"descr=") + all_xml.count(b" title="),
            },
            "structural_qa": {
                "zip_test": archive.testzip() is None,
                "required_parts_present": all(
                    name in names
                    for name in ("[Content_Types].xml", "word/document.xml", "word/styles.xml", "word/_rels/document.xml.rels")
                ),
                "relationship_targets_checked": [
                    {
                        "relationship_id": rel.get("Id"),
                        "target": rel.get("Target"),
                        "external": rel.get("TargetMode") == "External",
                    }
                    for rel in document_relationships
                ],
                "duplicate_docpr_ids": [
                    item
                    for item, count in Counter(
                        node.get("id") for node in document.findall(".//wp:docPr", NS) if node.get("id")
                    ).items()
                    if count > 1
                ],
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
