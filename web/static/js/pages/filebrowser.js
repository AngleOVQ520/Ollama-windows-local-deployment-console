// 本地文件 / 文件夹选择器（通过后端浏览磁盘）
import { get, post } from "../core/api.js";
import { icon } from "../core/icons.js";
import { $, esc, fmtBytes, h, modal, promptBox, toastErr } from "../core/ui.js";

export function pickPath({ mode = "dir", title, start = "" } = {}) {
  return new Promise((resolve) => {
    let cur = start, selected = null, result = null;
    const body = h(`<div class="fb"><div class="fb-drives"></div><div class="fb-path"><button class="btn sm icon" data-up data-tip="上一级">${icon("chevR", "sm")}</button>
      <input class="input sm" data-path placeholder="输入路径后回车"><button class="btn sm" data-mk>${icon("plus", "sm")}新建文件夹</button></div><div class="fb-list"></div>
      <div class="hint sel-hint">${mode === "dir" ? "进入目标文件夹后点击「选择此文件夹」" : "双击 .gguf 文件或选中后点击「选择」"}</div></div>`);
    $("[data-up] .ico", body).style.transform = "rotate(180deg)";
    const foot = h(`<div style="display:contents"><button class="btn ghost" data-c>取消</button><button class="btn primary" data-o>${mode === "dir" ? "选择此文件夹" : "选择"}</button></div>`);
    const m = modal({ title: title || (mode === "dir" ? "选择文件夹" : "选择 GGUF 文件"), body, foot, wide: true, icon: "folder", onClose: () => resolve(result) });
    const list = $(".fb-list", body), pathIn = $("[data-path]", body);
    const go = async (p) => {
      try {
        const d = await get(`/api/fs/browse?mode=${mode}&path=${encodeURIComponent(p || "")}`);
        cur = d.path;
        selected = null;
        pathIn.value = d.path;
        $(".fb-drives", body).innerHTML = d.drives.map((x) => `<button class="chip ${cur.toUpperCase().startsWith(x.path.toUpperCase()) ? "on" : ""}" data-d="${esc(x.path)}">${icon("hdd", "sm")}${esc(x.name)}${x.free ? `<span class="n">${fmtBytes(x.free, 0)} 可用</span>` : ""}</button>`).join("");
        $(".fb-drives", body).querySelectorAll("[data-d]").forEach((b) => (b.onclick = () => go(b.dataset.d)));
        $("[data-up]", body).onclick = () => go(d.parent ?? "");
        list.innerHTML = "";
        if (!d.path) { list.innerHTML = `<div class="empty">${icon("hdd")}<div>请选择上方的磁盘</div></div>`; return; }
        if (!d.entries.length) list.innerHTML = `<div class="empty" style="padding:30px">${icon("folder")}<div>空文件夹</div></div>`;
        for (const e of d.entries) {
          const it = h(`<div class="fb-item ${e.type}">${icon(e.type === "dir" ? "folder" : "file")}<span class="ellipsis">${esc(e.name)}</span>${e.size ? `<span class="sz">${fmtBytes(e.size)}</span>` : ""}</div>`);
          it.onclick = () => {
            if (e.type === "dir") go(e.path);
            else { list.querySelectorAll(".sel").forEach((x) => x.classList.remove("sel")); it.classList.add("sel"); selected = e.path; }
          };
          if (e.type === "file") it.ondblclick = () => { result = e.path; m.close(); };
          list.appendChild(it);
        }
      } catch (e) { toastErr(e); }
    };
    pathIn.onkeydown = (e) => { if (e.key === "Enter") go(pathIn.value.trim()); };
    $("[data-mk]", body).onclick = async () => {
      if (!cur) return;
      const n = await promptBox("新建文件夹", { placeholder: "文件夹名称" });
      if (!n) return;
      try { const r = await post("/api/fs/mkdir", { path: cur, name: n }); go(r.path); } catch (e) { toastErr(e); }
    };
    $("[data-c]", foot).onclick = m.close;
    $("[data-o]", foot).onclick = () => {
      if (mode === "dir") { if (!cur) return; result = cur; }
      else { if (!selected) return; result = selected; }
      m.close();
    };
    go(start);
  });
}
