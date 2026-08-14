import { useMemo } from "react";
import { Button } from "@patternfly/react-core";
import { AllCommunityModule, ModuleRegistry, themeQuartz } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import "./BuyerLedgerGrid.css";

ModuleRegistry.registerModules([AllCommunityModule]);

const buyerTheme = themeQuartz.withParams({ accentColor: "var(--color-primary)", backgroundColor: "var(--color-surface)", borderColor: "var(--color-border)", foregroundColor: "var(--color-text)", headerBackgroundColor: "var(--pf-t--global--background--color--secondary--default)", rowHeight: 40, fontSize: 14 });
const columns = [
  { headerName: "날짜", field: "date", width: 112 }, { headerName: "평형", field: "area", width: 100 },
  { headerName: "구분", field: "category", width: 88, cellEditor: "agSelectCellEditor", cellEditorParams: { values: ["매수", "매도", "전세", "월세"] } },
  { headerName: "금액", field: "budget", width: 128 }, { headerName: "단지", field: "complex", width: 156 },
  { headerName: "구입자", field: "buyer", width: 132 }, { headerName: "전화번호", field: "phone", width: 136 },
  { headerName: "부동산", field: "brokerage", width: 112 }, { headerName: "이사일", field: "moveDate", width: 112 },
  { headerName: "내용", field: "content", width: 230, tooltipField: "content" }, { headerName: "진행단계", field: "stage", width: 116 },
  { headerName: "완료여부", field: "completion", width: 96, cellEditor: "agSelectCellEditor", cellEditorParams: { values: ["진행", "완료"] } },
  { headerName: "담당자", field: "assignee", width: 96 }, { headerName: "바탕색", field: "background", width: 88 },
  { headerName: "만기일", field: "expiry", width: 112 }, { headerName: "분류", field: "classification", width: 100 }, { headerName: "비고", field: "memo", width: 168, tooltipField: "memo" },
];

const withinThreeMonths = (date) => {
  if (!date) return false;
  const parsed = new Date(date);
  const now = new Date("2026-08-14T00:00:00");
  const end = new Date(now);
  end.setMonth(end.getMonth() + 3);
  return parsed >= now && parsed <= end;
};

export function BuyerLedgerGrid({ rows = [], onRowsChange, onOpenDetail, onAddRow, assigneeFilter = "전체", onAssigneeFilterChange, periodMode = "all", onPeriodModeChange, readOnly = false }) {
  const filteredRows = useMemo(() => (Array.isArray(rows) ? rows : []).filter((row) => (periodMode === "three-months" ? withinThreeMonths(row.expiry || row.moveDate) : true)).filter((row) => assigneeFilter === "전체" || row.assignee === assigneeFilter), [rows, periodMode, assigneeFilter]);
  const assignees = useMemo(() => ["전체", ...new Set((rows || []).map((row) => row.assignee).filter(Boolean))], [rows]);
  const defaultColDef = useMemo(() => ({ editable: () => !readOnly, sortable: true, filter: "agTextColumnFilter", resizable: true, minWidth: 72, suppressKeyboardEvent: ({ event }) => Boolean(event?.isComposing && ["Enter", "Tab"].includes(event.key)) }), [readOnly]);
  const handleChange = ({ data, newValue, oldValue }) => { if (readOnly || Object.is(newValue, oldValue) || !onRowsChange) return; onRowsChange(rows.map((row) => row.id === data.id ? { ...row, ...data, saveState: "임시저장" } : row)); };
  return <section className="buyer-ledger-grid" data-screen-id="F1-PG-020" data-requirement-ids="F1-DM-01~07, F1-DM-08~16" aria-label="구입장 그리드">
    <div className="buyer-ledger-grid__toolbar"><div className="buyer-ledger-grid__period" role="group" aria-label="구입장 기간 필터"><Button variant={periodMode === "three-months" ? "primary" : "secondary"} onClick={() => onPeriodModeChange?.("three-months")}>3개월 이내만 보기</Button><Button variant={periodMode === "all" ? "primary" : "secondary"} onClick={() => onPeriodModeChange?.("all")}>모두 보기</Button></div><label>담당자 <select value={assigneeFilter} onChange={(event) => onAssigneeFilterChange?.(event.target.value)}>{assignees.map((assignee) => <option key={assignee}>{assignee}</option>)}</select></label><span className="buyer-ledger-grid__count" role="status">{filteredRows.length.toLocaleString()}건</span><Button variant="primary" onClick={onAddRow}>행 추가</Button></div>
    <div className="buyer-ledger-grid__table"><AgGridReact theme={buyerTheme} rowData={filteredRows} columnDefs={columns} defaultColDef={defaultColDef} getRowId={({ data }) => String(data.id)} rowHeight={40} headerHeight={40} ensureDomOrder animateRows={false} onCellValueChanged={handleChange} onRowClicked={({ data }) => onOpenDetail?.({ ...data, ledgerType: "buyer", rowKind: "buyer" })} /></div>
  </section>;
}
export default BuyerLedgerGrid;
