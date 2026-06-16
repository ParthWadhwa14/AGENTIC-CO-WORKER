"use client";

import type { Session } from "@supabase/supabase-js";
import {
  AlertCircle,
  CheckCircle2,
  Cloud,
  Database,
  FileUp,
  Inbox,
  Link,
  Loader2,
  LogOut,
  RefreshCw,
  Search,
  Send,
  Settings,
  Sparkles,
  Trash2,
  X
} from "lucide-react";
import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  askAgent,
  backendUrl,
  type ChatHistoryMessage,
  agentIngestDefaultScope,
  cleanupChatDocuments,
  executeAgentAction,
  getAgentProfile,
  getConnectionStatus,
  getDefaultScope,
  getDocuments,
  getSetupStatus,
  googleConnectUrl,
  ingestDefaultScope,
  removeScopeResource,
  updateAgentProfile,
  uploadFile
} from "@/lib/api";
import { supabase } from "@/lib/supabase";

type WorkspaceAppProps = {
  session: Session;
};

type Reference = {
  ref: number;
  document_id?: string;
  chunk_id?: string;
  title: string;
  file_name?: string;
  open_url?: string;
  source_type?: string;
};

type ChatTurn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  actionMemory?: string;
  references?: Reference[];
  proposedAction?: ProposedAction;
  pending?: boolean;
  error?: boolean;
  executed?: boolean;
};

type ProposedAction = {
  action_type: string;
  description: string;
  payload: Record<string, any>;
  requires_approval: boolean;
  risk_level?: "low" | "medium" | "high";
  confirmation_summary?: string;
  guardrail_warning?: string;
};

type ChatMode = "workspace" | "basic";

type AgentProfile = {
  agent_description: string;
  user_context: string;
  response_preferences: string;
};

type ScopeResource = {
  id: string;
  provider: string;
  resource_type: string;
  name: string;
  external_id?: string;
  mime_type?: string;
  web_url?: string;
  selector?: Record<string, any>;
  index_status?: string;
};

type Toast = {
  id: number;
  title: string;
  message: string;
  tone: "success" | "error" | "info";
};

const taskLabels: Record<string, string> = {
  "drive-sync": "Syncing Drive, Docs, and Sheets",
  "gmail-sync": "Syncing Gmail",
  "sync-all": "Syncing connected sources",
  "selected-ingest": "Indexing selected scope",
  upload: "Uploading and indexing file",
  agent: "Thinking through your workspace"
};

const SOURCE_OPTIONS = ["drive", "docs", "sheets", "gmail"] as const;
type SourceOption = (typeof SOURCE_OPTIONS)[number];

function renderFormattedAnswer(answer: string): ReactNode {
  const lines = answer.split("\n");
  const nodes: ReactNode[] = [];
  let bullets: string[] = [];
  let numbers: string[] = [];

  function flushBullets() {
    if (!bullets.length) return;
    const items = bullets;
    bullets = [];
    nodes.push(
      <ul className="my-3 list-disc space-y-1 pl-5" key={`ul-${nodes.length}`}>
        {items.map((item, index) => (
          <li key={`${item}-${index}`}>{formatInline(item)}</li>
        ))}
      </ul>
    );
  }

  function flushNumbers() {
    if (!numbers.length) return;
    const items = numbers;
    numbers = [];
    nodes.push(
      <ol className="my-3 list-decimal space-y-1 pl-5" key={`ol-${nodes.length}`}>
        {items.map((item, index) => (
          <li key={`${item}-${index}`}>{formatInline(item)}</li>
        ))}
      </ol>
    );
  }

  function flushLists() {
    flushBullets();
    flushNumbers();
  }

  function isTableStart(index: number) {
    return (
      lines[index]?.includes("|") &&
      lines[index + 1]?.trim().match(/^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/)
    );
  }

  function renderTable(startIndex: number) {
    const tableLines: string[] = [];
    let index = startIndex;
    while (index < lines.length && lines[index].includes("|")) {
      tableLines.push(lines[index]);
      index += 1;
    }

    const rows = tableLines
      .filter((_, rowIndex) => rowIndex !== 1)
      .map((line) =>
        line
          .trim()
          .replace(/^\|/, "")
          .replace(/\|$/, "")
          .split("|")
          .map((cell) => cell.trim())
      );

    const [headings, ...bodyRows] = rows;
    nodes.push(
      <div className="my-4 overflow-x-auto" key={`table-${nodes.length}`}>
        <table className="markdown-table">
          <thead>
            <tr>
              {headings.map((heading, headingIndex) => (
                <th key={`${heading}-${headingIndex}`}>{formatInline(heading)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bodyRows.map((row, rowIndex) => (
              <tr key={`row-${rowIndex}`}>
                {row.map((cell, cellIndex) => (
                  <td key={`${cell}-${cellIndex}`}>{formatInline(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );

    return index;
  }

  function formatInline(text: string): ReactNode {
    const parts = text.split(/(\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|`[^`]+`)/g);
    return parts.map((part, index) => {
      const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (link) {
        return (
          <a
            className="text-[var(--accent-strong)] underline"
            href={link[2]}
            key={index}
            rel="noreferrer"
            target="_blank"
          >
            {link[1]}
          </a>
        );
      }
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={index}>{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith("`") && part.endsWith("`")) {
        return <code key={index}>{part.slice(1, -1)}</code>;
      }
      return part;
    });
  }

  for (let index = 0; index < lines.length; index += 1) {
    const trimmed = lines[index].trim();
    if (!trimmed) {
      flushLists();
      continue;
    }

    if (isTableStart(index)) {
      flushLists();
      index = renderTable(index) - 1;
      continue;
    }

    if (trimmed.startsWith("### ")) {
      flushLists();
      nodes.push(
        <h5 className="mb-2 mt-4 text-base font-bold" key={index}>
          {formatInline(trimmed.slice(4))}
        </h5>
      );
      continue;
    }

    if (trimmed.startsWith("## ")) {
      flushLists();
      nodes.push(
        <h4 className="mb-2 mt-4 text-base font-bold" key={index}>
          {formatInline(trimmed.slice(3))}
        </h4>
      );
      continue;
    }

    if (trimmed.startsWith("# ")) {
      flushLists();
      nodes.push(
        <h3 className="mb-2 mt-4 text-lg font-bold" key={index}>
          {formatInline(trimmed.slice(2))}
        </h3>
      );
      continue;
    }

    if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      flushNumbers();
      bullets.push(trimmed.slice(2));
      continue;
    }

    const numbered = trimmed.match(/^\d+\.\s+(.+)$/);
    if (numbered) {
      flushBullets();
      numbers.push(numbered[1]);
      continue;
    }

    flushLists();
    nodes.push(
      <p className="my-2 leading-7" key={index}>
        {formatInline(trimmed)}
      </p>
    );
  }

  flushLists();
  return nodes;
}

function referenceUrl(openUrl?: string) {
  if (!openUrl) return "#";
  if (openUrl.startsWith("http://") || openUrl.startsWith("https://")) {
    return openUrl;
  }
  return `${backendUrl}${openUrl.startsWith("/") ? "" : "/"}${openUrl}`;
}

function cleanReferenceTitle(reference: Reference) {
  return reference.file_name || reference.title.replace(/\s+\([^)]*\)$/g, "");
}

function uniqueDocumentReferences(references: Reference[] = []) {
  const seen = new Set<string>();
  return references.filter((reference) => {
    const key =
      reference.document_id ||
      reference.open_url ||
      reference.file_name ||
      reference.title;
    if (seen.has(key)) return false;
    seen.add(key);
    return Boolean(reference.open_url);
  });
}

function chatHistoryFromTurns(turns: ChatTurn[]): ChatHistoryMessage[] {
  return turns
    .filter((turn) => !turn.pending && !turn.error && turn.content.trim())
    .map((turn) => ({
      role: turn.role,
      content: turn.actionMemory
        ? `${turn.content}\n\n${turn.actionMemory}`
        : turn.content
    }));
}

function referenceKey(reference: Reference) {
  return (
    reference.document_id ||
    reference.open_url ||
    reference.file_name ||
    reference.title
  );
}

function actionExecutionMemory(action: ProposedAction, result: any) {
  const memory = {
    type: "action_execution_result",
    action_type: result.action_type || action.action_type,
    payload: result.payload || action.payload,
    result: result.result || result
  };
  return {
    display: `**Executed:** ${memory.action_type} completed successfully.`,
    memory: [
      "```json action-memory",
      JSON.stringify(memory, null, 2),
      "```"
    ].join("\n")
  };
}

export function WorkspaceApp({ session }: WorkspaceAppProps) {
  const [setup, setSetup] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [documents, setDocuments] = useState<any[]>([]);
  const [query, setQuery] = useState("");
  const [chatMode, setChatMode] = useState<ChatMode>("workspace");
  const [useWebSearch, setUseWebSearch] = useState(true);
  const [chatTurns, setChatTurns] = useState<ChatTurn[]>([]);
  const [profile, setProfile] = useState<AgentProfile>({
    agent_description: "",
    user_context: "",
    response_preferences: ""
  });
  const [profileOpen, setProfileOpen] = useState(false);
  const [selectedSources, setSelectedSources] = useState<SourceOption[]>([
    "drive",
    "docs",
    "sheets",
    "gmail"
  ]);
  const [agentIngestFocus, setAgentIngestFocus] = useState("");
  const [scopeResources, setScopeResources] = useState<ScopeResource[]>([]);
  const [latestReferences, setLatestReferences] = useState<Reference[]>([]);
  const [pinnedReferences, setPinnedReferences] = useState<Reference[]>([]);
  const [priorityDocumentIds, setPriorityDocumentIds] = useState<string[]>([]);
  const [persistentPriorityDocumentIds, setPersistentPriorityDocumentIds] = useState<string[]>([]);
  const [persistentPriorityLoaded, setPersistentPriorityLoaded] = useState(false);
  const [knownDocumentIds, setKnownDocumentIds] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [activity, setActivity] = useState("");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [chatLoaded, setChatLoaded] = useState(false);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const userEmail = session.user.email || "";
  const userName =
    session.user.user_metadata?.full_name || session.user.email || "User";
  const chatStorageKey = `workspace-agent-chat:${session.user.id}`;
  const persistentPriorityStorageKey = `workspace-agent-persistent-priority:${session.user.id}`;

  function pushToast(
    title: string,
    message: string,
    tone: Toast["tone"] = "info"
  ) {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current.slice(-2), { id, title, message, tone }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 6500);
  }

  function removeToast(id: number) {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }

  function startGoogleConnect(service: "drive" | "gmail" | "workspace") {
    if (!setup?.google_oauth_configured) {
      pushToast(
        "Google OAuth is not ready",
        "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the backend, then restart it.",
        "error"
      );
      return;
    }

    const label = service === "gmail" ? "Gmail" : "Drive, Docs, and Sheets";
    sessionStorage.setItem("pendingGoogleService", label);
    setActivity(`Opening Google consent for ${label}...`);
    pushToast("Opening Google consent", `Redirecting to connect ${label}.`, "info");
    window.location.href = googleConnectUrl(session.user.id, service, userEmail);
  }

  const connectionCards = useMemo(
    () => [
      {
        title: "Drive, Docs, Sheets",
        description: "Read and sync supported files from Google Workspace.",
        connected: Boolean(status?.drive_connected),
        configured: Boolean(setup?.google_oauth_configured),
        service: "drive" as const,
        action: () => {
          setSelectedSources((current) =>
            Array.from(new Set([...current, "drive", "docs", "sheets"]))
          );
          pushToast(
            "Use Source Picker",
            "Select Drive/Docs/Sheets and run agent pick + ingest.",
            "info"
          );
        }
      },
      {
        title: "Gmail",
        description: "Read-only email indexing with filtered sync.",
        connected: Boolean(status?.gmail_connected),
        configured: Boolean(setup?.google_oauth_configured),
        service: "gmail" as const,
        action: () => {
          setSelectedSources((current) => Array.from(new Set([...current, "gmail"])));
          pushToast(
            "Use Source Picker",
            "Select Gmail and run agent pick + ingest.",
            "info"
          );
        }
      }
    ],
    [session.user.id, setup, status, userEmail]
  );

  async function refresh() {
    setActivity((current) => current || "Refreshing workspace status...");
    const [
      setupResult,
      connectionResult,
      documentResult,
      profileResult,
      scopeResult
    ] = await Promise.all([
      getSetupStatus(session.user.id),
      getConnectionStatus(session.user.id),
      getDocuments(session.user.id),
      getAgentProfile(session.user.id),
      getDefaultScope(session.user.id)
    ]);
    setSetup(setupResult);
    setStatus(connectionResult);
    setDocuments(documentResult.documents || []);
    setProfile({
      agent_description: profileResult.agent_description || "",
      user_context: profileResult.user_context || "",
      response_preferences: profileResult.response_preferences || ""
    });
    setScopeResources(scopeResult.resources || []);
    setActivity("");
  }

  async function runTask(label: string, task: () => Promise<any>) {
    const readableLabel = taskLabels[label] || label;
    setBusy(label);
    setActivity(`${readableLabel}...`);
    try {
      const result = await task();
      const message =
        result.status === "queued"
          ? `${readableLabel} was queued successfully.`
          : `${readableLabel} completed.`;
      pushToast("Task started", message, "success");
      await refresh();
    } catch (error) {
      pushToast(
        `${readableLabel} failed`,
        error instanceof Error ? error.message : "Something failed",
        "error"
      );
    } finally {
      setBusy("");
      setActivity("");
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem("file") as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    pushToast("Upload started", `Uploading ${file.name}.`, "info");
    await runTask("upload", () => uploadFile(session, file));
    form.reset();
  }

  async function saveProfile() {
    setBusy("profile");
    setActivity("Saving agent profile...");
    try {
      const saved = await updateAgentProfile(
        session.user.id,
        profile.agent_description,
        profile.user_context,
        profile.response_preferences
      );
      setProfile({
        agent_description: saved.agent_description || "",
        user_context: saved.user_context || "",
        response_preferences: saved.response_preferences || ""
      });
      setProfileOpen(false);
      pushToast("Profile saved", "Future answers will use these preferences.", "success");
    } catch (error) {
      pushToast(
        "Profile save failed",
        error instanceof Error ? error.message : "Could not save profile",
        "error"
      );
    } finally {
      setBusy("");
      setActivity("");
    }
  }

  async function removeSelectedResource(resourceId: string) {
    try {
      await removeScopeResource(session.user.id, resourceId);
      setScopeResources((current) =>
        current.filter((resource) => resource.id !== resourceId)
      );
      pushToast("Removed from scope", "This source will not be ingested.", "success");
    } catch (error) {
      pushToast(
        "Could not remove source",
        error instanceof Error ? error.message : "Scope update failed",
        "error"
      );
    }
  }

  async function ingestSelectedScope() {
    await runTask("selected-ingest", () => ingestDefaultScope(session.user.id));
  }

  async function agentPickAndIngest() {
    setBusy("agent-ingest");
    setActivity("Letting the agent choose source searches...");
    try {
      const result = await agentIngestDefaultScope(
        session.user.id,
        agentIngestFocus,
        selectedSources,
        true
      );
      const addedCount = result.added_resources?.length || 0;
      pushToast(
        "Agent ingest queued",
        `Selected ${addedCount} resource(s) and queued ingestion.`,
        "success"
      );
      await refresh();
    } catch (error) {
      pushToast(
        "Agent ingest failed",
        error instanceof Error ? error.message : "Could not run agent ingest",
        "error"
      );
    } finally {
      setBusy("");
      setActivity("");
    }
  }

  function togglePinnedReference(reference: Reference) {
    setPinnedReferences((current) => {
      const key = referenceKey(reference);
      if (current.some((item) => referenceKey(item) === key)) {
        return current.filter((item) => referenceKey(item) !== key);
      }
      return [...current, reference];
    });
  }

  function togglePriorityDocument(documentId: string) {
    setPriorityDocumentIds((current) => {
      if (current.includes(documentId)) {
        setPersistentPriorityDocumentIds((persistent) =>
          persistent.filter((id) => id !== documentId)
        );
        return current.filter((id) => id !== documentId);
      }
      return [...current, documentId];
    });
  }

  function togglePersistentPriorityDocument(documentId: string) {
    setPersistentPriorityDocumentIds((current) => {
      if (current.includes(documentId)) {
        return current.filter((id) => id !== documentId);
      }
      setPriorityDocumentIds((priority) =>
        priority.includes(documentId) ? priority : [...priority, documentId]
      );
      return [...current, documentId];
    });
  }

  async function approveAction(turnId: string, action: ProposedAction) {
    setBusy(`action-${turnId}`);
    setActivity("Executing approved action...");
    try {
      const result = await executeAgentAction(session.user.id, action);
      const executionMemory = actionExecutionMemory(action, result);
      setChatTurns((current) =>
        current.map((turn) =>
          turn.id === turnId
            ? {
                ...turn,
                executed: true,
                content: `${turn.content}\n\n${executionMemory.display}`,
                actionMemory: executionMemory.memory
              }
            : turn
        )
      );
      pushToast("Action executed", `${result.action_type} completed.`, "success");
    } catch (error) {
      pushToast(
        "Action blocked",
        error instanceof Error ? error.message : "Could not execute action",
        "error"
      );
    } finally {
      setBusy("");
      setActivity("");
    }
  }

  async function clearChatAndCleanup() {
    const keepDocumentIds = Array.from(new Set(persistentPriorityDocumentIds));
    setChatTurns([]);
    setLatestReferences([]);
    setPinnedReferences([]);
    setPriorityDocumentIds(keepDocumentIds);
    setBusy("clear-chat");
    setActivity("Clearing chat and pruning temporary indexed documents...");
    try {
      const result = await cleanupChatDocuments(session.user.id, keepDocumentIds);
      pushToast(
        "Chat cleared",
        result.deleted_count
          ? `Deleted ${result.deleted_count} temporary indexed document(s).`
          : "No temporary indexed documents needed cleanup.",
        "success"
      );
      await refresh();
    } catch (error) {
      pushToast(
        "Cleanup failed",
        error instanceof Error ? error.message : "Could not delete temporary documents",
        "error"
      );
    } finally {
      setBusy("");
      setActivity("");
    }
  }

  async function handleAsk(event: FormEvent) {
    event.preventDefault();
    const question = query.trim();
    if (!question) return;

    const userTurn: ChatTurn = {
      id: crypto.randomUUID(),
      role: "user",
      content: question
    };
    const assistantTurn: ChatTurn = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "Thinking through your workspace...",
      pending: true,
      references: []
    };
    const history = chatHistoryFromTurns(chatTurns);
    const pinnedDocumentIds = pinnedReferences
      .map((reference) => reference.document_id)
      .filter((id): id is string => Boolean(id));
    const selectedPriorityDocumentIds = Array.from(
      new Set([...priorityDocumentIds, ...persistentPriorityDocumentIds])
    );
    setChatTurns((current) => [...current, userTurn, assistantTurn]);
    setQuery("");
    setBusy("agent");
    setActivity(
      chatMode === "basic"
        ? "Preparing a professional response..."
        : "Searching and preparing the answer..."
    );
    try {
      const result = await askAgent(
        session.user.id,
        question,
        history,
        chatMode,
        useWebSearch,
        pinnedDocumentIds,
        selectedPriorityDocumentIds
      );
      const answerReferences = uniqueDocumentReferences(result.references || []);
      setLatestReferences(answerReferences);
      setChatTurns((current) =>
        current.map((turn) =>
          turn.id === assistantTurn.id
            ? {
                ...turn,
                content: result.answer || "I could not produce an answer.",
                references: answerReferences,
                proposedAction: result.proposed_action || undefined,
                pending: false
              }
            : turn
        )
      );
      pushToast(
        "Answer ready",
        result.references?.length
          ? `Used ${uniqueDocumentReferences(result.references).length} source link(s).`
          : "No matching indexed sources were found yet.",
        result.references?.length ? "success" : "info"
      );
      const profileResult = await getAgentProfile(session.user.id);
      setProfile({
        agent_description: profileResult.agent_description || "",
        user_context: profileResult.user_context || "",
        response_preferences: profileResult.response_preferences || ""
      });
    } catch (error) {
      setChatTurns((current) =>
        current.map((turn) =>
          turn.id === assistantTurn.id
            ? {
                ...turn,
                content:
                  error instanceof Error
                    ? error.message
                    : "Agent request failed",
                pending: false,
                error: true
              }
            : turn
        )
      );
      pushToast(
        "Chat failed",
        error instanceof Error ? error.message : "Agent request failed",
        "error"
      );
    } finally {
      setBusy("");
      setActivity("");
    }
  }

  async function signOut() {
    await supabase.auth.signOut();
  }

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(chatStorageKey);
      if (saved) {
        const parsed = JSON.parse(saved) as ChatTurn[];
        setChatTurns(parsed.filter((turn) => turn.content));
      }
    } catch {
      window.localStorage.removeItem(chatStorageKey);
    } finally {
      setChatLoaded(true);
    }
  }, [chatStorageKey]);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(persistentPriorityStorageKey);
      if (saved) {
        const parsed = JSON.parse(saved) as string[];
        setPersistentPriorityDocumentIds(parsed.filter(Boolean));
        setPriorityDocumentIds((current) =>
          Array.from(new Set([...current, ...parsed.filter(Boolean)]))
        );
      }
    } catch {
      window.localStorage.removeItem(persistentPriorityStorageKey);
    } finally {
      setPersistentPriorityLoaded(true);
    }
  }, [persistentPriorityStorageKey]);

  useEffect(() => {
    if (!chatLoaded) return;
    window.localStorage.setItem(chatStorageKey, JSON.stringify(chatTurns));
  }, [chatLoaded, chatStorageKey, chatTurns]);

  useEffect(() => {
    if (!persistentPriorityLoaded) return;
    window.localStorage.setItem(
      persistentPriorityStorageKey,
      JSON.stringify(persistentPriorityDocumentIds)
    );
  }, [
    persistentPriorityDocumentIds,
    persistentPriorityLoaded,
    persistentPriorityStorageKey
  ]);

  useEffect(() => {
    const indexedIds = documents
      .filter((document) => document.index_status === "indexed")
      .map((document) => document.id)
      .filter(Boolean);
    const newIndexedIds = indexedIds.filter((id) => !knownDocumentIds.includes(id));
    if (!newIndexedIds.length) return;

    setPriorityDocumentIds((current) =>
      Array.from(new Set([...current, ...newIndexedIds]))
    );
    setKnownDocumentIds((current) => Array.from(new Set([...current, ...indexedIds])));
  }, [documents, knownDocumentIds]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chatTurns, activity]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connected = params.get("google_connected");
    const googleError = params.get("google_error");
    const pendingService = sessionStorage.getItem("pendingGoogleService");
    if (connected) {
      const serviceName =
        pendingService || connected.replace("google_", "").replace("_", " ");
      pushToast(
        "Google connected",
        `${serviceName} is connected. You can sync it now.`,
        "success"
      );
      sessionStorage.removeItem("pendingGoogleService");
      window.history.replaceState({}, "", window.location.pathname);
    } else if (googleError) {
      pushToast("Google connection failed", googleError, "error");
      sessionStorage.removeItem("pendingGoogleService");
      window.history.replaceState({}, "", window.location.pathname);
    }

    refresh().catch((error) => {
      pushToast(
        "Could not load workspace status",
        error instanceof Error ? error.message : "Could not load status",
        "error"
      );
    });
  }, []);

  return (
    <main className="min-h-screen">
      <div className="fixed right-4 top-4 z-50 w-[min(380px,calc(100vw-2rem))] space-y-2">
        {toasts.map((toast) => (
          <div className={`toast ${toast.tone}`} key={toast.id}>
            <div className="flex gap-3">
              {toast.tone === "success" ? (
                <CheckCircle2 size={18} />
              ) : toast.tone === "error" ? (
                <AlertCircle size={18} />
              ) : (
                <Sparkles size={18} />
              )}
              <div className="min-w-0 flex-1">
                <p className="font-bold">{toast.title}</p>
                <p className="mt-1 text-sm">{toast.message}</p>
              </div>
              <button
                className="icon-btn"
                onClick={() => removeToast(toast.id)}
                title="Dismiss"
              >
                <X size={15} />
              </button>
            </div>
          </div>
        ))}
      </div>

      {profileOpen ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 px-4">
          <section className="card w-[min(720px,100%)] p-4 shadow-xl">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-bold">Agent Profile</h2>
                <p className="text-sm text-[var(--muted)]">
                  Shape how the co-worker thinks, prioritizes, and answers.
                </p>
              </div>
              <button
                className="icon-btn"
                onClick={() => setProfileOpen(false)}
                title="Close"
              >
                <X size={16} />
              </button>
            </div>
            <div className="mt-4 grid gap-3">
              <label className="grid gap-1 text-sm font-bold">
                Agent description
                <textarea
                  className="input min-h-24"
                  onChange={(event) =>
                    setProfile((current) => ({
                      ...current,
                      agent_description: event.target.value
                    }))
                  }
                  value={profile.agent_description}
                />
              </label>
              <label className="grid gap-1 text-sm font-bold">
                About you / your work
                <textarea
                  className="input min-h-24"
                  onChange={(event) =>
                    setProfile((current) => ({
                      ...current,
                      user_context: event.target.value
                    }))
                  }
                  value={profile.user_context}
                />
              </label>
              <label className="grid gap-1 text-sm font-bold">
                Answer preferences
                <textarea
                  className="input min-h-24"
                  onChange={(event) =>
                    setProfile((current) => ({
                      ...current,
                      response_preferences: event.target.value
                    }))
                  }
                  value={profile.response_preferences}
                />
              </label>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button className="btn ghost" onClick={() => setProfileOpen(false)}>
                Cancel
              </button>
              <button className="btn" disabled={busy === "profile"} onClick={saveProfile}>
                {busy === "profile" ? (
                  <Loader2 className="animate-spin" size={16} />
                ) : (
                  <Settings size={16} />
                )}
                Save profile
              </button>
            </div>
          </section>
        </div>
      ) : null}

      <header className="border-b border-[var(--border)] bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-4">
          <div>
            <h1 className="text-xl font-bold">Workspace Agent</h1>
            <p className="text-sm text-[var(--muted)]">{userName}</p>
          </div>
          <div className="flex items-center gap-2">
            <button className="btn secondary" onClick={() => setProfileOpen(true)}>
              <Settings size={17} />
              Profile
            </button>
            <button className="btn ghost" onClick={signOut}>
              <LogOut size={17} />
              Sign out
            </button>
          </div>
        </div>
      </header>

      <div className="dashboard-grid mx-auto grid max-w-6xl gap-4 px-5 py-5 lg:grid-cols-[280px_1fr_300px]">
        <aside className="scroll-column space-y-4">
          <section className="card p-4">
            <div className="flex items-center gap-2">
              <Link size={18} />
              <h2 className="font-bold">Retrieved sources</h2>
            </div>
            <p className="mt-2 text-xs leading-5 text-[var(--muted)]">
              Sources are used for the current answer only. Check a source to
              prioritize it for this chat.
            </p>
            <div className="mt-3 space-y-2">
              {latestReferences.length ? (
                latestReferences.map((reference) => {
                  const checked = pinnedReferences.some(
                    (item) => referenceKey(item) === referenceKey(reference)
                  );
                  return (
                    <label
                      className="flex gap-2 rounded-lg border border-[var(--border)] p-3 text-sm"
                      key={referenceKey(reference)}
                    >
                      <input
                        checked={checked}
                        disabled={!reference.document_id}
                        onChange={() => togglePinnedReference(reference)}
                        type="checkbox"
                      />
                      <span className="min-w-0">
                        <a
                          className="block truncate font-bold"
                          href={referenceUrl(reference.open_url)}
                          rel="noreferrer"
                          target="_blank"
                        >
                          {cleanReferenceTitle(reference)}
                        </a>
                        <span className="text-xs text-[var(--muted)]">
                          {reference.source_type || "source"}
                          {!reference.document_id ? " · current answer only" : ""}
                        </span>
                      </span>
                    </label>
                  );
                })
              ) : (
                <p className="text-sm text-[var(--muted)]">
                  No retrieved sources yet.
                </p>
              )}
            </div>
          </section>

          <section className="card p-4">
            <h2 className="font-bold">Pinned context</h2>
            <div className="mt-3 space-y-2">
              {pinnedReferences.length ? (
                pinnedReferences.map((reference) => (
                  <div
                    className="flex items-start justify-between gap-2 rounded-lg border border-[var(--border)] p-3 text-sm"
                    key={referenceKey(reference)}
                  >
                    <div className="min-w-0">
                      <p className="truncate font-bold">
                        {cleanReferenceTitle(reference)}
                      </p>
                      <p className="text-xs text-[var(--muted)]">
                        {reference.source_type || "source"}
                      </p>
                    </div>
                    <button
                      className="icon-btn"
                      onClick={() => togglePinnedReference(reference)}
                      title="Unpin"
                    >
                      <X size={14} />
                    </button>
                  </div>
                ))
              ) : (
                <p className="text-sm text-[var(--muted)]">
                  Check a retrieved document to prioritize it until chat is cleared.
                </p>
              )}
            </div>
          </section>

          <section className="card p-4">
            <div className="flex items-center gap-2">
              <Sparkles size={18} />
              <h2 className="font-bold">Sources</h2>
            </div>
            <div className="mt-4 space-y-3">
              {connectionCards.map((card) => (
                <div className="rounded-lg border border-[var(--border)] p-3" key={card.title}>
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h3 className="font-bold">{card.title}</h3>
                      <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
                        {card.description}
                      </p>
                    </div>
                    {card.connected ? (
                      <CheckCircle2 className="text-green-600" size={18} />
                    ) : (
                      <Cloud className="text-[var(--muted)]" size={18} />
                    )}
                  </div>
                  <div className="mt-3 flex gap-2">
                    <button
                      className="btn secondary flex-1 text-sm"
                      disabled={!card.configured || Boolean(busy)}
                      onClick={() => startGoogleConnect(card.service)}
                      title={
                        card.configured
                          ? "Connect Google account"
                          : "Backend Google OAuth credentials are not configured"
                      }
                    >
                      <Link size={15} />
                      {card.connected ? "Reconnect" : "Connect"}
                    </button>
                    <button
                      className="btn secondary"
                      disabled={!card.connected || Boolean(busy)}
                      onClick={card.action}
                      title="Pick sources"
                    >
                      <Search size={15} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="card p-4">
            <div className="flex items-center gap-2">
              <Database size={18} />
              <h2 className="font-bold">Source Picker</h2>
            </div>
            <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
              Discover metadata first, then index only selected resources.
            </p>

            <div className="mt-3 rounded-lg border border-[var(--border)] bg-[var(--panel-strong)] p-3">
              <div className="mb-3 grid grid-cols-2 gap-2">
                {SOURCE_OPTIONS.map((kind) => (
                  <label
                    className={`mode-chip flex items-center justify-center gap-2 ${selectedSources.includes(kind) ? "active" : ""}`}
                    key={kind}
                  >
                    <input
                      checked={selectedSources.includes(kind)}
                      onChange={(event) => {
                        setSelectedSources((current) =>
                          event.target.checked
                            ? Array.from(new Set([...current, kind]))
                            : current.filter((source) => source !== kind)
                        );
                      }}
                      type="checkbox"
                    />
                    {kind === "drive"
                      ? "Drive"
                      : kind === "docs"
                        ? "Docs"
                        : kind === "sheets"
                          ? "Sheets"
                          : "Gmail"}
                  </label>
                ))}
              </div>
              <label className="grid gap-1 text-xs font-bold">
                Optional agent focus
                <input
                  className="input"
                  onChange={(event) => setAgentIngestFocus(event.target.value)}
                  placeholder="e.g. internship applications, resume, JEE, active project..."
                  value={agentIngestFocus}
                />
              </label>
              <button
                className="btn mt-2 w-full text-sm"
                disabled={Boolean(busy) || !selectedSources.length}
                onClick={agentPickAndIngest}
              >
                {busy === "agent-ingest" ? (
                  <Loader2 className="animate-spin" size={15} />
                ) : (
                  <Sparkles size={15} />
                )}
                Agent pick + ingest
              </button>
              <p className="mt-2 text-xs leading-5 text-[var(--muted)]">
                The agent chooses safe metadata searches across connected sources,
                adds selected matches to scope, then queues selected ingestion.
              </p>
            </div>

            <div className="mt-4 border-t border-[var(--border)] pt-3">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-bold">Selected Scope</h3>
                <button
                  className="btn secondary text-sm"
                  disabled={!scopeResources.length || Boolean(busy)}
                  onClick={ingestSelectedScope}
                >
                  <RefreshCw
                    className={busy === "selected-ingest" ? "animate-spin" : ""}
                    size={14}
                  />
                  Ingest
                </button>
              </div>
              <div className="mt-2 max-h-48 space-y-2 overflow-y-auto">
                {scopeResources.slice(0, 8).map((resource) => (
                  <div
                    className="flex items-start justify-between gap-2 rounded-lg border border-[var(--border)] p-2 text-sm"
                    key={resource.id}
                  >
                    <div className="min-w-0">
                      <p className="truncate font-bold">{resource.name}</p>
                      <p className="text-xs text-[var(--muted)]">
                        {resource.provider} · {resource.resource_type}
                      </p>
                    </div>
                    <button
                      className="icon-btn"
                      onClick={() => removeSelectedResource(resource.id)}
                      title="Remove from scope"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
                {!scopeResources.length ? (
                  <p className="text-sm text-[var(--muted)]">
                    No selected resources yet.
                  </p>
                ) : null}
              </div>
            </div>
          </section>

          <section className="card p-4">
            <h2 className="font-bold">Upload</h2>
            <form className="mt-3 space-y-3" onSubmit={handleUpload}>
              <input className="input" name="file" type="file" />
              <button className="btn w-full" disabled={Boolean(busy)}>
                {busy === "upload" ? (
                  <Loader2 className="animate-spin" size={16} />
                ) : (
                  <FileUp size={16} />
                )}
                {busy === "upload" ? "Uploading..." : "Upload and index"}
              </button>
            </form>
          </section>
        </aside>

        <section className="card scroll-column min-h-[620px] p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold">Ask your workspace</h2>
              <p className="text-sm text-[var(--muted)]">
                Switch between workspace RAG and professional basic chat.
              </p>
            </div>
            <button
              className="btn secondary"
              disabled={Boolean(busy) || !scopeResources.length}
              onClick={ingestSelectedScope}
            >
              <RefreshCw
                className={busy === "selected-ingest" ? "animate-spin" : ""}
                size={16}
              />
              {busy === "selected-ingest" ? "Indexing..." : "Ingest selected"}
            </button>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--border)] bg-white p-3">
            <div className="flex gap-2">
              <button
                className={`mode-chip ${chatMode === "workspace" ? "active" : ""}`}
                onClick={() => setChatMode("workspace")}
              >
                Workspace RAG
              </button>
              <button
                className={`mode-chip ${chatMode === "basic" ? "active" : ""}`}
                onClick={() => setChatMode("basic")}
              >
                Basic chat
              </button>
            </div>
            <label className="flex items-center gap-2 text-sm text-[var(--muted)]">
              <input
                checked={useWebSearch}
                onChange={(event) => setUseWebSearch(event.target.checked)}
                type="checkbox"
              />
              Allow web expansion {setup?.serper_api_key_configured ? "ready" : "not configured"}
            </label>
          </div>

          {activity ? (
            <div className="mt-4 flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--panel-strong)] p-3 text-sm">
              <Loader2 className="animate-spin text-[var(--accent)]" size={16} />
              {activity}
            </div>
          ) : null}

          {setup && !setup.google_oauth_configured ? (
            <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              Google Drive/Gmail connection needs backend OAuth credentials:
              set <code>GOOGLE_CLIENT_ID</code> and{" "}
              <code>GOOGLE_CLIENT_SECRET</code>, then restart the backend.
            </div>
          ) : null}

          {setup && !setup.groq_api_key_configured ? (
            <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              Chat generation needs <code>GROQ_API_KEY</code> in the backend
              environment, then restart the backend.
            </div>
          ) : null}

          {setup?.qdrant && !setup.qdrant.reachable ? (
            <div className="mt-4 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-900">
              Qdrant is not reachable, so the agent cannot retrieve document
              references. Start Qdrant and sync/upload again.
            </div>
          ) : null}

          {setup?.qdrant?.reachable && setup.qdrant.chunk_count === 0 ? (
            <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              No vector chunks are indexed yet. Upload a document or sync
              Drive/Gmail, then wait for indexing to complete before asking.
            </div>
          ) : null}

          <div className="mt-4 flex items-center justify-between gap-3">
            <h3 className="font-bold">Chat</h3>
            {chatTurns.length ? (
              <button
                className="btn ghost text-sm"
                disabled={Boolean(busy)}
                onClick={clearChatAndCleanup}
              >
                {busy === "clear-chat" ? "Clearing..." : "Clear chat"}
              </button>
            ) : null}
          </div>

          <div className="chat-panel mt-3">
            {chatTurns.length ? (
              chatTurns.map((turn) => {
                const links = uniqueDocumentReferences(turn.references || []);
                return (
                  <article
                    className={`chat-message ${turn.role} ${turn.error ? "error" : ""}`}
                    key={turn.id}
                  >
                    <div className="chat-bubble">
                      {turn.pending ? (
                        <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
                          <Loader2 className="animate-spin" size={15} />
                          {turn.content}
                        </div>
                      ) : turn.role === "assistant" ? (
                        <div className="answer-content">
                          {renderFormattedAnswer(turn.content)}
                        </div>
                      ) : (
                        <p className="leading-7">{turn.content}</p>
                      )}

                      {turn.role === "assistant" && links.length ? (
                        <div className="source-links">
                          <p className="source-links-title">Sources</p>
                          <div className="flex flex-wrap gap-2">
                            {links.map((reference) => (
                              <a
                                className="source-link"
                                href={referenceUrl(reference.open_url)}
                                key={
                                  reference.document_id ||
                                  reference.open_url ||
                                  reference.title
                                }
                                rel="noreferrer"
                                target="_blank"
                              >
                                {cleanReferenceTitle(reference)}
                              </a>
                            ))}
                          </div>
                        </div>
                      ) : null}

                      {turn.role === "assistant" && turn.proposedAction ? (
                        <div className="approval-panel">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="font-bold">Review before execution</p>
                              <p className="mt-1 text-sm text-[var(--muted)]">
                                {turn.proposedAction.confirmation_summary ||
                                  turn.proposedAction.description}
                              </p>
                            </div>
                            <span className={`risk-badge ${turn.proposedAction.risk_level || "medium"}`}>
                              {turn.proposedAction.risk_level || "medium"} risk
                            </span>
                          </div>
                          {turn.proposedAction.guardrail_warning ? (
                            <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">
                              {turn.proposedAction.guardrail_warning}
                            </p>
                          ) : null}
                          <details className="mt-3">
                            <summary className="cursor-pointer text-sm font-bold">
                              Payload preview
                            </summary>
                            <pre className="payload-preview">
                              {JSON.stringify(turn.proposedAction.payload, null, 2)}
                            </pre>
                          </details>
                          <button
                            className="btn mt-3"
                            disabled={
                              Boolean(busy) ||
                              turn.executed ||
                              Boolean(turn.proposedAction.guardrail_warning)
                            }
                            onClick={() => approveAction(turn.id, turn.proposedAction!)}
                          >
                            {busy === `action-${turn.id}` ? (
                              <Loader2 className="animate-spin" size={16} />
                            ) : (
                              <CheckCircle2 size={16} />
                            )}
                            {turn.executed ? "Executed" : "Approve and execute"}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </article>
                );
              })
            ) : (
              <div className="rounded-lg border border-dashed border-[var(--border)] p-4 text-sm text-[var(--muted)]">
                Ask a question after uploading files or syncing Google sources.
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          <form className="mt-4 flex gap-2" onSubmit={handleAsk}>
            <input
              className="input"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Ask a follow-up or start a new question..."
              value={query}
            />
            <button className="btn" disabled={Boolean(busy) || !query.trim()}>
              {busy === "agent" ? (
                <Loader2 className="animate-spin" size={16} />
              ) : (
                <Send size={16} />
              )}
              {busy === "agent" ? "Thinking..." : "Ask"}
            </button>
          </form>
        </section>

        <aside className="scroll-column space-y-4">
          <section className="card p-4">
            <div className="flex items-center gap-2">
              <Inbox size={18} />
              <h2 className="font-bold">Indexed documents</h2>
            </div>
            {setup?.qdrant ? (
              <p className="mt-2 text-xs text-[var(--muted)]">
                Indexed docs: {setup.qdrant.indexed_document_count || 0} · User
                vector chunks: {setup.qdrant.chunk_count || 0}
              </p>
            ) : null}
            <div className="mt-3 space-y-2">
              {documents.map((document) => {
                const canPrioritize = document.index_status === "indexed";
                const priorityChecked =
                  priorityDocumentIds.includes(document.id) ||
                  persistentPriorityDocumentIds.includes(document.id);
                const persistentChecked = persistentPriorityDocumentIds.includes(
                  document.id
                );
                return (
                  <div
                    className="rounded-lg border border-[var(--border)] p-3 text-sm"
                    key={document.id}
                  >
                    <p className="truncate font-bold">{document.file_name}</p>
                    <p className="text-xs text-[var(--muted)]">
                      {document.source} · {document.index_status}
                    </p>
                    <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-[var(--muted)]">
                      <label className="flex items-center gap-2">
                        <input
                          checked={priorityChecked}
                          disabled={!canPrioritize}
                          onChange={() => togglePriorityDocument(document.id)}
                          type="checkbox"
                        />
                        Use now
                      </label>
                      <label className="flex items-center gap-2">
                        <input
                          checked={persistentChecked}
                          disabled={!canPrioritize}
                          onChange={() =>
                            togglePersistentPriorityDocument(document.id)
                          }
                          type="checkbox"
                        />
                        Keep
                      </label>
                    </div>
                  </div>
                );
              })}
              {!documents.length ? (
                <p className="text-sm text-[var(--muted)]">
                  Upload or sync sources to see documents.
                </p>
              ) : null}
            </div>
          </section>
        </aside>
      </div>
    </main>
  );
}
