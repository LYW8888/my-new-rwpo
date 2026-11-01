import React, {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { formRequest, inferSurname, nameReviewKey } from "./form-state.js";
import { longitudeText, matchCity, withPlace } from "./location-state.js";
import { requestNameReview } from "./analysis.js";
import NameReview from "./NameReview.jsx";
import { Chart, ClockSummary } from "./Results.jsx";
import LOCATIONS from "../../data/locations.json";
import { friendlyError, getClockInZone } from "./utils.js";

const SCENARIOS = [
  ["due_date", "预产期起名", "宝宝还没出生"],
  ["born", "已出生起名", "按真实出生时刻"],
  ["rename", "改名", "先分析现用姓名"],
];

export default forwardRef(function NamingForm(
  { onGenerate, busy, counts, message, setMessage, onDraftChange },
  controller,
) {
  const [scenario, setScenario] = useState("due_date");
  const [newbornSurname, setNewbornSurname] = useState("");
  const [currentName, setCurrentName] = useState("");
  const [surnameOverride, setSurnameOverride] = useState(null);
  const [people, setPeople] = useState(() => {
    const fresh = () => ({ dates: { dueDate: "", dueTime: "12:00", birthDate: "", birthTime: "" }, place: "", zone: "Asia/Shanghai", zoneManual: false, timeBasis: "civil", longitude: "", locationId: "", gender: "unknown" });
    return { newborn: fresh(), rename: fresh() };
  });
  const [length, setLength] = useState("2");
  const [elementPreference, setElementPreference] = useState("yongshen");
  const [draft, setDraft] = useState({});
  const [review, setReview] = useState(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [acceptedReview, setAcceptedReview] = useState(null);
  const formRef = useRef(null);
  const invalidField = useRef(null);
  const inFlightReview = useRef(false);
  const rename = scenario === "rename";
  const born = scenario !== "due_date";
  const personKey = rename ? "rename" : "newborn";
  const { dates, place, zone, timeBasis, longitude, locationId, gender } = people[personKey];
  function updatePerson(name, value) {
    setPeople(previous => ({ ...previous, [personKey]: { ...previous[personKey], [name]: typeof value === "function" ? value(previous[personKey][name]) : value } }));
  }
  const setDates = value => updatePerson("dates", value);
  const setZone = value => setPeople(previous => ({ ...previous, [personKey]: { ...previous[personKey], zone: value, zoneManual: true } }));
  const setTimeBasis = value => updatePerson("timeBasis", value);
  const setLongitude = value => updatePerson("longitude", value);
  const city = matchCity(place, LOCATIONS.cities);
  const cityCoordinate = city && longitude !== "" && Number(longitude) === city.longitude;
  const zoneLabel = zone === "Asia/Shanghai" ? "北京时间" : zone === "Asia/Taipei" ? "台北时间" : "香港时间";
  const surname = rename ? surnameOverride ?? inferSurname(currentName) : newbornSurname;
  const locked = busy || reviewBusy;
  const reviewCurrent = rename && !!review && nameReviewKey(draft) === review.key;
  const max = Math.max(1, Math.min(11, Number(counts[length]) || 11));

  const capture = useCallback(() => {
    if (!formRef.current) return;
    const data = formRequest(formRef.current);
    setDraft(data);
    onDraftChange?.(data);
  }, [onDraftChange]);
  useLayoutEffect(() => {
    if (!locked) capture();
  }, [scenario, surname, currentName, dates, place, zone, timeBasis, longitude, locationId, length, elementPreference, gender, locked, capture]);
  useEffect(() => {
    const field = formRef.current?.elements.candidateCount;
    if (!locked && field && Number(field.value) > max) {
      field.value = String(max);
      capture();
    }
  }, [max, locked, capture]);
  useLayoutEffect(() => {
    if (message && !invalidField.current) {
      focus(formRef.current?.querySelector("#formMessage"));
      const frame = requestAnimationFrame(() => focus(formRef.current?.querySelector("#formMessage")));
      return () => cancelAnimationFrame(frame);
    }
  }, [message]);

  useLayoutEffect(() => {
    if (review) focus(formRef.current?.querySelector("#currentReviewTitle"));
  }, [review]);

  function focus(element) {
    if (!element) return;
    for (let parent = element.parentElement; parent && parent !== formRef.current; parent = parent.parentElement)
      if (parent.tagName === "DETAILS") parent.open = true;
    element.focus({ preventScroll: true });
    element.scrollIntoView({ behavior: "instant", block: "start" });
  }
  function clearError() {
    invalidField.current?.removeAttribute("aria-invalid");
    invalidField.current?.removeAttribute("aria-describedby");
    invalidField.current = null;
    setMessage("");
  }
  function fail(text, field) {
    clearError();
    setMessage(text);
    if (field) {
      invalidField.current = field;
      field.setAttribute("aria-invalid", "true");
      field.setAttribute("aria-describedby", "formMessage");
      requestAnimationFrame(() => focus(field));
    }
    return false;
  }
  function validate(includePreferences = true) {
    const form = formRef.current;
    const fields = [...form.querySelectorAll(includePreferences ? "input,select,textarea" : ".basic-info input,.basic-info select,.birth-info input,.birth-info select,.time-settings input,.time-settings select,.family-options input")];
    const invalid = fields.find(field => !field.checkValidity());
    if (invalid) {
      if (invalid.name === "candidateCount") return fail(`方案数量请输入1–${max}的整数。`, invalid);
      const label = invalid.closest("label")?.querySelector(".field-label")?.textContent || invalid.closest("label")?.childNodes[0]?.textContent?.trim() || "必填项";
      return fail(`请填写或检查“${label}”。`, invalid);
    }
    if (![...surname.trim()].length || [...surname.trim()].length > 2 || [...surname.trim()].some(c => c !== "〇" && !/\p{Script=Han}/u.test(c)))
      return fail("姓氏请填写1–2个汉字，支持复姓。", form.elements.surname);
    if (rename && (!currentName.trim().startsWith(surname.trim()) || [...currentName.trim()].length <= [...surname.trim()].length || [...currentName.trim()].some(c => c !== "〇" && !/\p{Script=Han}/u.test(c))))
      return fail("请填写含姓氏的完整现用姓名，并确认识别的姓氏。", form.elements.currentName);
    if (born) {
      const clock = getClockInZone(zone);
      if (dates.birthDate > clock.date) return fail("实际出生日期不能晚于今天。", form.elements.birthDate);
      if (dates.birthDate === clock.date && dates.birthTime) {
        const [hours, minutes] = dates.birthTime.split(":").map(Number);
        if (hours * 60 + minutes > clock.minutes) return fail("实际出生时间不能晚于当前时间。", form.elements.birthTime);
      }
    }
    if (includePreferences) {
      const chars = name => new Set([...(form.elements[name]?.value || "")].filter(c => /\p{Script=Han}/u.test(c)));
      const required = chars("requiredChars");
      const avoided = new Set([...chars("avoidedChars"), ...chars("tabooChars")]);
      if (required.size > Number(length)) return fail("必用字数量不能超过名的字数。", form.elements.requiredChars);
      if ([...required].some(c => avoided.has(c))) return fail("必用字与避用字或家族避讳有冲突。", form.elements.requiredChars);
      if ([...chars("likedChars")].some(c => chars("avoidedChars").has(c))) return fail("喜欢的字和避用字不能重复。", form.elements.avoidedChars);
    }
    clearError();
    return true;
  }
  function changeScenario(value) {
    clearError();
    setScenario(value);
    setAcceptedReview(null);
  }
  function edit(index = 0, fieldName) {
    clearError();
    requestAnimationFrame(() => {
      const form = formRef.current;
      if (fieldName) return focus(form.elements[fieldName === "locationId" ? "place" : fieldName]);
      if (index === 2) return focus(form.querySelector("#preferencesTitle"));
      focus(form.querySelector(index === 1 ? "#birthInfoTitle" : "#basicInfoTitle"));
    });
  }
  function showReview() {
    requestAnimationFrame(() => focus(formRef.current.querySelector("#currentReviewTitle")));
  }
  async function analyzeCurrentName() {
    if (locked || inFlightReview.current || !validate(false)) return;
    const data = formRequest(formRef.current);
    if (review && nameReviewKey(data) === review.key) return showReview();
    inFlightReview.current = true;
    setReviewBusy(true);
    try {
      const payload = await requestNameReview(data);
      setReview({ payload, key: nameReviewKey(data) });
      setAcceptedReview(null);
      setDraft(data);
      onDraftChange?.(data);
      showReview();
    } catch (error) {
      setMessage(friendlyError(error.message));
    } finally {
      inFlightReview.current = false;
      setReviewBusy(false);
    }
  }
  function generate(accept = false) {
    if (locked || !validate(!rename)) return;
    const data = formRequest(formRef.current);
    if (rename) {
      if (!review || nameReviewKey(data) !== review.key) return analyzeCurrentName();
      if (!accept && acceptedReview !== review.key) return showReview();
      if (accept) setAcceptedReview(review.key);
      if (!validate()) return;
    }
    setDraft(data);
    onDraftChange?.(data);
    onGenerate(data);
  }
  useImperativeHandle(controller, () => ({
    openStep: edit,
    resume: () => edit(0),
    submit: () => generate(),
  }));

  function setCity(value) {
    setPeople(previous => ({ ...previous, [personKey]: withPlace(previous[personKey], value, LOCATIONS.cities) }));
    if (["longitude", "place"].includes(invalidField.current?.name)) clearError();
  }
  function surnameField() {
    return <label><span className="field-label">姓氏</span>
      <input name="surname" value={surname} onChange={e => rename ? setSurnameOverride(e.target.value) : setNewbornSurname(e.target.value)} required maxLength={4} placeholder="例如：林、欧阳" />
    </label>;
  }
  return <section className="form-section simple-form-section wrap" id="form">
    <div className="intro">
      <p className="eyebrow">A NAME BEGINS HERE</p>
      <h2>填好基本信息，<br />让名字有个好开始。</h2>
      <p>偏好可以以后再调。先看看适合的名字与依据。</p>
      <div className="simple-flow-note"><b>{rename ? "先了解现名，再推荐新名" : "一页填写，直接生成"}</b><span>{rename ? "填写资料 → 现名报告 → 推荐改名" : "填好姓氏和时间即可，城市和偏好按需补充。"}</span></div>
    </div>
    <form id="namingForm" ref={formRef} noValidate aria-busy={locked} onChange={event => {
      if (invalidField.current?.name === event.target.name) clearError();
      capture();
    }} onSubmit={event => { event.preventDefault(); rename ? analyzeCurrentName() : generate(); }}>
      <input type="hidden" name="algorithm" value="literary_v3" />
      <input type="hidden" name="purpose" value={rename ? "rename" : "newborn"} />
      <input type="hidden" name="mode" value={born ? "born" : "due_date"} />
      <div id="formMessage" tabIndex={-1} className="form-message error" role="alert" hidden={!message}>{message}</div>
      <fieldset className="basic-info" disabled={locked}>
        <legend id="basicInfoTitle" tabIndex={-1}>这次为谁取名</legend>
        <div className="scenario-choices" role="group" aria-label="起名场景">
          {SCENARIOS.map(([value, title, hint]) => <label key={value}>
            <input type="radio" name="scenario" value={value} checked={scenario === value} onChange={() => changeScenario(value)} />
            <span>{title}</span><small>{hint}</small>
          </label>)}
        </div>
        <div className="grid basic-fields">
          {rename ? <label id="currentNameField"><span className="field-label">现用姓名</span><input name="currentName" value={currentName} onChange={e => { setCurrentName(e.target.value); if (surnameOverride !== null && !e.target.value.trim().startsWith(surnameOverride)) setSurnameOverride(null); }} required maxLength={20} placeholder="例如：欧阳明哲" /><small className="surname-detection">{surname ? `已识别姓氏：${surname}` : "输入全名后自动识别姓氏"}<button type="button" onClick={() => edit(0, "surname")}>修改姓氏</button></small></label> : surnameField()}
          <label><span className="field-label">性别<span className="optional-label">可选</span></span><select name="gender" value={gender} onChange={e => updatePerson("gender", e.target.value)}><option value="unknown">未知 / 暂不确定</option><option value="male">男</option><option value="female">女</option></select></label>
        </div>
      </fieldset>
      <fieldset className="birth-info" disabled={locked}>
        <legend id="birthInfoTitle" tabIndex={-1}>{born ? "出生时间与地点" : "预产期与预计出生地"}</legend>
        <div className="grid birth-fields">
          <label className={!born ? "due-date-field" : ""}><span className="field-label">{born ? "实际出生日期" : "预产期日期"}</span><input type="date" name={born ? "birthDate" : "dueDate"} min="1900-01-01" max="2100-12-31" required value={born ? dates.birthDate : dates.dueDate} onChange={e => setDates(v => ({ ...v, [born ? "birthDate" : "dueDate"]: e.target.value }))} /></label>
          {born && <label><span className="field-label">准确出生时间</span><input name="birthTime" type="time" required value={dates.birthTime} onChange={e => setDates(v => ({ ...v, birthTime: e.target.value }))} /></label>}
          <label className={born ? "place-field full-width" : "place-field"}><span className="field-label">{born ? "出生城市或地区" : "预计出生城市或地区"}<span className="optional-label">可选</span></span><input name="place" value={place} onChange={e => setCity(e.target.value)} list="birthCities" placeholder="选城市可自动带入时区与经度" autoComplete="off" aria-describedby="placeHelp" /><datalist id="birthCities">{LOCATIONS.cities.map(c => <option key={c.id} value={c.name} />)}</datalist></label>
        </div>
        <p id="placeHelp" className="place-help">{city ? `已匹配${city.name}，${cityCoordinate ? `城市中心约${longitudeText(longitude)}` : longitude !== "" ? `自定义经度${longitudeText(longitude)}` : "请补充经度"}。` : longitude !== "" ? `已填写手动经度${longitudeText(longitude)}。` : place.trim() ? "该地点尚未匹配经度，可保留文字；真太阳时需手动填写经度。" : "可留空；选城市后自动带入时区和经度。"}{timeBasis === "civil" ? "当前按民用时间排盘，不作经度修正。" : "已启用真太阳时，经度将用于排盘修正。"}</p>
        <p className="simple-time-note">{born ? "请按出生记录填写。" : "预产期可填未来日期，默认12:00作参考。"}<button type="button" onClick={() => edit(1, "zone")}>{zoneLabel} · 调整</button></p>
      </fieldset>
      <details className="naming-preferences">
        <summary>偏好与名字设置<span>{length}字名 · {draft.candidateCount || 3}个方案 · 可选</span></summary>
        <fieldset disabled={locked}>
          <legend id="preferencesTitle" tabIndex={-1}>按你的心意调整</legend>
          <div className="grid">
            <label><span className="field-label">名的字数（不含姓）</span><select name="length" value={length} onChange={e => setLength(e.target.value)}><option value="2">两字名</option><option value="1">单字名</option><option value="3">三字名</option></select></label>
            <label><span className="field-label">方案数量</span><input name="candidateCount" type="number" min="1" max={max} required defaultValue="3" inputMode="numeric" /><small>可选1–{max}个，条件较严时展示实际数量。</small></label>
          </div>
          <div className="grid"><label>喜欢的字<input name="likedChars" maxLength={100} placeholder="例如：安、清（排序偏好）" /></label><label>必须避开的字<input name="avoidedChars" maxLength={100} placeholder="例如：伟、刚" /></label></div>
          <label>希望名字传达的气质<textarea name="meaning" rows="2" placeholder="例如：清朗、坚韧、自然山水" /></label>
          <div className="tags"><span>偏好风格</span>{[["classical", "清雅古典"], ["modern", "现代简洁"], ["nature", "自然山水"], ["bright", "明朗开阔"]].map(([value, label]) => <label key={value}><input type="checkbox" name="style" value={value} defaultChecked={value === "classical"} />{label}</label>)}</div>
          <details className="family-options"><summary>家庭姓氏与读音</summary>
            {rename && surnameField()}
            <label>父母姓氏<input name="parents" maxLength={12} placeholder="例如：林、沈" /></label>
            <label className="inline-check"><input type="checkbox" name="honorParents" value="true" />希望名中呼应父母姓氏</label>
            <label>姓氏读音<input name="surnameReading" maxLength={32} placeholder="多音姓可填 shàn；留空用常用姓氏读音" /></label>
          </details>
          <details className="naming-constraints"><summary>辈分、家族避讳与传统参考</summary>
            <div className="grid"><label>辈分或必用字<input name="requiredChars" maxLength={30} placeholder="每个字至少出现一次" /></label><label>家族避讳字<input name="tabooChars" maxLength={100} placeholder="只填需要避开的字" /></label></div>
            <label className="inline-check"><input type="checkbox" name="tabooHomophones" value="true" />同时避开这些字的普通话同音字</label>
            <label>五格数理<select name="numerologyMode" defaultValue="reference"><option value="reference">展示计算参考</option><option value="strict">严格筛选人格、地格、总格</option><option value="off">关闭五格展示</option></select><small>严格筛选可能减少数量；未知笔画保持未知。</small></label>
            <label>传统文化选字参考<select name="elementPreference" value={elementPreference} onChange={e => setElementPreference(e.target.value)}><option value="yongshen">按四柱喜用参考（月令扶抑法）</option><option value="auto">按生辰起卦体卦意象</option><option value="none">仅按读音、风格和心意</option>{["木", "火", "土", "金", "水"].map(e => <option key={e} value={e}>自选{e}意象</option>)}</select></label>
          </details>
          <details className="time-settings"><summary>时区与排盘时间设置</summary>
            <div className="grid"><label>时区<select name="zone" value={zone} onChange={e => setZone(e.target.value)}><option value="Asia/Shanghai">中国标准时间 UTC+8</option><option value="Asia/Taipei">台北时间 UTC+8</option><option value="Asia/Hong_Kong">香港时间 UTC+8</option></select></label>
              {!born && <label>预产期参考时间<input name="dueTime" type="time" value={dates.dueTime} onChange={e => setDates(v => ({ ...v, dueTime: e.target.value }))} /></label>}
            </div>
            <label>日柱与时柱时间口径<select name="timeBasis" value={timeBasis} onChange={e => setTimeBasis(e.target.value)}><option value="civil">当地民用时钟</option><option value="apparent_solar">真太阳时（按经度修正）</option></select></label>
            {timeBasis === "apparent_solar" && <div className="solar-fields">
              <input type="hidden" name="locationId" value={locationId} />
              <p className="coordinate-source">{cityCoordinate ? `已使用${city.name}城市中心经度，无需重复选城市。` : "可以回到上方选择城市自动带入，或填写实际出生地经度。"}<button type="button" onClick={() => edit(1, "place")}>{city ? "更换城市" : "选择城市"}</button></p>
              {city && !cityCoordinate && <button type="button" className="restore-coordinate" onClick={() => { setLongitude(String(city.longitude)); if (invalidField.current?.name === "longitude") clearError(); }}>恢复{city.name}城市中心经度</button>}
              <label><span className="field-label">出生地经度</span><input name="longitude" type="number" min="-180" max="180" step="0.000001" required value={longitude} onChange={e => setLongitude(e.target.value)} /><small>东经填正数，西经填负数；0也是有效经度。城市中心为近似值，可按实际地点调整。</small></label>
            </div>}
          </details>
        </fieldset>
      </details>
      <div className="simple-submit">
        <button className="primary" type="submit" disabled={locked}>{reviewBusy ? "正在分析现名…" : busy ? "正在生成…" : rename ? reviewCurrent ? "查看现名报告" : "分析现用姓名" : "生成名字方案 ✦"}</button>
        <small>无需登录。资料不会自动保存。</small>
      </div>
      {rename && review && <section className="simple-review" aria-label="现名报告与改名推荐">
        <h3 id="currentReviewTitle" tabIndex={-1}>先看现名，再选新名</h3>
        {reviewCurrent ? <>
          <p className="review-basis">分析依据：{dates.birthDate} {dates.birthTime} · {place || "地点未填写"}</p>
          <NameReview review={review.payload.analysis.name_review} id="formNameReview" compact />
          <ClockSummary chart={review.payload.analysis.bazi} />
          <details className="review-chart"><summary>查看本次四柱与起卦依据</summary><Chart analysis={review.payload.analysis} id="reviewTraditionalBasis" /></details>
          <div className="review-next"><button type="button" className="secondary" onClick={() => edit(0)}>修改资料</button><button type="button" className="primary" disabled={locked} onClick={() => generate(true)}>{busy ? "正在推荐…" : "根据这份报告推荐新名字"}</button></div>
        </> : <div className="review-stale"><p>姓名或出生资料已修改，请重新分析现名后继续。</p><button type="button" className="primary" disabled={locked} onClick={analyzeCurrentName}>重新分析现用姓名</button></div>}
      </section>}
      <p className="generation-progress" role="status" hidden={!locked}>{reviewBusy ? "正在整理现名分析与出生依据…" : "正在整理名字与取字依据…"}</p>
    </form>
  </section>;
});
