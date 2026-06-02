// Background polling timer.
// Runs in a Web Worker — setInterval here is NOT throttled by background-tab policies.
let timer: ReturnType<typeof setInterval> | null = null;

self.addEventListener("message", (e: MessageEvent<{ type: "start" | "stop"; intervalMs?: number }>) => {
  const { type, intervalMs } = e.data;
  if (type === "start") {
    if (timer !== null) clearInterval(timer);
    timer = setInterval(() => (self as unknown as Worker).postMessage({ type: "tick" }), intervalMs ?? 3000);
  } else if (type === "stop") {
    if (timer !== null) { clearInterval(timer); timer = null; }
  }
});
