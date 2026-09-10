import {
  Bullseye,
  Button,
  EmptyState,
  EmptyStateActions,
  EmptyStateBody,
  EmptyStateFooter,
} from "@patternfly/react-core";
import { ExclamationCircleIcon } from "@patternfly/react-icons";
import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

interface RootErrorBoundaryProps {
  children: ReactNode;
}

interface RootErrorBoundaryState {
  failed: boolean;
}

/**
 * React 렌더링 오류가 빈 화면으로 끝나지 않게 하는 최상위 복구 경계.
 *
 * 이 경계는 오류 원문을 화면·로그·외부 서비스로 보내지 않는다. 이번 범위에는 브라우저 telemetry가
 * 없으므로 사용자가 할 수 있는 안전한 복구 동작만 제공한다.
 */
export class RootErrorBoundary extends Component<RootErrorBoundaryProps, RootErrorBoundaryState> {
  override state: RootErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): RootErrorBoundaryState {
    return { failed: true };
  }

  override componentDidCatch(_error: Error, _errorInfo: ErrorInfo): void {
    // 의도적으로 전송하거나 출력하지 않는다. 브라우저 telemetry는 현재 범위가 아니다.
  }

  override render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return <RootErrorFallback />;
  }
}

function RootErrorFallback() {
  return (
    <main aria-label="애플리케이션 오류">
      <Bullseye style={{ minHeight: "100vh" }}>
        <EmptyState
          status="danger"
          icon={ExclamationCircleIcon}
          titleText="화면을 표시하지 못했습니다"
          headingLevel="h1"
        >
          <EmptyStateBody>
            작성 중인 변경 사항이 저장되지 않았을 수 있습니다. 화면을 새로고침한 뒤 다시 시도해
            주세요.
          </EmptyStateBody>
          <EmptyStateFooter>
            <EmptyStateActions>
              <Button type="button" variant="primary" onClick={() => window.location.reload()}>
                화면 새로고침
              </Button>
            </EmptyStateActions>
          </EmptyStateFooter>
        </EmptyState>
      </Bullseye>
    </main>
  );
}
