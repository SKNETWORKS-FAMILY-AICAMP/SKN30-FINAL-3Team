import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Button, Checkbox, Dropdown, DropdownItem, DropdownList, Label, MenuToggle,
  Modal, ModalBody, ModalFooter, ModalHeader,
  Spinner, TextInput, Toolbar, ToolbarContent, ToolbarGroup, ToolbarItem,
} from "@patternfly/react-core";
import {
  AddCircleOIcon, BellIcon, ColumnsIcon, EllipsisVIcon,
  ExclamationTriangleIcon, FilterIcon, HelpIcon, MicrophoneIcon, OutlinedCommentsIcon, SaveIcon, SearchIcon,
  UserIcon,
} from "@patternfly/react-icons";
import { useBuyerLedger, useComplexOptions, usePropertyLedger } from "./features/ledger/index.ts";
import { describeForUser, isEmptyDraft } from "./features/ledger/index.ts";
import { isMockSource } from "./config/env.ts";
import { PROTOTYPE_ASSUMPTIONS } from "./config/prototypeAssumptions.js";
import { COLUMN_PRESETS, LedgerGrid } from "./features/LedgerGrid.jsx";
import { BuyerLedgerGrid } from "./features/BuyerLedgerGrid.jsx";
import DetailWorkspace from "./features/DetailWorkspace.jsx";
import BuyerDetailWorkspace from "./features/BuyerDetailWorkspace.jsx";
import { CrossMatchSection, resetCrossJudgmentCache } from "./features/f3/index.ts";
import { CampaignWorkspace } from "./features/CampaignWorkspace.jsx";
import { HomeScreen } from "./features/HomeScreen.tsx";
import VoiceMemoModal from "./features/VoiceMemoModal.jsx";
import { currentUser, useAuth } from "./features/auth/index.ts";

const compactNavItems = ["배치 캠페인"];

const viewStates = [
  ["normal", "기본 화면"], ["loading", "불러오는 중"], ["filtered-empty", "결과 없음"],
  ["load-error", "불러오기 오류"], ["offline", "오프라인"],
];

/**
 * 한 손님에게 보낼 문안 초안.
 *
 * 손님마다 붙는 맥락이 다르다. 교차 판정에서 왔으면 기준 세대 조건을, 장부에서 직접 골랐으면
 * 그 손님의 세대 조건을 넣는다. 사용자가 고친 문안은 여기서 다시 만들지 않는다.
 */
function buildRecipientDraft(composer, recipient) {
  const name = String(recipient?.title || "").split(" · ")[0] || "고객";
  const anchor = composer?.anchorRow;
  const context = recipient?.context;

  if (composer?.parentContext === "buyer-detail" && anchor) {
    const wanted = [anchor.complex || "희망 단지", anchor.area, anchor.budget].filter(Boolean).join(" ");
    return `안녕하세요. ${anchor.buyer || "손님"} 고객의 ${wanted} 조건과 관련해 ${name}님께 확인드립니다. 상담 가능 시간을 알려주세요.`;
  }

  const unit = context || anchor;
  if (unit?.complex) {
    const spec = [unit.area, unit.listingType || "매물"].filter(Boolean).join(" ");
    return `${name}님, ${unit.complex} ${unit.building || "-"}동 ${unit.unit || "-"}호 ${spec} 조건을 확인드리려고 연락드립니다. 검토 가능하시면 편한 시간을 알려주세요.`;
  }
  return `${name}님, 보유 세대 관련 확인을 위해 연락드립니다. 편한 시간을 알려주세요.`;
}

function recipientKey(recipient) {
  return String(recipient?.id ?? recipient?.phone ?? "");
}

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
    /* 손님별 문안 보관소. 손님을 바꿔도 앞서 고쳐 둔 문안이 사라지지 않게 한다. */
    drafts: (() => {
      const first = recipients.find((recipient) => !recipient.excluded);
      return first && payload?.draft ? { [recipientKey(first)]: payload.draft } : {};
    })(),
    activeRecipientId: recipientKey(recipients.find((recipient) => !recipient.excluded)),
  };
}

export function AppShell() {
  // 로그인 여부는 AuthGate가 이미 걸렀다. 여기서는 헤더 표시와 로그아웃만 다룬다.
  const { state: authState, isSubmitting: authSubmitting, signOut, markSessionExpired } = useAuth();
  const user = currentUser(authState);
  // 장부 데이터는 features/ledger가 소유한다. mock/API 전환은 VITE_LEDGER_SOURCE가 정한다.
  const ledgerEnabled = isMockSource() || user != null;
  const ledgerQuery = useMemo(() => ({}), []);
  /*
   * 담당 열은 세대에 `assigned_user_id`만 들어 있어 이름 조회표가 없으면 늘 빈칸이다.
   * 계약에 사용자 목록 엔드포인트가 없으므로 지금 이름을 아는 사람은 로그인한 본인뿐이다.
   * 다른 담당자는 이름 대신 빈칸이 되며, 사용자 목록이 생기면 이 함수만 넓히면 된다.
   */
  const userName = useCallback(
    (userId) => (userId != null && userId === user?.id ? user.displayName : ""),
    [user],
  );
  const propertyLedger = usePropertyLedger(ledgerQuery, { enabled: ledgerEnabled, userName });
  const buyerLedger = useBuyerLedger(ledgerQuery, { enabled: ledgerEnabled });
  const rows = propertyLedger.state.rows;
  const buyerRows = buyerLedger.state.rows;
  const setRows = propertyLedger.replaceRows;
  const setBuyerRows = buyerLedger.replaceRows;

  // 단지는 세대의 상위 레코드다. 목록도 생성도 /property-complexes를 쓴다.
  const complexes = useComplexOptions({ enabled: ledgerEnabled });
  const complexOptions = complexes.options;

  // 세션이 끊긴 채로 장부를 열어두지 않는다. 사무소 공용 PC를 전제하므로(F1-SE-11)
  // 401을 본 순간 게이트를 다시 세워 로그인 화면으로 돌린다.
  const propertyLoadError = propertyLedger.state.error;
  const buyerLoadError = buyerLedger.state.error;
  useEffect(() => {
    if (propertyLoadError?.kind === "unauthorized" || buyerLoadError?.kind === "unauthorized") {
      // 실행 식별자와 후보 요약은 중개사무소 안에서만 유효하다. 사무소 공용 PC를 전제하므로
      // 세션이 끊긴 자리에 남겨 두면 다음 사용자가 앞 사용자의 실행을 조회하게 된다.
      resetCrossJudgmentCache();
      markSessionExpired();
    }
  }, [propertyLoadError, buyerLoadError, markSessionExpired]);

  const [activeNav, setActiveNav] = useState("홈");
  const [searchQuery, setSearchQuery] = useState("");
  const [complexFilter, setComplexFilter] = useState("전체");
  const [saveFilter, setSaveFilter] = useState("전체");
  const [columnPreset, setColumnPreset] = useState("all");
  const [buyerPeriodMode, setBuyerPeriodMode] = useState("all");
  const [buyerAssigneeFilter, setBuyerAssigneeFilter] = useState("전체");
  const [selectedRows, setSelectedRows] = useState([]);
  const [selectionResetToken, setSelectionResetToken] = useState(0);
  const [detailRow, setDetailRow] = useState(null);
  const [f2FocusRequest, setF2FocusRequest] = useState(0);
  const [crossMatchOpen, setCrossMatchOpen] = useState(false);
  /** 교차 판정 패널로 스크롤·포커스를 옮겨도 되는 시점. 사용자가 직접 열었을 때만 올린다. */
  const [crossMatchFocusRequest, setCrossMatchFocusRequest] = useState(0);
  const [viewState, setViewState] = useState("normal");
  const [moreOpen, setMoreOpen] = useState(false);
  const [columnMenuOpen, setColumnMenuOpen] = useState(false);
  const [messageComposer, setMessageComposer] = useState(null);
  const [messageCopied, setMessageCopied] = useState(false);
  const [campaignRows, setCampaignRows] = useState([]);
  /** 장부를 정하지 않은 신규 음성메모 접수 팝업. 상단바 어디서나 연다. */
  const [intakeOpen, setIntakeOpen] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(timer);
  }, [toast]);
  const [jumpQuery, setJumpQuery] = useState("");
  const [batchEditOpen, setBatchEditOpen] = useState(false);
  /** 삭제 확인 대상. { rows, source } 형태이며 null이면 확인 창을 닫는다. */
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [batchEditField, setBatchEditField] = useState("assignee");
  const [batchEditValue, setBatchEditValue] = useState("김이순");
  const [scheduleSuggestion, setScheduleSuggestion] = useState(null);
  const addRowButtonRef = useRef(null);

  const selectedRowIds = useMemo(() => selectedRows.map((row) => row.id), [selectedRows]);
  // 프로토타입 상태 선택기는 유지하되, 실제 로드 상태가 있으면 그쪽이 우선한다.
  const activeStatus = activeNav === "구입장" ? buyerLedger.state.status : propertyLedger.state.status;
  const effectiveViewState = activeStatus === "loading" ? "loading" : activeStatus === "error" ? "load-error" : viewState;
  const composerRecipients = messageComposer?.recipients.filter((recipient) => !recipient.excluded) || [];
  const activeComposerRecipient = composerRecipients.find((recipient) => recipientKey(recipient) === messageComposer?.activeRecipientId);
  const isCampaign = activeNav === "배치 캠페인";
  const isHome = activeNav === "홈";
  /* 신규 접수는 열려 있는 상세가 없는 빈 행에서 시작한다. 참조가 흔들리면 팝업이 매번 초기화된다. */
  const intakeDraft = useMemo(() => ({}), []);

  /*
   * 상세를 열어도 교차 판정을 시작하지 않는다.
   *
   * 패널이 열리는 순간 실행이 접수되므로(useCrossJudgment의 enabled), 상세 진입만으로
   * 판정 실행이 만들어졌다. 실행 시점은 사용자가 [교차 판정]으로 정한다(F3-CR-03·04).
   * 다른 행으로 옮기면 이전 행의 패널을 닫는다.
   */
  useEffect(() => {
    setCrossMatchOpen(false);
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
    const ledger = nextRow?.ledgerType === "buyer" || nextRow?.rowKind === "buyer" ? buyerLedger : propertyLedger;
    ledger.patchRow(nextRow.id, () => nextRow);
    setDetailRow(nextRow);
    return nextRow;
  };

  const handleAddRow = ({ focusF2 = false } = {}) => {
    const draft = propertyLedger.addDraft();
    if (focusF2) setF2FocusRequest((current) => current + 1);
    setDetailRow({ ...draft, ledgerType: "property", rowKind: "property" });
  };

  const handleAddBuyerRow = () => {
    const draft = buyerLedger.addDraft();
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

  const requestDeleteRows = (rows, source) => {
    if (rows.length === 0) return;
    setDeleteTarget({ rows, source });
  };

  /*
   * 실제 삭제. 확인 화면은 호출한 쪽이 책임진다.
   * 부분 실패를 성공으로 뭉뚱그리지 않고, 실패한 행은 열려 있는 화면에서 그대로 둔다.
   * 자체 확인 창에서 오류를 직접 보여주는 호출부는 reportFailure를 꺼서 같은 말을 두 번 하지 않는다.
   */
  const deleteRows = async (rows, { reportFailure = true } = {}) => {
    const failures = [];
    for (const row of rows) {
      const ledger = row.ledgerType === "buyer" || row.rowKind === "buyer" ? buyerLedger : propertyLedger;
      try {
        await ledger.deleteRow(row);
      } catch (error) {
        failures.push({ row, message: describeForUser(error) });
      }
    }

    setSelectedRows([]);
    setSelectionResetToken((current) => current + 1);
    const deletedRows = rows.filter((row) => !failures.some((failure) => failure.row.id === row.id));
    if (detailRow && deletedRows.some((row) => row.id === detailRow.id)) closeDetail();

    const deleted = deletedRows.length;
    if (failures.length === 0) {
      setToast({ variant: "success", title: `${deleted.toLocaleString()}건을 삭제했습니다.` });
    } else if (deleted === 0) {
      if (reportFailure) setToast({ variant: "danger", title: `삭제하지 못했습니다 · ${failures[0].message}` });
    } else {
      setToast({
        variant: "warning",
        title: `${deleted.toLocaleString()}건을 삭제했고 ${failures.length.toLocaleString()}건은 실패했습니다 · ${failures[0].message}`,
      });
    }

    return failures;
  };

  /** 확인 창의 삭제 버튼. */
  const confirmDelete = async () => {
    const rows = deleteTarget?.rows ?? [];
    if (rows.length === 0) return;
    setIsDeleting(true);
    await deleteRows(rows);
    setIsDeleting(false);
    setDeleteTarget(null);
  };

  /*
   * 세대·구입장 상세의 삭제.
   *
   * 상세는 자체 확인 창에서 대상과 영향을 보여주고 오류도 그 자리에서 알린다.
   * 여기서 확인 창을 한 번 더 띄우면 같은 질문을 두 번 하게 되므로 바로 실행하고,
   * 실패는 던져서 상세가 열린 채로 사유를 보여주게 한다.
   */
  const deleteRowFromDetail = async (row) => {
    const failures = await deleteRows([row], { reportFailure: false });
    if (failures.length > 0) throw new Error(failures[0].message);
  };

  /*
   * 그리드에서 고친 내용은 화면 상태로만 남는다. 여기서 한 번에 서버로 보낸다.
   * 상세를 열지 않고도 저장할 수 있어야 장부를 표처럼 쓸 수 있다.
   */
  const pendingPropertyRows = useMemo(
    () => rows.filter((row) => row.saveState === "임시저장" || row.sync?.status === "failed" || row.sync?.status === "conflict"),
    [rows],
  );
  const pendingBuyerRows = useMemo(
    () => buyerRows.filter((row) => row.saveState === "임시저장" || row.sync?.status === "failed" || row.sync?.status === "conflict"),
    [buyerRows],
  );
  const pendingRows = activeNav === "구입장" ? pendingBuyerRows : pendingPropertyRows;
  const [isSavingPending, setIsSavingPending] = useState(false);

  const savePendingRows = async () => {
    const ledger = activeNav === "구입장" ? buyerLedger : propertyLedger;
    const targets = pendingRows;
    if (targets.length === 0) return;
    setIsSavingPending(true);

    const failures = [];
    for (const row of targets) {
      try {
        await ledger.saveRow(row);
      } catch (error) {
        failures.push({ row, message: describeForUser(error) });
      }
    }
    setIsSavingPending(false);

    const saved = targets.length - failures.length;
    if (failures.length === 0) {
      setToast({ variant: "success", title: `${saved.toLocaleString()}건을 저장했습니다.` });
    } else if (saved === 0) {
      setToast({ variant: "danger", title: `저장하지 못했습니다 · ${failures[0].message}` });
    } else {
      setToast({
        variant: "warning",
        title: `${saved.toLocaleString()}건 저장, ${failures.length.toLocaleString()}건 실패 · ${failures[0].message}`,
      });
    }
  };

  const clearSelection = () => {
    setSelectedRows([]);
    setSelectionResetToken((current) => current + 1);
    setToast({ variant: "info", title: "선택한 행을 모두 해제했습니다. 필터와 정렬은 유지됩니다." });
    window.requestAnimationFrame(() => addRowButtonRef.current?.focus());
  };

  /** 매물장에서 고른 세대에 음성메모를 반영한다. 대상이 이미 정해져 있어 장부를 판정하지 않는다. */
  const openSelectedRowF2 = () => {
    if (selectedRows.length !== 1) {
      setToast({ variant: "warning", title: "선택 세대 음성메모는 대상 세대를 한 건만 선택해 주세요." });
      return;
    }
    setF2FocusRequest((current) => current + 1);
    setDetailRow({ ...selectedRows[0], ledgerType: "property", rowKind: "property" });
  };

  /*
   * 홈·상단바의 신규 음성메모 접수 반영.
   *
   * 어느 장부인지는 분석이 정한다. 그 장부에 빈 행을 만들고 사용자가 고른 제안만 채운 뒤
   * 상세를 열어 준다. 여기서 저장하지 않는다. 상세에서 확인하고 저장해야 서버로 간다.
   */
  const applyIntake = (patch, f2Draft, meta) => {
    const isBuyer = meta?.ledgerType === "buyer";
    const ledger = isBuyer ? buyerLedger : propertyLedger;
    const draftRow = ledger.addDraft();
    const nextRow = { ...draftRow, ...patch, f2Draft };
    ledger.patchRow(draftRow.id, () => nextRow);

    setIntakeOpen(false);
    if (activeNav !== (isBuyer ? "구입장" : "매물장")) {
      setSelectedRows([]);
      setSelectionResetToken((current) => current + 1);
    }
    setActiveNav(isBuyer ? "구입장" : "매물장");
    setDetailRow(nextRow);
    setToast({
      variant: "success",
      title: `${isBuyer ? "구입장" : "매물장"}에 신규 행을 추가했습니다. 내용을 확인한 뒤 저장하세요.`,
    });
  };

  const openMessageComposer = (payload) => {
    setMessageCopied(false);
    setMessageComposer(normalizeComposer(payload));
  };

  /** 문안을 이 손님 기준으로 바꾼다. 이미 고쳐 둔 문안이 있으면 그대로 되살린다. */
  const selectComposerRecipient = (recipient) => {
    const key = recipientKey(recipient);
    setMessageCopied(false);
    setMessageComposer((current) => {
      if (current == null) return current;
      const kept = current.drafts?.[key];
      return {
        ...current,
        activeRecipientId: key,
        draft: kept ?? buildRecipientDraft(current, recipient),
      };
    });
  };

  const changeComposerDraft = (text) => {
    setMessageCopied(false);
    setMessageComposer((current) => (current == null ? current : {
      ...current,
      draft: text,
      drafts: { ...current.drafts, [current.activeRecipientId]: text },
    }));
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
        // 손님별 문안을 만들 때 쓰는 세대 조건.
        context: { complex: row.complex, building: row.building, unit: row.unit, area: row.area, listingType: row.listingType },
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

  /** 단지 삭제. 세대가 남아 있으면 서버가 거절하며, 그 사유를 선택기 안에서 그대로 보여준다. */
  const handleDeleteComplex = async (option) => {
    try {
      await complexes.deleteComplex(option);
      setToast({ variant: "success", title: `${option.name} 단지를 삭제했습니다.` });
    } catch (error) {
      throw new Error(describeForUser(error));
    }
  };

  const handleCreateComplex = async ({ name, address }) => {
    const normalizedName = name.trim();
    const duplicate = complexOptions.find((option) =>
      option.name.toLocaleLowerCase("ko-KR") === normalizedName.toLocaleLowerCase("ko-KR"));
    if (duplicate) throw new Error(`이미 등록된 단지입니다: ${duplicate.name}`);
    // 서버가 준 id를 받아야 이 단지로 세대를 저장할 수 있다.
    const created = await complexes.createComplex({ name: normalizedName, address });
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
    if (item !== "홈" && item !== "매물장" && item !== "구입장" && item !== "배치 캠페인") {
      alert(`${item}: 대표 F1 업무 흐름 검증이 끝난 뒤 같은 디자인 언어로 확장하는 화면입니다.`);
      return;
    }
    if (item === "배치 캠페인" && selectedRows.length > 0) setCampaignRows(selectedRows);
    if (item !== activeNav) {
      setSelectedRows([]);
      setSelectionResetToken((current) => current + 1);
    }
    setActiveNav(item);
  };

  const isBuyerDetail = detailRow?.ledgerType === "buyer" || detailRow?.rowKind === "buyer";

  /*
   * 상세 닫기.
   *
   * 값을 하나도 넣지 않은 미저장 행은 그리드에 남기지 않는다(F1-GR-32).
   * 행 추가만 하고 닫으면 저장할 것이 없는 빈 임시저장 행만 쌓인다.
   * 값이 있는 미저장 행(예: 음성메모 접수)은 다시 열어 저장할 수 있게 남긴다.
   */
  const closeDetail = () => {
    if (isEmptyDraft(detailRow)) (isBuyerDetail ? buyerLedger : propertyLedger).discardRow(detailRow);
    setCrossMatchOpen(false);
    setDetailRow(null);
  };
  const discardDetail = () => {
    if (detailRow?.ledgerType === "buyer" || detailRow?.rowKind === "buyer") buyerLedger.discardRow(detailRow);
    else if (detailRow) propertyLedger.discardRow(detailRow);
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
    const targetLabel = isBuyerDetail
      ? savedRow.buyer || "별칭 미입력"
      : `${savedRow.building || "미입력"}동 ${savedRow.unit || "미입력"}호`;

    // 낙관적 반영 후 서버에 보낸다. 실패하면 행의 sync 상태가 남고 사용자에게 알린다.
    updateRow(savedRow);
    /*
     * 저장 트리거는 그대로 둔다(F3-CR-01·02). 저장이 성공하면 서버가 실행을 접수하므로,
     * 화면이 패널을 닫아 두면 이미 도는 판정의 결과를 아무도 보지 못한다.
     * 화면이 보내는 실행 요청은 같은 입력 버전의 활성 실행을 재사용한다.
     */
    setCrossMatchOpen(true);
    const ledger = isBuyerDetail ? buyerLedger : propertyLedger;
    // 상세 화면이 저장 중 표시와 오류 배너를 띄우려면 promise를 그대로 돌려줘야 한다.
    return ledger.saveRow(savedRow).then(
      (persisted) => {
        setDetailRow((current) => (current?.id === persisted.id ? persisted : current));
        setToast({ variant: "success", title: `${targetLabel}을(를) 저장했습니다.` });
      },
      (error) => {
        setToast({ variant: "danger", title: `${targetLabel} 저장에 실패했습니다 · ${describeForUser(error)}` });
        throw error;
      },
    );
  };
  const handleEvidenceOpen = () => {
    const targetId = isBuyerDetail ? "buyer-content" : "detail-log";
    const target = document.getElementById(targetId);
    target?.scrollIntoView({ block: "center", behavior: "smooth" });
    window.requestAnimationFrame(() => target?.focus());
  };
  const openCrossMatch = () => {
    setCrossMatchOpen(true);
    setCrossMatchFocusRequest((current) => current + 1);
  };

  /* 앵커 도출과 실행 확보는 타입 검사를 받는 `CrossMatchSection`이 소유한다. */
  const crossMatchPanel = <CrossMatchSection
    isOpen={crossMatchOpen}
    focusRequest={crossMatchFocusRequest}
    onClose={() => setCrossMatchOpen(false)}
    row={detailRow}
    parentContext={isBuyerDetail ? "buyer-detail" : "unit-detail"}
    /* 후보 표시 이름은 판정 응답에 없다. 이미 불러온 반대편 장부에서 찾는다. */
    propertyRows={propertyLedger.state.rows}
    buyerRows={buyerLedger.state.rows}
    onComposeMessage={openMessageComposer}
    onOpenEvidence={handleEvidenceOpen}
    onLater={() => { closeDetail(); setToast({ variant: "success", title: "F1 보류·후속 처리 목록에 추가했습니다." }); }}
    onFeedbackResult={({ ok, cause }) => setToast(ok
      ? { variant: "success", title: "관심없음 피드백을 기록했습니다." }
      : { variant: "danger", title: describeForUser(cause) })}
    onSchedule={({ candidate }) => setScheduleSuggestion({ candidate, anchorRow: detailRow })}
  />;

  return <div className="app-shell app-shell--compact-ledger">
    <main className={`work-area${
      isHome
        ? " work-area--home"
        : isCampaign
          ? " work-area--campaign"
          : viewState === "offline"
            ? " work-area--offline"
            : ""
    }`}>
      <header className="f1-topbar">
        <div className="f1-product-title"><strong>집크크</strong><span>beta</span></div>
        {/* 홈은 본문에 보이는 h1이 있다. 여기서 또 h1을 두면 화면 제목이 둘이 된다. */}
        {!isHome && <h1 className="pf-v6-screen-reader">{isCampaign ? "배치 캠페인" : activeNav}</h1>}
        <nav className="f1-ledger-switch" aria-label="주요 화면">
          {["홈", "매물장", "구입장"].map((item) => <button key={item} type="button" aria-current={activeNav === item ? "page" : undefined} className={activeNav === item ? "active" : ""} onClick={() => navTo(item)}>{item}</button>)}
        </nav>
        {/* 동·호 조회와 통합 검색은 장부 위에서만 뜻이 있다. 홈에서는 걸 곳이 없어 감춘다. */}
        {!isHome && <>
          <div className="jump-control f1-topbar__jump"><input value={jumpQuery} onChange={(event) => setJumpQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && jumpQuery.trim()) handleJump(); }} placeholder="동·호 조회 예) 101 203" aria-label="동·호 조회" /><Button variant="secondary" onClick={handleJump} isDisabled={!jumpQuery.trim()}>조회</Button></div>
          <div className="masthead-search"><SearchIcon aria-hidden="true" /><input type="text" aria-label="통합 검색" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="통합 검색 (성명·전화번호·로그)" /></div>
        </>}
        {activeNav === "매물장" && <div className="f1-topbar__counts"><span>필터 {filteredCount.toLocaleString()}건</span><span>전체 {propertyLedger.state.totalCount.toLocaleString()}건</span></div>}
        <div className="masthead-actions">
          <Button className="f1-topbar__intake" variant="secondary" icon={<MicrophoneIcon />} aria-controls="f2-modal" aria-describedby="topbar-intake-help" onClick={() => setIntakeOpen(true)}>음성메모 입력</Button>
          <span id="topbar-intake-help" className="pf-v6-screen-reader">음성을 분석해 매도의뢰는 매물장, 매수문의는 구입장에 신규 행으로 추가합니다.</span>
          <Button variant="plain" aria-label="알림" icon={<BellIcon />} />
          <Button variant="plain" aria-label="도움말" icon={<HelpIcon />} />
          <Button variant="plain" aria-label="사용자 메뉴" icon={<UserIcon />} />
          {user && (
            <>
              <span className="user-name" title={`${user.loginId} · ${user.role}`}>
                {user.displayName}
              </span>
              <Button
                variant="secondary"
                size="sm"
                isDisabled={authSubmitting}
                onClick={() => { resetCrossJudgmentCache(); void signOut(); }}
                style={{ marginLeft: "8px" }}
              >
                로그아웃
              </Button>
            </>
          )}
        </div>
      </header>

      {isHome ? (
        <HomeScreen
          onVoiceIntake={() => setIntakeOpen(true)}
          onOpenPropertyLedger={() => navTo("매물장")}
          onOpenBuyerLedger={() => navTo("구입장")}
          propertyCount={propertyLedger.state.status === "ready" ? propertyLedger.state.totalCount : null}
          buyerCount={buyerLedger.state.status === "ready" ? buyerLedger.state.totalCount : null}
        />
      ) : isCampaign ? (
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
          <div className="f1-control-strip__top-row">
            <div className="f1-control-strip__left-group">
              <div className="ledger-tabs" role="tablist" aria-label="장부 유형">{["아파트", "상가", "주택", "재건축"].map((tab, index) => <button key={tab} id={`ledger-tab-${index}`} role="tab" aria-selected={index === 0} aria-controls="ledger-grid-panel" aria-disabled={index !== 0} disabled={index !== 0} tabIndex={index === 0 ? 0 : -1} title={index !== 0 ? "현재 프로토타입에서 사용할 수 없는 장부 유형입니다" : undefined} className={index === 0 ? "active" : ""} type="button">{tab}</button>)}</div>
              {selectedRows.length ? <>
                <strong role="status" aria-live="polite">{selectedRows.length}건 선택됨</strong>
                <Button variant="link" onClick={clearSelection}>전체 선택 해제</Button>
                <Button variant="secondary" icon={<MicrophoneIcon />} aria-controls="f2-modal" aria-describedby={selectedRows.length > 1 ? "f2-selected-entry-help" : undefined} isDisabled={selectedRows.length > 1} onClick={openSelectedRowF2}>선택 세대 음성메모</Button>
                {selectedRows.length > 1 && <span id="f2-selected-entry-help" className="pf-v6-screen-reader">선택 세대 음성메모는 대상 세대를 한 건만 선택해야 합니다.</span>}
                <Button variant="secondary" onClick={() => setBatchEditOpen(true)}>일괄 편집</Button>
                <Button variant="secondary" isDanger onClick={() => requestDeleteRows(selectedRows, "grid")}>삭제</Button>
                <Button variant="secondary" icon={<OutlinedCommentsIcon />} onClick={openDirectMessage}>문자 작성</Button>
                <Button variant="secondary" icon={<FilterIcon />} onClick={startCampaign}>F3 캠페인</Button>
              </> : <>
                <Button ref={addRowButtonRef} icon={<AddCircleOIcon />} onClick={() => handleAddRow()}>행 추가</Button>
                <Button variant="primary" icon={<SaveIcon />} isDisabled={pendingPropertyRows.length === 0 || isSavingPending} isLoading={isSavingPending} onClick={savePendingRows}>{pendingPropertyRows.length > 0 ? `변경 저장 · ${pendingPropertyRows.length.toLocaleString()}건` : "변경 저장"}</Button>
              </>}
            </div>
            <div className="f1-control-strip__right-group">
              {activeNav === "매물장" && <Dropdown isOpen={columnMenuOpen} onSelect={() => setColumnMenuOpen(false)} onOpenChange={setColumnMenuOpen} popperProps={{ placement: "bottom-end" }} toggle={(ref) => <MenuToggle ref={ref} variant="plain" icon={<ColumnsIcon />} onClick={() => setColumnMenuOpen((open) => !open)} isExpanded={columnMenuOpen}>열 프리셋 · {COLUMN_PRESETS.find((preset) => preset.value === columnPreset)?.label || "기본 (12)"}</MenuToggle>}><DropdownList>{COLUMN_PRESETS.map((preset) => <DropdownItem key={preset.value} onClick={() => { setColumnPreset(preset.value); setColumnMenuOpen(false); }}>{preset.label} · {preset.description}</DropdownItem>)}</DropdownList></Dropdown>}
              <Dropdown isOpen={moreOpen} onSelect={() => setMoreOpen(false)} onOpenChange={setMoreOpen} popperProps={{ placement: "bottom-end" }} toggle={(ref) => <MenuToggle ref={ref} variant="plain" aria-label="프로토타입 상태 도구" onClick={() => setMoreOpen((open) => !open)} isExpanded={moreOpen}><EllipsisVIcon /></MenuToggle>}><DropdownList>{viewStates.map(([value, label]) => <DropdownItem key={value} onClick={() => setViewState(value)}>{`프로토타입 상태 · ${label}${viewState === value ? " · 현재" : ""}`}</DropdownItem>)}</DropdownList></Dropdown>
            </div>
          </div>

          <div className="f1-control-strip__bottom-row">
            <div className="filter-row">
              <label className={`filter-control${complexFilter === "전체" ? "" : " active-filter"}`}><FilterIcon aria-hidden="true" /><span>단지</span><select value={complexFilter} onChange={(event) => setComplexFilter(event.target.value)}>{["전체", ...complexOptions.map((option) => option.name)].map((value) => <option key={value}>{value}</option>)}</select></label>
              <label className="filter-control"><span>저장 상태</span><select value={saveFilter} onChange={(event) => setSaveFilter(event.target.value)}>{["전체", "임시저장", "저장 완료"].map((value) => <option key={value}>{value}</option>)}</select></label>
              <Button variant="link" onClick={clearFilters} isDisabled={!searchQuery && complexFilter === "전체" && saveFilter === "전체" && viewState !== "filtered-empty"}>모든 필터 해제</Button>
            </div>
            <nav className="f1-quick-nav" aria-label="F1 보조 업무">{compactNavItems.map((item) => <button key={item} type="button" className={activeNav === item ? "active" : ""} onClick={() => navTo(item)}>{item}</button>)}</nav>
          </div>
        </div> : <div className="f1-control-strip f1-control-strip--buyer">
          <div className="f1-control-strip__left-group">
            {/* 매물장과 같은 자리·같은 순서에 둔다. 장부를 오갈 때 행 추가를 다시 찾지 않게 한다. */}
            <Button icon={<AddCircleOIcon />} onClick={handleAddBuyerRow}>행 추가</Button>
            <Button variant="primary" icon={<SaveIcon />} isDisabled={pendingBuyerRows.length === 0 || isSavingPending} isLoading={isSavingPending} onClick={savePendingRows}>{pendingBuyerRows.length > 0 ? `변경 저장 · ${pendingBuyerRows.length.toLocaleString()}건` : "변경 저장"}</Button>
          </div>
          <nav className="f1-quick-nav" aria-label="F1 보조 업무">{compactNavItems.map((item) => <button key={item} type="button" className={activeNav === item ? "active" : ""} onClick={() => navTo(item)}>{item}</button>)}</nav>
        </div>}

        {activeNav === "구입장" ? <BuyerLedgerGrid rows={buyerRows} onRowsChange={setBuyerRows} onOpenDetail={setDetailRow} assigneeFilter={buyerAssigneeFilter} onAssigneeFilterChange={setBuyerAssigneeFilter} periodMode={buyerPeriodMode} onPeriodModeChange={setBuyerPeriodMode} /> : <LedgerGrid rows={rows} onRowsChange={setRows} onOpenDetail={(row) => setDetailRow({ ...row, ledgerType: "property", rowKind: "property" })} onSelectionChange={setSelectedRows} selectedRowIds={selectedRowIds} selectionResetToken={selectionResetToken} viewState={effectiveViewState} searchQuery={searchQuery} complexFilter={complexFilter} saveFilter={saveFilter} columnPreset={columnPreset} onRetry={() => { setViewState("normal"); propertyLedger.reload(); }} onClearFilters={clearFilters} onAddRow={handleAddRow} readOnly={false} />}
        <footer className="grid-statusbar"><span>{activeNav === "매물장" ? filteredCount.toLocaleString() : buyerRows.length.toLocaleString()}건 표시</span><span>{selectedRows.length}건 선택</span><span>{viewState === "offline" ? "변경 내용 브라우저 보관" : "수정 내용은 임시저장"}</span><span className="statusbar-spacer" /><span>{activeNav === "매물장" ? "정렬: 동·호 오름차순" : "정렬: 최종접촉일"}</span><span>{activeNav === "매물장" ? "기본 (12) / 전체 (30)" : "구입장 17열"}</span><span>Enter 편집 · Space 선택 · Esc 취소</span></footer>
      </>}
    </main>

    {isBuyerDetail ? (
      <BuyerDetailWorkspace
        row={detailRow}
        isOpen={Boolean(detailRow)}
        focusF2Request={f2FocusRequest}
        onClose={closeDetail}
        onDiscard={discardDetail}
        onDelete={deleteRowFromDetail}
        onSave={saveDetail}
        onOpenCrossMatch={openCrossMatch}
        isCrossMatchOpen={crossMatchOpen}
        crossMatchPanel={crossMatchPanel}
      />
    ) : (
      <DetailWorkspace
        row={detailRow}
        isOpen={Boolean(detailRow)}
        focusF2Request={f2FocusRequest}
        complexOptions={complexOptions}
        onCreateComplex={handleCreateComplex}
        onDeleteComplex={handleDeleteComplex}
        onClose={closeDetail}
        onDiscard={discardDetail}
        onDelete={deleteRowFromDetail}
        onSave={saveDetail}
        onOpenCrossMatch={openCrossMatch}
        isCrossMatchOpen={crossMatchOpen}
        crossMatchPanel={crossMatchPanel}
      />
    )}

    <VoiceMemoModal
      isOpen={intakeOpen}
      ledgerType="auto"
      draft={intakeDraft}
      onClose={() => setIntakeOpen(false)}
      onApply={applyIntake}
    />

    <Modal variant="small" isOpen={Boolean(messageComposer)} onClose={closeMessageComposer}>
      <ModalHeader title="문자 작성" description="손님별 문안과 번호를 확인한 뒤 복사합니다. 실제 발송은 외부 도구에서 진행합니다." />
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
        <details className="message-composer__details" open>
          <summary>번호 목록 · {composerRecipients.length}건</summary>
          <ul className="message-composer__number-list">
            {composerRecipients.map((recipient) => {
              const key = recipientKey(recipient);
              const isActive = key === messageComposer.activeRecipientId;
              return <li key={key} className={isActive ? "is-active" : ""}>
                <span>{recipient.title} · {recipient.phone}</span>
                <Button variant={isActive ? "primary" : "secondary"} onClick={() => selectComposerRecipient(recipient)} aria-pressed={isActive}>
                  {isActive ? "현재 문안" : "이 손님 문안"}
                </Button>
              </li>;
            })}
          </ul>
          <label>복사할 번호<textarea value={composerRecipients.map((recipient) => recipient.phone).join("\n")} readOnly /></label>
        </details>
        <label className="message-composer__draft-label"><span>문안{activeComposerRecipient ? ` · ${activeComposerRecipient.title}` : ""}</span><span>{messageComposer.draft.length.toLocaleString()}자</span><textarea value={messageComposer.draft} onChange={(event) => changeComposerDraft(event.target.value)} /></label>
        {composerRecipients.length > 1 && <p className="message-composer__draft-hint">문안은 손님마다 따로 보관됩니다. 번호 목록에서 손님을 바꿔도 고쳐 둔 문안은 그대로 남습니다.</p>}
      </div>}</ModalBody>
      <ModalFooter><Button variant={messageCopied ? "secondary" : "primary"} isDisabled={!composerRecipients.length} onClick={async () => { try { if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable"); await navigator.clipboard.writeText(composerRecipients.map((recipient) => recipient.phone).join("\n")); setMessageCopied(true); setToast({ variant: "success", title: "번호 목록을 복사했습니다. 발송은 외부 도구에서 진행합니다." }); } catch { setMessageCopied(false); setToast({ variant: "warning", title: "번호를 복사하지 못했습니다. 번호 목록을 선택해 직접 복사해 주세요." }); } }}>{messageCopied ? "번호 목록 복사됨" : "번호 목록 복사"}</Button><Button variant="link" onClick={closeMessageComposer}>닫기</Button></ModalFooter>
    </Modal>
    <Modal variant="small" isOpen={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)}>
      <ModalHeader titleIconVariant="warning" title="삭제할까요?" description="삭제한 행은 장부 목록과 검색에서 즉시 사라집니다. 데이터는 서버에 남고 상담 로그·매물 이력도 보존되지만, 화면에서 되돌리는 기능은 없습니다. 되살리려면 관리자에게 요청해야 합니다." />
      <ModalBody>
        <p role="status">대상 {(deleteTarget?.rows.length ?? 0).toLocaleString()}건</p>
        <ul className="delete-target-list">
          {(deleteTarget?.rows ?? []).slice(0, 5).map((row) => <li key={row.id}>{row.ledgerType === "buyer" || row.rowKind === "buyer" ? (row.buyer || "별칭 미입력") : `${row.complex || "단지 미입력"} ${row.building || "-"}동 ${row.unit || "-"}호`}</li>)}
          {(deleteTarget?.rows.length ?? 0) > 5 && <li>외 {((deleteTarget?.rows.length ?? 0) - 5).toLocaleString()}건</li>}
        </ul>
      </ModalBody>
      <ModalFooter>
        <Button variant="danger" onClick={confirmDelete} isLoading={isDeleting} isDisabled={isDeleting}>삭제</Button>
        <Button variant="link" onClick={() => setDeleteTarget(null)} isDisabled={isDeleting}>취소</Button>
      </ModalFooter>
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
    {effectiveViewState === "loading" && <div className="global-progress" aria-label="그리드 데이터 불러오는 중"><Spinner size="md" /></div>}
    {toast && <Alert className="workspace-alert" variant={toast.variant} isInline isLiveRegion title={toast.title} actionClose={<Button variant="plain" aria-label="알림 닫기" onClick={() => setToast(null)} />} />}
  </div>;
}
