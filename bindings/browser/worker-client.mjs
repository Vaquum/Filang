/** Connect to a same-origin Filang module worker. Close to release its recording. */
export function openFilangWorker(url = new URL("./worker.mjs", import.meta.url)) {
  const worker = new Worker(url, {type: "module"});
  const pending = new Map();
  let closed = false;
  let sequence = 0;

  function stop(error) {
    if (closed) return;
    closed = true;
    worker.terminate();
    for (const request of pending.values()) request.reject(error);
    pending.clear();
  }

  worker.onmessage = ({data: {id, value, error, errorName, progress}}) => {
    const request = pending.get(id);
    if (!request) return;
    if (progress) {
      request.progress?.(progress);
      return;
    }
    pending.delete(id);
    if (error) request.reject(errorName === "AbortError" ? new DOMException(error, errorName) : new Error(error));
    else request.resolve(value);
  };
  worker.onerror = ({message}) => stop(new Error(message || "Filang worker failed"));

  function ask(method, args, progress) {
    if (closed) return Promise.reject(new Error("Filang worker is closed"));
    const id = ++sequence;
    return new Promise((resolve, reject) => {
      pending.set(id, {resolve, reject, progress});
      try { worker.postMessage({id, method, args}); }
      catch (error) { pending.delete(id); reject(error); }
    });
  }

  return {
    ask(method, ...args) { return ask(method, args); },
    searchComposer(packet, {timeframes = 31, endMasks, radius = 0, onProgress} = {}) {
      return ask("searchComposer", [packet, {timeframes, endMasks, radius}], onProgress);
    },
    close() { stop(new Error("Filang worker has closed")); },
  };
}
