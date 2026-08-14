import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  Button,
  EmptyState,
  EmptyStateActions,
  EmptyStateBody,
  EmptyStateFooter,
  Spinner,
} from "@patternfly/react-core";
import {
  ExclamationCircleIcon,
  SearchIcon,
} from "@patternfly/react-icons";
import {
  AllCommunityModule,
  ModuleRegistry,
  themeQuartz,
} from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { PROTOTYPE_ASSUMPTIONS } from "../config/prototypeAssumptions.js";
import "./LedgerGrid.css";

ModuleRegistry.registerModules([AllCommunityModule]);

const GRID_VIEW_STATES = new Set([
  "normal",
  "loading",
  "filtered-empty",
  "load-error",
  "offline",
]);

const ALL_FILTER_VALUES = new Set(["", "전체", "all", "ALL"]);

const ledgerGridTheme = themeQuartz.withParams({
  accentColor: "#0066cc",
  backgroundColor: "#ffffff",
  borderColor: "#d2d2d2",
  cellHorizontalPadding: 12,
  columnBorder: { color: "#e7e7e7" },
  fontFamily: ["Noto Sans KR", "NanumBarunGothic", "Noto Sans", "Arial", "sans-serif"],
  fontSize: 13,
  foregroundColor: "#151515",
  headerBackgroundColor: "#f5f5f5",
  headerFontSize: 12,
  headerFontWeight: 600,
  headerTextColor: "#3c3f42",
  oddRowBackgroundColor: "#fafafa",
  rowBorder: { color: "#e7e7e7" },
  rowHeight: 40,
  rowHoverColor: "#eef6fc",
  selectedRowBackgroundColor: "#e7f1fa",
  spacing: 4,
  wrapperBorder: { color: "#b8bbbe" },
  wrapperBorderRadius: 0,
});

function normalizeText(value) {
  return String(value ?? "").trim().toLocaleLowerCase("ko-KR");
}

function compactText(value) {
  return normalizeText(value).replace(/[\s-]/g, "");
}

function matchesChoice(value, filterValue) {
  if (filterValue == null || ALL_FILTER_VALUES.has(String(filterValue))) {
    return true;
  }

  const acceptedValues = Array.isArray(filterValue) ? filterValue : [filterValue];
  if (acceptedValues.length === 0) return true;

  const normalizedValue = normalizeText(value);
  return acceptedValues.some((candidate) => normalizeText(candidate) === normalizedValue);
}

function matchesSearch(row, query) {
  const normalizedQuery = normalizeText(query);
  if (!normalizedQuery) return true;

  const haystack = Object.values(row ?? {}).join(" ");
  return (
    normalizeText(haystack).includes(normalizedQuery) ||
    compactText(haystack).includes(compactText(normalizedQuery))
  );
}

function numericStringComparator(left, right) {
  const leftNumber = Number.parseInt(String(left ?? "").replace(/\D/g, ""), 10);
  const rightNumber = Number.parseInt(String(right ?? "").replace(/\D/g, ""), 10);

  if (Number.isNaN(leftNumber) || Number.isNaN(rightNumber)) {
    return String(left ?? "").localeCompare(String(right ?? ""), "ko-KR", {
      numeric: true,
    });
  }

  return leftNumber - rightNumber;
}

function isImeNavigationEvent(params) {
  const event = params?.event;
  return Boolean(event?.isComposing && (event.key === "Enter" || event.key === "Tab"));
}

function StatusCell({ value, kind }) {
  if (!value) return null;

  const classKey = String(value).replace(/\s+/g, "-");
  return (
    <span className={`ledger-grid__status ledger-grid__status--${kind}-${classKey}`}>
      {value}
    </span>
  );
}

function DetailLinkCell({ value, data, onOpenDetail, field }) {
  if (!value) return null;

  const detailLabel = `${data?.complex ?? ""} ${data?.building ?? ""}동 ${
    data?.unit ?? ""
  }호 상세 열기`.trim();

  const handleOpen = (event) => {
    event.stopPropagation();
    if (typeof onOpenDetail === "function") onOpenDetail(data);
  };

  return (
    <Button
      type="button"
      variant="link"
      isInline
      isAriaDisabled={typeof onOpenDetail !== "function"}
      className="ledger-grid__detail-link"
      aria-label={detailLabel}
      data-detail-field={field}
      onClick={handleOpen}
    >
      {value}
    </Button>
  );
}

function GridStateOverlay({ state, onRetry, onClearFilters, onAddRow }) {
  if (state === "loading") {
    return (
      <div className="ledger-grid__overlay ledger-grid__overlay--loading" role="status">
        <Spinner size="xl" aria-label="매물장 불러오는 중" />
        <strong>매물장을 불러오고 있습니다</strong>
        <span>열과 필터 위치는 그대로 유지됩니다.</span>
      </div>
    );
  }

  if (state === "load-error") {
    return (
      <div className="ledger-grid__overlay" role="alert">
        <EmptyState
          variant="sm"
          status="danger"
          icon={ExclamationCircleIcon}
          titleText="매물장을 불러오지 못했습니다"
          headingLevel="h3"
        >
          <EmptyStateBody>
            기존 입력은 변경하지 않았습니다. 같은 화면에서 다시 불러올 수 있습니다.
          </EmptyStateBody>
          <EmptyStateFooter>
            <EmptyStateActions>
              <Button variant="primary" onClick={onRetry}>다시 시도</Button>
            </EmptyStateActions>
          </EmptyStateFooter>
        </EmptyState>
      </div>
    );
  }

  if (state === "dataset-empty") {
    return (
      <div className="ledger-grid__overlay">
        <EmptyState
          variant="sm"
          icon={SearchIcon}
          titleText="등록된 세대가 없습니다"
          headingLevel="h3"
        >
          <EmptyStateBody>행 추가 또는 단지 세대 일괄 생성으로 시작할 수 있습니다.</EmptyStateBody>
          <EmptyStateFooter>
            <EmptyStateActions>
              <Button variant="primary" onClick={onAddRow}>행 추가</Button>
            </EmptyStateActions>
          </EmptyStateFooter>
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="ledger-grid__overlay">
      <EmptyState
        variant="sm"
        icon={SearchIcon}
        titleText="조건에 맞는 세대가 없습니다"
        headingLevel="h3"
      >
        <EmptyStateBody>
          검색어를 지우거나 단지·저장 상태·AI 처리 상태 필터를 완화해 주세요.
        </EmptyStateBody>
        <EmptyStateFooter>
          <EmptyStateActions>
            <Button variant="primary" onClick={onClearFilters}>모든 필터 해제</Button>
          </EmptyStateActions>
        </EmptyStateFooter>
      </EmptyState>
    </div>
  );
}

export function LedgerGrid({
  rows = [],
  onRowsChange,
  onOpenDetail,
  onSelectionChange,
  viewState = "normal",
  searchQuery = "",
  complexFilter = "전체",
  saveFilter = "전체",
  aiFilter = "전체",
  onRetry,
  onClearFilters,
  onAddRow,
  readOnly = false,
  selectedRowIds = [],
  selectionResetToken = 0,
}) {
  const gridApiRef = useRef(null);
  const safeRows = Array.isArray(rows) ? rows : [];
  const normalizedViewState = GRID_VIEW_STATES.has(viewState) ? viewState : "normal";
  const suppressRows =
    normalizedViewState === "filtered-empty" || normalizedViewState === "load-error";

  const rowData = useMemo(() => {
    if (suppressRows) return [];

    return safeRows
      .filter(
        (row) =>
          matchesSearch(row, searchQuery) &&
          matchesChoice(row.complex, complexFilter) &&
          matchesChoice(row.saveState, saveFilter) &&
          matchesChoice(row.aiState, aiFilter),
      )
      .map((row) => ({ ...row }));
  }, [safeRows, searchQuery, complexFilter, saveFilter, aiFilter, suppressRows]);

  const overlayState = useMemo(() => {
    if (
      normalizedViewState === "loading" ||
      normalizedViewState === "filtered-empty" ||
      normalizedViewState === "load-error"
    ) {
      return normalizedViewState;
    }

    if (safeRows.length === 0) return "dataset-empty";
    if (rowData.length === 0) return "filtered-empty";
    return undefined;
  }, [normalizedViewState, rowData.length, safeRows.length]);

  const defaultColDef = useMemo(
    () => ({
      editable: () => !readOnly,
      enableCellChangeFlash: true,
      filter: "agTextColumnFilter",
      minWidth: 72,
      resizable: true,
      sortable: true,
      suppressKeyboardEvent: isImeNavigationEvent,
      suppressMovable: false,
    }),
    [readOnly],
  );

  const selectionColumnDef = useMemo(
    () => ({
      headerName: "선택",
      pinned: "left",
      lockPinned: true,
      lockPosition: "left",
      maxWidth: 44,
      minWidth: 44,
      resizable: false,
      sortable: false,
      suppressHeaderMenuButton: true,
      suppressMovable: true,
      width: 44,
    }),
    [],
  );

  const rowSelection = useMemo(
    () => ({
      mode: "multiRow",
      checkboxes: true,
      headerCheckbox: true,
      checkboxLocation: "selectionColumn",
      enableClickSelection: false,
      selectAll: "filtered",
    }),
    [],
  );

  const detailCellRendererParams = useMemo(
    () => ({ onOpenDetail }),
    [onOpenDetail],
  );

  const columnDefs = useMemo(
    () => [
      {
        headerName: "단지",
        field: "complex",
        pinned: "left",
        lockPinned: true,
        lockPosition: "left",
        suppressMovable: true,
        editable: false,
        minWidth: 160,
        width: 160,
        cellRenderer: DetailLinkCell,
        cellRendererParams: { ...detailCellRendererParams, field: "complex" },
      },
      {
        headerName: "동",
        field: "building",
        pinned: "left",
        lockPinned: true,
        lockPosition: "left",
        suppressMovable: true,
        comparator: numericStringComparator,
        sort: "asc",
        sortIndex: 0,
        minWidth: 64,
        width: 64,
      },
      {
        headerName: "호",
        field: "unit",
        pinned: "left",
        lockPinned: true,
        lockPosition: "left",
        suppressMovable: true,
        editable: false,
        comparator: numericStringComparator,
        sort: "asc",
        sortIndex: 1,
        minWidth: 64,
        width: 64,
        cellRenderer: DetailLinkCell,
        cellRendererParams: { ...detailCellRendererParams, field: "unit" },
      },
      {
        headerName: "저장 상태",
        field: "saveState",
        editable: false,
        width: 112,
        cellRenderer: (params) => <StatusCell {...params} kind="save" />,
      },
      {
        headerName: "AI 처리 상태",
        field: "aiState",
        editable: false,
        width: 112,
        cellRenderer: (params) => <StatusCell {...params} kind="ai" />,
      },
      { headerName: "평형", field: "area", width: 72 },
      {
        headerName: "현매물",
        field: "listingType",
        width: 96,
        cellEditor: "agSelectCellEditor",
        cellEditorParams: { values: ["", "매매", "전세", "월세"] },
      },
      { headerName: "금액", field: "price", width: 112 },
      { headerName: "만기일", field: "expiry", width: 112 },
      { headerName: "임대인", field: "owner", width: 136 },
      { headerName: "상담 로그", field: "log", width: 260, tooltipField: "log" },
      { headerName: "담당", field: "assignee", width: 88 },
      {
        headerName: "세대 상태",
        field: "householdState",
        width: 104,
        cellEditor: "agSelectCellEditor",
        cellEditorParams: { values: ["일반", "매물화", "거래진행", "거래완료"] },
      },
      { headerName: "보증금", field: "deposit", width: 104 },
      { headerName: "차임", field: "rent", width: 96 },
      { headerName: "임차인", field: "tenant", width: 112 },
      { headerName: "연락처", field: "phone", width: 136 },
      {
        headerName: "방향",
        field: "direction",
        width: 88,
        cellEditor: "agSelectCellEditor",
        cellEditorParams: { values: ["남향", "남동향", "남서향", "동향"] },
      },
      { headerName: "층", field: "floor", width: 72 },
      { headerName: "방", field: "rooms", width: 64, filter: "agNumberColumnFilter" },
      { headerName: "욕실", field: "baths", width: 64, filter: "agNumberColumnFilter" },
      { headerName: "최근 통화일", field: "lastContact", width: 112 },
      { headerName: "입력 출처", field: "source", width: 96, editable: false },
      { headerName: "개인정보 동의", field: "consent", width: 120 },
      { headerName: "비고", field: "memo", width: 168, tooltipField: "memo" },
      { headerName: "등록일", field: "createdAt", width: 112, editable: false },
      { headerName: "수정일", field: "updatedAt", width: 112, editable: false },
      { headerName: "등록자", field: "createdBy", width: 88, editable: false },
      { headerName: "수정자", field: "updatedBy", width: 88, editable: false },
      { headerName: "주차", field: "parking", width: 72 },
      { headerName: "입주", field: "moveIn", width: 88 },
      { headerName: "세무", field: "tax", width: 96 },
      { headerName: "레코드 ID", field: "id", width: 112, editable: false },
    ],
    [detailCellRendererParams],
  );

  const handleCellValueChanged = useCallback(
    ({ data, newValue, oldValue }) => {
      if (readOnly || !data || Object.is(newValue, oldValue)) return;

      const nextData = {
        ...data,
        saveState:
          data.complex?.trim() && data.building?.trim() && data.unit?.trim() && data.duplicateCheck
            ? data.aiState === "분석 완료" || data.aiState === "검토 필요"
              ? "검토 필요"
              : "저장 완료"
            : "작성 중",
      };
      const nextRows = safeRows.map((row) =>
        String(row.id) === String(data.id) ? { ...row, ...nextData } : row,
      );
      if (typeof onRowsChange === "function") onRowsChange(nextRows);
    },
    [onRowsChange, readOnly, safeRows],
  );

  const handleSelectionChanged = useCallback(
    ({ api }) => {
      if (typeof onSelectionChange === "function") {
        onSelectionChange(api.getSelectedRows());
      }
    },
    [onSelectionChange],
  );

  const handleGridReady = useCallback(({ api }) => {
    gridApiRef.current = api;
    api.setGridAriaProperty("label", "매물장 세대 그리드");
  }, []);

  useEffect(() => {
    gridApiRef.current?.deselectAll();
  }, [selectionResetToken]);

  const handleFirstDataRendered = useCallback(({ api }) => {
    const selectedIds = new Set(selectedRowIds.map(String));
    if (selectedIds.size === 0) return;
    const nodes = [];
    api.forEachNode((node) => {
      if (node.data?.id && selectedIds.has(String(node.data.id))) nodes.push(node);
    });
    if (nodes.length > 0) api.setNodesSelected({ nodes, newValue: true });
  }, [selectedRowIds]);

  return (
    <section
      id="ledger-grid-panel"
      role="tabpanel"
      aria-labelledby="ledger-tab-0"
      className={`ledger-grid ledger-grid--${normalizedViewState}${
        readOnly ? " ledger-grid--read-only" : ""
      }`}
      aria-label="매물장 세대 그리드"
      aria-busy={normalizedViewState === "loading"}
      aria-readonly={readOnly}
      data-screen-id="F1-PG-010"
      data-requirement-ids="F1-GR-01~47, F1-SR-01~08, F1-TR-01~03, F2-LIST-01~04, F2-SAVE-02"
    >
      <div className="ledger-grid__ag-grid">
        <AgGridReact
          theme={ledgerGridTheme}
          ariaLabel="매물장 세대 그리드"
          localeText={{
            ariaHeaderSelection: "전체 행 선택 열",
            ariaRowSelectAll: "Space 키로 현재 필터 결과 전체 선택 전환",
            ariaRowToggleSelection: "Space 키로 행 선택 전환",
            ariaRowSelect: "Space 키로 이 행 선택",
            ariaRowDeselect: "Space 키로 이 행 선택 해제",
            ariaRowSelectionDisabled: "이 행은 선택할 수 없음",
            ariaToggleCellValue: "Space 키로 셀 값 전환",
          }}
          onGridReady={handleGridReady}
          rowData={rowData}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          getRowId={({ data }) => String(data.id)}
          rowHeight={40}
          headerHeight={40}
          animateRows={false}
          ensureDomOrder
          enableCellTextSelection
          enterNavigatesVertically
          enterNavigatesVerticallyAfterEdit
          singleClickEdit={false}
          stopEditingWhenCellsLoseFocus
          undoRedoCellEditing
          undoRedoCellEditingLimit={PROTOTYPE_ASSUMPTIONS.grid.undoLimit}
          rowSelection={rowSelection}
          selectionColumnDef={selectionColumnDef}
          onCellValueChanged={handleCellValueChanged}
          onSelectionChanged={handleSelectionChanged}
          onFirstDataRendered={handleFirstDataRendered}
          activeOverlay={overlayState ? GridStateOverlay : undefined}
          activeOverlayParams={overlayState ? { state: overlayState, onRetry, onClearFilters, onAddRow } : undefined}
          suppressOverlays={["noRows"]}
          tooltipShowDelay={300}
        />
      </div>
    </section>
  );
}

export default LedgerGrid;
