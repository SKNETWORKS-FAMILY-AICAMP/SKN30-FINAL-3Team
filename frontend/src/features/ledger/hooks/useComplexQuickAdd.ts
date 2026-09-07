/**
 * 새 단지 빠른 추가.
 *
 * 매물장 화면 여러 곳(필터 옆, 상세)에서 짧은 모달로 단지를 만드는 상태와 제출 흐름을 다룬다.
 * 단지명은 서버 계약(`backend/src/api/schemas/property_ledger.py`의
 * `PropertyComplexCreateRequest.name`, `min_length=1, max_length=150`)과 같은 기준으로
 * 클라이언트에서도 먼저 검증해, 잘못된 입력이 그대로 API 경계를 넘지 않게 한다.
 * 주소(`road_address`)는 서버에 선언된 길이 제한이 없어 trim만 한다.
 *
 * 검증이나 생성 요청이 실패하면 원인을 단지명 입력에 연결된 오류로 표시하고 그 입력으로
 * 포커스를 되돌린다. 지금까지 실패 원인(빈 값, 길이 초과, 중복, 서버 오류)이 모두 단지명과
 * 관련돼 있어 필드를 하나만 둔다.
 */

import { useCallback, useRef, useState } from "react";
import type { RefObject } from "react";

const COMPLEX_NAME_MAX_LENGTH = 150;

export interface ComplexQuickAddInput {
  name: string;
  address: string;
}

export interface ComplexQuickAddController<TCreated> {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  name: string;
  setName: (value: string) => void;
  address: string;
  setAddress: (value: string) => void;
  nameError: string;
  isSubmitting: boolean;
  nameInputRef: RefObject<HTMLInputElement | null>;
  submit: () => Promise<TCreated | undefined>;
}

export function useComplexQuickAdd<TCreated>(
  onCreate: (input: ComplexQuickAddInput) => Promise<TCreated>,
): ComplexQuickAddController<TCreated> {
  const [isOpen, setIsOpen] = useState(false);
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [nameError, setNameError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const nameInputRef = useRef<HTMLInputElement>(null);

  const open = useCallback(() => {
    setName("");
    setAddress("");
    setNameError("");
    setIsOpen(true);
  }, []);

  const close = useCallback(() => {
    if (isSubmitting) return;
    setIsOpen(false);
  }, [isSubmitting]);

  const submit = useCallback(async (): Promise<TCreated | undefined> => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setNameError("단지명을 입력해 주세요.");
      nameInputRef.current?.focus();
      return undefined;
    }
    if (trimmedName.length > COMPLEX_NAME_MAX_LENGTH) {
      setNameError(`단지명은 ${COMPLEX_NAME_MAX_LENGTH}자를 넘을 수 없습니다.`);
      nameInputRef.current?.focus();
      return undefined;
    }
    setIsSubmitting(true);
    setNameError("");
    try {
      const created = await onCreate({ name: trimmedName, address: address.trim() });
      setIsOpen(false);
      return created;
    } catch (error) {
      setNameError(error instanceof Error ? error.message : "단지를 추가하지 못했습니다.");
      nameInputRef.current?.focus();
      return undefined;
    } finally {
      setIsSubmitting(false);
    }
  }, [address, name, onCreate]);

  return { isOpen, open, close, name, setName, address, setAddress, nameError, isSubmitting, nameInputRef, submit };
}
