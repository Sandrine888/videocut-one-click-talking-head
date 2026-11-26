const puppeteer = require("puppeteer-core");
const fs = require("fs");
const path = require("path");
const http = require("http");
const { spawn } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const URL = "file:///" + path.join(ROOT, "动效工作台.html").split(path.sep).join("/");
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const OUT = __dirname;
const results = [];
const ok = (name, cond, extra) => results.push({ name, pass: !!cond, extra: extra === undefined ? null : extra });

// Edge 后台常驻进程会接管 puppeteer 的启动握手，改为手动 spawn 无头实例再 connect
const PORT = 9400 + (Date.now() % 400);
const UDD = path.join(process.env.TEMP || OUT, "wbtest_profile_" + Date.now());
let edgeProc = spawn(EDGE, [
  "--headless=new", `--user-data-dir=${UDD}`, "--no-sandbox",
  "--allow-file-access-from-files", "--autoplay-policy=no-user-gesture-required",
  "--mute-audio", `--remote-debugging-port=${PORT}`, "about:blank",
], { stdio: "ignore" });
process.on("exit", () => { try { edgeProc.kill(); } catch (_) {} });
async function waitBrowser() {
  for (let i = 0; i < 120; i++) {
    try {
      const j = await new Promise((res, rej) =>
        http.get(`http://127.0.0.1:${PORT}/json/version`, r => { let d = ""; r.on("data", c => d += c); r.on("end", () => res(JSON.parse(d))); }).on("error", rej));
      return j;
    } catch (_) { await new Promise(r => setTimeout(r, 250)); }
  }
  throw new Error("headless Edge 未能在调试端口启动");
}

(async () => {
  const info = await waitBrowser();
  const browser = await puppeteer.connect({ browserWSEndpoint: info.webSocketDebuggerUrl });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push("pageerror: " + e.message));
  page.on("console", m => { if (m.type() === "error") errors.push("console: " + m.text()); });
  page.on("requestfailed", r => {
    const u = r.url(), err = (r.failure() || {}).errorText || "";
    if ((err.includes("ERR_ABORTED")) && (u.endsWith(".mp4") || u.startsWith("blob:"))) return;
    errors.push("reqfail: " + u.split("/").pop() + " " + err);
  });
  await page.setViewport({ width: 1440, height: 900 });
  await page.goto(URL, { waitUntil: "networkidle0", timeout: 60000 });
  await page.waitForFunction("document.getElementById('vMain').readyState >= 2 && document.getElementById('vOff').readyState >= 2 && document.getElementById('vLight').readyState >= 2", { timeout: 30000 });
  await new Promise(r => setTimeout(r, 500));

  // ---- A 结构：只保留四块，其余已删 ----
  const A = await page.evaluate(() => {
    const $ = id => document.getElementById(id);
    return {
      overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      rows: $("segList").children.length,
      ctrlVisible: $("ctrlCard").getBoundingClientRect().height > 200,
      ranges: document.querySelectorAll("#ctrlCard input[type=range]").length,
      switches: document.querySelectorAll("#ctrlCard .sw input").length,
      sections: [...document.querySelectorAll("main > section")].map(s => s.id),
      removed: {
        liveStage: !!$("stageWrap") && !!$("overlay") && !!$("vMain"),
        liveCheck: !$("chkFace") && !$("vioList") && !$("statLine"),
        evidence: !document.querySelector(".evi"),
        legend: !document.querySelector(".legend"),
        repNums: !document.querySelector(".rep-nums"),
      },
      files: document.querySelectorAll(".files a").length,
      cmpVideos: [$("vMain"), $("vOff"), $("vLight")].map(v => v.readyState),
    };
  });
  ok("A 四区结构 tune/compare/files", A.sections.join() === "tune,compare,files", A.sections);
  ok("A 实时预览舞台保留", A.removed.liveStage);
  ok("A 实时几何自检已删除", A.removed.liveCheck);
  ok("A 证据帧/看什么/硬指标已删除", A.removed.evidence && A.removed.legend && A.removed.repNums);
  ok("A 无横向溢出", !A.overflowX);
  ok("A 24 段落行", A.rows === 24);
  ok("A 参数台常驻可见", A.ctrlVisible);
  ok("A 控件数>=7", A.ranges + A.switches >= 7, { ranges: A.ranges, switches: A.switches });
  ok("A 交付文件 7 链接", A.files === 7, A.files);
  ok("A 三版视频可解码", A.cmpVideos.every(r => r >= 2), A.cmpVideos);
  await page.screenshot({ path: path.join(OUT, "shot_desktop_lab.png") });

  // ---- S 实时预览舞台行为 ----
  await page.evaluate(() => { document.getElementById("vMain").currentTime = 14.5; });
  await new Promise(r => setTimeout(r, 400));
  const S1 = await page.evaluate(() => ({
    txt: document.getElementById("ovSub").textContent.trim(),
    hl: document.querySelector("#ovSub .hl")?.textContent,
    badgeShown: getComputedStyle(document.getElementById("ovBadge")).display !== "none",
    badgeTxt: document.getElementById("ovBadge").textContent,
    time: document.getElementById("ovTime").textContent,
  }));
  ok("S 定位14.5s→叠加显示第7条(高亮ASR)与第2节角标", S1.txt.includes("比如说") && S1.hl === "ASR" && S1.badgeShown && S1.badgeTxt.includes("第2节"), S1);
  const S2 = await page.evaluate(() => {
    const el = document.getElementById("rgFs"); el.value = 64; el.dispatchEvent(new Event("input", { bubbles: true }));
    return new Promise(r => setTimeout(() => r(getComputedStyle(document.querySelector(".sub-line")).fontSize), 300));
  });
  ok("S 字号滑杆即时改变叠加字号", parseFloat(S2) > 14, S2);
  await page.evaluate(() => { const el = document.getElementById("rgFs"); el.value = 48; el.dispatchEvent(new Event("input", { bubbles: true })); });
  await page.evaluate(() => { const el = document.getElementById("swEffects"); el.checked = false; el.dispatchEvent(new Event("change", { bubbles: true })); });
  await new Promise(r => setTimeout(r, 400));
  const S3 = await page.evaluate(() => ({
    badge: getComputedStyle(document.getElementById("ovBadge")).display === "none",
    hl: document.querySelectorAll("#ovSub .hl").length,
    op: document.getElementById("ovSub").style.opacity,
  }));
  ok("S 关动效→叠加无角标/高亮且常显", S3.badge && S3.hl === 0 && parseFloat(S3.op) === 1, S3);
  await page.evaluate(() => { const el = document.getElementById("swEffects"); el.checked = true; el.dispatchEvent(new Event("change", { bubbles: true })); });
  await page.evaluate(() => document.getElementById("btnMainPlay").click());
  await new Promise(r => setTimeout(r, 900));
  const S4 = await page.evaluate(() => ({ playing: !document.getElementById("vMain").paused, t: document.getElementById("vMain").currentTime }));
  ok("S 预览播放推进", S4.playing && S4.t > 14.6, S4);
  await page.evaluate(() => document.getElementById("btnCmpPlay").click());
  await new Promise(r => setTimeout(r, 300));
  const S5 = await page.evaluate(() => ({ mainPaused: document.getElementById("vMain").paused, cmp: !document.getElementById("vOff").paused }));
  ok("S 起播对照自动暂停预览（互斥）", S5.mainPaused && S5.cmp, S5);
  await page.evaluate(() => { document.getElementById("vOff").pause(); document.getElementById("vLight").pause(); });
  const tlbb = await (await page.$("#tlMain")).boundingBox();
  await page.mouse.move(tlbb.x + tlbb.width * 0.5, tlbb.y + tlbb.height / 2);
  await page.mouse.down(); await page.mouse.up();
  await new Promise(r => setTimeout(r, 300));
  const S6 = await page.evaluate(() => document.getElementById("vMain").currentTime);
  ok("S 预览时间轴拖拽定位", Math.abs(S6 - 0.5 * 46.266667) < 1.2, S6);

  // ---- B 段落点击定位对照样片 ----
  await page.evaluate(() => { document.documentElement.style.scrollBehavior = "auto"; });
  await page.evaluate(() => document.querySelectorAll(".seg-row")[6].click());
  await new Promise(r => setTimeout(r, 150));
  const B = await page.evaluate(() => ({
    off: document.getElementById("vOff").currentTime,
    light: document.getElementById("vLight").currentTime,
    act: document.querySelector(".seg-row.act")?.dataset.idx,
    playing: !document.getElementById("vOff").paused,
  }));
  await page.evaluate(() => { document.getElementById("vOff").pause(); document.getElementById("vLight").pause(); });
  await new Promise(r => setTimeout(r, 200));
  ok("B 点击第7条→两版定位13.44s并起播", Math.abs(B.off - 13.441) < 0.25 && Math.abs(B.light - B.off) < 0.1 && B.playing, B);

  // ---- C 参数即时反映到段落列表 ----
  const setRange = (id, v) => page.evaluate((id, v) => {
    const el = document.getElementById(id); el.value = v;
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, id, v);
  await setRange("rgChars", 12);
  await new Promise(r => setTimeout(r, 200));
  const C1 = await page.evaluate(() => document.querySelectorAll(".seg-row")[5].querySelector(".meta").textContent);
  ok("C 每行12字→第6条2行", C1.includes("2行"), C1);
  await page.evaluate(() => { const el = document.getElementById("colHl"); el.value = "#ff4f9a"; el.dispatchEvent(new Event("input", { bubbles: true })); });
  const C2 = await page.evaluate(() => getComputedStyle(document.querySelector(".seg-row .x .hl")).color);
  ok("C 高亮换色即时生效", C2 === "rgb(255, 79, 154)", C2);
  await page.evaluate(() => { const el = document.getElementById("swEffects"); el.checked = false; el.dispatchEvent(new Event("change", { bubbles: true })); });
  const C3 = await page.evaluate(() => ({
    hls: document.querySelectorAll(".seg-row .x .hl").length,
    ass: window.buildAss(),
  }));
  ok("C 关动效→列表无高亮且ASS无fad/角标", C3.hls === 0 && !C3.ass.includes("\\fad") && !C3.ass.includes("Badge"), { hls: C3.hls });
  await page.evaluate(() => { const el = document.getElementById("swEffects"); el.checked = true; el.dispatchEvent(new Event("change", { bubbles: true })); });
  await page.click("#btnReset");
  await new Promise(r => setTimeout(r, 200));
  const C4 = await page.evaluate(() => ({
    meta: document.querySelectorAll(".seg-row")[5].querySelector(".meta").textContent,
    hl: getComputedStyle(document.querySelector(".seg-row .x .hl")).color,
    fade: document.getElementById("rgFade").value,
  }));
  ok("C 重置回默认(1行/黄色/120ms)", C4.meta.includes("1行") && C4.hl === "rgb(255, 255, 0)" && C4.fade === "120", C4);
  await page.click("#btnRandom");
  await new Promise(r => setTimeout(r, 200));
  const C5 = await page.evaluate(() => ({ fade: +document.getElementById("rgFade").value, toast: document.getElementById("toast").classList.contains("show") }));
  ok("C 随机参数生效+toast", C5.fade >= 80 && C5.fade <= 150 && C5.toast, C5);
  await page.click("#btnReset");

  // ---- D 走带：播放/倍速/帧步/键盘 ----
  await page.evaluate(() => { document.getElementById("vOff").currentTime = 14.5; document.getElementById("vLight").currentTime = 14.5; });
  await page.evaluate(() => document.getElementById("compare").scrollIntoView());
  await new Promise(r => setTimeout(r, 300));
  await page.click("#btnCmpPlay");
  await new Promise(r => setTimeout(r, 1000));
  const D1 = await page.evaluate(() => ({
    off: !document.getElementById("vOff").paused, light: !document.getElementById("vLight").paused,
    drift: Math.abs(document.getElementById("vOff").currentTime - document.getElementById("vLight").currentTime),
    t: document.getElementById("vOff").currentTime,
  }));
  ok("D 同步播放且漂移<120ms", D1.off && D1.light && D1.drift < 0.12 && D1.t > 15, D1);
  await page.click("#btnCmpPlay");
  await page.click("#btnFwd");
  await new Promise(r => setTimeout(r, 250));
  const D2 = await page.evaluate(() => document.getElementById("vOff").currentTime);
  ok("D 帧步进前进", D2 > D1.t + 0.02, { before: D1.t, after: D2 });
  await page.evaluate(() => document.body.focus());
  await page.keyboard.press("ArrowLeft");
  await new Promise(r => setTimeout(r, 250));
  const D3 = await page.evaluate(() => document.getElementById("vOff").currentTime);
  ok("D 左方向键后退一帧", D3 < D2, { D2, D3 });
  await page.select("#selSpeed", "1.5");
  const D4 = await page.evaluate(() => [document.getElementById("vOff").playbackRate, document.getElementById("vLight").playbackRate]);
  ok("D 倍速同步两版", D4.join() === "1.5,1.5", D4);
  await page.select("#selSpeed", "1");
  await page.click("#btnCmpRestart");
  await new Promise(r => setTimeout(r, 250));
  const D5 = await page.evaluate(() => document.getElementById("vOff").currentTime);
  ok("D 回零", D5 < 0.1, D5);

  // ---- E 时间轴拖拽 ----
  const bb = await (await page.$("#tlCmp")).boundingBox();
  await page.mouse.move(bb.x + bb.width * 0.3, bb.y + bb.height / 2);
  await page.mouse.down();
  await new Promise(r => setTimeout(r, 200));
  const E1 = await page.evaluate(() => document.getElementById("vOff").currentTime);
  await page.mouse.move(bb.x + bb.width * 0.6, bb.y + bb.height / 2, { steps: 6 });
  await page.mouse.up();
  await new Promise(r => setTimeout(r, 250));
  const E2 = await page.evaluate(() => ({
    off: document.getElementById("vOff").currentTime,
    light: document.getElementById("vLight").currentTime,
  }));
  ok("E 拖拽30%≈13.9s", Math.abs(E1 - 0.3 * 46.266667) < 0.8, E1);
  ok("E 拖拽60%两版同步", Math.abs(E2.off - 0.6 * 46.266667) < 0.8 && Math.abs(E2.off - E2.light) < 0.15, E2);

  // ---- F 静音 ----
  await page.click("#btnMute");
  const F1 = await page.evaluate(() => ({
    m: [document.getElementById("vOff"), document.getElementById("vLight")].every(v => v.muted),
    cls: document.getElementById("btnMute").classList.contains("muted"),
    txt: document.querySelector("#btnMute .txt").textContent,
  }));
  ok("F 一键全静音+状态文案", F1.m && F1.cls && F1.txt === "已静音", F1);
  await page.click("#btnMute");
  const F2 = await page.evaluate(() => [document.getElementById("vOff"), document.getElementById("vLight")].every(v => !v.muted));
  ok("F 再点恢复", F2);
  await page.screenshot({ path: path.join(OUT, "shot_desktop_compare.png") });

  // ---- G 导出与 python 产物逐行一致 + 真实下载 ----
  const G0 = await page.evaluate(() => {
    const ass = window.buildAss();
    return {
      dialogues: (ass.match(/^Dialogue:/gm) || []).length,
      fad: (ass.match(/\\fad\(120,0\)/g) || []).length,
      badges: (ass.match(/,Badge,,/g) || []).length,
      hl: (ass.match(/\{\\c&H00FFFF&\}/g) || []).length,
    };
  });
  ok("G ASS 28事件/24淡入/4角标/2高亮", G0.dialogues === 28 && G0.fad === 24 && G0.badges === 4 && G0.hl === 2, G0);
  const pyAss = fs.readFileSync(path.join(ROOT, "社团项目", "d_output", "微信视频2026-11-21_213120_116_cut_light.ass"), "utf8");
  const dlg = s => s.split(/\r?\n/).filter(l => l.startsWith("Dialogue:")).map(l => l.trim());
  const jsAss = await page.evaluate(() => window.buildAss());
  const a = dlg(pyAss), b = dlg(jsAss);
  const diff = [];
  for (let i = 0; i < Math.max(a.length, b.length); i++) if (a[i] !== b[i]) diff.push({ i, py: a[i], js: b[i] });
  ok("G 导出 ASS 与 effects.py 产物逐行一致", diff.length === 0, diff.slice(0, 4));
  const dl = path.join(OUT, "dl"); fs.mkdirSync(dl, { recursive: true });
  const bclient = await browser.target().createCDPSession();
  await bclient.send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: dl, eventsEnabled: true });
  await page.evaluate(() => document.getElementById("tune").scrollIntoView());
  await new Promise(r => setTimeout(r, 300));
  await page.click("#btnAss");
  await new Promise(r => setTimeout(r, 3000));
  ok("G ASS 真实下载落盘", fs.readdirSync(dl).some(f => f.endsWith(".ass")), fs.readdirSync(dl));
  await page.click("#btnJson");
  await new Promise(r => setTimeout(r, 2500));
  ok("G JSON 真实下载落盘", fs.readdirSync(dl).some(f => f.endsWith(".json")), fs.readdirSync(dl));

  // ---- H 平板 / 手机 ----
  await page.setViewport({ width: 1000, height: 800 });
  await new Promise(r => setTimeout(r, 500));
  ok("H 1000px 无横向溢出", !(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)));
  await page.screenshot({ path: path.join(OUT, "shot_tablet.png") });
  await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
  await page.evaluate(() => window.scrollTo(0, 0));
  await new Promise(r => setTimeout(r, 600));
  const H1 = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    ctrlH: document.getElementById("ctrlCard").getBoundingClientRect().height,
  }));
  ok("H 390px 无横向溢出", !H1.overflow, H1);
  ok("H 手机参数台不折叠", H1.ctrlH > 300, H1.ctrlH);
  await page.screenshot({ path: path.join(OUT, "shot_mobile_top.png") });
  await page.evaluate(() => document.getElementById("compare").scrollIntoView());
  await new Promise(r => setTimeout(r, 600));
  await page.screenshot({ path: path.join(OUT, "shot_mobile_compare.png") });
  ok("H 手机对比区无溢出", !(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)));

  // ---- I 重复交互稳定性 ----
  await page.setViewport({ width: 1440, height: 900 });
  await page.evaluate(() => document.getElementById("compare").scrollIntoView());
  for (let i = 0; i < 6; i++) { await page.click("#btnCmpPlay"); await new Promise(r => setTimeout(r, 150)); }
  const I1 = await page.evaluate(() => [document.getElementById("vOff"), document.getElementById("vLight")].filter(v => !v.paused).length);
  ok("I 交替播放状态一致", I1 === 0 || I1 === 2, I1);
  await page.evaluate(() => { document.getElementById("vOff").pause(); document.getElementById("vLight").pause(); });

  // ---- J 导入视频/字幕 + 横竖屏自适应 ----
  const pv = path.join(ROOT, "社团项目", "微信视频2026-11-21_213120_116_cut.mp4");
  await (await page.$("#fileVideo")).uploadFile(pv);
  await page.waitForFunction("window.__state().cmpLive && window.__state().W===720", { timeout: 20000 });
  const J1 = await page.evaluate(() => window.__state());
  ok("J 导入竖屏视频→objectURL 接管三播放器并读出真实分辨率/时长", J1.cmpLive && J1.orient === "portrait" && J1.W === 720 && J1.H === 1280 && Math.abs(J1.dur - 46.27) < 0.5, J1);
  await page.evaluate(() => { document.getElementById("vOff").currentTime = 14.5; });
  await new Promise(r => setTimeout(r, 400));
  const J2 = await page.evaluate(() => ({
    shown: getComputedStyle(document.getElementById("ovCmp")).display !== "none",
    txt: document.getElementById("ovCmpSub").textContent.trim(),
    hl: document.querySelector("#ovCmpSub .hl")?.textContent,
    badge: document.getElementById("ovCmpBadge").textContent,
  }));
  ok("J 导入后对照轻动效格用叠加模拟字幕/高亮/角标", J2.shown && J2.txt.includes("比如说") && J2.hl === "ASR" && J2.badge.includes("第2节"), J2);
  await page.evaluate(() => { document.getElementById("vOff").pause(); document.getElementById("vLight").pause(); });

  const lv = path.join(ROOT, "videocut", "demo_output", "test_landscape.mp4");
  await (await page.$("#fileVideo")).uploadFile(lv);
  await page.waitForFunction("window.__state().orient==='landscape'", { timeout: 20000 });
  const J3 = await page.evaluate(() => Object.assign(window.__state(), {
    ar: getComputedStyle(document.getElementById("stageWrap")).aspectRatio,
    fsMax: document.getElementById("rgFs").max,
    badgeTop: document.getElementById("ovBadge").style.top,
    land: document.body.classList.contains("land"),
    swW: document.getElementById("stageWrap").getBoundingClientRect().width,
    swH: document.getElementById("stageWrap").getBoundingClientRect().height,
  }));
  ok("J 横屏视频→landscape/16:9 舞台/滑杆范围 24-48/字号默认 36", J3.W === 1920 && J3.H === 1080 && J3.fsMax === "48" && J3.fs === 36 && J3.chars === 22 && J3.ar.replace(/\s/g, "") === "1920/1080", J3);
  ok("J 横屏预览区横跨整行放大(宽>600且高>340)", J3.land && J3.swW > 600 && J3.swH > 340, { swW: Math.round(J3.swW), swH: Math.round(J3.swH) });

  const lsSrt = path.join(OUT, "landscape.srt");
  fs.writeFileSync(lsSrt, "1\n00:00:00,500 --> 00:00:03,000\n大家好，欢迎来到我的频道。\n\n2\n00:00:03,200 --> 00:00:06,000\n今天聊聊 FunASR 的用法。\n\n3\n00:00:06,500 --> 00:00:09,000\n这个功能提升了 30% 的效率。\n\n4\n00:00:09,200 --> 00:00:11,500\n我们下期再见。\n");
  await (await page.$("#fileSubs")).uploadFile(lsSrt);
  await page.waitForFunction("window.__state().segs===4", { timeout: 10000 });
  const J4 = await page.evaluate(() => ({
    rows: document.getElementById("segList").children.length,
    st: window.__state(),
    sub: document.getElementById("segList").children[1].querySelector(".x").textContent,
    hl: document.getElementById("segList").children[1].querySelector(".x .hl")?.textContent,
  }));
  ok("J 导入横屏 SRT→4 条解析/高亮选词/段落表重建", J4.rows === 4 && J4.st.chaps === 0 && J4.sub.includes("FunASR") && J4.hl === "FunASR", { rows: J4.rows, chaps: J4.st.chaps, hl: J4.hl });
  await page.screenshot({ path: path.join(OUT, "shot_landscape_import.png") });

  await page.click("#btnLoadSample");
  await page.waitForFunction("!window.__state().cmpLive && window.__state().segs===24", { timeout: 10000 });
  const J5 = await page.evaluate(() => window.__state());
  ok("J 恢复示例→竖屏 24 条 / DUR 46.27 / 模拟叠加关闭", J5.orient === "portrait" && Math.abs(J5.dur - 46.27) < 0.01 && !J5.cmpLive && J5.W === 1080, J5);
  await page.evaluate(() => { const el = document.getElementById("swEffects"); el.checked = true; el.dispatchEvent(new Event("change", { bubbles: true })); });

  ok("Z console/page/请求 零错误", errors.length === 0, errors.slice(0, 8));
  await browser.close();
  const fails = results.filter(r => !r.pass);
  fs.writeFileSync(path.join(OUT, "results.json"), JSON.stringify({ results, errors }, null, 2));
  console.log(results.map(r => `${r.pass ? "PASS" : "FAIL"}  ${r.name}${r.extra !== null ? "  " + JSON.stringify(r.extra) : ""}`).join("\n"));
  console.log(`\n${results.length - fails.length}/${results.length} PASS`);
  process.exit(0);
})().catch(e => { console.error("SCRIPT ERROR", e); fs.writeFileSync(path.join(OUT, "results.json"), JSON.stringify({ results, errors: [String(e)] }, null, 2)); process.exit(1); });