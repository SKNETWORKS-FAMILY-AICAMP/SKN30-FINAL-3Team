import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Button, Checkbox, Dropdown, DropdownItem, DropdownList, Label, MenuToggle,
  Modal, ModalBody, ModalFooter, ModalHeader,
  Spinner, TextInput, Toolbar, ToolbarContent, ToolbarGroup, ToolbarItem,
} from "@patternfly/react-core";
import {
  AddCircleOIcon, BellIcon, ColumnsIcon, EllipsisVIcon,
  ExclamationTriangleIcon, FilterIcon, HelpIcon, MicrophoneIcon, OutlinedCommentsIcon, SearchIcon,
  UserIcon,
} from "@patternfly/react-icons";
import { createBuyerRows, createLedgerRows, emptyBuyerRow, emptyDraftRow, initialComplexes } from "./data/ledgerData.js";
import { PROTOTYPE_ASSUMPTIONS } from "./config/prototypeAssumptions.js";
import { COLUMN_PRESETS, LedgerGrid } from "./features/LedgerGrid.jsx";
import { BuyerLedgerGrid } from "./features/BuyerLedgerGrid.jsx";
import DetailWorkspace from "./features/DetailWorkspace.jsx";
import BuyerDetailWorkspace from "./features/BuyerDetailWorkspace.jsx";
import { CrossMatchPanel } from "./features/CrossMatchPanel.jsx";
import { CampaignWorkspace } from "./features/CampaignWorkspace.jsx";
import { useAuth } from "./context/AuthContext.jsx";

const compactNavItems = ["배치 캠페인"];

const viewStates = [
  ["normal", "기본 화면"], ["loading", "불러오는 중"], ["filtered-empty", "결과 없음"],
  ["load-error", "불러오기 오류"], ["offline", "오프라인"],
];

function normalizeComposer(payload) {
  const rawRecipients = payload?.recipients || (payload?.phone
    ? [{ id: payload.candidate?.id || payload.phone, title: payload.title, phone: payload.phone }]
    : []);
  const inputCount = rawRecipients.length;
  const normalized = rawRecipients.map((recipient) => {
    const consentAllowed = !recipient.consent || recipient.consent === "동의" || recipient.consent === "O";
    const exclusionReason = !recipient.phone
      ? "연락처 없음"
      : !consentAllowed
        ? "연락 동의 X 또는 확인 필요"
        : "";
    return { ...recipient, excluded: Boolean(exclusionReason), lockedExcluded: Boolean(exclusionReason), exclusionReason };
  });
  const consentExcludedCount = normalized.filter((recipient) => recipient.phone && recipient.lockedExcluded).length;
  const uniqueByPhone = new Map();
  const recipients = normalized.map((recipient) => {
    if (recipient.excluded) return recipient;
    const key = String(recipient.phone).replace(/\D/g, "");
    if (uniqueByPhone.has(key)) return { ...recipient, excluded: true, lockedExcluded: true, exclusionReason: "중복 연락처" };
    uniqueByPhone.set(key, recipient);
    return recipient;
  });
  return {
    ...payload,
    source: payload?.source || "F3 교차 판정",
    recipients,
    inputCount,
    noPhoneCount: normalized.filter((recipient) => !recipient.phone).length,
    consentExcludedCount,
    duplicateCount: recipients.filter((recipient) => recipient.exclusionReason === "중복 연락처").length,
    draft: payload?.draft || "",
  };
}

export function AppShell() {
  const { user, isAuthenticated, loginDev, logout, loading: authLoading } = useAuth();
  const [rows, setRows] = useState(() => createLedgerRows(6));
  const [buyerRows, setBuyerRows] = useState(() => createBuyerRows(4));
  const [complexOptions, setComplexOptions] = useState(() => initialComplexes.map((name) => ({ name, address: "" })));
  const [activeNav, setActiveNav] = useState("매물장");
  const [searchQuery, setSearchQuery] = useState("");
  const [complexFilter, setComplexFilter] = useState("래미안 원베일리");
  const [saveFilter, setSaveFilter] = useState("전체");
  const [columnPreset, setColumnPreset] = useState("all");
  const [buyerPeriodMode, setBuyerPeriodMode] = useState("all");
  const [buyerAssigneeFilter, setBuyerAssigneeFilter] = useState("전체");
  const [selectedRows, setSelectedRows] = useState([]);
  const [selectionResetToken, setSelectionResetToken] = useState(0);
  const [detailRow, setDetailRow] = useState(null);
  const [f2FocusRequest, setF2FocusRequest] = useState(0);
  const [crossMatchOpen, setCrossMatchOpen] = useState(false);
  const [viewState, setViewState] = useState("normal");
  const [moreOpen, setMoreOpen] = useState(false);
  const [columnMenuOpen, setColumnMenuOpen] = useState(false);
  const [messageComposer, setMessageComposer] = useState(null);
  const [messageCopied, setMessageCopied] = useState(false);
  const [campaignRows, setCampaignRows] = useState([]);
  const [toast, setToast] = useState(null);
  const [jumpQuery, setJumpQuery] = useState("");
  const [batchEditOpen, setBatchEditOpen] = useState(false);
  const [batchEditField, setBatchEditField] = useState("assignee");
  const [batchEditValue, setBatchEditValue] = useState("김이순");
  const [scheduleSuggestion, setScheduleSuggestion] = useState(null);
  const addRowButtonRef = useRef(null);

  const selectedRowIds = useMemo(() => selectedRows.map((row) => row.id), [selectedRows]);
  const composerRecipients = messageComposer?.recipients.filter((recipient) => !recipient.excluded) || [];
  const isCampaign = activeNav === "배치 캠페인";

  useEffect(() => {
    setCrossMatchOpen(Boolean(detailRow));
  }, [detailRow?.id]);

  const filteredCount = useMemo(() => {
    if (viewState === "filtered-empty") return 0;
    const query = searchQuery.trim().toLowerCase();
    return rows.filter((row) => {
      const textMatch = !query || [row.complex, row.building, row.unit, row.owner, row.phone, row.log]
        .some((value) => String(value || "").toLowerCase().includes(query));
      return textMatch && (complexFilter === "전체" || row.complex === complexFilter)
        && (saveFilter === "전체" || row.saveState === saveFilter);
    }).length;
  }, [rows, searchQuery, complexFilter, saveFilter, viewState]);

  const updateRow = (nextRow) => {
    if (nextRow?.ledgerType === "buyer" || nextRow?.rowKind === "buyer") {
      setBuyerRows((current) => current.map((row) => (row.id === nextRow.id ? nextRow : row)));
    } else {
      setRows((current) => current.map((row) => (row.id === nextRow.id ? nextRow : row)));
    }
    setDetailRow(nextRow);
    return nextRow;
  };

  const handleAddRow = ({ focusF2 = false } = {}) => {
    const draft = { ...emptyDraftRow, id: `DRAFT-${Date.now()}` };
    setRows((current) => [draft, ...current]);
    if (focusF2) setF2FocusRequest((current) => current + 1);
    setDetailRow({ ...draft, ledgerType: "property", rowKind: "property" });
  };

  const handleAddBuyerRow = () => {
    const draft = { ...emptyBuyerRow, id: `BUYER-DRAFT-${Date.now()}`, ledgerType: "buyer", rowKind: "buyer" };
    setBuyerRows((current) => [draft, ...current]);
    setDetailRow(draft);
  };

  const applyBatchEdit = () => {
    if (selectedRows.length === 0) return;
    setRows((current) => current.map((row) => selectedRows.some((selected) => selected.id === row.id) ? { ...row, [batchEditField]: batchEditValue, saveState: "임시저장" } : row));
    setSelectedRows([]);
    setSelectionResetToken((current) => current + 1);
    setBatchEditOpen(false);
    setToast({ variant: "success", title: `${selectedRows.length}건을 일괄 수정했습니다. 임시저장 상태로 확인 후 저장하세요.` });
  };

  const clearSelection = () => {
    setSelectedRows([]);
    setSelectionResetToken((current) => current + 1);
    setToast({ variant: "info", title: "선택한 행을 모두 해제했습니다. 필터와 정렬은 유지됩니다." });
    window.requestAnimationFrame(() => addRowButtonRef.current?.focus());
  };

  const openF2Entry = () => {
    if (selectedRows.length > 1) {
      setToast({ variant: "warning", title: "음성메모 입력은 대상 세대를 한 건만 선택해 주세요." });
      return;
    }
    setF2FocusRequest((current) => current + 1);
    if (selectedRows.length === 1) setDetailRow({ ...selectedRows[0], ledgerType: "property", rowKind: "property" });
    else handleAddRow();
  };

  const openMessageComposer = (payload) => {
    setMessageCopied(false);
    setMessageComposer(normalizeComposer(payload));
  };

  const closeMessageComposer = () => {
    setMessageCopied(false);
    setMessageComposer(null);
  };

  const openDirectMessage = () => {
    openMessageComposer({
      mode: "mvp-copy-only",
      source: "직접 선택",
      recipients: selectedRows.map((row) => ({
        id: row.id,
        title: `${row.owner || "성명 미입력"} · ${row.complex} ${row.building}동 ${row.unit}호`,
        phone: row.phone,
        consent: row.consent,
      })),
      draft: "안녕하세요. 보유 세대 관련 확인을 위해 연락드립니다. 편한 시간을 알려주세요.",
    });
  };

  const startCampaign = () => {
    if (selectedRows.length === 0) {
      setToast({ variant: "warning", title: "F3 캠페인을 시작할 세대를 먼저 선택해 주세요." });
      return;
    }
    setCampaignRows(selectedRows);
    setActiveNav("배치 캠페인");
  };

  const handleCreateComplex = ({ name, address }) => {
    const normalizedName = name.trim();
    const normalizedAddress = address.trim();
    const duplicate = complexOptions.find((option) =>
      option.name.toLocaleLowerCase("ko-KR") === normalizedName.toLocaleLowerCase("ko-KR")
      || (normalizedAddress && option.address && option.address === normalizedAddress));
    if (duplicate) throw new Error(`이미 등록된 단지입니다: ${duplicate.name}`);
    const created = { name: normalizedName, address: normalizedAddress };
    setComplexOptions((current) => [...current, created].sort((left, right) => left.name.localeCompare(right.name, "ko")));
    setToast({ variant: "success", title: `${created.name} 단지를 추가하고 현재 상세에 선택했습니다.` });
    return created;
  };

  const clearFilters = () => {
    setSearchQuery(""); setComplexFilter("전체"); setSaveFilter("전체");
    if (viewState === "filtered-empty") setViewState("normal");
  };

  const handleJump = () => {
    const query = jumpQuery.replace(/\s/g, "");
    const match = rows.find((row) => `${row.building}동${row.unit}호`.includes(query) || `${row.building}${row.unit}`.includes(query));
    if (match) {
      setDetailRow(match);
      setToast({ variant: "info", title: `${match.building}동 ${match.unit}호를 열었습니다.` });
    } else setToast({ variant: "warning", title: "일치하는 동·호를 찾지 못했습니다." });
  };

  const navTo = (item) => {
    if (item === "배치 캠페인" && selectedRows.length > 0) setCampaignRows(selectedRows);
    if (item !== activeNav) {
      setSelectedRows([]);
      setSelectionResetToken((current) => current + 1);
    }
    setActiveNav(item);
  };

  const isBuyerDetail = detailRow?.ledgerType === "buyer" || detailRow?.rowKind === "buyer";
  const closeDetail = () => { setCrossMatchOpen(false); setDetailRow(null); };
  const discardDetail = () => {
    if (detailRow?.id?.startsWith("BUYER-DRAFT-")) setBuyerRows((current) => current.filter((row) => row.id !== detailRow.id));
    else if (detailRow?.id?.startsWith("DRAFT-")) setRows((current) => current.filter((row) => row.id !== detailRow.id));
    closeDetail();
  };
  const saveDetail = (nextRow) => {
    const propertyColumns = isBuyerDetail ? {} : {
      salePrice: nextRow.listingType === "매매" ? nextRow.price || "" : nextRow.salePrice || "",
      leaseDeposit: nextRow.listingType === "전세" ? nextRow.price || nextRow.deposit || "" : nextRow.leaseDeposit || "",
      rentCondition: nextRow.listingType === "월세" ? [nextRow.deposit, nextRow.rent].filter(Boolean).join(" / ") : nextRow.rentCondition || "",
      ownerPhone: nextRow.phone || nextRow.ownerPhone || "",
    };
    const savedRow = {
      ...nextRow,
      ...propertyColumns,
      ledgerType: isBuyerDetail ? "buyer" : "property",
      rowKind: isBuyerDetail ? "buyer" : "property",
    };
    updateRow(savedRow);
    setCrossMatchOpen(true);
    const targetLabel = isBuyerDetail
      ? savedRow.buyer || "별칭 미입력"
      : `${savedRow.building || "미입력"}동 ${savedRow.unit || "미입력"}호`;
    setToast({ variant: "success", title: `${targetLabel}을(를) ${savedRow.saveState} 상태로 저장했습니다.` });
  };
  const handleEvidenceOpen = () => {
    const targetId = isBuyerDetail ? "buyer-content" : "detail-log";
    const target = document.getElementById(targetId);
    target?.scrollIntoView({ block: "center", behavior: "smooth" });
    window.requestAnimationFrame(() => target?.focus());
  };
  const crossMatchPanel = <CrossMatchPanel
    isOpen={crossMatchOpen}
    onClose={() => setCrossMatchOpen(false)}
    anchorRow={detailRow}
    parentContext={isBuyerDetail ? "buyer-detail" : "unit-detail"}
    onComposeMessage={openMessageComposer}
    onOpenEvidence={handleEvidenceOpen}
    onLater={() => { closeDetail(); setActiveNav("보류"); setToast({ variant: "success", title: "F1 보류·후속 처리 목록에 추가했습니다." }); }}
    onInterest={({ reason }) => setToast({ variant: "info", title: `관심없음 피드백을 기록했습니다 · ${reason}` })}
    onSchedule={({ candidate }) => setScheduleSuggestion({ candidate, anchorRow: detailRow })}
  />;

  return <div className="app-shell app-shell--compact-ledger">
    <main className={`work-area${
      isCampaign
        ? " work-area--campaign"
        : viewState === "offline"
          ? " work-area--offline"
          : ""
    }`}>
      <header className="f1-topbar">
        <div className="f1-product-title"><strong>F1 장부</strong><span>PROTOTYPE</span></div>
        <h1 className="pf-v6-screen-reader">{isCampaign ? "배치 캠페인" : activeNav}</h1>
        <div className="f1-ledger-switch" role="tablist" aria-label="F1 장부 전환">
          {["매물장", "구입장"].map((item) => <button key={item} type="button" role="tab" aria-selected={activeNav === item} className={activeNav === item ? "active" : ""} onClick={() => navTo(item)}>{item}</button>)}
        </div>
        <div className="jump-control f1-topbar__jump"><input value={jumpQuery} onChange={(event) => setJumpQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && jumpQuery.trim()) handleJump(); }} placeholder="동·호 조회 예) 101 203" aria-label="동·호 조회" /><Button variant="secondary" onClick={handleJump} isDisabled={!jumpQuery.trim()}>조회</Button></div>
        <div className="masthead-search"><SearchIcon aria-hidden="true" /><TextInput aria-label="통합 검색" value={searchQuery} onChange={(_event, value) => setSearchQuery(value)} placeholder="통합 검색 (성명·전화번호·로그)" /></div>
        {activeNav === "매물장" && <div className="f1-topbar__counts"><span>필터 {filteredCount.toLocaleString()}건</span><span>전체 {rows.length.toLocaleString()}건</span></div>}
        <div className="masthead-actions">
          <Label color={viewState === "offline" ? "orange" : "green"}>{viewState === "offline" ? "오프라인" : "연결됨"}</Label>
          <Button variant="plain" aria-label="알림" icon={<BellIcon />} />
          <Button variant="plain" aria-label="도움말" icon={<HelpIcon />} />
          <Button variant="plain" aria-label="사용자 메뉴" icon={<UserIcon />} />
          {isAuthenticated && user ? (
            <>
              <span className="user-name" title={`ID: ${user.login_id} (${user.role})`}>
                {user.display_name}
              </span>
              <Button variant="secondary" size="sm" onClick={logout} style={{ marginLeft: "8px" }}>
                로그아웃
              </Button>
            </>
          ) : (
            <Button
              variant="primary"
              size="sm"
              isLoading={authLoading}
              onClick={async () => {
                try {
                  const result = await loginDev();
                  setToast({ variant: "success", title: `개발 세션으로 로그인했습니다 (${result?.user?.display_name || "개발사용자"}).` });
                } catch (err) {
                  setToast({ variant: "warning", title: `개발 로그인 안내: 백엔드 서버 연결이 필요합니다 (${err.message}).` });
                }
              }}
            >
              개발용 로그인
            </Button>
          )}
        </div>
      </header>
      {toast && <Alert className="workspace-alert" variant={toast.variant} isInline isLiveRegion title={toast.title} actionClose={<Button variant="plain" aria-label="알림 닫기" onClick={() => setToast(null)} />} />}

      {isCampaign ? (
        <CampaignWorkspace targets={campaignRows} onBack={() => setActiveNav("매물장")} onOpenComposer={openMessageComposer} />
      ) : <>
        {viewState === "offline" && (
          <div
            className="offline-banner"
            role="status"
            aria-live="polite"
            aria-atomic="true"
            data-screen-id="F1-PG-010"
            data-requirement-ids="F1-GR-35, F1-NF-14"
          >
            <ExclamationTriangleIcon aria-hidden="true" />
            <strong>오프라인 · 변경 내용은 브라우저에 보관됩니다.</strong>
            <span>연결 복구 후 자동 전송됩니다.</span>
          </div>
        )}

        {activeNav === "매물장" ? <div className="f1-control-strip">
          <div className="ledger-tabs" role="tablist" aria-label="장부 유형">{["아파트", "상가", "주택", "재건축"].map((tab, index) => <button key={tab} id={`ledger-tab-${index}`} role="tab" aria-selected={index === 0} aria-controls="ledger-grid-panel" aria-disabled={index !== 0} disabled={index !== 0} tabIndex={index === 0 ? 0 : -1} title={index !== 0 ? "현재 프로토타입에서 사용할 수 없는 장부 유형입니다" : undefined} className={index === 0 ? "active" : ""} type="button">{tab}</button>)}</div>

          <Toolbar className="ledger-toolbar" aria-label={selectedRows.length ? "선택한 행 작업" : "매물장 작업 도구"}><ToolbarContent>
            {selectedRows.length ? <ToolbarGroup>
              <ToolbarItem><strong role="status" aria-live="polite">{selectedRows.length}건 선택됨</strong></ToolbarItem>
              <ToolbarItem><Button variant="link" onClick={clearSelection}>전체 선택 해제</Button></ToolbarItem>
              <ToolbarItem><Button variant="secondary" icon={<MicrophoneIcon />} aria-controls="f2-modal" aria-describedby={selectedRows.length > 1 ? "f2-selected-entry-help" : undefined} isDisabled={selectedRows.length > 1} onClick={openF2Entry}>음성메모 입력</Button></ToolbarItem>
              {selectedRows.length > 1 && <ToolbarItem><span id="f2-selected-entry-help" className="pf-v6-screen-reader">음성메모 입력은 대상 세대를 한 건만 선택해야 합니다.</span></ToolbarItem>}
              <ToolbarItem><Button variant="secondary" onClick={() => setBatchEditOpen(true)}>일괄 편집</Button></ToolbarItem>
              <ToolbarItem><Button variant="secondary" icon={<OutlinedCommentsIcon />} onClick={openDirectMessage}>문자 작업</Button></ToolbarItem>
              <ToolbarItem><Button variant="secondary" icon={<FilterIcon />} onClick={startCampaign}>F3 캠페인</Button></ToolbarItem>
            </ToolbarGroup> : <ToolbarGroup>
              <ToolbarItem><Button ref={addRowButtonRef} icon={<AddCircleOIcon />} onClick={() => handleAddRow()}>행 추가</Button></ToolbarItem>
              <ToolbarItem><Button variant="secondary" icon={<MicrophoneIcon />} aria-controls="f2-modal" aria-describedby="f2-entry-help" onClick={openF2Entry}>음성메모 입력</Button></ToolbarItem>
              <ToolbarItem><span id="f2-entry-help" className="pf-v6-screen-reader">선택이 없으면 신규 세대를 만들고, 한 건 선택 시 해당 상세 위에 음성메모 팝업을 엽니다.</span></ToolbarItem>
            </ToolbarGroup>}
            <ToolbarGroup align={{ default: "alignEnd" }}>
              {activeNav === "매물장" && <ToolbarItem><Dropdown isOpen={columnMenuOpen} onSelect={() => setColumnMenuOpen(false)} onOpenChange={setColumnMenuOpen} toggle={(ref) => <MenuToggle ref={ref} variant="plain" icon={<ColumnsIcon />} onClick={() => setColumnMenuOpen((open) => !open)} isExpanded={columnMenuOpen}>열 프리셋 · {COLUMN_PRESETS.find((preset) => preset.value === columnPreset)?.label || "기본 (12)"}</MenuToggle>}><DropdownList>{COLUMN_PRESETS.map((preset) => <DropdownItem key={preset.value} onClick={() => { setColumnPreset(preset.value); setColumnMenuOpen(false); }}>{preset.label} · {preset.description}</DropdownItem>)}</DropdownList></Dropdown></ToolbarItem>}
              <ToolbarItem><Dropdown isOpen={moreOpen} onSelect={() => setMoreOpen(false)} onOpenChange={setMoreOpen} toggle={(ref) => <MenuToggle ref={ref} variant="plain" aria-label="프로토타입 상태 도구" onClick={() => setMoreOpen((open) => !open)} isExpanded={moreOpen}><EllipsisVIcon /></MenuToggle>}><DropdownList>{viewStates.map(([value, label]) => <DropdownItem key={value} onClick={() => setViewState(value)}>{`프로토타입 상태 · ${label}${viewState === value ? " · 현재" : ""}`}</DropdownItem>)}</DropdownList></Dropdown></ToolbarItem>
            </ToolbarGroup>
          </ToolbarContent></Toolbar>

          <div className="filter-row">
            <label className={`filter-control${complexFilter === "전체" ? "" : " active-filter"}`}><FilterIcon aria-hidden="true" /><span>단지</span><select value={complexFilter} onChange={(event) => setComplexFilter(event.target.value)}>{["전체", ...complexOptions.map((option) => option.name)].map((value) => <option key={value}>{value}</option>)}</select></label>
            <label className="filter-control"><span>저장 상태</span><select value={saveFilter} onChange={(event) => setSaveFilter(event.target.value)}>{["전체", "임시저장", "저장 완료"].map((value) => <option key={value}>{value}</option>)}</select></label>
            <Button variant="link" onClick={clearFilters} isDisabled={!searchQuery && complexFilter === "전체" && saveFilter === "전체" && viewState !== "filtered-empty"}>모든 필터 해제</Button>
          </div>

          <nav className="f1-quick-nav" aria-label="F1 보조 업무">{compactNavItems.map((item) => <button key={item} type="button" className={activeNav === item ? "active" : ""} onClick={() => navTo(item)}>{item}</button>)}</nav>
        </div> : <nav className="f1-quick-nav f1-quick-nav--standalone" aria-label="F1 보조 업무">{compactNavItems.map((item) => <button key={item} type="button" className={activeNav === item ? "active" : ""} onClick={() => navTo(item)}>{item}</button>)}</nav>}

        {activeNav === "매물장" ? <LedgerGrid rows={rows} onRowsChange={setRows} onOpenDetail={(row) => setDetailRow({ ...row, ledgerType: "property", rowKind: "property" })} onSelectionChange={setSelectedRows} selectedRowIds={selectedRowIds} selectionResetToken={selectionResetToken} viewState={viewState} searchQuery={searchQuery} complexFilter={complexFilter} saveFilter={saveFilter} columnPreset={columnPreset} onRetry={() => setViewState("normal")} onClearFilters={clearFilters} onAddRow={handleAddRow} readOnly={false} /> : activeNav === "구입장" ? <BuyerLedgerGrid rows={buyerRows} onRowsChange={setBuyerRows} onOpenDetail={setDetailRow} onAddRow={handleAddBuyerRow} assigneeFilter={buyerAssigneeFilter} onAssigneeFilterChange={setBuyerAssigneeFilter} periodMode={buyerPeriodMode} onPeriodModeChange={setBuyerPeriodMode} /> : <section className="scope-placeholder"><h2>{activeNav}</h2><p>대표 F1 업무 흐름 검증이 끝난 뒤 같은 디자인 언어로 확장하는 화면입니다.</p><Button variant="secondary" onClick={() => setActiveNav("매물장")}>매물장으로 돌아가기</Button></section>}
        <footer className="grid-statusbar"><span>{activeNav === "매물장" ? filteredCount.toLocaleString() : buyerRows.length.toLocaleString()}건 표시</span><span>{selectedRows.length}건 선택</span><span>{viewState === "offline" ? "변경 내용 브라우저 보관" : "수정 내용은 임시저장"}</span><span className="statusbar-spacer" /><span>{activeNav === "매물장" ? "정렬: 동·호 오름차순" : "정렬: 최종접촉일"}</span><span>{activeNav === "매물장" ? "기본 (12) / 전체 (33)" : "구입장 17열"}</span><span>Enter 편집 · Space 선택 · Esc 취소</span></footer>
      </>}
    </main>

    {isBuyerDetail ? (
      <BuyerDetailWorkspace
        row={detailRow}
        isOpen={Boolean(detailRow)}
        focusF2Request={f2FocusRequest}
        onClose={closeDetail}
        onDiscard={discardDetail}
        onSave={saveDetail}
        crossMatchPanel={crossMatchPanel}
      />
    ) : (
      <DetailWorkspace
        row={detailRow}
        isOpen={Boolean(detailRow)}
        focusF2Request={f2FocusRequest}
        complexOptions={complexOptions}
        onCreateComplex={handleCreateComplex}
        onClose={closeDetail}
        onDiscard={discardDetail}
        onSave={saveDetail}
        onOpenCrossMatch={() => setCrossMatchOpen(true)}
        isCrossMatchOpen={crossMatchOpen}
        crossMatchPanel={crossMatchPanel}
      />
    )}

    <Modal variant="small" isOpen={Boolean(messageComposer)} onClose={closeMessageComposer}>
      <ModalHeader title="문자 작업" description="대상과 문안을 확인한 뒤 번호를 복사합니다. 실제 발송은 외부 도구에서 진행합니다." />
      <ModalBody>{messageComposer && <div className="message-composer" data-screen-id="F1-PNL-030 F1-MOD-060" data-requirement-ids="F1-MS-01~15, F1-UD-28, F3-CR-15, F3-BT-13~20">
        <div className="message-composer__context">
          <Label color="blue" variant="outline">대상 출처 · {messageComposer.source}</Label>
          <strong role="status">{composerRecipients.length}명 번호 확정</strong>
        </div>
        <p className="message-composer__summary">원본 {messageComposer.inputCount}건 · 제외 {messageComposer.inputCount - composerRecipients.length}건 · 중복 {messageComposer.duplicateCount}건 · 연락처 없음 {messageComposer.noPhoneCount}건 · 동의 X·확인 필요 {messageComposer.consentExcludedCount}건</p>
        <details className="message-composer__details" open={messageComposer.recipients.length <= 5}>
          <summary>대상 확인·제외 · {messageComposer.recipients.length}건</summary>
          <fieldset className="message-composer__recipients">
            <legend className="pf-v6-screen-reader">대상 확인·제외</legend>
            {messageComposer.recipients.map((recipient) => <Checkbox key={recipient.id || recipient.phone} id={`message-recipient-${String(recipient.id || recipient.phone).replace(/[^a-zA-Z0-9_-]/g, "-")}`} label={`${recipient.title} · ${recipient.phone || "연락처 없음"}${recipient.exclusionReason ? ` · 제외: ${recipient.exclusionReason}` : ""}`} isChecked={!recipient.excluded} isDisabled={recipient.lockedExcluded} onChange={(_event, checked) => { setMessageCopied(false); setMessageComposer((current) => ({ ...current, recipients: current.recipients.map((item) => item === recipient ? { ...item, excluded: !checked } : item) })); }} />)}
          </fieldset>
        </details>
        <details className="message-composer__details">
          <summary>번호 목록 · {composerRecipients.length}건</summary>
          <label>복사할 번호<textarea value={composerRecipients.map((recipient) => recipient.phone).join("\n")} readOnly /></label>
        </details>
        <label className="message-composer__draft-label"><span>문안</span><span>{messageComposer.draft.length.toLocaleString()}자</span><textarea value={messageComposer.draft} onChange={(event) => setMessageComposer((current) => ({ ...current, draft: event.target.value }))} /></label>
      </div>}</ModalBody>
      <ModalFooter><Button variant={messageCopied ? "secondary" : "primary"} isDisabled={!composerRecipients.length} onClick={async () => { try { if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable"); await navigator.clipboard.writeText(composerRecipients.map((recipient) => recipient.phone).join("\n")); setMessageCopied(true); setToast({ variant: "success", title: "번호 목록을 복사했습니다. 발송은 외부 도구에서 진행합니다." }); } catch { setMessageCopied(false); setToast({ variant: "warning", title: "번호를 복사하지 못했습니다. 번호 목록을 선택해 직접 복사해 주세요." }); } }}>{messageCopied ? "번호 목록 복사됨" : "번호 목록 복사"}</Button><Button variant="link" onClick={closeMessageComposer}>닫기</Button></ModalFooter>
    </Modal>
    <Modal variant="small" isOpen={batchEditOpen} onClose={() => setBatchEditOpen(false)}>
      <ModalHeader title="일괄 편집 확인" description="변경 전후 값을 확인한 뒤 적용합니다. 적용한 행은 임시저장 상태가 됩니다." />
      <ModalBody>
        <p className="batch-edit-summary" role="status">대상 {selectedRows.length.toLocaleString()}건</p>
        <label className="batch-edit-field"><span>변경 필드</span><select value={batchEditField} onChange={(event) => setBatchEditField(event.target.value)}><option value="assignee">담당</option><option value="householdState">세대 상태</option><option value="listingType">현매물</option><option value="memo">비고</option></select></label>
        <label className="batch-edit-field"><span>변경 값</span>{batchEditField === "assignee" ? <select value={batchEditValue} onChange={(event) => setBatchEditValue(event.target.value)}><option>김이순</option><option>실장</option><option>박소장</option></select> : batchEditField === "householdState" ? <select value={batchEditValue} onChange={(event) => setBatchEditValue(event.target.value)}><option>일반</option><option>매물화</option><option>거래진행</option><option>거래완료</option></select> : batchEditField === "listingType" ? <select value={batchEditValue} onChange={(event) => setBatchEditValue(event.target.value)}><option value="">(비어 있음)</option><option>매매</option><option>전세</option><option>월세</option></select> : <input value={batchEditValue} onChange={(event) => setBatchEditValue(event.target.value)} />}</label>
      </ModalBody>
      <ModalFooter><Button variant="primary" onClick={applyBatchEdit} isDisabled={!selectedRows.length}>적용</Button><Button variant="link" onClick={() => setBatchEditOpen(false)}>취소</Button></ModalFooter>
    </Modal>
    <Modal variant="small" isOpen={Boolean(scheduleSuggestion)} onClose={() => setScheduleSuggestion(null)}>
      <ModalHeader title="일정 제안 검토" description="F3가 제안했으며 사용자가 승인해야 F1 일정으로 저장됩니다." />
      <ModalBody>
        {scheduleSuggestion && <div data-screen-id="F1-MOD-080" data-requirement-ids="F1-SC-01, F1-SC-04~05, F3-CR-18, F3-IF-04~05">
          <p><strong>{scheduleSuggestion.candidate?.title}</strong></p>
          <label className="batch-edit-field"><span>일정 제목</span><input defaultValue="후보 조건 재확인" /></label>
          <label className="batch-edit-field"><span>예정일</span><input type="date" defaultValue="2026-08-18" /></label>
        </div>}
      </ModalBody>
      <ModalFooter><Button variant="primary" onClick={() => { setScheduleSuggestion(null); setToast({ variant: "success", title: "F3 제안을 승인해 F1 일정으로 저장했습니다." }); }}>일정 저장</Button><Button variant="link" onClick={() => setScheduleSuggestion(null)}>취소</Button></ModalFooter>
    </Modal>
    {viewState === "loading" && <div className="global-progress" aria-label="그리드 데이터 불러오는 중"><Spinner size="md" /></div>}
  </div>;
}
