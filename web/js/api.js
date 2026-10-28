// Talks to the Purefile backend on the same origin. Nothing else is contacted.

export class ApiError extends Error {
  constructor(code, message = code) {
    super(message);
    this.code = code;
  }
}

export async function getConfig() {
  const response = await fetch("/api/config");
  if (!response.ok) throw new ApiError("server_error");
  return response.json();
}

/**
 * Upload one file as the raw request body. XHR (rather than fetch) is used
 * because it reports upload progress, which matters for large videos.
 * Returns { promise, abort }.
 */
export function uploadFile(file, onProgress) {
  const xhr = new XMLHttpRequest();
  const promise = new Promise((resolve, reject) => {
    xhr.open("POST", "/api/files");
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.setRequestHeader("X-File-Name", encodeURIComponent(file.name));
    xhr.responseType = "json";
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    });
    xhr.upload.addEventListener("load", () => onProgress(1));
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response);
      } else {
        const detail = xhr.response?.detail;
        reject(new ApiError(detail?.code || "server_error", detail?.message));
      }
    });
    xhr.addEventListener("error", () => reject(new ApiError("network")));
    xhr.addEventListener("abort", () => reject(new ApiError("aborted")));
    xhr.send(file);
  });
  return { promise, abort: () => xhr.abort() };
}

export function deleteFile(id) {
  // keepalive lets the request finish even if the page is being closed.
  return fetch(`/api/files/${id}`, { method: "DELETE", keepalive: true }).catch(() => {});
}

export function zipUrl(ids) {
  return `/api/zip?ids=${ids.join(",")}`;
}
