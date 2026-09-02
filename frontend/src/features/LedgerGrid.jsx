import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { Button, EmptyState, EmptyStateActions, EmptyStateBody, EmptyStateFooter, Spinner } from "@patternfly/react-core";
import { ExclamationCircleIcon, SearchIcon } from "@patternfly/react-icons";
import { AllCommunityModule, ModuleRegistry, themeQuartz } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { PROTOTYPE_ASSUMPTIONS } from "../config/prototypeAssumptions.js";
import { DEAL_TYPE_CHOICES, applyDealType, dealTypeValue } from "./ledger/model/dealType.ts";
import "./LedgerGrid.css";

ModuleRegistry.registerModules([AllCommunityModule]);

/**
 * 목록에서 고르면서 직접 입력도 되는 편집기.
 *
 * `agSelectCellEditor`는 목록 밖의 값을 넣을 수 없고, `<datalist>`는 입력한 글자로 목록을 걸러낸다.
 * 둘 다 장부에 맞지 않는다. 분류에 없는 현장 표기가 늘 섞이므로 자유 입력을 막지 않되,
 * 지금 칸에 무엇이 적혀 있든 고를 수 있는 값 전체를 항상 보여준다.
 */
export const ComboCellEditor = forwardRef(function ComboCellEditor(
  { value, values = [], colDef, onValueChange, stopEditing, api },
  ref,
) {
  const [current, setCurrent] = useState(value ?? "");
  const inputRef = useRef(null);
  // AG Grid 36은 onValueChange로 값을 받는다. getValue는 예전 방식과의 호환용으로 함께 둔다.
  useImperativeHandle(ref, () => ({ getValue: () => current }), [current]);
  useEffect(() => { inputRef.current?.focus(); inputRef.current?.select(); }, []);

  const update = (next) => { setCurrent(next); onValueChange?.(next); };
  const finish = (cancel = false) => {
    // AG Grid 36 React 편집기는 stopEditing을 항상 넘겨주지 않는다. api를 먼저 쓴다.
    if (typeof api?.stopEditing === "function") api.stopEditing(cancel);
    else stopEditing?.(cancel);
  };
  const choose = (option) => { update(option); finish(); };

  return <div className="ledger-grid__combo">
    <input
      ref={inputRef}
      className="ledger-grid__cell-editor"
      value={current}
      aria-label={`${colDef?.headerName || "값"} 선택 또는 입력`}
      onChange={(event) => update(event.target.value)}
    />
    <ul className="ledger-grid__combo-list" aria-label={`${colDef?.headerName || "값"} 선택지`}>
      {values.length === 0 && <li className="ledger-grid__combo-empty">입력한 값이 다음부터 이 목록에 쌓입니다.</li>}
      {values.map((option) => <li key={option}>
        <button
          type="button"
          className={option === current ? "is-current" : ""}
          // mousedown으로 처리한다. click까지 기다리면 그 전에 포커스가 빠져 편집이 닫힌다.
          onMouseDown={(event) => { event.preventDefault(); choose(option); }}
        >{option}</button>
      </li>)}
    </ul>
  </div>;
});

/**
 * 달력에서 고르는 날짜 편집기. 저장 형식은 그리드 전체가 쓰는 YYYY-MM-DD를 유지한다.
 *
 * 칸을 열 때 `showPicker()`로 달력을 자동으로 띄우지 않는다. 달력이 뜨면서 포커스가 옮겨가
 * 편집이 닫혔다 다시 열리고, 그 과정에서 방금 고른 날짜가 버려진다. 달력은 입력칸 오른쪽의
 * 달력 아이콘으로 연다.
 */
export const DateCellEditor = forwardRef(function DateCellEditor(
  { value, colDef, onValueChange, stopEditing, api },
  ref,
) {
  const [current, setCurrent] = useState(isIsoDate(value) ? value : "");
  const inputRef = useRef(null);
  useImperativeHandle(ref, () => ({ getValue: () => current }), [current]);
  useEffect(() => { inputRef.current?.focus(); }, []);
  return <input
    ref={inputRef}
    type="date"
    className="ledger-grid__cell-editor ledger-grid__cell-editor--date"
    value={current}
    aria-label={`${colDef?.headerName || "날짜"} 선택`}
    onChange={(event) => { setCurrent(event.target.value); onValueChange?.(event.target.value); }}
    // 날짜 입력은 Enter를 자체 처리해 그리드까지 전달하지 않는다. 여기서 직접 끝낸다.
    onKeyDown={(event) => {
      if (event.key !== "Enter" && event.key !== "Escape") return;
      // 그리드까지 올려보내면 편집을 끝낸 직후 같은 칸을 다시 열어 값이 되돌아간다.
      event.preventDefault();
      event.stopPropagation();
      const cancel = event.key === "Escape";
      if (typeof api?.stopEditing === "function") api.stopEditing(cancel);
      else stopEditing?.(cancel);
    }}
  />;
});

/**
 * 날짜와 자유 문구를 함께 받는 편집기.
 *
 * 명도 같은 칸은 실제로 "즉시", "협의"처럼 적기도 하고 날짜를 적기도 한다.
 * 한쪽 형식만 강요하면 나머지를 적을 곳이 없어지므로 둘 다 받는다.
 */
export const TextOrDateCellEditor = forwardRef(function TextOrDateCellEditor(
  { value, colDef, onValueChange, stopEditing, api },
  ref,
) {
  const [current, setCurrent] = useState(value ?? "");
  const inputRef = useRef(null);
  useImperativeHandle(ref, () => ({ getValue: () => current }), [current]);
  useEffect(() => { inputRef.current?.focus(); inputRef.current?.select(); }, []);

  const update = (next) => { setCurrent(next); onValueChange?.(next); };
  const finish = (cancel = false) => {
    if (typeof api?.stopEditing === "function") api.stopEditing(cancel);
    else stopEditing?.(cancel);
  };

  return <div className="ledger-grid__text-or-date">
    <input
      ref={inputRef}
      className="ledger-grid__cell-editor"
      value={current}
      aria-label={`${colDef?.headerName || "값"} 입력`}
      placeholder="즉시·협의 또는 날짜"
      onChange={(event) => update(event.target.value)}
    />
    <label className="ledger-grid__text-or-date-picker">
      <span className="pf-v6-screen-reader">{`${colDef?.headerName || "값"} 날짜로 선택`}</span>
      <input
        type="date"
        value={isIsoDate(current) ? current : ""}
        onChange={(event) => { update(event.target.value); finish(); }}
        onKeyDown={(event) => {
          if (event.key !== "Enter" && event.key !== "Escape") return;
          event.preventDefault();
          event.stopPropagation();
          finish(event.key === "Escape");
        }}
      />
    </label>
  </div>;
});

/** 목록에서 고르는 칸임을 알리는 화살표. 한 번 클릭하면 편집이 시작된다. */
function DropdownCell({ value }) {
  return <span className="ledger-grid__affordance-cell">
    <span className="ledger-grid__affordance-value">{value}</span>
    <span className="ledger-grid__affordance-mark" aria-hidden="true">▾</span>
  </span>;
}

/** 달력에서 고르는 칸임을 알리는 표시. 이모지는 글꼴에 따라 제각각이라 도형으로 그린다. */
function DateCell({ value }) {
  return <span className="ledger-grid__affordance-cell">
    <span className="ledger-grid__affordance-value">{value}</span>
    <svg className="ledger-grid__affordance-mark" viewBox="0 0 16 16" width="12" height="12" aria-hidden="true" focusable="false">
      <rect x="1.5" y="3" width="13" height="11.5" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <path d="M1.5 6.5h13M5 1.5v3M11 1.5v3" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  </span>;
}

function isIsoDate(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

export const COLUMN_PRESETS = [
  { value: "basic", label: "기본 (12)", description: "식별·상태·담당 중심" },
  { value: "lease", label: "임대차", description: "현 임대차·만기 중심" },
  { value: "listing", label: "매물화", description: "매물 조건·금액 중심" },
  { value: "all", label: "전체 (30)", description: "전체 필드 표시" },
];
const GRID_VIEW_STATES = new Set(["normal", "loading", "filtered-empty", "load-error", "offline"]);
const ALL_FILTER_VALUES = new Set(["", "전체", "all", "ALL"]);
const basicFields = ["complex", "area", "building", "unit", "saveState", "type", "direction", "householdState", "listingType", "salePrice", "expiry", "assignee"];
const leaseFields = [...basicFields, "deposit", "rent", "loan", "tenant", "tenantPhone", "clearance", "lastContact"];
const listingFields = [...basicFields, "clearance", "salePrice", "leaseDeposit", "rentCondition", "receivedAt", "facilityState", "memo"];

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
/**
 * 행의 상태 칸.
 *
 * 다른 열과 성격이 다르다. 세대의 속성이 아니라 이 행이 지금 어떤 상태인지를 나타낸다.
 * 그래서 편집할 수 없고, 가로 스크롤과 무관하게 늘 보이도록 왼쪽에 고정한다.
 * 서버 저장 중·실패·충돌도 여기서 함께 알린다. 그러지 않으면 저장이 실패해도 화면에 흔적이 없다.
 */
function StatusCell({ value, data }) {
  const sync = data?.sync;
  if (sync?.status === "saving") {
    return <span className="ledger-grid__status ledger-grid__status--sync-saving">저장 중</span>;
  }
  if (sync?.status === "failed") {
    return <span className="ledger-grid__status ledger-grid__status--sync-failed" title={sync.reason}>저장 실패</span>;
  }
  if (sync?.status === "conflict") {
    return <span className="ledger-grid__status ledger-grid__status--sync-conflict" title={sync.reason}>충돌</span>;
  }
  if (!value) return null;
  const classKey = String(value).replace(/\s+/g, "-");
  return <span className={`ledger-grid__status ledger-grid__status--save-${classKey}`}>{value}</span>;
}
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

/** 목록 선택 칸 공통 설정. 목록이 셀 밖으로 나갈 수 있어 팝업으로 띄운다. */
const dropdownColumn = (values) => ({
  cellEditor: ComboCellEditor,
  cellEditorParams: { values },
  cellEditorPopup: true,
  cellEditorPopupPosition: "under",
  cellRenderer: DropdownCell,
  cellClass: "ledger-grid__affordance",
});

/**
 * 선택지를 미리 정하지 않고, 그 열에 이미 들어 있는 값을 모아 보여주는 칸.
 *
 * 분류를 우리가 정할 수 없는 열에 쓴다. 사용자가 쓰는 표기를 그대로 받고, 한 번 입력한 값은
 * 다음부터 목록에서 고를 수 있다. 목록은 편집을 시작할 때 현재 불러온 행들에서 다시 모은다.
 */
const learnedDropdownColumn = (field) => ({
  cellEditor: ComboCellEditor,
  cellEditorParams: (params) => ({ values: valuesInColumn(params.api, field) }),
  cellEditorPopup: true,
  cellEditorPopupPosition: "under",
  cellRenderer: DropdownCell,
  cellClass: "ledger-grid__affordance",
});

function valuesInColumn(api, field) {
  const seen = new Set();
  api?.forEachNode?.((node) => {
    const value = String(node?.data?.[field] ?? "").trim();
    if (value !== "") seen.add(value);
  });
  return [...seen].sort((left, right) => left.localeCompare(right, "ko"));
}

const dateColumn = {
  cellEditor: DateCellEditor,
  cellRenderer: DateCell,
  cellClass: "ledger-grid__affordance",
};
/**
 * 매물장 열 정의. AI 처리 상태는 장부 목록에 포함하지 않는다.
 *
 * 매매·전세·월세 3열은 '거래유형' 1열로 합쳤다. 서버는 세 값을 독립 boolean으로 갖고 있어
 * 한 매물이 둘 이상일 수 있으므로, 표시는 '매매·전세'처럼 이어 붙이고 편집도 그 형태를 받는다.
 */
const PROPERTY_COLUMNS = [
  // 행의 상태는 값이 아니라 행 전체에 붙는 표시다. 값 열 사이에 끼우지 않고 맨 앞에 둔다.
  column("상태", "saveState", { width: 96, minWidth: 96, editable: false, cellRenderer: StatusCell, pinned: "left", lockPinned: true, lockPosition: "left", suppressMovable: true, filter: false, sortable: false }),
  column("단지", "complex", { pinned: "left", lockPinned: true, lockPosition: "left", suppressMovable: true, minWidth: 160, width: 160, editable: false }), column("평형", "area", { width: 78 }), column("동", "building", { pinned: "left", lockPinned: true, lockPosition: "left", suppressMovable: true, comparator: numericStringComparator, sort: "asc", sortIndex: 0, width: 64 }), column("호", "unit", { pinned: "left", lockPinned: true, lockPosition: "left", suppressMovable: true, editable: false, comparator: numericStringComparator, sort: "asc", sortIndex: 1, width: 64 }), column("타입", "type", { width: 96, ...learnedDropdownColumn("type") }), column("방향", "direction", { width: 96, ...dropdownColumn(["남향", "남동향", "남서향", "동향", "서향", "북향"]) }), column("최근 통화일", "lastContact", { width: 124, editable: false, ...dateColumn }), column("현상태", "householdState", { width: 112, ...dropdownColumn(["일반", "매물화", "거래진행", "거래완료"]) }), column("보증(현)", "deposit", { width: 104 }), column("차임(현)", "rent", { width: 96 }), column("융자", "loan", { width: 96 }), column("만기일", "expiry", { width: 124, ...dateColumn }), column("접수일", "receivedAt", { width: 124, ...dateColumn }), column("거래유형", "listingType", { width: 120, valueGetter: ({ data }) => dealTypeValue(data), valueSetter: ({ data, newValue }) => applyDealType(data, newValue), ...dropdownColumn(DEAL_TYPE_CHOICES) }), column("명도", "clearance", { width: 132, cellEditor: TextOrDateCellEditor, cellEditorPopup: true, cellEditorPopupPosition: "under", cellRenderer: DateCell, cellClass: "ledger-grid__affordance" }), column("매매가", "salePrice", { width: 112 }), column("전세보증금", "leaseDeposit", { width: 120 }), column("보증금 / 차임", "rentCondition", { width: 136 }), column("스펙", "spec", { width: 112 }), column("붙박이", "builtIn", { width: 112 }), column("시설상태", "facilityState", { width: 120, ...dropdownColumn(["양호", "보통", "수리 필요", "올수리", "부분수리"]) }), column("상담 로그", "log", { width: 260, tooltipField: "log" }), column("임대인", "owner", { width: 136 }), column("임대인 전화", "ownerPhone", { width: 136 }), column("임대부동산", "brokerage", { width: 120 }), column("임차인", "tenant", { width: 112 }), column("임차인 전화", "tenantPhone", { width: 136 }), column("담당", "assignee", { width: 88, editable: false }), column("비고", "memo", { width: 168, tooltipField: "memo" }),
];
/*
 * 「최근 통화일」과 「담당」은 편집하지 않는다.
 *
 * 통화일은 상담 로그가 갱신하는 파생값이고(요구사항 13.1), 담당은 서버가 이름이 아니라
 * `assigned_user_id`를 받는데 직원 목록 API가 아직 없다. 둘 다 여기서 고쳐도 서버로 갈 수
 * 없으므로, 편집을 열어 두면 고친 값이 저장된 줄 알고 그대로 사라진다.
 * 담당 배정은 세대 상세의 「나에게 배정」에서 한다.
 */
/** 값 목록 필터 대상. 저장 상태는 세대의 속성이 아니고 상단 필터가 이미 다루므로 뺀다. */
const VALUE_FILTER_COLUMNS = PROPERTY_COLUMNS.filter(({ field }) => field !== "saveState");

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
    <div className="ledger-grid__controls" aria-label="그리드 값 필터"><label className="ledger-grid__value-filter-select"><span>값 목록 필터</span><select value={valueFilterField} onChange={(event) => setValueFilterField(event.target.value)}>{VALUE_FILTER_COLUMNS.map(({ field, headerName }) => <option key={field} value={field}>{headerName}</option>)}</select></label><ValueFilter rows={valueFilterRows} field={valueFilterField} accepted={currentAccepted} onChange={(next) => setValueFilters((current) => ({ ...current, [valueFilterField]: next }))} />{Object.keys(valueFilters).length > 0 && <Button variant="link" onClick={() => setValueFilters({})}>값 필터 해제</Button>}</div>
    <div className="ledger-grid__ag-grid"><AgGridReact theme={ledgerGridTheme} ariaLabel="매물장 세대 그리드" localeText={{ ariaHeaderSelection: "전체 행 선택 열", ariaRowSelectAll: "Space 키로 현재 필터 결과 전체 선택 전환", ariaRowToggleSelection: "Space 키로 행 선택 전환", ariaRowSelect: "Space 키로 이 행 선택", ariaRowDeselect: "Space 키로 이 행 선택 해제", ariaRowSelectionDisabled: "이 행은 선택할 수 없음", ariaToggleCellValue: "Space 키로 셀 값 전환" }} onGridReady={handleGridReady} rowData={rowData} columnDefs={columnDefs} defaultColDef={defaultColDef} getRowId={({ data }) => String(data.id)} rowHeight={40} headerHeight={40} animateRows={false} ensureDomOrder enableCellTextSelection enterNavigatesVertically enterNavigatesVerticallyAfterEdit singleClickEdit stopEditingWhenCellsLoseFocus undoRedoCellEditing undoRedoCellEditingLimit={PROTOTYPE_ASSUMPTIONS.grid.undoLimit} rowSelection={rowSelection} selectionColumnDef={selectionColumnDef} onCellValueChanged={handleCellValueChanged} onSelectionChanged={handleSelectionChanged} onFirstDataRendered={handleFirstDataRendered} activeOverlay={overlayState ? GridStateOverlay : undefined} activeOverlayParams={overlayState ? { state: overlayState, onRetry, onClearFilters: handleClearFilters, onAddRow } : undefined} suppressOverlays={["noRows"]} tooltipShowDelay={300} /></div>
  </section>;
}
export default LedgerGrid;
