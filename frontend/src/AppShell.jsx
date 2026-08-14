import { useMemo, useRef, useState } from "react";
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
import { createLedgerRows, emptyDraftRow, initialComplexes } from "./data/ledgerData.js";
import { PROTOTYPE_ASSUMPTIONS } from "./config/prototypeAssumptions.js";
import { LedgerGrid } from "./features/LedgerGrid.jsx";
import DetailWorkspace from "./features/DetailWorkspace.jsx";
import { CrossMatchPanel } from "./features/CrossMatchPanel.jsx";
import { CampaignWorkspace } from "./features/CampaignWorkspace.jsx";

const compactNavItems = ["연락처", "일정", "계약", "보류", "배치 캠페인", "사용자·권한", "설정"];

const viewStates = [
  ["normal", "기본 화면"], ["loading", "불러오는 중"], ["filtered-empty", "결과 없음"],
  ["load-error", "불러오기 오류"], ["offline", "오프라인"],
];

function normalizeComposer(payload) {
  const rawRecipients = payload?.recipients || (payload?.phone
    ? [{ id: payload.candidate?.id || payload.phone, title: payload.title, phone: payload.phone }]
    : []);
  const inputCount = rawRecipients.length;
  const withPhone = rawRecipients.filter((recipient) => recipient.phone);
  const consentExcludedCount = withPhone.filter((recipient) => recipient.consent && recipient.consent !== "동의").length;
  const eligible = withPhone.filter((recipient) => !recipient.consent || recipient.consent === "동의");
  const uniqueByPhone = new Map();
  eligible.forEach((recipient) => {
    const key = String(recipient.phone).replace(/\D/g, "");
    if (!uniqueByPhone.has(key)) uniqueByPhone.set(key, recipient);
  });
  const recipients = Array.from(uniqueByPhone.values());
  return {
    ...payload,
    source: payload?.source || "F3 교차 판정",
    recipients,
    inputCount,
    noPhoneCount: inputCount - withPhone.length,
    consentExcludedCount,
    duplicateCount: eligible.length - recipients.length,
    draft: payload?.draft || "",
  };
}

export function AppShell() {
  const [rows, setRows] = useState(() => createLedgerRows(PROTOTYPE_ASSUMPTIONS.grid.demoRowCount));
  const [complexOptions, setComplexOptions] = useState(() => initialComplexes.map((name) => ({ name, address: "" })));
  const [activeNav, setActiveNav] = useState("매물장");
  const [searchQuery, setSearchQuery] = useState("");
  const [complexFilter, setComplexFilter] = useState("래미안 원베일리");
  const [saveFilter, setSaveFilter] = useState("전체");
  const [aiFilter, setAiFilter] = useState("전체");
  const [selectedRows, setSelectedRows] = useState([]);
  const [selectionResetToken, setSelectionResetToken] = useState(0);
  const [detailRow, setDetailRow] = useState(null);
  const [f2FocusRequest, setF2FocusRequest] = useState(0);
  const [crossMatchOpen, setCrossMatchOpen] = useState(false);
  const [viewState, setViewState] = useState("normal");
  const [moreOpen, setMoreOpen] = useState(false);
  const [messageComposer, setMessageComposer] = useState(null);
  const [messageCopied, setMessageCopied] = useState(false);
  const [campaignRows, setCampaignRows] = useState([]);
  const [toast, setToast] = useState(null);
  const [jumpQuery, setJumpQuery] = useState("");
  const addRowButtonRef = useRef(null);

  const selectedRowIds = useMemo(() => selectedRows.map((row) => row.id), [selectedRows]);
  const composerRecipients = messageComposer?.recipients.filter((recipient) => !recipient.excluded) || [];
  const isCampaign = activeNav === "배치 캠페인";

  const filteredCount = useMemo(() => {
    if (viewState === "filtered-empty") return 0;
    const query = searchQuery.trim().toLowerCase();
    return rows.filter((row) => {
      const textMatch = !query || [row.complex, row.building, row.unit, row.owner, row.phone, row.log]
        .some((value) => String(value || "").toLowerCase().includes(query));
      return textMatch && (complexFilter === "전체" || row.complex === complexFilter)
        && (saveFilter === "전체" || row.saveState === saveFilter)
        && (aiFilter === "전체" || row.aiState === aiFilter);
    }).length;
  }, [rows, searchQuery, complexFilter, saveFilter, aiFilter, viewState]);

  const updateRow = (nextRow) => {
    setRows((current) => current.map((row) => (row.id === nextRow.id ? nextRow : row)));
    setDetailRow(nextRow);
    return nextRow;
  };

  const handleAddRow = ({ focusF2 = false } = {}) => {
    const draft = { ...emptyDraftRow, id: `DRAFT-${Date.now()}` };
    setRows((current) => [draft, ...current]);
    if (focusF2) setF2FocusRequest((current) => current + 1);
    setDetailRow(draft);
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
    if (selectedRows.length === 1) setDetailRow(selectedRows[0]);
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
    setSearchQuery(""); setComplexFilter("전체"); setSaveFilter("전체"); setAiFilter("전체");
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
    setActiveNav(item);
  };

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
        <div className="masthead-actions"><Label color={viewState === "offline" ? "orange" : "green"}>{viewState === "offline" ? "오프라인" : "연결됨"}</Label><Button variant="plain" aria-label="알림" icon={<BellIcon />} /><Button variant="plain" aria-label="도움말" icon={<HelpIcon />} /><Button variant="plain" aria-label="사용자 메뉴" icon={<UserIcon />} /><span className="user-name">김이순</span></div>
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

        <div className="f1-control-strip">
          <div className="ledger-tabs" role="tablist" aria-label="장부 유형">{["아파트", "상가", "주택", "재건축"].map((tab, index) => <button key={tab} id={`ledger-tab-${index}`} role="tab" aria-selected={index === 0} aria-controls="ledger-grid-panel" aria-disabled={index !== 0} disabled={index !== 0} tabIndex={index === 0 ? 0 : -1} title={index !== 0 ? "현재 프로토타입에서 사용할 수 없는 장부 유형입니다" : undefined} className={index === 0 ? "active" : ""} type="button">{tab}</button>)}</div>

          <Toolbar className="ledger-toolbar" aria-label={selectedRows.length ? "선택한 행 작업" : "매물장 작업 도구"}><ToolbarContent>
            {selectedRows.length ? <ToolbarGroup>
              <ToolbarItem><strong role="status" aria-live="polite">{selectedRows.length}건 선택됨</strong></ToolbarItem>
              <ToolbarItem><Button variant="link" onClick={clearSelection}>전체 선택 해제</Button></ToolbarItem>
              <ToolbarItem><Button variant="secondary" icon={<MicrophoneIcon />} aria-controls="f2-panel" aria-describedby={selectedRows.length > 1 ? "f2-selected-entry-help" : undefined} isDisabled={selectedRows.length > 1} onClick={openF2Entry}>음성메모 입력</Button></ToolbarItem>
              {selectedRows.length > 1 && <ToolbarItem><span id="f2-selected-entry-help" className="pf-v6-screen-reader">음성메모 입력은 대상 세대를 한 건만 선택해야 합니다.</span></ToolbarItem>}
              <ToolbarItem><Button variant="secondary" isDisabled>일괄 편집</Button></ToolbarItem>
              <ToolbarItem><Button variant="secondary" icon={<OutlinedCommentsIcon />} onClick={openDirectMessage}>문자 작업</Button></ToolbarItem>
              <ToolbarItem><Button variant="secondary" icon={<FilterIcon />} onClick={startCampaign}>F3 캠페인</Button></ToolbarItem>
            </ToolbarGroup> : <ToolbarGroup>
              <ToolbarItem><Button ref={addRowButtonRef} icon={<AddCircleOIcon />} onClick={() => handleAddRow()}>행 추가</Button></ToolbarItem>
              <ToolbarItem><Button variant="secondary" icon={<MicrophoneIcon />} aria-controls="f2-panel" aria-describedby="f2-entry-help" onClick={openF2Entry}>음성메모 입력</Button></ToolbarItem>
              <ToolbarItem><span id="f2-entry-help" className="pf-v6-screen-reader">선택이 없으면 신규 세대를 만들고, 한 건 선택 시 해당 상세의 F2 음성메모 영역으로 이동합니다.</span></ToolbarItem>
            </ToolbarGroup>}
            <ToolbarGroup align={{ default: "alignEnd" }}>
              <ToolbarItem><Label className="column-view-label" color="blue" variant="outline" icon={<ColumnsIcon />}>기본 12열</Label></ToolbarItem>
              <ToolbarItem><Dropdown isOpen={moreOpen} onSelect={() => setMoreOpen(false)} onOpenChange={setMoreOpen} toggle={(ref) => <MenuToggle ref={ref} variant="plain" aria-label="프로토타입 상태 도구" onClick={() => setMoreOpen((open) => !open)} isExpanded={moreOpen}><EllipsisVIcon /></MenuToggle>}><DropdownList>{viewStates.map(([value, label]) => <DropdownItem key={value} onClick={() => setViewState(value)}>{`프로토타입 상태 · ${label}${viewState === value ? " · 현재" : ""}`}</DropdownItem>)}</DropdownList></Dropdown></ToolbarItem>
            </ToolbarGroup>
          </ToolbarContent></Toolbar>

          <div className="filter-row">
            <label className={`filter-control${complexFilter === "전체" ? "" : " active-filter"}`}><FilterIcon aria-hidden="true" /><span>단지</span><select value={complexFilter} onChange={(event) => setComplexFilter(event.target.value)}>{["전체", ...complexOptions.map((option) => option.name)].map((value) => <option key={value}>{value}</option>)}</select></label>
            <label className="filter-control"><span>저장 상태</span><select value={saveFilter} onChange={(event) => setSaveFilter(event.target.value)}>{["전체", "작성 중", "검토 필요", "저장 완료"].map((value) => <option key={value}>{value}</option>)}</select></label>
            <label className="filter-control"><span>AI 처리 상태</span><select value={aiFilter} onChange={(event) => setAiFilter(event.target.value)}>{["전체", "대기", "음성 분석 중", "분석 완료", "분석 실패"].map((value) => <option key={value}>{value}</option>)}</select></label>
            <Button variant="link" onClick={clearFilters} isDisabled={!searchQuery && complexFilter === "전체" && saveFilter === "전체" && aiFilter === "전체" && viewState !== "filtered-empty"}>모든 필터 해제</Button>
          </div>

          <nav className="f1-quick-nav" aria-label="F1 보조 업무">{compactNavItems.map((item) => <button key={item} type="button" className={activeNav === item ? "active" : ""} onClick={() => navTo(item)}>{item}</button>)}</nav>
        </div>

        {activeNav !== "매물장" ? <section className="scope-placeholder"><h2>{activeNav}</h2><p>대표 F1 업무 흐름 검증이 끝난 뒤 같은 디자인 언어로 확장하는 화면입니다.</p><Button variant="secondary" onClick={() => setActiveNav("매물장")}>매물장으로 돌아가기</Button></section> : <LedgerGrid rows={rows} onRowsChange={setRows} onOpenDetail={setDetailRow} onSelectionChange={setSelectedRows} selectedRowIds={selectedRowIds} selectionResetToken={selectionResetToken} viewState={viewState} searchQuery={searchQuery} complexFilter={complexFilter} saveFilter={saveFilter} aiFilter={aiFilter} onRetry={() => setViewState("normal")} onClearFilters={clearFilters} onAddRow={handleAddRow} readOnly={false} />}
        <footer className="grid-statusbar"><span>{filteredCount.toLocaleString()}건 표시</span><span>{selectedRows.length}건 선택</span><span>{viewState === "offline" ? "변경 내용 브라우저 보관" : "모든 변경 저장됨"}</span><span className="statusbar-spacer" /><span>정렬: 동·호 오름차순</span><span>기본 (12) / 전체 (33)</span><span>Enter 편집 · Space 선택 · Esc 취소</span></footer>
      </>}
    </main>

    <DetailWorkspace row={detailRow} isOpen={Boolean(detailRow)} focusF2Request={f2FocusRequest} complexOptions={complexOptions} onCreateComplex={handleCreateComplex} onClose={() => { setCrossMatchOpen(false); setDetailRow(null); }} onDiscard={() => { if (detailRow?.id?.startsWith("DRAFT-")) setRows((current) => current.filter((row) => row.id !== detailRow.id)); setCrossMatchOpen(false); setDetailRow(null); }} onSave={(nextRow) => { updateRow(nextRow); setToast({ variant: "success", title: `${nextRow.building || "미입력"}동 ${nextRow.unit || "미입력"}호를 ${nextRow.saveState} 상태로 저장했습니다.` }); }} onOpenCrossMatch={() => setCrossMatchOpen(true)} isCrossMatchOpen={crossMatchOpen} crossMatchPanel={<CrossMatchPanel isOpen={crossMatchOpen} onClose={() => setCrossMatchOpen(false)} anchorRow={detailRow} onComposeMessage={openMessageComposer} />} />

    <Modal variant="small" isOpen={Boolean(messageComposer)} onClose={closeMessageComposer}>
      <ModalHeader title="문자 작업" description="대상과 문안을 확인한 뒤 번호를 복사합니다. 실제 발송은 외부 도구에서 진행합니다." />
      <ModalBody>{messageComposer && <div className="message-composer" data-screen-id="F1-PNL-030 F1-MOD-060" data-requirement-ids="F1-MS-01~17, F3-CR-15, F3-BT-13~20">
        <div className="message-composer__context">
          <Label color="blue" variant="outline">대상 출처 · {messageComposer.source}</Label>
          <strong role="status">{composerRecipients.length}명 번호 확정</strong>
        </div>
        <p className="message-composer__summary">원본 {messageComposer.inputCount}건 · 제외 {messageComposer.recipients.length - composerRecipients.length}건 · 중복 {messageComposer.duplicateCount}건 · 연락처 없음 {messageComposer.noPhoneCount}건 · 동의 확인 {messageComposer.consentExcludedCount}건</p>
        <details className="message-composer__details" open={messageComposer.recipients.length <= 5}>
          <summary>대상 확인·제외 · {messageComposer.recipients.length}건</summary>
          <fieldset className="message-composer__recipients">
            <legend className="pf-v6-screen-reader">대상 확인·제외</legend>
            {messageComposer.recipients.map((recipient) => <Checkbox key={recipient.id || recipient.phone} id={`message-recipient-${String(recipient.id || recipient.phone).replace(/[^a-zA-Z0-9_-]/g, "-")}`} label={`${recipient.title} · ${recipient.phone}`} isChecked={!recipient.excluded} onChange={(_event, checked) => { setMessageCopied(false); setMessageComposer((current) => ({ ...current, recipients: current.recipients.map((item) => item === recipient ? { ...item, excluded: !checked } : item) })); }} />)}
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
    {viewState === "loading" && <div className="global-progress" aria-label="그리드 데이터 불러오는 중"><Spinner size="md" /></div>}
  </div>;
}
