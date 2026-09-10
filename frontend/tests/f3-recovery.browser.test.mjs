import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { before, after, test } from "node:test";
import { chromium } from "playwright";

let server, browser, baseUrl;
before(async () => {
  server = spawn(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "0"], {
    env: {...process.env, VITE_LEDGER_SOURCE:"mock", VITE_F3_SOURCE:"mock",
      VITE_AUTH_DEVELOPMENT_ENABLED:"true", VITE_MOCK_LATENCY_MS:"0", VITE_MOCK_ROW_COUNT:"40",
      VITE_API_BASE_URL:"/api/v1", FRONTEND_BACKEND_ORIGIN:"http://127.0.0.1:8013"},
    stdio:["ignore","pipe","pipe"],
  });
  baseUrl = await new Promise((resolve,reject) => {
    const timer = setTimeout(() => reject(new Error("Vite startup timeout")),30000);
    let output = "";
    const read = data => {
      output += String(data);
      const match=String(data).replace(/\x1b\[[0-9;]*m/g,"").match(/http:\/\/127\.0\.0\.1:\d+\//);
      if(match){clearTimeout(timer);resolve(match[0]);}
    };
    server.stdout.on("data",read);server.stderr.on("data",read);
    server.on("exit", code=>{clearTimeout(timer);reject(new Error(`Vite exited ${code}: ${output}`));});
  });
  browser=await chromium.launch();
});
after(async()=>{await browser?.close();server?.kill();});
async function fixture(t, changes={}) {
  const page=await browser.newPage();t.after(()=>page.close());
  await page.clock.install();
  await page.goto(`${baseUrl}tests/fixtures/f3-recovery.html`);
  await page.getByRole("button",{name:"열기",exact:true}).waitFor();
  await page.evaluate(changes=>Object.assign(window.recovery,changes),changes);
  return page;
}
async function state(page,value){await page.waitForFunction(value=>document.querySelector("#state")?.textContent===value,value);}
async function stats(page){return page.evaluate(()=>({submissions:window.recovery.submissions,statusGets:window.recovery.statusGets,resultGets:window.recovery.resultGets}));}

test("60초를 넘어 300초까지 조회하고 중단 후 기존 실행을 GET으로만 복구한다",async t=>{
  const p=await fixture(t);
  await p.getByRole("button",{name:"열기",exact:true}).click();await state(p,"judging");
  await p.clock.runFor(66000);await state(p,"judging");
  await p.clock.runFor(240000);await state(p,"paused");
  await p.evaluate(()=>Object.assign(window.recovery,{status:"COMPLETED",resultStatus:"COMPLETED"}));
  await p.getByRole("button",{name:"다시 확인",exact:true}).click();await state(p,"ready");
  assert.equal((await stats(p)).submissions,1);
  assert.equal(await p.locator("#run").textContent(),"1");
});
test("통신 오류는 재판정 없이 기존 결과 조회를 재개한다",async t=>{
  const p=await fixture(t,{failure:"network"});
  await p.getByRole("button",{name:"열기",exact:true}).click();await state(p,"failed");
  assert.equal(await p.locator("#resume").textContent(),"true");
  await p.evaluate(()=>Object.assign(window.recovery,{failure:"",status:"COMPLETED",resultStatus:"COMPLETED"}));
  await p.getByRole("button",{name:"다시 확인",exact:true}).click();await state(p,"ready");
  assert.equal((await stats(p)).submissions,1);
});
test("기존 실행 404는 자동 POST 없이 명시적 재판정을 기다린다",async t=>{
  const p=await fixture(t,{status:"COMPLETED",resultStatus:"COMPLETED"});
  await p.getByRole("button",{name:"열기",exact:true}).click();await state(p,"ready");
  await p.getByRole("button",{name:"닫기",exact:true}).click();await state(p,"unavailable");
  await p.evaluate(()=>{window.recovery.failure="notFound";});
  await p.getByRole("button",{name:"열기",exact:true}).click();await state(p,"failed");
  assert.equal((await stats(p)).submissions,1);
  assert.equal(await p.locator("#resume").textContent(),"false");
  await p.evaluate(()=>{window.recovery.failure="";});
  await p.getByRole("button",{name:"다시 판정",exact:true}).click();await state(p,"ready");
  assert.equal((await stats(p)).submissions,2);
});
test("result가 먼저 완료되면 즉시 완료 표시하고 polling을 끝낸다",async t=>{
  const p=await fixture(t,{resultStatus:"COMPLETED"});
  await p.getByRole("button",{name:"열기",exact:true}).click();await state(p,"ready");
  await p.clock.runFor(20000);assert.equal((await stats(p)).statusGets,1);
  await p.getByRole("button",{name:"다음 페이지",exact:true}).click();await state(p,"ready");
  assert.equal((await stats(p)).submissions,1);
});
test("세션 종료 뒤 늦은 접수 응답은 새 세션 캐시에 들어가지 않는다",async t=>{
  const p=await fixture(t,{holdCreate:true,status:"COMPLETED",resultStatus:"COMPLETED"});
  await p.getByRole("button",{name:"열기",exact:true}).click();await state(p,"queueing");
  await p.getByRole("button",{name:"세션 종료",exact:true}).click();await state(p,"unavailable");
  await p.evaluate(()=>{window.recovery.holdCreate=false;window.recovery.release();});
  await p.getByRole("button",{name:"열기",exact:true}).click();await state(p,"ready");
  assert.equal((await stats(p)).submissions,2);
  assert.equal(await p.locator("#run").textContent(),"2");
});
test("입력 변경은 이전 실행 재개로 덮을 수 없고 명시적 재판정만 허용한다",async t=>{
  const p=await fixture(t,{status:"COMPLETED",resultStatus:"COMPLETED"});
  await p.getByRole("button",{name:"열기",exact:true}).click();await state(p,"ready");
  await p.getByRole("button",{name:"버전 변경",exact:true}).click();await state(p,"superseded");
  await p.getByRole("button",{name:"다시 확인",exact:true}).click();await state(p,"superseded");
  assert.equal((await stats(p)).submissions,1);
  await p.getByRole("button",{name:"다시 판정",exact:true}).click();await state(p,"ready");
  assert.equal((await stats(p)).submissions,2);
});
