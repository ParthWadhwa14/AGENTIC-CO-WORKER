import type { Session } from "@supabase/supabase-js";

const configuredBackendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/+$/, "") || "";

export const backendUrl = configuredBackendUrl;

function backendPath(path: string) {
  return `${backendUrl}${path}`;
}

function backendOrigin() {
  if (backendUrl) {
    return backendUrl;
  }
  if (typeof window !== "undefined") {
    return window.location.origin;
  }
  return "http://localhost:3000";
}

async function request(path: string, options: RequestInit = {}) {
  const response = await fetch(backendPath(path), {
    ...options,
    headers: {
      ...(options.headers || {})
    }
  });

  if (!response.ok) {
    const message = await response.text();
    let detail = message;
    const contentType = response.headers.get("content-type") || "";
    if (
      contentType.includes("text/html") ||
      message.trimStart().startsWith("<!DOCTYPE html")
    ) {
      detail = [
        `Backend endpoint ${path} returned an HTML ${response.status} page.`,
        "Check that NEXT_PUBLIC_BACKEND_URL points to your Railway backend URL, not your Vercel frontend URL."
      ].join(" ");
    } else {
      try {
        const parsed = JSON.parse(message);
        detail = parsed.detail || parsed.message || message;
      } catch {
        detail = message;
      }
    }
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  return response.json();
}

export async function getSetupStatus() {
  return request("/setup/status");
}

export function googleConnectUrl(
  userId: string,
  service: "drive" | "gmail" | "workspace",
  email?: string
) {
  const url = new URL("/auth/google/start", backendOrigin());
  url.searchParams.set("user_id", userId);
  url.searchParams.set("service", service);
  if (email) {
    url.searchParams.set("login_hint", email);
  }
  return url.toString();
}

export async function getConnectionStatus(userId: string) {
  return request(`/auth/google/status?user_id=${encodeURIComponent(userId)}`);
}

export async function getDocuments(userId: string) {
  return request(`/documents?user_id=${encodeURIComponent(userId)}`);
}

export async function cleanupChatDocuments(
  userId: string,
  keepDocumentIds: string[] = []
) {
  return request("/documents/cleanup-chat", {
    method: "POST",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify({
      user_id: userId,
      keep_document_ids: keepDocumentIds
    })
  });
}

export async function syncDrive(userId: string, mode = "incremental") {
  return request(`/drive/sync?user_id=${encodeURIComponent(userId)}&mode=${mode}`, {
    method: "POST"
  });
}

export async function syncGmail(userId: string, mode = "partial") {
  return request(`/gmail/sync?user_id=${encodeURIComponent(userId)}&mode=${mode}`, {
    method: "POST"
  });
}

export async function syncAll() {
  return request("/sync/all", { method: "POST" });
}

export type ChatHistoryMessage = {
  role: "user" | "assistant";
  content: string;
};

export async function askAgent(
  userId: string,
  query: string,
  history: ChatHistoryMessage[] = [],
  mode: "workspace" | "basic" = "workspace",
  useWebSearch = true,
  pinnedDocumentIds: string[] = [],
  priorityDocumentIds: string[] = []
) {
  return request("/agent/ask", {
    method: "POST",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify({
      user_id: userId,
      query,
      history,
      mode,
      use_web_search: useWebSearch,
      pinned_document_ids: pinnedDocumentIds,
      priority_document_ids: priorityDocumentIds,
      limit: 8
    })
  });
}

export async function executeAgentAction(userId: string, action: any) {
  return request("/agent/actions/execute", {
    method: "POST",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify({
      user_id: userId,
      action,
      approved: true
    })
  });
}

export async function getAgentProfile(userId: string) {
  return request(`/agent/profile?user_id=${encodeURIComponent(userId)}`);
}

export async function updateAgentProfile(
  userId: string,
  agentDescription: string,
  userContext: string,
  responsePreferences: string
) {
  return request("/agent/profile", {
    method: "PUT",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify({
      user_id: userId,
      agent_description: agentDescription,
      user_context: userContext,
      response_preferences: responsePreferences
    })
  });
}

export async function searchDriveSources(
  userId: string,
  query: string,
  mimeType = ""
) {
  const params = new URLSearchParams({ user_id: userId, q: query });
  if (mimeType) params.set("mime_type", mimeType);
  return request(`/sources/drive/search?${params.toString()}`);
}

export async function searchGmailSources(userId: string, query: string) {
  const params = new URLSearchParams({ user_id: userId, q: query });
  return request(`/sources/gmail/search?${params.toString()}`);
}

export async function getDefaultScope(userId: string) {
  return request(`/scopes/default?user_id=${encodeURIComponent(userId)}`);
}

export async function addScopeResource(userId: string, resource: any) {
  return request(`/scopes/default/resources?user_id=${encodeURIComponent(userId)}`, {
    method: "POST",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify(resource)
  });
}

export async function removeScopeResource(userId: string, resourceId: string) {
  return request(
    `/scopes/resources/${encodeURIComponent(resourceId)}?user_id=${encodeURIComponent(userId)}`,
    { method: "DELETE" }
  );
}

export async function ingestDefaultScope(userId: string) {
  return request(`/scopes/default/ingest?user_id=${encodeURIComponent(userId)}`, {
    method: "POST"
  });
}

export async function agentIngestDefaultScope(
  userId: string,
  focus = "",
  providers: string[] = [],
  autoIngest = false
) {
  return request("/scopes/default/agent-ingest", {
    method: "POST",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify({
      user_id: userId,
      focus,
      providers,
      auto_ingest: autoIngest
    })
  });
}

export async function uploadFile(session: Session, file: File) {
  const body = new FormData();
  body.append("user_id", session.user.id);
  body.append("file", file);

  return request("/upload", {
    method: "POST",
    body
  });
}
