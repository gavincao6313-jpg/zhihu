import { useEffect, useRef } from "react";

/**
 * Calls `callback` every `intervalMs` milliseconds while `active` is true.
 * Uses a Web Worker so the timer is NOT throttled when the browser tab is hidden.
 * Safe to use in background tabs during long live-stream sessions.
 */
export function useWorkerInterval(
  callback: () => void,
  intervalMs: number,
  active: boolean,
): void {
  // Always call the latest callback version without restarting the worker.
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    if (!active) return;

    const worker = new Worker(
      new URL("./polling.worker.ts", import.meta.url),
      { type: "module" },
    );
    worker.onmessage = () => callbackRef.current();
    worker.postMessage({ type: "start", intervalMs });

    return () => {
      worker.postMessage({ type: "stop" });
      worker.terminate();
    };
  }, [active, intervalMs]);
}
