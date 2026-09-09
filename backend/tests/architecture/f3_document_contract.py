"""Compare stable contract values while allowing explanatory prose to evolve."""

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REFERENCES = REPOSITORY_ROOT / ".agents" / "skills" / "project-wiki" / "references"


def contract_rows(document: str) -> dict[str, list[str]]:
    return {
        cells[0].strip("`"): cells[1:]
        for line in document.splitlines()
        if line.strip().startswith("|")
        for cells in [[cell.strip() for cell in line.strip().strip("|").split("|")]]
        if len(cells) >= 2
    }


def implemented_api_states() -> set[str]:
    rows = contract_rows((REFERENCES / "contracts/api-f3.md").read_text(encoding="utf-8"))
    return {
        identifier
        for identifier, cells in rows.items()
        if re.fullmatch(r"[A-Z_]+", identifier) and cells[-1] == "구현됨"
    }
