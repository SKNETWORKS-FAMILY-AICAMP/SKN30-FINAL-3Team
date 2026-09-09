import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  DataList,
  DataListItem,
  DataListItemRow,
  DataListItemCells,
  DataListCell,
  Drawer,
  DrawerActions,
  DrawerCloseButton,
  DrawerContent,
  DrawerContentBody,
  DrawerHead,
  DrawerPanelBody,
  DrawerPanelContent,
  FormSelect,
  FormSelectOption,
  Label,
  Skeleton,
  Tab,
  Tabs,
  TabTitleText,
  TextInput,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
} from "@patternfly/react-core";
import { ApiError, isCanceled } from "../../../shared/api/index.ts";
import { judgmentApi } from "./api.ts";
import type { ListQuery } from "./api.ts";
import { dateLabel, filters, gradeLabel } from "./model.ts";
import type { JudgmentPage, JudgmentTarget, ResultFilter } from "./model.ts";
import type { OpenLedger } from "./CandidateDetail.tsx";
import { JudgmentResult } from "./JudgmentResult.tsx";
import { readJudgmentLocation, writeJudgmentLocation } from "./navigation.ts";
import type { JudgmentSelection } from "./navigation.ts";
import {
  isDenied,
  isInvalidCursor,
  judgmentError,
} from "./useJudgmentTarget.ts";
import { TargetStatus } from "./TargetStatus.tsx";
import "./Judgments.css";
interface Props {
  active: boolean;
  suspended?: boolean;
  userId?: number;
  assignees?: readonly { id: number; displayName: string }[];
  complexes?: readonly { id: number; name: string }[];
  onOpenLedger: OpenLedger;
  onSessionExpired: () => void;
}
export function JudgmentResultsPage({
  active,
  suspended = false,
  userId,
  assignees = [],
  complexes = [],
  onOpenLedger,
  onSessionExpired,
}: Props) {
  const [selection, setSelection] = useState<JudgmentSelection | null>(
    () => readJudgmentLocation(window.location.search).selection,
  );
  const [query, setQuery] = useState<ListQuery>({
    anchor_type: selection?.anchor_type ?? "LISTING",
    filter: "HAS_MATCH",
    limit: 20,
  });
  const [search, setSearch] = useState("");
  const [page, setPage] = useState<JudgmentPage | null>(null);
  const [pendingPage, setPendingPage] = useState<JudgmentPage | null>(null);
  const [error, setError] = useState("");
  const [pageNotice, setPageNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<(string | undefined)[]>([]);
  const [refresh, setRefresh] = useState(0);
  const trigger = useRef<HTMLElement | null>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const session = useRef(onSessionExpired);
  session.current = onSessionExpired;
  useEffect(() => {
    if (active) writeJudgmentLocation(selection);
  }, [active, selection]);
  useEffect(() => {
    const normalized = search.trim() || undefined;
    if (!active || query.q === normalized) return;
    const timer = setTimeout(() => {
      setQuery((q) => ({ ...q, q: normalized, cursor: undefined }));
      setHistory([]);
    }, 350);
    return () => clearTimeout(timer);
  }, [search, active, query.q]);
  useEffect(() => {
    if (!active || suspended) return;
    const c = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    setLoading(true);
    setError("");
    const load = async (background = false) => {
      try {
        const value = await judgmentApi.list(query, c.signal);
        if (c.signal.aborted) return;
        if (background) setPendingPage(value);
        else {
          setPage(value);
          setPendingPage(null);
        }
        setError("");
      } catch (cause) {
        if (c.signal.aborted || isCanceled(cause)) return;
        if (isInvalidCursor(cause) && query.cursor != null) {
          setQuery((q) => ({ ...q, cursor: undefined }));
          setHistory([]);
          setPage(null);
          setPendingPage(null);
          setPageNotice(
            "목록이 변경되어 첫 페이지로 돌아왔습니다. 필터와 선택 대상은 유지했습니다.",
          );
          return;
        }
        if (isDenied(cause)) {
          setPage(null);
          setPendingPage(null);
          setSelection(null);
        }
        setError(judgmentError(cause));
        if (cause instanceof ApiError && cause.kind === "unauthorized")
          session.current();
      } finally {
        if (!c.signal.aborted) {
          setLoading(false);
          timer = setTimeout(() => {
            if (!document.hidden) void load(true);
          }, 10_000);
        }
      }
    };
    const resume = () => {
      if (!document.hidden && !c.signal.aborted) {
        clearTimeout(timer);
        void load(true);
      }
    };
    document.addEventListener("visibilitychange", resume);
    void load();
    return () => {
      c.abort();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", resume);
    };
  }, [active, suspended, query, refresh]);
  const change = (patch: Partial<ListQuery>) => {
    setQuery((q) => ({ ...q, ...patch, cursor: undefined }));
    setHistory([]);
    setPage(null);
    setPendingPage(null);
  };
  const select = (value: JudgmentSelection | null) => {
    setSelection(value);
    if (!value)
      requestAnimationFrame(() => {
        const element = trigger.current;
        const current = element?.id
          ? document.getElementById(element.id)
          : element;
        current?.focus();
      });
  };
  useEffect(() => {
    if (!active || !selection || suspended) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (
        event.key !== "Escape" ||
        event.defaultPrevented ||
        document.querySelector('[role="dialog"]')
      )
        return;
      event.preventDefault();
      select(null);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [active, selection, suspended]);
  const open = (target: JudgmentTarget, element: HTMLElement) => {
    trigger.current = element;
    select({
      anchor_type: target.anchor.anchor_type,
      anchor_id: target.anchor.anchor_id,
      result_id: target.result_id,
    });
  };
  const refreshPage = () => {
    if (pendingPage) {
      setPage(pendingPage);
      setPendingPage(null);
    } else setRefresh((v) => v + 1);
  };
  if (!active) return null;
  const availableAssignees =
    page?.assignees.map((a) => ({ id: a.id, displayName: a.display_name })) ??
    assignees;
  const panel = (
    <DrawerPanelContent
      widths={{ default: "width_66" }}
      inert={selection == null || suspended}
    >
      <DrawerHead>
        <h2 ref={title} tabIndex={-1}>
          판정 결과 상세
        </h2>
        <DrawerActions>
          <DrawerCloseButton
            onClick={() => select(null)}
            aria-label="결과 상세 닫기"
          />
        </DrawerActions>
      </DrawerHead>
      <DrawerPanelBody>
        {selection && !suspended && (
          <JudgmentResult
            selection={selection}
            onSelection={select}
            onOpenLedger={onOpenLedger}
            onSessionExpired={onSessionExpired}
          />
        )}
      </DrawerPanelBody>
    </DrawerPanelContent>
  );
  return (
    <section
      className="f3-judgments"
      aria-label="교차 판정 업무 목록"
      onKeyDown={(e) => {
        if (e.key === "Escape" && selection && !suspended) {
          e.stopPropagation();
          select(null);
        }
      }}
    >
      <header className="f3-judgments__heading">
        <div>
          <h1>교차 판정</h1>
          <p>
            준비된 연결 후보를 확인하고 다음 상담을 검토하세요. 등급은 같은 기준
            대상 안의 비교입니다.
          </p>
        </div>
        <Button variant="secondary" isDisabled={loading} onClick={refreshPage}>
          목록 새로고침
        </Button>
      </header>
      <p>마지막 목록 확인 {page ? dateLabel(page.checked_at) : "확인 중"}</p>
      {pendingPage && pendingPage.revision !== page?.revision && (
        <Alert variant="info" isInline title="목록에 변경이 있습니다">
          <Button variant="link" isInline onClick={refreshPage}>
            새 목록 적용
          </Button>
        </Alert>
      )}
      <Tabs
        activeKey={query.anchor_type}
        onSelect={(_e, key) => {
          if (key === "LISTING" || key === "REQUIREMENT") {
            change({ anchor_type: key });
            select(null);
          }
        }}
        aria-label="판정 기준"
      >
        <Tab
          eventKey="LISTING"
          title={<TabTitleText>매물 기준</TabTitleText>}
        />
        <Tab
          eventKey="REQUIREMENT"
          title={<TabTitleText>손님 기준</TabTitleText>}
        />
      </Tabs>
      <Toolbar>
        <ToolbarContent>
          <ToolbarItem>
            <label htmlFor="f3-result-filter">결과 상태</label>
            <FormSelect
              id="f3-result-filter"
              value={query.filter}
              onChange={(_e, value) => {
                if (filters.some((f) => f.value === value))
                  change({ filter: value as ResultFilter });
              }}
            >
              {filters.map((f) => (
                <FormSelectOption
                  key={f.value}
                  value={f.value}
                  label={`${f.label} (${page?.counts[f.value] ?? "…"})`}
                />
              ))}
            </FormSelect>
          </ToolbarItem>
          <ToolbarItem>
            <label htmlFor="f3-result-search">대상·후보 검색</label>
            <TextInput
              id="f3-result-search"
              value={search}
              onChange={(_e, value) => setSearch(value)}
              placeholder="표시명 또는 단지"
            />
          </ToolbarItem>
          <ToolbarItem>
            <label htmlFor="f3-assignee">기준 대상 담당자</label>
            <FormSelect
              id="f3-assignee"
              value={query.assignee_id ?? ""}
              onChange={(_e, value) =>
                change({ assignee_id: value ? Number(value) : undefined })
              }
            >
              <FormSelectOption value="" label="사무소 전체" />
              {availableAssignees.map((a) => (
                <FormSelectOption
                  key={a.id}
                  value={a.id}
                  label={a.displayName}
                />
              ))}
            </FormSelect>
          </ToolbarItem>
          {userId != null && (
            <ToolbarItem>
              <Button
                variant="link"
                onClick={() => change({ assignee_id: userId })}
              >
                내 담당
              </Button>
            </ToolbarItem>
          )}
        </ToolbarContent>
      </Toolbar>
      <details>
        <summary>거래유형·단지 필터</summary>
        <Toolbar>
          <ToolbarContent>
            <ToolbarItem>
              <label htmlFor="f3-trade">거래유형</label>
              <FormSelect
                id="f3-trade"
                value={query.trade_type ?? ""}
                onChange={(_e, value) =>
                  change({ trade_type: value || undefined })
                }
              >
                {[
                  ["", "전체"],
                  ["SALE", "매매"],
                  ["JEONSE", "전세"],
                  ["MONTHLY_RENT", "월세"],
                ].map(([value, label]) => (
                  <FormSelectOption
                    key={value}
                    value={value}
                    label={label ?? ""}
                  />
                ))}
              </FormSelect>
            </ToolbarItem>
            <ToolbarItem>
              <label htmlFor="f3-complex">단지</label>
              <FormSelect
                id="f3-complex"
                value={query.complex_id ?? ""}
                onChange={(_e, value) =>
                  change({ complex_id: value ? Number(value) : undefined })
                }
              >
                <FormSelectOption value="" label="전체" />
                {complexes.map((c) => (
                  <FormSelectOption key={c.id} value={c.id} label={c.name} />
                ))}
              </FormSelect>
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
      </details>
      <div className="f3-judgments__actions" aria-label="숨겨진 결과 확인">
        {filters
          .filter((f) => ["HAS_UNJUDGED", "NEEDS_ATTENTION"].includes(f.value))
          .map((f) => (
            <Button
              key={f.value}
              variant="link"
              onClick={() => change({ filter: f.value })}
            >
              {f.label} {page?.counts[f.value] ?? "…"}건 보기
            </Button>
          ))}
      </div>
      {pageNotice && <Alert variant="info" isInline title={pageNotice} />}
      {error && (
        <Alert variant="warning" isInline title={error}>
          <Button
            variant="link"
            isInline
            onClick={() => setRefresh((v) => v + 1)}
          >
            다시 조회
          </Button>
        </Alert>
      )}
      <Drawer
        isExpanded={selection != null && !suspended}
        onExpand={() => title.current?.focus()}
      >
        <DrawerContent panelContent={panel}>
          <DrawerContentBody>
            {loading && !page && (
              <Skeleton screenreaderText="판정 목록 불러오는 중" />
            )}
            {page?.items.length === 0 && (
              <Alert
                variant="info"
                isInline
                title="현재 필터에 해당하는 대상이 없습니다"
              >
                미판정 조건 후보와 확인 필요 목록도 확인해 주세요.
              </Alert>
            )}
            {page && (
              <DataList aria-label="판정 대상 목록" isCompact>
                {page.items.map((target) => (
                  <DataListItem
                    key={`${target.anchor.anchor_type}-${target.anchor.anchor_id}`}
                    aria-labelledby={`f3-anchor-${target.anchor.anchor_id}`}
                  >
                    <DataListItemRow>
                      <DataListItemCells
                        dataListCells={[
                          <DataListCell key="target">
                            <Button
                              id={`f3-anchor-${target.anchor.anchor_id}`}
                              variant="link"
                              isInline
                              onClick={(e) => open(target, e.currentTarget)}
                            >
                              {target.anchor.display_name} 결과 보기
                            </Button>
                            <p>
                              {target.anchor.current_conditions ??
                                "현재 조건 미기재"}{" "}
                              · 담당 {target.anchor.assignee_name ?? "미지정"}
                            </p>
                            <TargetStatus
                              target={target}
                              snapshotOutdated={
                                pendingPage != null &&
                                pendingPage.revision !== page.revision
                              }
                            />
                          </DataListCell>,
                          <DataListCell key="candidates">
                            {target.representative_candidates.map((c) => (
                              <p key={c.candidate_id}>
                                {c.target.display_name} · 담당{" "}
                                {c.target.assignee_name ?? "미지정"}{" "}
                                <Label>{gradeLabel(c.match_grade)}</Label>{" "}
                                {(target.freshness !== "CURRENT" ||
                                  (pendingPage != null &&
                                    pendingPage.revision !==
                                      page.revision)) && (
                                  <Label color="orange">
                                    {target.freshness !== "CURRENT"
                                      ? "이전 분석"
                                      : "이전 조회"}
                                  </Label>
                                )}
                                <br />
                                {c.target.current_conditions ?? ""}
                                <br />
                                {c.evaluation_basis ?? "AI 미판정 조건 후보"}
                              </p>
                            ))}
                          </DataListCell>,
                        ]}
                      />
                    </DataListItemRow>
                  </DataListItem>
                ))}
              </DataList>
            )}
            <div className="f3-judgments__actions">
              <Button
                variant="secondary"
                isDisabled={history.length === 0 || loading}
                onClick={() => {
                  setQuery((q) => ({ ...q, cursor: history.at(-1) }));
                  setHistory((h) => h.slice(0, -1));
                }}
              >
                이전 페이지
              </Button>
              <span>페이지 {history.length + 1}</span>
              <Button
                variant="secondary"
                isDisabled={!page?.next_cursor || loading}
                onClick={() => {
                  setHistory((h) => [...h, query.cursor]);
                  setQuery((q) => ({
                    ...q,
                    cursor: page?.next_cursor ?? undefined,
                  }));
                }}
              >
                다음 페이지
              </Button>
            </div>
          </DrawerContentBody>
        </DrawerContent>
      </Drawer>
    </section>
  );
}
