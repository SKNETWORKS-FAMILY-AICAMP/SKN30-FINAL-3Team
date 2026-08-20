/**
 * 단지 선택지.
 *
 * 단지는 세대의 필수 상위 레코드다. `POST /property-units`가 `complex_id`(숫자)를 요구하므로
 * 화면이 이름만 들고 있으면 저장할 수 없다. 그래서 선택지는 이름이 아니라 서버 id를 함께 싣는다.
 *
 * 목록과 생성 모두 `/property-complexes`를 쓴다. 화면에서 만든 단지도 서버 id를 받아 돌아오므로
 * 곧바로 세대 저장에 쓸 수 있다.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { LedgerApiError, isCanceled } from "../api/errors.ts";
import { ledgerTransport } from "../api/ledgerTransport.ts";
import { MAX_PAGE_SIZE } from "../model/dto.ts";
import type { ComplexSummaryDto } from "../model/dto.ts";

export interface ComplexOption {
  id: number;
  name: string;
  address: string;
  /** 삭제 요청에 함께 보내는 낙관적 잠금 값. */
  rowVersion: number;
}

export interface ComplexCreateInput {
  name: string;
  address?: string;
}

export interface ComplexOptions {
  options: ComplexOption[];
  status: "loading" | "ready" | "error";
  error: LedgerApiError | null;
  /** 단지를 만들고 서버가 준 id로 선택지에 더한다. 저장에 바로 쓸 수 있는 값을 돌려준다. */
  createComplex: (input: ComplexCreateInput) => Promise<ComplexOption>;
  /** 단지를 지운다. 세대가 남아 있으면 서버가 거절하고 그 사유가 그대로 올라온다. */
  deleteComplex: (option: ComplexOption) => Promise<void>;
  reload: () => void;
}

function toOption(dto: ComplexSummaryDto): ComplexOption {
  return { id: dto.id, name: dto.name, address: dto.road_address ?? "", rowVersion: dto.row_version };
}

function byName(left: ComplexOption, right: ComplexOption): number {
  return left.name.localeCompare(right.name, "ko");
}

export function useComplexOptions(options: { enabled?: boolean } = {}): ComplexOptions {
  const enabled = options.enabled ?? true;
  const [items, setItems] = useState<ComplexOption[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<LedgerApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    setStatus("loading");

    ledgerTransport
      .listComplexes({ limit: MAX_PAGE_SIZE, offset: 0 }, controller.signal)
      .then((page) => {
        if (controller.signal.aborted) return;
        setItems(page.items.map(toOption).sort(byName));
        setStatus("ready");
        setError(null);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted || isCanceled(cause)) return;
        setStatus("error");
        setError(
          cause instanceof LedgerApiError
            ? cause
            : new LedgerApiError({ kind: "server", message: "단지 목록을 불러오지 못했습니다.", cause }),
        );
      });

    return () => controller.abort();
  }, [enabled, reloadToken]);

  const createComplex = useCallback(async (input: ComplexCreateInput): Promise<ComplexOption> => {
    const created = await ledgerTransport.createComplex({
      name: input.name.trim(),
      road_address: input.address?.trim() || null,
      memo: null,
    });
    const option = toOption(created);
    setItems((current) => [...current.filter((entry) => entry.id !== option.id), option].sort(byName));
    return option;
  }, []);

  const deleteComplex = useCallback(async (option: ComplexOption): Promise<void> => {
    await ledgerTransport.deleteComplex(option.id, option.rowVersion);
    setItems((current) => current.filter((entry) => entry.id !== option.id));
  }, []);

  const reload = useCallback(() => setReloadToken((current) => current + 1), []);

  return useMemo(
    () => ({ options: items, status, error, createComplex, deleteComplex, reload }),
    [items, status, error, createComplex, deleteComplex, reload],
  );
}
