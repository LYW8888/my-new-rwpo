# 序名 · 现代东方命名

当前新表单默认使用古籍取名v3：原句取意、受控组合、六维评分、必用字/避讳、康熙笔画与可配置五格。完整口径见[古籍取名规则](data/NAMING_V3.md)，数据与出处说明见[资料说明](data/naming/README.md)。旧客户端未传算法字段时仍按v2重算，下面历史规则说明适用于对应版本。

响应式中文起名与改名原型。前端使用 React 19 与 Vite 8，后端使用 Python。已接入四柱、干支阴阳、地支藏干、十神与年月日时起卦，并将明确的部首五行规则和用户偏好用于候选排序。经典规则已完成15处固定版本录文对照，数值采用公开的序名分析参数；提供可选真太阳时、月令取格与扶抑分析，名字寓意按现代字义整理。

## 安装与运行

需要 Python 3.9+、系统时区数据库，以及 Node.js 20.19–20.x 或 22.12+（建议使用受支持的 LTS 版本）。安装依赖并构建 React 前端：

```bash
python3 -m pip install -r requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
python3 scripts/import_naming_corpus.py
python3 server.py
```

访问 `http://localhost:4173`。Python 服务从 `frontend/dist` 提供构建后的页面和静态资源；没有构建时首页返回 503，API 仍可用。服务提供 `/api/health`、`/api/catalog`、`/api/classics`、`/api/product`、`/api/name-counts`、`/api/analyze` 和 `/api/name-review`。四柱由服务端计算；服务不可用时页面会提示重试，不会回退到虚构的排盘。

开发时先启动 Python 服务（默认端口 4173），再在另一个终端执行 `npm run dev --prefix frontend`，访问 Vite 给出的本地地址；开发服务器将 `/api` 和 `/data` 代理到 Python 服务。每次部署前重新运行前端构建，构建目录和 `node_modules` 不提交到 Git。根目录的旧 `index.html`、`app.js`、`service-worker.js` 仅保留历史回滚资料，生产首页使用 React 版本；旧界面混填日期不再符合当前API校验。

## 四柱排盘口径

- 支持 1900–2100 年、`Asia/Shanghai`、`Asia/Taipei`、`Asia/Hong_Kong`。输入为所选地区的当地民用日期和时间；夏令时不存在或重复的时刻会要求核对。
- 年柱以立春交接时刻为界，月柱以十二“节”的交接时刻为界。历法库节气时刻按 UTC+8 标准时间解释，再转换至所选时区。
- 日柱按当地民用时间 23:00 换日，23:00–00:59 为子时。其他流派可能采用不同换日口径。
- 日/时柱默认使用民用时钟，可在出生信息中选择真太阳时并填写经度或城市中心；系统同时处理历史时区/夏令时与均时差。年、月柱始终按原始物理时刻的节气确定。城市中心仅为近似位置，具体经度可修改；不会猜测自由文本地址。
- 表面五行计数统计四个天干和四个地支各一项；藏干次数单独展示，不混加、不赋季节权重，不能直接推出旺衰、喜用神或运势。
- 新生儿起名分为预产期与已出生两条独立流程。预产期允许未来时间，默认12:00作参考；已出生只使用实际出生日期和准确时间，拒绝未来出生时刻。一份请求不能混填两种日期，不再自动切换计算依据。
- 改名固定使用实际出生信息；必须填写完整现用姓名，先查看现名分析，再设置偏好并生成改名方案。候选排除现用全名。
- 若输入时刻距节交接不超过 2 分钟，返回边界提醒和交接前后可能的年、月柱；请核对出生记录和节气时刻。

## 核验与局限

历法引擎固定为 [`lunar_python` 1.4.8](https://github.com/6tail/lunar-python)（MIT）。测试基于立春、惊蛰、晚子时和已知日期样例，并与 [`sxtwl` 2.0.7](https://github.com/yuangu/sxtwl_cpp) 交叉比较：固定随机种子下 1,407 个非节气交接日的四柱一致；2,613 个节交接记录（含相邻年记录）最大时刻差约 54.4 秒。两个库有共同的寿星天文历来源，因此这不是完全独立的天文观测验证。

香港天文台公开历表在本次执行环境返回 HTTP 403，尚未完成权威历表逐条对照或机构认证。时区历史数据、精确出生时间及真太阳时仍会影响结果。复现跨库检查：

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/verify_bazi_crosscheck.py
python3 scripts/verify_solar_terms_skyfield.py
```

第二项使用 Skyfield 和 JPL DE421 星历，以地心视黄经交点独立比较节气时刻：1900–2050 年每 5 年抽取 12 节，共 372 个样本，最大绝对时差约 45.9 秒。DE421 只覆盖到 2053 年，抽样不覆盖全部时间，也不是对四柱全部规则的独立核验或机构认证。

## 自动化测试

```bash
python3 -m unittest discover -s tests -v
node --test tests/test_*.js
# 首次运行需安装浏览器：npx --prefix frontend playwright install chromium
npm run test:e2e --prefix frontend
```

启动服务后可运行 `python3 scripts/simulate_100_users.py --base-url http://127.0.0.1:4173`，生成 100 条可重复的合成用户路径；结果不是实际用户访谈。历史反馈见 `reports/simulated-100-users.md`。

## API 示例

```bash
curl -s -X POST http://localhost:4173/api/analyze -H 'Content-Type: application/json' -d '{"mode":"due_date","surname":"林","dueDate":"2099-04-16","dueTime":"12:00","place":"杭州","zone":"Asia/Shanghai","length":2,"candidateCount":5,"gender":"unknown"}'
```

`analysis.bazi` 包含四柱、日主、表面五行计数、前后节气、规则口径、来源和节气边界提示。`analysis.workflow`、`purpose_code` 和 `mode` 标识当前业务场景；新请求的 `bazi_comparison` 固定为空，旧报告对照资料仍可阅读。改名必须提供 `purpose=rename`、`mode=born` 与以姓氏开头的完整 `currentName`。先请求 `/api/name-review` 获取 `analysis.name_review`（不返回候选），确认后使用 `/api/analyze` 推荐。推荐接口也重新生成相同出生事实下的现名分析，不能提交伪造报告代替计算。`analysis.traditional` 返回干支阴阳、藏干、十神、月支本气和独立计数；`analysis.gua` 返回年月日时起卦的农历参数、算式、六爻、本卦、变卦与体用。`analysis.naming_reference` 说明排序的五行偏好，`ranking_version` 记录规则版本。详见 [算法与资料边界](data/ALGORITHM.md)。

候选及展示资料统一来自 `data/names.json`，当前有 65 条人工整理的候选（单字名 25、两字名 30、三字名 10），并非已核验字典。筛选和排序由 `/api/analyze` 统一完成，前端展示服务端提供的资料与核验状态。`likedChars` 是逐字排序偏好，并不保证每个名字都包含；`avoidedChars` 是逐字排除条件，仅作用于名，不排除姓氏。两者支持汉字、空格和常用分隔符，不能包含相同的字。筛选后数量不足时返回实际可用数量；没有匹配时返回空列表，不以不同字数或含避用字的名字补足。重新生成会在符合条件的候选池中轮换，后续轮次用于浏览而非每次都重新抽取最高分，候选池不足时可能重复。旧版 `chars` 字段仍支持“喜欢清，避开刚”等简单写法，建议新客户端使用独立字段。

`candidates[].pronunciation` 用 [`pypinyin` 0.55.0](https://github.com/mozillazg/python-pinyin)（MIT）逐字对照普通话读音。现有 65 条候选的预设读音均可在该库单字读音中找到；多音姓氏列出字典选项，不自动断定姓氏的正确读法。姓与名含相同字时会提示用户自行判断。此对照不代表姓名读音已获权威核验，不能检查方言、完整谐音或判断名字好坏；未收录和不匹配都明确标示。Unicode 官方数据在当前执行环境被网络代理拒绝访问，尚未完成官方字表对照。

API省略 `elementPreference` 时兼容原有 `auto` 体卦意象；新表单默认 `yongshen`，按月令格局与扶抑喜用规则试算选字，遇中和、临界或特殊组合时不强指定喜用。`none` 关闭五行排序，也可手选 `木/火/土/金/水`。经典原文与分析参数分别可查，体卦五行和扶抑喜用是两个不同选项。`honorParents=true` 时才将父母姓氏的汉字加入用字偏好；避用字始终优先。

首次使用为一页表单：预产期起名填写姓氏、预产期即可生成，参考时间默认12:00；已出生起名使用实际出生日期与准确时间。城市在民用时间模式可不填；选择已收录城市会自动带入时区与经度，启用真太阳时后直接用于修正，无需重复选城市。未知地点可手动输入经度；更换或清空城市会清除旧经度。结果和报告显示实际时间口径、经度来源与修正结果，详见 [出生地与时间联动](reports/location-time-flow.md)。性别可选，默认未知；名字默认两字名、3个方案，字数、数量、偏好、避讳及排盘设置默认收起。改名输入完整现用姓名后自动识别常见复姓（可手动修正），先查看现名速览，再明确点击推荐新名字；完整现名报告和四柱依据可展开。宝宝与改名对象的出生资料分别保留在当前页面内存中，不自动混填。切换场景时收起旧场景方案，修改现名或出生依据后须重新分析。流程对照及实测截图见 [操作流程精简记录](reports/simplified-flow.md)。

修改条件需要明确应用，换组可返回本次浏览历史并保留比较清单。请求失败保留上一份方案。收藏面板支持搜索、复制清单、回到方案及清空撤销。结果先展示候选，再展示排盘。可选1–3个候选并排查看读音、寓意、部首五行及分项理由；比较与收藏不自动保存出生信息。下载报告与客户主动保存的记录都保留计算依据，新旧报告分别标注，旧演示记录不会被改写为新规则结果。

真太阳时字段 `timeBasis/longitude/locationId`、月令格局、旺衰权重、扶抑喜用的取值与复核条件详见 [完整规则说明](data/MINGLI_RULES.md)。`analysis.mingli` 返回逐项权重、根气、敏感性、取格和喜用参考，`analysis.bazi.time_correction` 返回修正项与民用/太阳钟对照。均时差已与本地JPL DE421独立方法做204个样本对照，最大差约2.861秒；只验证均时差，不是命理规则认证。复现：`python3 scripts/verify_equation_of_time.py`（需开发依赖）。

出处核对记录见 [经典依据说明](data/CLASSICAL_SOURCES.md)。`analysis.source_audit` 保留15处引文、篇章、底本标识和固定版本链接；`analysis.traditional.relationships` 返回八个干支的28组两两关系及四柱相对日主的关系，`analysis.mingli.strength` 的逐项权重含生克、阴阳同异及十神。数字化录文核对与项目数值参数分开标识，不把数学测试当作运势认证。

```bash
python3 scripts/verify_classical_sources.py  # 离线检查本地引文和规则表
python3 scripts/verify_classical_sources.py --fetch  # 从固定Git提交重新核对原文
```

## 隐私与产品状态

收藏的名字、拼音和寓意只保存在浏览器本地，可从页面底部清除；出生信息提交至同源分析服务，不写入收藏。下载方案和名字心愿卡由浏览器生成；心愿卡只包含用户主动填写的名字、祝愿及网站域名，不自动加入出生信息。推荐链接由首页地址和固定的 `utm_source=share&utm_medium=referral` 来源参数组成，不附带表单、出生或收藏数据；复制与系统分享由用户主动操作，当前没有站内推荐归因统计。支付接口尚未接入，正式上线前需补齐隐私政策、数据保存及删除流程、支付与报告交付。

服务仅公开页面所需的静态文件和 API，不提供项目目录浏览或数据库文件下载；API 响应设置 `no-store`，服务工作线程只缓存公开静态资源。自带的 Python HTTP 服务主要供开发和验证使用，本身不提供 HTTPS。对外部署需通过可信的 HTTPS 反向代理，并确认代理不会直接公开项目目录或记录请求体中的出生信息；还需按实际部署环境配置访问控制、限流和运维监控。

部署准备示例和验证步骤见 [`deploy/README.md`](deploy/README.md)；示例尚未在目标服务器执行，正式政策和运营信息需由实际运营方补全。

## 经营、客服与财务隔离基础

产品采用一次购买、一次确认范围、一次交付的服务规划，不订阅、不自动续费，正常流程不设置退款步骤。项目提供内部客服状态、财务手工登记及单次履约状态机，支持重复请求去重、并发尝试保护、失败重试上限和固定报告摘要；尚未连接支付或自动报告任务。角色边界、服务范围、异常处理、部署条件及内部命令见 [单次服务与隔离说明](operations/README.md)。工具需要目标服务器上独立的系统账号、目录权限和身份审计；当前尚未配置目标服务器或真实支付。

## 网页管理后台

已加入独立 Django + React 后台：密码和动态验证码登录、首次改密、员工开通/停用、经营汇总、客服工单、财务手工登记与冲销、单次履约状态及岗位审计。服务端验证岗位权限；网关通过校验系统 UID 的 Unix socket 调用各自独立的岗位进程。没有默认账号，尚未部署到线上，也未接入真实支付或报告交付。安装、开通账号、隔离配置和验证命令见 [后台部署说明](backoffice/README.md)。

## 客户“我的服务”

匿名免费体验继续开放。新增独立的手机号验证码登录、明确确认后保存免费体验方案、账号内找回报告、删除记录及过期清理；员工账号与客户账号不共用数据库或 Cookie。报告正文加密，免费记录可找回 30 天；没有新增付费订单或收费接口。短信凭据未配置时登录默认关闭，页面仍可免登录体验及本地下载。供应商配置、数据范围、部署和测试见 [客户服务说明](customer/README.md)。

生成按钮的故障检查：服务器更新后先构建前端并重启应用，再运行 `python3 scripts/check_site.py --url http://127.0.0.1:4173`。页面与接口路由、资源缺失或旧版静态首页的问题会给出具体原因，详见 [部署排查](deploy/README.md)。

本轮实际页面走查、已修复的问题及验证范围见 [体验走查记录](reports/ux-review.md)。

起名与改名的当前业务边界、现名分析顺序、接口兼容变化及部署验收见[场景流程修正](reports/workflow-correction.md)。


## 古籍取名v3接口

新表单提交 `algorithm=literary_v3`。接口保留原有三条业务流程，支持新增字段：`requiredChars`（每字必用）、`tabooChars`（家族避讳）、`tabooHomophones`（普通话同音避讳）、`surnameReading`（指定多音姓读音）、`numerologyMode=off/reference/strict`。避用与必用冲突直接报错；缺少可引用义项返回实际空结果及原因，不换字数补足。

`/api/naming-corpus` 返回真实资料统计；`/api/name-counts?algorithm=literary_v3` 返回基础受控候选池数量，具体筛选数量以分析响应为准。`analysis.corpus/search/filters/page_size` 分别记录资料版本、搜索范围、筛选计数和分页大小。新名字的 `citations/source_kind/numerology/pronunciation.evaluation` 保存原句行号与SHA、取字类型、五格与完整读音；六维评分见 `ranking.criteria`。所有报告下载及账号主动保存均保留这些字段。

资料库含3,636条字典记录、5,543条正文、82个编辑取名片段、121个正向义项。自动推荐按这些可解释义项生成，不将3,636字任意拼成名字。原句对照不自动等于底本逐字精校；近五年用字热度及真实重名概率没有输入统计数据，未启用。

本地合成场景验证：`python3 scripts/validate_literary_naming.py`。部署前运行资料导入，再重启命名服务及客户服务；只读参考数据不改变账号、客服和财务权限隔离。
