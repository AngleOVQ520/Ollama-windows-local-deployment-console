// HTTP 与事件流封装
import { getLang } from "./i18n.js";

export async function api(path, { method = "GET", body, raw = false, signal } = {}) {
  // X-Lang：让后端返回的错误 / 日志 / 阶段名跟随界面语言
  const opt = { method, headers: { "X-Lang": getLang() }, signal };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  if (raw) return r;
  let d;
  try { d = await r.json(); } catch { throw new Error(`HTTP ${r.status}`); }
  if (!d.ok) throw new Error(d.error || `HTTP ${r.status}`);
  return d.data;
}
export const get = (p) => api(p);
export const post = (p, body = {}) => api(p, { method: "POST", body });
export const patch = (p, body = {}) => api(p, { method: "PATCH", body });
export const put = (p, body = {}) => api(p, { method: "PUT", body });
export const del = (p) => api(p, { method: "DELETE" });

// 全局事件总线（后端 SSE → 前端订阅）
const handlers = {};
let es = null;
let connected = false;
export function on(type, fn) {
  (handlers[type] ||= new Set()).add(fn);
  return () => handlers[type].delete(fn);
}
export function emit(type, data) {
  handlers[type]?.forEach((fn) => { try { fn(data); } catch (e) { console.error(e); } });
}
const TYPES = ["load", "engines", "job", "models_changed", "convs_changed", "usage", "system", "log",
               "image", "image_done"];
export function connectEvents() {
  if (es) es.close();
  es = new EventSource("/api/events?lang=" + getLang());
  es.onopen = () => { if (!connected) { connected = true; emit("_conn", true); } };
  es.onerror = () => { if (connected) { connected = false; emit("_conn", false); } };
  for (const t of TYPES) es.addEventListener(t, (e) => emit(t, JSON.parse(e.data)));
}

// 对话生成流：支持断线续传（from 参数）
export function streamRun(runId, handlersMap) {
  let idx = 0;
  let closed = false;
  let src = null;
  let retries = 0;
  const RETRY_MAX = 5;
  const RETRY_DELAYS = [800, 1600, 3200, 5000, 5000];
  const open = () => {
    src = new EventSource(`/api/runs/${runId}/stream?from=${idx}&lang=${getLang()}`);
    for (const t of ["status", "thinking", "content", "notice", "done"]) {
      src.addEventListener(t, (e) => {
        idx++;
        const d = JSON.parse(e.data);
        handlersMap[t]?.(d);
        if (t === "done") { closed = true; src.close(); }
      });
    }
    src.onopen = () => { retries = 0; };
    src.onerror = () => {
      // 必须在 close() 之前读 readyState：close() 会把它改成 CLOSED(2)
      const dead = src.readyState === EventSource.CLOSED;
      src.close();
      if (closed) return;
      if (dead || retries >= RETRY_MAX) {
        // 永久失败（HTTP 非 200 / 类型不对）或超过重试上限：停止重连并通知调用方
        closed = true;
        handlersMap.failed?.({ error: "生成已中断（任务不存在或后端已重启）" });
        return;
      }
      const delay = RETRY_DELAYS[retries] ?? 5000;
      retries++;
      setTimeout(() => { if (!closed) open(); }, delay);
    };
  };
  open();
  return { close() { closed = true; src?.close(); } };
}
