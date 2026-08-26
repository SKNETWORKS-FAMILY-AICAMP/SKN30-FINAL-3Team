/**
 * 첫 화면.
 *
 * 이 플랫폼에서 시작할 수 있는 일은 세 가지다. 음성메모로 새 상담을 접수하거나,
 * 매물장을 열거나, 구입장을 여는 것이다. 장부를 곧바로 띄우면 신규 접수가
 * 표 안의 부수 동작으로 밀리므로 여기서 세 진입점을 같은 높이에 둔다.
 */

import { ArrowRightIcon, BuildingIcon, MicrophoneIcon, UsersIcon } from "@patternfly/react-icons";
import "./HomeScreen.css";

export interface HomeScreenProps {
  onVoiceIntake: () => void;
  onOpenPropertyLedger: () => void;
  onOpenBuyerLedger: () => void;
  /** 장부에 실린 행 수. 아직 불러오지 못했으면 표시하지 않는다. */
  propertyCount: number | null;
  buyerCount: number | null;
}

function countLabel(count: number | null): string {
  return count == null ? "불러오는 중" : `${count.toLocaleString()}건`;
}

export function HomeScreen({
  onVoiceIntake,
  onOpenPropertyLedger,
  onOpenBuyerLedger,
  propertyCount,
  buyerCount,
}: HomeScreenProps) {
  return (
    <section
      className="home-screen"
      aria-labelledby="home-screen-heading"
      data-screen-id="F1-PG-000"
    >
      <div className="home-screen__inner">
        <h1 id="home-screen-heading" className="home-screen__heading">무엇부터 할까요?</h1>
        <p className="home-screen__lead">
          상담 음성으로 새 행을 접수하거나 장부를 바로 열 수 있습니다.
        </p>

        <ul className="home-screen__actions">
          <li>
            <button type="button" className="home-action home-action--primary" onClick={onVoiceIntake}>
              <span className="home-action__icon" aria-hidden="true"><MicrophoneIcon /></span>
              <span className="home-action__body">
                <strong className="home-action__title">음성 메모 입력</strong>
                <span className="home-action__desc">
                  음성을 분석해 매도의뢰는 매물장에, 매수문의는 구입장에 신규 행으로 추가합니다.
                </span>
              </span>
              <span className="home-action__go" aria-hidden="true"><ArrowRightIcon /></span>
            </button>
          </li>
          <li>
            <button type="button" className="home-action" onClick={onOpenPropertyLedger}>
              <span className="home-action__icon" aria-hidden="true"><BuildingIcon /></span>
              <span className="home-action__body">
                <strong className="home-action__title">매물장 연결</strong>
                <span className="home-action__desc">세대와 매물 정보를 표로 조회하고 편집합니다.</span>
              </span>
              <span className="home-action__meta">{countLabel(propertyCount)}</span>
              <span className="home-action__go" aria-hidden="true"><ArrowRightIcon /></span>
            </button>
          </li>
          <li>
            <button type="button" className="home-action" onClick={onOpenBuyerLedger}>
              <span className="home-action__icon" aria-hidden="true"><UsersIcon /></span>
              <span className="home-action__body">
                <strong className="home-action__title">구입장 연결</strong>
                <span className="home-action__desc">손님과 희망 조건을 표로 조회하고 편집합니다.</span>
              </span>
              <span className="home-action__meta">{countLabel(buyerCount)}</span>
              <span className="home-action__go" aria-hidden="true"><ArrowRightIcon /></span>
            </button>
          </li>
        </ul>
      </div>
    </section>
  );
}
