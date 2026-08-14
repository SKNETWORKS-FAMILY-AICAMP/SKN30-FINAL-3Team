import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, EmptyState, EmptyStateActions, EmptyStateBody, EmptyStateFooter, Spinner } from "@patternfly/react-core";
import { ExclamationCircleIcon, SearchIcon } from "@patternfly/react-icons";
import { AllCommunityModule, ModuleRegistry, themeQuartz } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { PROTOTYPE_ASSUMPTIONS } from "../config/prototypeAssumptions.js";
import "./LedgerGrid.css";

ModuleRegistry.registerModules([AllCommunityModule]);

export const COLUMN_PRESETS = [
  { value: "basic", label: "기본 (12)", description: "식별·상태·담당 중심" },
  { value: "lease", label: "임대차", description: "현 임대차·만기 중심" },
  { value: "listing", label: "매물화", description: "매물 조건·금액 중심" },
  { value: "all", label: "전체 (33)", description: "전체 필드 표시" },
];
const GRID_VIEW_STATES = new Set(["normal", "loading", "filtered-empty", "load-error", "offline"]);
const ALL_FILTER_VALUES = new Set(["", "전체", "all", "ALL"]);
const basicFields = ["complex", "area", "building", "unit", "saveState", "type", "direction", "householdState", "listingType", "salePrice", "expiry", "assignee"];
const leaseFields = [...basicFields, "deposit", "rent", "loan", "tenant", "tenantPhone", "clearance", "lastContact"];
const listingFields = [...basicFields, "clearance", "saleFlag", "leaseFlag", "monthlyFlag", "salePrice", "leaseDeposit", "rentCondition", "receivedAt", "facilityState", "memo"];

const ledgerGridTheme = themeQuartz.withParams({ accentColor: "var(--color-primary)", backgroundColor: "var(--color-surface)", borderColor: "var(--color-border)", cellHorizontalPadding: 12, columnBorder: { color: "var(--color-border)" }, fontFamily: ["Red Hat Text", "Noto Sans KR", "Apple SD Gothic Neo", "sans-serif"], fontSize: 14, foregroundColor: "var(--color-text)", headerBackgroundColor: "var(--pf-t--global--background--color--secondary--default)", headerFontSize: 14, headerFontWeight: 600, headerTextColor: "var(--color-text)", oddRowBackgroundColor: "var(--pf-t--global--background--color--secondary--default)", rowBorder: { color: "var(--color-border)" }, rowHeight: 40, rowHoverColor: "var(--pf-t--global--background--color--action--hover)", selectedRowBackgroundColor: "var(--pf-t--global--background--color--action--selected)", spacing: 4, wrapperBorder: { color: "var(--color-border)" }, wrapperBorderRadius: 0 });

function normalizeText(value) { return String(value ?? "").trim().toLocaleLowerCase("ko-KR"); }
function compactText(value) { return normalizeText(value).replace(/[\s-]/g, ""); }
function matchesChoice(value, filterValue) {
  if (filterValue == null || ALL_FILTER_VALUES.has(String(filterValue))) return true;
  const values = Array.isArray(filterValue) ? filterValue : [filterValue];
  if (values.length === 0) return true;
  const normalized = normalizeText(value);
  return values.some((candidate) => normalizeText(candidate) === normalized);
}
function matchesSearch(row, query) {
  const normalizedQuery = normalizeText(query);
  if (!normalizedQuery) return true;
  const haystack = Object.values(row ?? {}).join(" ");
  return normalizeText(haystack).includes(normalizedQuery) || compactText(haystack).includes(compactText(normalizedQuery));
}
function matchesValues(value, accepted) { if (!accepted) return true; const key = String(value ?? "").trim() || "__EMPTY__"; return accepted.has(key); }
function numericStringComparator(left, right) {
  const leftNumber = Number.parseInt(String(left ?? "").replace(/\D/g, ""), 10);
  const rightNumber = Number.parseInt(String(right ?? "").replace(/\D/g, ""), 10);
  if (Number.isNaN(leftNumber) || Number.isNaN(rightNumber)) return String(left ?? "").localeCompare(String(right ?? ""), "ko-KR", { numeric: true });
  return leftNumber - rightNumber;
}
function isImeNavigationEvent(params) { const event = params?.event; return Boolean(event?.isComposing && (event.key === "Enter" || event.key === "Tab")); }
function StatusCell({ value }) { if (!value) return null; const classKey = String(value).replace(/\s+/g, "-"); return <span className={`ledger-grid__status ledger-grid__status--save-${classKey}`}>{value}</span>; }
function DetailLinkCell({ value, data, onOpenDetail, field }) {
  if (!value) return null;
  const detailLabel = `${data?.complex ?? ""} ${data?.building ?? ""}동 ${data?.unit ?? ""}호 상세 열기`.trim();
  return <Button type="button" variant="link" isInline isAriaDisabled={typeof onOpenDetail !== "function"} className="ledger-grid__detail-link" aria-label={detailLabel} data-detail-field={field} onClick={(event) => { event.stopPropagation(); if (typeof onOpenDetail === "function") onOpenDetail(data); }}>{value}</Button>;
}
function GridStateOverlay({ state, onRetry, onClearFilters, onAddRow }) {
  if (state === "loading") return <div className="ledger-grid__overlay ledger-grid__overlay--loading" role="status"><Spinner size="xl" aria-label="매물장 불러오는 중" /><strong>매물장을 불러오고 있습니다</strong><span>열과 필터 위치는 그대로 유지됩니다.</span></div>;
  if (state === "load-error") return <div className="ledger-grid__overlay" role="alert"><EmptyState variant="sm" status="danger" icon={ExclamationCircleIcon} titleText="매물장을 불러오지 못했습니다" headingLevel="h3"><EmptyStateBody>기존 입력은 변경하지 않았습니다. 같은 화면에서 다시 불러올 수 있습니다.</EmptyStateBody><EmptyStateFooter><EmptyStateActions><Button variant="primary" onClick={onRetry}>다시 시도</Button></EmptyStateActions></EmptyStateFooter></EmptyState></div>;
  if (state === "dataset-empty") return <div className="ledger-grid__overlay"><EmptyState variant="sm" icon={SearchIcon} titleText="등록된 세대가 없습니다" headingLevel="h3"><EmptyStateBody>행 추가 또는 단지 세대 일괄 생성으로 시작할 수 있습니다.</EmptyStateBody><EmptyStateFooter><EmptyStateActions><Button variant="primary" onClick={onAddRow}>행 추가</Button></EmptyStateActions></EmptyStateFooter></EmptyState></div>;
  return <div className="ledger-grid__overlay"><EmptyState variant="sm" icon={SearchIcon} titleText="조건에 맞는 세대가 없습니다" headingLevel="h3"><EmptyStateBody>검색어 또는 값 필터를 완화해 주세요.</EmptyStateBody><EmptyStateFooter><EmptyStateActions><Button variant="primary" onClick={onClearFilters}>모든 필터 해제</Button></EmptyStateActions></EmptyStateFooter></EmptyState></div>;
}
const column = (headerName, field, extra = {}) => ({ headerName, field, minWidth: 84, width: 112, ...extra });
/** 13.1의 매물장 33필드. AI 처리 상태는 장부 목록에 포함하지 않는다. */
const PROPERTY_COLUMNS = [
  column("단지", "complex", { pinned: "left", lockPinned: true, lockPosition: "left", suppressMovable: true, minWidth: 160, width: 160, editable: false }), column("평형", "area", { width: 78 }), column("동", "building", { pinned: "left", lockPinned: true, lockPosition: "left", suppressMovable: true, comparator: numericStringComparator, sort: "asc", sortIndex: 0, width: 64 }), column("호", "unit", { pinned: "left", lockPinned: true, lockPosition: "left", suppressMovable: true, editable: false, comparator: numericStringComparator, sort: "asc", sortIndex: 1, width: 64 }), column("저장 상태", "saveState", { width: 112, editable: false, cellRenderer: StatusCell }), column("타입", "type", { width: 72 }), column("방향", "direction", { width: 88, cellEditor: "agSelectCellEditor", cellEditorParams: { values: ["", "남향", "남동향", "남서향", "동향"] } }), column("최근 통화일", "lastContact", { width: 112 }), column("현상태", "householdState", { width: 104, cellEditor: "agSelectCellEditor", cellEditorParams: { values: ["일반", "매물화", "거래진행", "거래완료"] } }), column("보증(현)", "deposit", { width: 104 }), column("차임(현)", "rent", { width: 96 }), column("융자", "loan", { width: 96 }), column("만기일", "expiry", { width: 112 }), column("접수일", "receivedAt", { width: 112 }), column("현매물", "listingType", { width: 96, cellEditor: "agSelectCellEditor", cellEditorParams: { values: ["", "매매", "전세", "월세"] } }), column("명도", "clearance", { width: 96 }), column("매매", "saleFlag", { width: 72 }), column("전세", "leaseFlag", { width: 72 }), column("월세", "monthlyFlag", { width: 72 }), column("매매가", "salePrice", { width: 112 }), column("전세보증금", "leaseDeposit", { width: 120 }), column("보증금 / 차임", "rentCondition", { width: 136 }), column("스펙", "spec", { width: 112 }), column("붙박이", "builtIn", { width: 112 }), column("시설상태", "facilityState", { width: 112 }), column("상담 로그", "log", { width: 260, tooltipField: "log" }), column("임대인", "owner", { width: 136 }), column("임대인 전화", "ownerPhone", { width: 136 }), column("임대부동산", "brokerage", { width: 120 }), column("임차인", "tenant", { width: 112 }), column("임차인 전화", "tenantPhone", { width: 136 }), column("담당", "assignee", { width: 88 }), column("비고", "memo", { width: 168, tooltipField: "memo" }),
];
function visibleFieldsForPreset(preset) { if (preset === "all") return new Set(PROPERTY_COLUMNS.map(({ field }) => field)); if (preset === "lease") return new Set(leaseFields); if (preset === "listing") return new Set(listingFields); return new Set(basicFields); }

function ValueFilter({ rows, field, onChange, accepted }) {
  const values = useMemo(() => { const counts = new Map(); rows.forEach((row) => { const raw = String(row?.[field] ?? "").trim(); const key = raw || "__EMPTY__"; counts.set(key, (counts.get(key) || 0) + 1); }); return [...counts.entries()].sort(([left], [right]) => left === "__EMPTY__" ? -1 : right === "__EMPTY__" ? 1 : left.localeCompare(right, "ko-KR", { numeric: true })); }, [rows, field]);
  const toggle = (key) => { const next = new Set(accepted || []); if (next.has(key)) next.delete(key); else next.add(key); onChange(next); };
  return <details className="ledger-grid__value-filter"><summary>값 필터 · {values.length}개</summary><div className="ledger-grid__value-filter-menu"><div className="ledger-grid__value-filter-actions"><button type="button" onClick={() => onChange(new Set(values.map(([key]) => key)))}>전체 선택</button><button type="button" onClick={() => onChange(new Set())}>전체 해제</button></div>{values.map(([key, count]) => <label key={key}><input type="checkbox" checked={Boolean(accepted?.has(key))} onChange={() => toggle(key)} /><span>{key === "__EMPTY__" ? "(비어 있음)" : key}</span><small>{count}</small></label>)}</div></details>;
}

export function LedgerGrid({ rows = [], onRowsChange, onOpenDetail, onSelectionChange, viewState = "normal", searchQuery = "", complexFilter = "전체", saveFilter = "전체", onRetry, onClearFilters, onAddRow, readOnly = false, selectedRowIds = [], selectionResetToken = 0, columnPreset = "basic" }) {
  const gridApiRef = useRef(null);
  const [valueFilterField, setValueFilterField] = useState("complex");
  const [valueFilters, setValueFilters] = useState({});
  const safeRows = Array.isArray(rows) ? rows : [];
  const normalizedViewState = GRID_VIEW_STATES.has(viewState) ? viewState : "normal";
  const suppressRows = normalizedViewState === "filtered-empty" || normalizedViewState === "load-error";
  const visibleFields = useMemo(() => visibleFieldsForPreset(columnPreset), [columnPreset]);
  const rowData = useMemo(() => { if (suppressRows) return []; return safeRows.filter((row) => matchesSearch(row, searchQuery) && matchesChoice(row.complex, complexFilter) && matchesChoice(row.saveState, saveFilter) && Object.entries(valueFilters).every(([field, accepted]) => matchesValues(row[field], accepted))).map((row) => ({ ...row })); }, [safeRows, searchQuery, complexFilter, saveFilter, valueFilters, suppressRows]);
  const overlayState = useMemo(() => { if (["loading", "filtered-empty", "load-error"].includes(normalizedViewState)) return normalizedViewState; if (safeRows.length === 0) return "dataset-empty"; if (rowData.length === 0) return "filtered-empty"; return undefined; }, [normalizedViewState, rowData.length, safeRows.length]);
  const defaultColDef = useMemo(() => ({ editable: () => !readOnly, enableCellChangeFlash: true, filter: "agTextColumnFilter", minWidth: 72, resizable: true, sortable: true, suppressKeyboardEvent: isImeNavigationEvent, suppressMovable: false }), [readOnly]);
  const selectionColumnDef = useMemo(() => ({ headerName: "선택", pinned: "left", lockPinned: true, lockPosition: "left", maxWidth: 44, minWidth: 44, resizable: false, sortable: false, suppressHeaderMenuButton: true, suppressMovable: true, width: 44 }), []);
  const rowSelection = useMemo(() => ({ mode: "multiRow", checkboxes: true, headerCheckbox: true, checkboxLocation: "selectionColumn", enableClickSelection: false, selectAll: "filtered" }), []);
  const columnDefs = useMemo(() => PROPERTY_COLUMNS.map((definition) => { const next = { ...definition, hide: !visibleFields.has(definition.field) }; if (definition.field === "complex" || definition.field === "owner") next.cellRenderer = (params) => <DetailLinkCell {...params} onOpenDetail={onOpenDetail} field={definition.field} />; return next; }), [onOpenDetail, visibleFields]);
  const handleCellValueChanged = useCallback(({ data, newValue, oldValue }) => { if (readOnly || !data || Object.is(newValue, oldValue)) return; const nextRows = safeRows.map((row) => String(row.id) === String(data.id) ? { ...row, ...data, saveState: "임시저장" } : row); if (typeof onRowsChange === "function") onRowsChange(nextRows); }, [onRowsChange, readOnly, safeRows]);
  const handleSelectionChanged = useCallback(({ api }) => { if (typeof onSelectionChange === "function") onSelectionChange(api.getSelectedRows()); }, [onSelectionChange]);
  const handleGridReady = useCallback(({ api }) => { gridApiRef.current = api; api.setGridAriaProperty("label", "매물장 세대 그리드"); }, []);
  useEffect(() => { gridApiRef.current?.deselectAll(); }, [selectionResetToken]);
  const handleFirstDataRendered = useCallback(({ api }) => { const ids = new Set(selectedRowIds.map(String)); if (ids.size === 0) return; const nodes = []; api.forEachNode((node) => { if (node.data?.id && ids.has(String(node.data.id))) nodes.push(node); }); if (nodes.length > 0) api.setNodesSelected({ nodes, newValue: true }); }, [selectedRowIds]);
  const valueFilterRows = useMemo(() => safeRows.filter((row) => matchesSearch(row, searchQuery) && matchesChoice(row.complex, complexFilter) && matchesChoice(row.saveState, saveFilter)), [safeRows, searchQuery, complexFilter, saveFilter]);
  const currentAccepted = valueFilters[valueFilterField] || new Set();
  const handleClearFilters = useCallback(() => { setValueFilters({}); onClearFilters?.(); }, [onClearFilters]);
  return <section id="ledger-grid-panel" role="tabpanel" aria-labelledby="ledger-tab-0" className={`ledger-grid ledger-grid--${normalizedViewState}${readOnly ? " ledger-grid--read-only" : ""}`} aria-label="매물장 세대 그리드" aria-busy={normalizedViewState === "loading"} aria-readonly={readOnly} data-screen-id="F1-PG-010" data-requirement-ids="F1-GR-01~45, F1-SR-01~08, F1-TR-01~03, F2-LIST-01~04">
    <div className="ledger-grid__controls" aria-label="그리드 값 필터"><label className="ledger-grid__value-filter-select"><span>값 목록 필터</span><select value={valueFilterField} onChange={(event) => setValueFilterField(event.target.value)}>{PROPERTY_COLUMNS.map(({ field, headerName }) => <option key={field} value={field}>{headerName}</option>)}</select></label><ValueFilter rows={valueFilterRows} field={valueFilterField} accepted={currentAccepted} onChange={(next) => setValueFilters((current) => ({ ...current, [valueFilterField]: next }))} />{Object.keys(valueFilters).length > 0 && <Button variant="link" onClick={() => setValueFilters({})}>값 필터 해제</Button>}</div>
    <div className="ledger-grid__ag-grid"><AgGridReact theme={ledgerGridTheme} ariaLabel="매물장 세대 그리드" localeText={{ ariaHeaderSelection: "전체 행 선택 열", ariaRowSelectAll: "Space 키로 현재 필터 결과 전체 선택 전환", ariaRowToggleSelection: "Space 키로 행 선택 전환", ariaRowSelect: "Space 키로 이 행 선택", ariaRowDeselect: "Space 키로 이 행 선택 해제", ariaRowSelectionDisabled: "이 행은 선택할 수 없음", ariaToggleCellValue: "Space 키로 셀 값 전환" }} onGridReady={handleGridReady} rowData={rowData} columnDefs={columnDefs} defaultColDef={defaultColDef} getRowId={({ data }) => String(data.id)} rowHeight={40} headerHeight={40} animateRows={false} ensureDomOrder enableCellTextSelection enterNavigatesVertically enterNavigatesVerticallyAfterEdit singleClickEdit={false} stopEditingWhenCellsLoseFocus undoRedoCellEditing undoRedoCellEditingLimit={PROTOTYPE_ASSUMPTIONS.grid.undoLimit} rowSelection={rowSelection} selectionColumnDef={selectionColumnDef} onCellValueChanged={handleCellValueChanged} onSelectionChanged={handleSelectionChanged} onFirstDataRendered={handleFirstDataRendered} activeOverlay={overlayState ? GridStateOverlay : undefined} activeOverlayParams={overlayState ? { state: overlayState, onRetry, onClearFilters: handleClearFilters, onAddRow } : undefined} suppressOverlays={["noRows"]} tooltipShowDelay={300} /></div>
  </section>;
}
export default LedgerGrid;
