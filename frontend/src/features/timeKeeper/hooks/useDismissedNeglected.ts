/**
 * 밀린 재연락·재확인의 "다시 보지 않기" 상태를 화면에 연결한다.
 *
 * 저장소 자체의 읽기·쓰기는 `model/dismissed.ts`가 맡는다. 여기서는 그 저장소를 컴포넌트
 * 생명주기 동안 하나만 만들고, `dismiss` 호출이 실제로 다시 그리게 만드는 일만 한다.
 */

import { useCallback, useRef, useState } from "react";
import { createDismissedNeglectedStore } from "../model/dismissed.ts";

export interface DismissedNeglectedControl {
  isDismissed: (key: string) => boolean;
  dismiss: (key: string) => void;
}

export function useDismissedNeglected(): DismissedNeglectedControl {
  const store = useRef(createDismissedNeglectedStore());
  // 저장소는 참조를 그대로 유지하는 가변 상태라, 값이 바뀌었다는 사실만 다시 그리기에 알린다.
  const [, notifyChanged] = useState(0);

  const dismiss = useCallback((key: string) => {
    store.current.dismiss(key);
    notifyChanged((count) => count + 1);
  }, []);

  const isDismissed = useCallback((key: string) => store.current.isDismissed(key), []);

  return { isDismissed, dismiss };
}
