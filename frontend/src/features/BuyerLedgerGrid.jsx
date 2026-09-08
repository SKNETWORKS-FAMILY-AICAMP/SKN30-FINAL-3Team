import { useEffect, useMemo, useRef } from "react";
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
  // 서버는 `assigned_user_id`를 받고 직원 목록 API가 아직 없다. 여기서 고친 이름은 저장되지 못한다.
  { headerName: "담당자", field: "assignee", width: 96, editable: false }, { headerName: "바탕색", field: "background", width: 88 },
  { headerName: "만기일", field: "expiry", width: 112 }, { headerName: "분류", field: "classification", width: 100 }, { headerName: "비고", field: "memo", width: 168, tooltipField: "memo" },
];

export function BuyerLedgerGrid({ rows = [], onRowsChange, onOpenDetail, onSelectionChange, selectedRowIds = [], selectionResetToken = 0, assigneeFilter = "전체", onAssigneeFilterChange, readOnly = false }) {
  const gridApiRef = useRef(null);
  const filteredRows = useMemo(() => (Array.isArray(rows) ? rows : []).filter((row) => assigneeFilter === "전체" || row.assignee === assigneeFilter), [rows, assigneeFilter]);
  const assignees = useMemo(() => ["전체", ...new Set((rows || []).map((row) => row.assignee).filter(Boolean))], [rows]);
  const defaultColDef = useMemo(() => ({ editable: () => !readOnly, sortable: true, filter: "agTextColumnFilter", resizable: true, minWidth: 72, suppressKeyboardEvent: ({ event }) => Boolean(event?.isComposing && ["Enter", "Tab"].includes(event.key)) }), [readOnly]);
  const selectionColumnDef = useMemo(() => ({ headerName: "선택", pinned: "left", lockPinned: true, lockPosition: "left", maxWidth: 44, minWidth: 44, resizable: false, sortable: false, suppressHeaderMenuButton: true, suppressMovable: true, width: 44 }), []);
  const rowSelection = useMemo(() => ({ mode: "multiRow", checkboxes: true, headerCheckbox: true, checkboxLocation: "selectionColumn", enableClickSelection: false, selectAll: "filtered" }), []);
  const handleChange = ({ data, newValue, oldValue }) => { if (readOnly || Object.is(newValue, oldValue) || !onRowsChange) return; onRowsChange(rows.map((row) => row.id === data.id ? { ...row, ...data, saveState: "임시저장" } : row)); };
  const handleGridReady = ({ api }) => { gridApiRef.current = api; };
  const handleSelectionChanged = ({ api }) => onSelectionChange?.(api.getSelectedRows());
  useEffect(() => { gridApiRef.current?.deselectAll(); }, [selectionResetToken]);
  const handleFirstDataRendered = ({ api }) => {
    const ids = new Set(selectedRowIds.map(String));
    if (ids.size === 0) return;
    const nodes = [];
    api.forEachNode((node) => { if (node.data?.id && ids.has(String(node.data.id))) nodes.push(node); });
    if (nodes.length > 0) api.setNodesSelected({ nodes, newValue: true });
  };
  return <section className="buyer-ledger-grid" data-screen-id="F1-PG-020" data-requirement-ids="F1-DM-01~07, F1-DM-08~16, F1-DM-06" aria-label="구입장 그리드">
    <div className="buyer-ledger-grid__toolbar"><label>담당자 <select value={assigneeFilter} onChange={(event) => onAssigneeFilterChange?.(event.target.value)}>{assignees.map((assignee) => <option key={assignee}>{assignee}</option>)}</select></label><span className="buyer-ledger-grid__count" role="status">{filteredRows.length.toLocaleString()}건</span></div>
    <div className="buyer-ledger-grid__table"><AgGridReact theme={buyerTheme} rowData={filteredRows} columnDefs={columns} defaultColDef={defaultColDef} getRowId={({ data }) => String(data.id)} rowHeight={40} headerHeight={40} ensureDomOrder animateRows={false} rowSelection={rowSelection} selectionColumnDef={selectionColumnDef} onGridReady={handleGridReady} onSelectionChanged={handleSelectionChanged} onFirstDataRendered={handleFirstDataRendered} onCellValueChanged={handleChange} onRowClicked={({ data }) => onOpenDetail?.({ ...data, ledgerType: "buyer", rowKind: "buyer" })} /></div>
  </section>;
}
export default BuyerLedgerGrid;
