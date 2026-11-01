// Requests and draft comparison share one explicit input shape. No birth data is persisted.
export function formRequest(form) {
  const fd = new FormData(form);
  const data = Object.fromEntries(fd.entries());
  delete data.style;
  delete data.scenario;
  data.place = String(data.place || "").trim();
  if (data.timeBasis !== "apparent_solar") {
    delete data.longitude;
    delete data.locationId;
  }
  data.styles = fd.getAll("style");
  data.surname = String(data.surname || "").trim();
  if (data.mode === "born") {
    delete data.dueDate;
    delete data.dueTime;
  } else {
    delete data.birthDate;
    delete data.birthTime;
  }
  if (data.purpose !== "rename") delete data.currentName;
  data.variant = 0;
  return data;
}
export function requestKey(data = {}) {
  const defaults = {
    algorithm: "legacy_v2",
    numerologyMode: "reference",
    purpose: "newborn",
    mode: "due_date",
    gender: "unknown",
    zone: "Asia/Shanghai",
    length: "2",
    candidateCount: "3",
    dueTime: "12:00",
    elementPreference: "yongshen",
    timeBasis: "civil",
  };
  const names = [
    "algorithm",
    "requiredChars",
    "tabooChars",
    "surnameReading",
    "numerologyMode",
    "surname",
    "purpose",
    "mode",
    "gender",
    "zone",
    "length",
    "candidateCount",
    "dueDate",
    "dueTime",
    "birthDate",
    "birthTime",
    "place",
    "parents",
    "currentName",
    "meaning",
    "likedChars",
    "avoidedChars",
    "elementPreference",
    "timeBasis",
    "longitude",
    "locationId",
  ];
  const normalized = Object.fromEntries(
    names.map((key) => [key, String(data[key] ?? defaults[key] ?? "").trim()]),
  );
  for (const key of ["length", "candidateCount"])
    if (normalized[key] && Number.isFinite(Number(normalized[key])))
      normalized[key] = String(Number(normalized[key]));
  if (normalized.mode === "born") {
    normalized.dueDate = "";
    normalized.dueTime = "";
  } else {
    normalized.birthDate = "";
    normalized.birthTime = "";
  }
  if (normalized.purpose !== "rename") normalized.currentName = "";
  if (normalized.timeBasis !== "apparent_solar") {
    normalized.longitude = "";
    normalized.locationId = "";
  } else if (
    normalized.longitude &&
    Number.isFinite(Number(normalized.longitude))
  )
    normalized.longitude = String(Number(normalized.longitude));
  normalized.styles = [
    ...new Set(Array.isArray(data.styles) ? data.styles : []),
  ].sort();
  normalized.tabooHomophones = [true,"true","1","on"].includes(data.tabooHomophones);
  normalized.honorParents = [true, "true", "1", "on"].includes(
    data.honorParents,
  );
  return JSON.stringify(normalized);
}

// Existing-name analysis depends on identity and birth facts, not future-name preferences.
export function nameReviewKey(data = {}) {
  return requestKey({
    ...Object.fromEntries(["algorithm", "surnameReading", "surname", "purpose", "mode", "currentName", "birthDate", "birthTime", "gender", "place", "zone", "timeBasis", "longitude", "locationId"].map(key => [key, data[key]])),
    styles: [],
  });
}
export function workflowId(data = {}) {
  return data.purpose === "rename" ? "rename" : `newborn_${data.mode || "due_date"}`;
}

export function workflowLabel(data = {}) {
  return data.purpose === "rename" ? "改名方案" : data.mode === "born" ? "新生儿起名 · 已出生" : "新生儿起名 · 预产期";
}

// A readable default for common compound surnames; the user can correct it.
export function inferSurname(fullName = "") {
  const text = String(fullName).trim();
  const compounds = new Set("万俟 司马 上官 欧阳 夏侯 诸葛 闻人 东方 赫连 皇甫 尉迟 公羊 澹台 公冶 宗政 濮阳 淳于 单于 太叔 申屠 公孙 仲孙 轩辕 令狐 钟离 宇文 长孙 慕容 鲜于 闾丘 司徒 司空 亓官 司寇 仉督 子车 颛孙 端木 巫马 公西 漆雕 乐正 壤驷 公良 拓跋 夹谷 宰父 谷梁 段干 百里 东郭 南门 呼延 归海 羊舌 微生 有琴 梁丘 左丘 东门 西门 伯赏 南宫 第五".split(" "));
  const chars = [...text];
  const pair = chars.slice(0, 2).join("");
  return compounds.has(pair) ? pair : chars[0] || "";
}
