import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

async function selectScenario(page, scenario) {
  await page.locator(`[name=scenario][value=${scenario}]`).locator("..").click();
}
async function openSettings(page) {
  const details = page.locator(".naming-preferences");
  if (!(await details.evaluate(el => el.open))) await details.locator(":scope > summary").click();
}
async function openDetail(page, selector) {
  await openSettings(page);
  const details = page.locator(selector);
  if (!(await details.evaluate(el => el.open))) await details.locator(":scope > summary").click();
}
async function fillInfo(page, { scenario = "due_date", surname = "林", currentName = "林明哲", date = "2099-12-23", time = "12:00", place = "杭州" } = {}) {
  if (scenario !== "due_date") await selectScenario(page, scenario);
  if (scenario === "rename") await page.locator("[name=currentName]").fill(currentName);
  else await page.locator("[name=surname]").fill(surname);
  await page.locator(`[name=${scenario === "due_date" ? "dueDate" : "birthDate"}]`).fill(date);
  if (scenario !== "due_date") await page.locator("[name=birthTime]").fill(time);
  await page.locator("[name=place]").fill(place);
}
async function generate(page, options = {}) {
  await fillInfo(page, options);
  await page.locator("#namingForm button[type=submit]").click();
  await expect(page.locator("#cards .card")).toHaveCount(3);
}
async function downloaded(page, selector = "#downloadReport") {
  const pending = page.waitForEvent("download");
  await page.locator(selector).click();
  return readFile(await (await pending).path(), "utf8");
}

for (const width of [1280, 390]) {
  test(`首次预产期起名一页填写、一次生成 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 });
    await page.goto("/");
    await expect(page.locator(".naming-preferences")).not.toHaveAttribute("open", "");
    await expect(page.locator("[name=length]")).toBeHidden();
    await expect(page.locator("[name=dueTime]")).toBeHidden();
    let calls = 0;
    page.on("request", request => { if (request.url().endsWith("/api/analyze")) calls++; });
    await fillInfo(page);
    const request = page.waitForRequest("**/api/analyze");
    await page.getByRole("button", { name: "生成名字方案 ✦", exact: true }).click();
    const input = (await request).postDataJSON();
    await expect(page.locator("#cards .card")).toHaveCount(3);
    expect(calls).toBe(1);
    expect(input).toMatchObject({ purpose: "newborn", mode: "due_date", dueTime: "12:00", length: "2", candidateCount: "3", gender: "unknown", algorithm: "literary_v3" });
    expect(input).not.toHaveProperty("birthDate");
    expect(input).not.toHaveProperty("scenario");
    await expect(page.locator("#summary")).toContainText("新生儿起名 · 预产期");
    await expect(page.locator("#namingForm")).not.toContainText("下一步");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  });
  test(`已出生资料直接生成，结果及报告独立 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 }); await page.goto("/");
    const response = page.waitForResponse("**/api/analyze");
    await generate(page, { scenario: "born", date: "2024-02-04", time: "16:27" });
    const data = await (await response).json();
    expect(data.analysis.bazi.reference).toBe(false);
    await expect(page.locator("[name=dueDate]")).toHaveCount(0);
    await expect(page.locator("#summary")).toContainText("新生儿起名 · 已出生");
    await expect(page.locator(".boundary-notice")).toContainText("出生时刻");
    const report = await downloaded(page);
    expect(report).toContain("实际出生信息：2024-02-04 16:27");
    expect(report).not.toContain("预产期参考四柱");
  });
  test(`改名自动识别复姓、先报告再一次推荐 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 }); await page.goto("/");
    const calls = [];
    page.on("request", request => { if (/\/api\/(analyze|name-review)$/.test(request.url())) calls.push(new URL(request.url()).pathname); });
    await fillInfo(page, { scenario: "rename", currentName: "欧阳明哲", date: "1998-08-13", time: "13:48" });
    await expect(page.locator(".surname-detection")).toContainText("欧阳");
    await expect(page.locator("[name=surname]")).toBeHidden();
    await page.getByRole("button", { name: "分析现用姓名", exact: true }).click();
    await expect(page.locator("#formNameReview")).toBeVisible();
    await expect(page.locator("#cards .card")).toHaveCount(0);
    expect(calls).toEqual(["/api/name-review"]);
    await expect(page.locator("#currentReviewTitle")).toBeFocused();
    await expect(page.getByRole("button", { name: "根据这份报告推荐新名字", exact: true })).toBeInViewport();
    await page.getByRole("button", { name: "根据这份报告推荐新名字", exact: true }).click();
    await expect(page.locator("#cards .card")).toHaveCount(3);
    expect(calls).toEqual(["/api/name-review", "/api/analyze"]);
    await expect(page.locator("#summary")).toContainText("改名方案");
    await expect(page.locator("#summary")).not.toContainText("新生儿");
    expect(await page.locator("#cards h3").allTextContents()).not.toContain("欧阳明哲");
    const report = await downloaded(page);
    expect(report.indexOf("## 现用姓名分析")).toBeLessThan(report.indexOf("## 改名候选"));
    expect(report).toContain("现用姓名：欧阳明哲");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  });
  test(`古籍原句、六维与报告有据可查 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 }); await page.goto("/");
    const response = page.waitForResponse("**/api/analyze"); await generate(page);
    const result = await (await response).json(); expect(result.analysis.corpus.character_records).toBe(3636);
    expect(result.analysis.available_candidate_count).toBeGreaterThan(65);
    const card = page.locator("#cards .card").first();
    await expect(card.locator(".card-status")).toHaveText("原句已对照");
    await card.locator(".literary-citations > summary").click();
    await expect(card.locator("blockquote").first()).toHaveText(result.candidates[0].citations[0].quote);
    await card.locator(".name-evidence > summary").click();
    await expect(card.locator(".name-evidence")).toContainText("典故出处");
    const report = await downloaded(page);
    for (const value of ["literary-match-v3", "文件SHA-256", "取字方式", "逐字康熙笔画", "全名读音", "经典原文与计算方法"]) expect(report).toContain(value);
  });
}

test("切换场景保留各自输入，只提交当前日期", async ({ page }) => {
  await page.goto("/"); await fillInfo(page);
  await selectScenario(page, "born"); await page.locator("[name=birthDate]").fill("2024-01-05"); await page.locator("[name=birthTime]").fill("13:48");
  await selectScenario(page, "due_date"); await expect(page.locator("[name=dueDate]")).toHaveValue("2099-12-23");
  await expect(page.locator("[name=birthDate]")).toHaveCount(0);
  await selectScenario(page, "born"); await expect(page.locator("[name=birthTime]")).toHaveValue("13:48");
  const pending = page.waitForRequest("**/api/analyze"); await page.locator("button[type=submit]").click(); const input = (await pending).postDataJSON();
  expect(input).not.toHaveProperty("dueDate"); expect(input).not.toHaveProperty("dueTime");
  await expect(page.locator("#cards .card")).toHaveCount(3);
});

test("一页表单回车直接生成，不再跳转步骤", async ({ page }) => {
  await page.goto("/"); await fillInfo(page);
  await page.locator("[name=place]").press("Enter"); await expect(page.locator("#cards .card")).toHaveCount(3);
});

test("缺少必填项定位输入，出生未来时间不能通过", async ({ page }) => {
  await page.goto("/"); await page.locator("button[type=submit]").click(); await expect(page.locator("[name=surname]")).toBeFocused();
  await fillInfo(page, { scenario: "born", date: "2099-01-01" }); await page.locator("button[type=submit]").click();
  await expect(page.locator("#formMessage")).toContainText("不能晚于今天"); await expect(page.locator("[name=birthDate]")).toBeFocused();
  await page.locator("[name=birthDate]").fill("2024-01-05"); await page.locator("[name=birthTime]").fill(""); await page.locator("button[type=submit]").click(); await expect(page.locator("[name=birthTime]")).toBeFocused();
});

test("隐藏偏好中的数量错误会展开定位，输入不会丢失", async ({ page }) => {
  await page.goto("/"); await fillInfo(page); await openSettings(page); await page.locator("[name=candidateCount]").fill("0");
  await page.locator(".naming-preferences > summary").click(); await page.locator("button[type=submit]").click();
  await expect(page.locator("[name=candidateCount]")).toBeFocused(); await expect(page.locator("#formMessage")).toContainText("1–11"); await expect(page.locator("[name=surname]")).toHaveValue("林");
});

test("字库数量晚到会修正选中的数量上限", async ({ page }) => {
  await page.route("**/api/name-counts*", async route => { await new Promise(resolve => setTimeout(resolve, 700)); await route.fulfill({ json: { counts: { 1: 15, 2: 15, 3: 5 } } }); });
  await page.goto("/"); await openSettings(page); await page.locator("[name=length]").selectOption("3"); await page.locator("[name=candidateCount]").fill("11");
  await expect(page.locator("[name=candidateCount]")).toHaveValue("5");
});

test("改名分析失败可重试，出生资料变更后必须重新分析", async ({ page }) => {
  await page.goto("/"); await fillInfo(page, { scenario: "rename", currentName: "李明哲", date: "1998-08-13" });
  const abort = route => route.abort(); await page.route("**/api/name-review", abort);
  await page.locator("button[type=submit]").click(); await expect(page.locator("#formMessage")).toContainText("无法连接");
  await page.unroute("**/api/name-review", abort); await page.locator("button[type=submit]").click(); await expect(page.locator("#formNameReview")).toBeVisible();
  await page.locator("[name=birthTime]").fill("13:48"); await expect(page.locator(".review-stale")).toBeVisible();
  await expect(page.getByRole("button", { name: "根据这份报告推荐新名字" })).toHaveCount(0);
  const response = page.waitForResponse("**/api/name-review"); await page.getByRole("button", { name: "重新分析现用姓名", exact: true }).click();
  expect((await (await response).json()).analysis.name_review.findings.at(-1).detail).toContain("13:48");
  await page.getByRole("button", { name: "根据这份报告推荐新名字", exact: true }).click(); await expect(page.locator("#cards .card")).toHaveCount(3);
});

test("现名报告可重复查看且不重复请求，未来偏好不阻挡分析", async ({ page }) => {
  await page.goto("/"); await fillInfo(page, { scenario: "rename", currentName: "李明哲", date: "1998-08-13" });
  await openDetail(page, ".naming-constraints"); await page.locator("[name=requiredChars]").fill("安"); await page.locator("[name=tabooChars]").fill("安");
  let requests = 0; page.on("request", r => { if (r.url().endsWith("/api/name-review")) requests++; });
  await page.locator("button[type=submit]").click(); await expect(page.locator("#formNameReview")).toBeVisible();
  await page.locator("button[type=submit]").click(); expect(requests).toBe(1);
  await page.getByRole("button", { name: "根据这份报告推荐新名字", exact: true }).click(); await expect(page.locator("#formMessage")).toContainText("冲突"); await expect(page.locator("[name=requiredChars]")).toBeFocused();
});

test("识别的姓氏可修正，修改名字后保留明确的姓氏设置", async ({ page }) => {
  await page.goto("/"); await selectScenario(page, "rename"); await page.locator("[name=currentName]").fill("阿布知远");
  await page.getByRole("button", { name: "修改姓氏", exact: true }).click(); await expect(page.locator("[name=surname]")).toBeFocused(); await page.locator("[name=surname]").fill("阿布");
  await page.locator("[name=currentName]").fill("阿布安宁"); await expect(page.locator(".surname-detection")).toContainText("阿布");
  await selectScenario(page, "due_date"); await page.locator("[name=surname]").fill("林"); await selectScenario(page, "rename"); await expect(page.locator(".surname-detection")).toContainText("阿布"); await selectScenario(page, "due_date"); await expect(page.locator("[name=surname]")).toHaveValue("林");
});

test("切换到改名立即收起新生儿旧方案和下载入口", async ({ page }) => {
  await page.goto("/"); await generate(page); await selectScenario(page, "rename");
  await expect(page.locator("#cards .card")).toHaveCount(0); await expect(page.locator("#downloadReport")).toBeDisabled(); await expect(page.locator("#summary")).not.toContainText("新生儿");
});

test("修改偏好需要应用，失败保留旧结果并可重试", async ({ page }) => {
  await page.goto("/"); await generate(page); const names = await page.locator("#cards h3").allTextContents();
  await page.getByRole("button", { name: "调整偏好", exact: true }).first().click(); await expect(page.locator("#preferencesTitle")).toBeFocused(); await page.locator("[name=likedChars]").fill("安");
  await expect(page.getByRole("region", { name: "尚未应用的修改" })).toBeVisible(); const abort = route => route.abort(); await page.route("**/api/analyze", abort);
  await page.getByRole("button", { name: "应用修改并生成", exact: true }).click(); await expect(page.locator("#formMessage")).toContainText("无法连接"); expect(await page.locator("#cards h3").allTextContents()).toEqual(names); await expect(page.locator("#downloadReport")).toBeEnabled();
  await page.unroute("**/api/analyze", abort); const request = page.waitForRequest("**/api/analyze"); await page.getByRole("button", { name: "应用修改并生成", exact: true }).click(); expect((await request).postDataJSON().likedChars).toBe("安"); await expect(page.getByRole("region", { name: "尚未应用的修改" })).toHaveCount(0);
});

test("上一组和下一组使用缓存，比较可跨组保留", async ({ page }) => {
  await page.goto("/"); await generate(page); const original = await page.locator("#cards h3").allTextContents(); let requests = 0;
  page.on("request", r => { if (r.url().endsWith("/api/analyze")) requests++; });
  await page.locator("#cards .compare-name").first().click(); await page.locator("#regenerate").click(); await expect(page.locator("#resultStatus")).toContainText("第 2 组"); await expect(page.locator("#candidateComparison")).toContainText("已选 1/3");
  await page.locator("#cards .compare-name").first().click(); await page.locator("#previousGroup").click(); expect(await page.locator("#cards h3").allTextContents()).toEqual(original);
  await page.locator("#regenerate").click(); expect(requests).toBe(1); await expect(page.locator("#candidateComparison")).toContainText("已选 2/3");
});

test("比较最多三个，可移除后继续选", async ({ page }) => {
  await page.goto("/"); await fillInfo(page); await openSettings(page); await page.locator("[name=candidateCount]").fill("4"); await page.locator("button[type=submit]").click(); await expect(page.locator("#cards .card")).toHaveCount(4);
  for (let i = 0; i < 3; i++) await page.locator("#cards .compare-name").nth(i).click(); await expect(page.locator("#cards .compare-name").nth(3)).toBeDisabled();
  await page.locator("#cards .compare-name").first().click(); await expect(page.locator("#cards .compare-name").nth(3)).toBeEnabled();
});

for (const length of [1, 3]) test(`${length}字名可选择11个方案且保留必用字`, async ({ page }) => {
  await page.goto("/"); await fillInfo(page); await openSettings(page); await page.locator("[name=length]").selectOption(String(length)); await page.locator("[name=candidateCount]").fill("11");
  if (length === 3) { await openDetail(page, ".naming-constraints"); await page.locator("[name=requiredChars]").fill("安"); }
  await page.locator("button[type=submit]").click(); await expect(page.locator("#cards .card")).toHaveCount(11);
  const names = await page.locator("#cards h3").allTextContents(); expect(names.every(n => [...n].length === length + 1)).toBeTruthy(); expect(new Set(names).size).toBe(11); if (length === 3) expect(names.every(n => n.includes("安"))).toBeTruthy();
});

test("必用字与避讳生效，冲突展开定位且旧结果保留", async ({ page }) => {
  await page.goto("/"); await fillInfo(page, { surname: "欧阳" }); await openDetail(page, ".naming-constraints"); await page.locator("[name=requiredChars]").fill("安"); await page.locator("[name=tabooChars]").fill("宁"); await page.locator("button[type=submit]").click(); await expect(page.locator("#cards .card")).toHaveCount(3);
  const names = await page.locator("#cards h3").allTextContents(); expect(names.every(n => n.includes("安") && !n.includes("宁"))).toBeTruthy(); await page.locator("[name=avoidedChars]").fill("安");
  await page.locator(".naming-preferences > summary").click(); await page.locator("button[type=submit]").click(); await expect(page.locator("[name=requiredChars]")).toBeFocused(); await expect(page.locator("#formMessage")).toContainText("冲突"); expect(await page.locator("#cards h3").allTextContents()).toEqual(names);
});

test("未覆盖必用字返回空候选，修改入口直接定位", async ({ page }) => {
  await page.goto("/"); await fillInfo(page); await openDetail(page, ".naming-constraints"); await page.locator("[name=requiredChars]").fill("龘"); await page.locator("button[type=submit]").click(); await expect(page.locator("#cards .empty-result")).toContainText("龘"); await expect(page.locator("#downloadReport")).toBeDisabled();
  await page.getByRole("button", { name: "调整必用字或避讳", exact: true }).click(); await expect(page.locator("[name=requiredChars]")).toBeFocused();
});

test("单字必用只有一个结果，看完不循环", async ({ page }) => {
  await page.goto("/"); await fillInfo(page); await openSettings(page); await page.locator("[name=length]").selectOption("1"); await openDetail(page, ".naming-constraints"); await page.locator("[name=requiredChars]").fill("安"); await page.locator("button[type=submit]").click(); await expect(page.locator("#cards .card")).toHaveCount(1); await expect(page.locator("#regenerate")).toBeDisabled();
});

test("五格严格筛选与未知笔画可以调整", async ({ page }) => {
  await page.goto("/"); await fillInfo(page); await openDetail(page, ".naming-constraints"); await page.locator("[name=numerologyMode]").selectOption("strict");
  let response = page.waitForResponse("**/api/analyze"); await page.locator("button[type=submit]").click(); expect((await (await response).json()).candidates.every(x => x.numerology.strict_pass)).toBeTruthy(); await expect(page.locator("#cards .card")).toHaveCount(3);
  await page.locator("[name=requiredChars]").fill("清"); await page.locator("button[type=submit]").click(); await expect(page.locator("#cards .empty-result")).toBeVisible();
  await page.getByRole("button", { name: "调整数理筛选", exact: true }).click(); await expect(page.locator("[name=numerologyMode]")).toBeFocused(); await page.locator("[name=numerologyMode]").selectOption("off"); await page.locator("button[type=submit]").click(); await expect(page.locator("#cards .card")).toHaveCount(3);
});

test("多音姓读法贯穿生成和报告", async ({ page }) => {
  await page.goto("/"); await fillInfo(page, { surname: "单" }); await openDetail(page, ".family-options"); await page.locator("[name=surnameReading]").fill("dān"); const response = page.waitForResponse("**/api/analyze"); await page.locator("button[type=submit]").click(); expect((await (await response).json()).candidates.every(x => x.pronunciation.evaluation.full_pinyin.startsWith("dān "))).toBeTruthy(); await expect(page.locator("#cards .name-full-reading").first()).toContainText("dān");
});

for (const width of [1280, 390]) test(`真太阳时、旺衰与经典依据保留 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 950 }); await page.goto("/"); await fillInfo(page, { scenario: "born", date: "2024-02-10", time: "23:05" });
  await page.locator("[name=place]").fill("喀什"); await page.getByRole("button", { name: /北京时间 · 调整/ }).click(); await expect(page.locator("[name=zone]")).toBeFocused(); await page.locator("[name=timeBasis]").selectOption("apparent_solar"); await expect(page.locator("[name=longitude]")).toHaveValue("75.99"); await expect(page.locator("select[name=locationId]")).toHaveCount(0); await page.locator("button[type=submit]").click(); await expect(page.locator("#cards .card")).toHaveCount(3);
  await expect(page.getByRole("region", { name: "排盘时间修正" })).toContainText("23:05:00"); await expect(page.getByRole("region", { name: "排盘时间修正" })).toContainText("日柱、时柱有变化");
  const area = page.getByRole("region", { name: "格局旺衰与喜用参考" }); await area.locator(".classical-evidence > summary").click(); await expect(area.locator(".classical-evidence")).toContainText("15 处录文已核对");
  await expect(page.locator("#summary .time-basis-note")).toContainText("真太阳时已应用"); await expect(page.locator("#summary .time-basis-note")).toContainText("喀什");
  const report = await downloaded(page); for (const word of ["真太阳钟", "75.99", "城市中心近似经度（喀什）", "四柱分析：", "扶抑喜用参考", "经典原文与计算方法"]) expect(report).toContain(word);
});

test("真太阳时缺失经度会展开定位，输入完整可继续", async ({ page }) => {
  await page.goto("/"); await fillInfo(page, { place: "未收录地点" }); await openDetail(page, ".time-settings"); await page.locator("[name=timeBasis]").selectOption("apparent_solar"); await page.locator(".naming-preferences > summary").click(); await page.locator("button[type=submit]").click(); await expect(page.locator("[name=longitude]")).toBeFocused(); await page.locator("[name=longitude]").fill("120.16"); await page.locator("button[type=submit]").click(); await expect(page.locator("#cards .card")).toHaveCount(3);
});

for (const scenario of ["due_date", "born", "rename"]) test(`民用时间不填城市也能完成${scenario}`, async ({ page }) => {
  await page.setViewportSize({width:390,height:950}); await page.goto("/");
  await fillInfo(page, {scenario, place:"", date:scenario === "due_date" ? "2099-12-23" : "2024-02-10"});
  await expect(page.locator("#placeHelp")).toContainText("可留空");
  if (scenario === "rename") {
    await page.locator("button[type=submit]").click(); await expect(page.locator("#formNameReview")).toBeVisible();
    await expect(page.locator(".simple-review .time-basis-note")).toContainText("按民用时间排盘");
  }
  const pending=page.waitForRequest("**/api/analyze");
  if (scenario === "rename") await page.getByRole("button", {name:"根据这份报告推荐新名字",exact:true}).click();
  else await page.locator("button[type=submit]").click();
  const data=(await pending).postDataJSON(); expect(data.place).toBe(""); expect(data).not.toHaveProperty("longitude"); expect(data).not.toHaveProperty("locationId");
  await expect(page.locator("#cards .card")).toHaveCount(3); await expect(page.locator("#summary")).toContainText("地点未填写");
  await expect(page.locator("#summary .time-basis-note")).toContainText("不用于经度修正");
  expect(await downloaded(page)).toContain("出生地点：未填写");
});

test("城市只选一次，更换地点清除旧经度，手动0经度可用", async ({ page }) => {
  await page.goto("/"); await fillInfo(page); await openDetail(page, ".time-settings"); await page.locator("[name=timeBasis]").selectOption("apparent_solar");
  await expect(page.locator("[name=longitude]")).toHaveValue("120.16");
  await page.locator("[name=longitude]").fill(""); await page.getByRole("button", {name:"恢复杭州城市中心经度",exact:true}).click(); await expect(page.locator("[name=longitude]")).toHaveValue("120.16");
  await page.locator("[name=longitude]").fill("120.15"); await page.locator("[name=place]").fill("杭州市"); await expect(page.locator("[name=longitude]")).toHaveValue("120.15");
  await page.locator("[name=place]").fill("成都"); await expect(page.locator("[name=longitude]")).toHaveValue("104.07");
  await page.locator("[name=place]").fill(""); await expect(page.locator("[name=longitude]")).toHaveValue(""); await expect(page.locator("[name=locationId]")).toHaveValue("");
  await page.locator("button[type=submit]").click(); await expect(page.locator("[name=longitude]")).toBeFocused();
  await page.locator("[name=longitude]").fill("0"); const pending=page.waitForResponse("**/api/analyze"); await page.locator("button[type=submit]").click();
  await expect(page.locator("#placeHelp")).toContainText("已填写手动经度0°E");
  const value=await (await pending).json(); expect(value.analysis.bazi.time_correction).toMatchObject({applied:true,longitude:0,location:{coordinate_source:"manual"}});
  await expect(page.locator("#cards .card")).toHaveCount(3); await expect(page.locator("#summary .time-basis-note")).toContainText("0°E"); await expect(page.locator("#summary .time-basis-note")).toContainText("手动填写经度");
});

test("真太阳时切回民用时间时不提交经度，重新启用仍保留调整", async ({ page }) => {
  await page.goto("/"); await fillInfo(page,{place:"臺北市"}); await openDetail(page,".time-settings"); await page.locator("[name=timeBasis]").selectOption("apparent_solar");
  await expect(page.locator("[name=longitude]")).toHaveValue("121.57"); await expect(page.locator("[name=zone]")).toHaveValue("Asia/Taipei");
  await page.locator("[name=longitude]").fill("121.56"); await page.locator("[name=timeBasis]").selectOption("civil");
  const pending=page.waitForRequest("**/api/analyze"); await page.locator("button[type=submit]").click(); const data=(await pending).postDataJSON(); expect(data).not.toHaveProperty("longitude"); expect(data).not.toHaveProperty("locationId");
  await expect(page.locator("#cards .card")).toHaveCount(3); await page.locator("[name=timeBasis]").selectOption("apparent_solar"); await expect(page.locator("[name=longitude]")).toHaveValue("121.56");
});

test("改名换城市后重新分析，并把同一修正依据用于推荐", async ({ page }) => {
  await page.goto("/"); await fillInfo(page,{scenario:"rename",currentName:"李明哲",date:"2024-02-10"}); await openDetail(page,".time-settings"); await page.locator("[name=timeBasis]").selectOption("apparent_solar");
  await page.locator("button[type=submit]").click(); await expect(page.locator("#formNameReview")).toBeVisible();
  await page.locator("[name=place]").fill("成都"); await expect(page.locator(".review-stale")).toBeVisible();
  const pending=page.waitForResponse("**/api/name-review"); await page.getByRole("button",{name:"重新分析现用姓名",exact:true}).click();
  const review=await (await pending).json(); expect(review.analysis.bazi.time_correction.location.label).toBe("成都");
  const recommendation=page.waitForResponse("**/api/analyze"); await page.getByRole("button",{name:"根据这份报告推荐新名字",exact:true}).click();
  const value=await (await recommendation).json(); expect(value.analysis.bazi.time_correction).toEqual(review.analysis.bazi.time_correction);
  await expect(page.locator("#summary .time-basis-note")).toContainText("成都");
});

for (const [status, body, text] of [[404, "missing", "未接通起名接口"], [502, "<html>bad gateway</html>", "暂时不可用"], [200, "<html>static page</html>", "无法识别"]]) test(`接口错误${status}-${text}可见并支持重试`, async ({ page }) => {
  await page.goto("/"); await fillInfo(page); await page.route("**/api/analyze", route => route.fulfill({ status, contentType: "text/html", body })); await page.locator("button[type=submit]").click(); await expect(page.locator("#formMessage")).toContainText(text); await expect(page.locator("#formMessage")).toBeInViewport(); await expect(page.locator("button[type=submit]")).toBeEnabled(); await expect(page.locator("#cards .card")).toHaveCount(0);
});

test("重复点击只提交一次，等待结束后可重试", async ({ page }) => {
  await page.goto("/"); await fillInfo(page); let count = 0; let release;
  const gate = new Promise(resolve => { release = resolve; });
  const hold = async route => { count++; await gate; await route.continue(); }; await page.route("**/api/analyze", hold);
  await page.locator("button[type=submit]").click(); await expect(page.locator("button[type=submit]")).toBeDisabled(); await page.locator("button[type=submit]").evaluate(el => el.click()); expect(count).toBe(1); release(); await expect(page.locator("#cards .card")).toHaveCount(3);
});

test("收藏搜索、复制、清空撤销和Esc返回保持完整", async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async text => { window.__copied = text; } } }); });
  await page.goto("/"); await generate(page); await page.locator("#cards .save").first().click(); const name = await page.locator("#cards h3").first().textContent(); await page.locator("#savedButton").click(); const panel = page.locator("#savedPanel"); await expect(panel).toBeVisible();
  await panel.getByLabel("查找收藏").fill("不存在的名字"); await expect(panel).toContainText("没有找到匹配"); await panel.getByRole("button", { name: "查看全部收藏", exact: true }).click();
  await panel.getByRole("button", { name: "复制收藏清单", exact: true }).click(); const copied = await page.evaluate(() => window.__copied); expect(copied).toContain(name); expect(copied).not.toContain("2099");
  await panel.getByRole("button", { name: "清空本机收藏", exact: true }).click(); await panel.getByRole("button", { name: "撤销", exact: true }).click(); await expect(panel).toContainText(name); await page.keyboard.press("Escape"); await expect(panel).toBeHidden(); await expect(page.locator("#savedButton")).toBeFocused();
});

test("旧收藏可用，心愿卡与推荐链接不含出生信息", async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem("序名收藏", JSON.stringify(["林安"])); Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async text => { window.__copied = text; } } }); });
  await page.goto("/?birthDate=秘密#private"); await generate(page); await page.locator("#cards .make-keepsake").first().click(); const pending = page.waitForEvent("download"); await page.locator("#downloadKeepsake").click(); const file = await readFile(await (await pending).path()); expect(file.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  await page.locator("#copySiteLink").click(); const link = await page.evaluate(() => window.__copied); expect(link).not.toContain("birthDate"); expect(link).not.toContain("秘密"); expect(link).toContain("utm_source=share");
});

test("320px键盘可选择场景和操作导航，减少动态效果生效", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 850 }); await page.emulateMedia({ reducedMotion: "reduce" }); await page.goto("/"); await page.locator("[name=scenario][value=rename]").focus(); await page.keyboard.press("Space"); await expect(page.locator("[name=currentName]")).toBeVisible();
  const button = page.locator("#mobileMenuButton"); await button.focus(); await page.keyboard.press("Enter"); await expect(page.locator("#mobileMenu")).toBeVisible(); await page.keyboard.press("Escape"); await expect(button).toBeFocused();
  expect(await page.locator(".orb").evaluate(el => getComputedStyle(el, "::before").animationName)).toBe("none"); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test("清理旧版本缓存，匿名使用不要求登录购买", async ({ page }) => {
  await page.goto("/"); await page.evaluate(async () => { await (await navigator.serviceWorker.ready).unregister(); const cache = await caches.open("xuming-mvp-v26"); await cache.put("/old", new Response("old")); }); await page.reload();
  await page.waitForFunction(async () => !(await caches.keys()).includes("xuming-mvp-v26")); await generate(page); await expect(page.getByRole("button", { name: "立即购买" })).toHaveCount(0);
});

test("超时结束等待并保留输入，可以重试生成", async ({ page }) => {
  await page.goto("/"); await fillInfo(page);
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const hold = async route => { await gate; try { await route.abort(); } catch {} };
  await page.route("**/api/analyze", hold);
  await page.locator("button[type=submit]").click();
  await expect(page.locator("#formMessage")).toContainText("响应超时", { timeout: 20000 });
  await expect(page.locator("button[type=submit]")).toBeEnabled();
  await expect(page.locator("[name=dueDate]")).toHaveValue("2099-12-23");
  release(); await page.unroute("**/api/analyze", hold);
  await page.locator("button[type=submit]").click(); await expect(page.locator("#cards .card")).toHaveCount(3);
});

test("折叠偏好不丢设置，选城市带入对应时区", async ({ page }) => {
  await page.goto("/"); await fillInfo(page, { place: "台北" });
  await page.locator("[name=gender]").selectOption("female");
  await openSettings(page); await page.locator("[name=length]").selectOption("1"); await page.locator("[name=candidateCount]").fill("7");
  await page.locator("[name=likedChars]").fill("安"); await page.locator(".naming-preferences > summary").click();
  const pending = page.waitForRequest("**/api/analyze"); await page.locator("button[type=submit]").click();
  expect((await pending).postDataJSON()).toMatchObject({ gender: "female", length: "1", candidateCount: "7", likedChars: "安", zone: "Asia/Taipei" });
  await expect(page.locator("#cards .card")).toHaveCount(7);
});

test("表单资料不落本机收藏，离线仍能制作心愿卡", async ({ page, context }) => {
  await page.goto("/"); await generate(page); await page.locator("#cards .save").first().click();
  const stored = await page.evaluate(() => JSON.stringify(Object.entries(localStorage)));
  expect(stored).not.toContain("2099-12-23"); expect(stored).not.toContain("dueDate"); expect(stored).not.toContain("birthDate");
  await page.evaluate(() => navigator.serviceWorker.ready); await context.setOffline(true); await page.reload();
  await page.locator("#keepsakeName").fill("林安");
  const pending = page.waitForEvent("download"); await page.locator("#downloadKeepsake").click(); const image = await readFile(await (await pending).path());
  expect(image.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
});

test("宝宝与改名对象的出生资料分别保留，不自动混填", async ({ page }) => {
  await page.goto("/"); await fillInfo(page, { scenario: "born", date: "2024-01-05", time: "12:00", place: "杭州" }); await page.locator("[name=gender]").selectOption("male");
  await selectScenario(page, "rename"); await page.locator("[name=currentName]").fill("李明哲");
  await expect(page.locator("[name=birthDate]")).toHaveValue(""); await expect(page.locator("[name=place]")).toHaveValue(""); await expect(page.locator("[name=gender]")).toHaveValue("unknown");
  await page.locator("[name=birthDate]").fill("1998-08-13"); await page.locator("[name=birthTime]").fill("13:48"); await page.locator("[name=place]").fill("台北");
  await selectScenario(page, "born"); await expect(page.locator("[name=birthDate]")).toHaveValue("2024-01-05"); await expect(page.locator("[name=place]")).toHaveValue("杭州"); await expect(page.locator("[name=gender]")).toHaveValue("male");
  await selectScenario(page, "rename"); await expect(page.locator("[name=birthDate]")).toHaveValue("1998-08-13"); await expect(page.locator("[name=zone]")).toHaveValue("Asia/Taipei");
});
