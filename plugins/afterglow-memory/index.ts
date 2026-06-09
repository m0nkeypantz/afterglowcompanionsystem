import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { spawn } from "child_process";
import { existsSync, readFileSync, writeFileSync, appendFileSync } from "fs";
import { join } from "path";

const HOME = process.env.HOME || process.env.USERPROFILE || "";
const WORKSPACE = process.env.OPENCLAW_WORKSPACE || join(HOME, ".openclaw", "workspace");
const PYTHON = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const AFTERGLOW_SCRIPT = join(WORKSPACE, "scripts", "afterglow.py");
const TURN_CONTEXT_SCRIPT = join(WORKSPACE, "scripts", "turn_context.py");
const RECALL_OUTPUT = join(WORKSPACE, "brain", "afterglow_prompt_recall.md");
const RESPONSE_CONTEXT = join(WORKSPACE, "brain", "current_response_context.json");
const EMOTIONAL_STATE = join(WORKSPACE, "brain", "context", "emotional_state.md");
const INBOUND_PATH = join(WORKSPACE, "brain", "current_inbound_message.txt");
const DELIVERY_LOG = join(WORKSPACE, "brain", "afterglow_delivery_writeback.jsonl");

const BLOCKING_CONTEXT_TIMEOUT_MS = Number(process.env.AFTERGLOW_CONTEXT_TIMEOUT_MS || 45000);
const BLOCKING_CONTEXT_COMPACT = process.env.AFTERGLOW_BLOCKING_COMPACT !== "0";
const BLOCKING_CONTEXT_FAST = process.env.AFTERGLOW_BLOCKING_FAST !== "0";
const MAX_CONTEXT_CHARS = 180000;
const MAX_SUPPLEMENT_CHARS = 120000;

type RedactionRule = { name: string; pattern: RegExp; replacement: string };

const PUBLIC_REDACTIONS: RedactionRule[] = [
  { name: "api_key_value", pattern: /\b(sk-[a-zA-Z0-9]{20,}|sk-or-[a-zA-Z0-9_-]{20,}|eyJ[a-zA-Z0-9_\-]{20,}|[0-9a-f]{40,})\b/g, replacement: "[redacted credential]" },
  { name: "labeled_secret", pattern: /\b(api[_\-\s]?key|token|secret|password)\s*[:=]\s*\S{8,}/gi, replacement: "[redacted credential]" },
  { name: "phone_number", pattern: /\b(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}\b/g, replacement: "[redacted phone]" },
];

let lastBlockingContextText = "";

function oneLine(value: unknown, limit = 700): string {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length <= limit ? text : `${text.slice(0, Math.max(0, limit - 3)).trim()}...`;
}

function redactPublicOutbound(content: string): { content: string; reasons: string[] } {
  let redacted = String(content || "");
  const reasons: string[] = [];
  for (const rule of PUBLIC_REDACTIONS) {
    const before = redacted;
    redacted = redacted.replace(rule.pattern, rule.replacement);
    if (redacted !== before) reasons.push(rule.name);
  }
  return { content: redacted, reasons };
}

function extractUserMessageFromPrompt(body: string): string {
  const text = String(body || "");
  const tag = text.match(/<(?:user|human|companion_user|turn)_message>\s*([\s\S]*?)\s*<\/(?:user|human|companion_user|turn)_message>/i);
  if (tag && tag[1]?.trim()) return tag[1].trim();
  return text
    .replace(/```[\s\S]*?```/g, "")
    .replace(/Conversation info[\s\S]*?"timestamp":\s*"[^"]*"\s*\}/g, "")
    .replace(/Sender \(untrusted[\s\S]*?\}\s*/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function isSystemishPrompt(body: string): boolean {
  const text = String(body || "").trim();
  if (!text) return true;
  const skip = [
    "HEARTBEAT",
    "INTERNAL PULSE",
    "AUTONOMOUS PULSE",
    "CNS Snapshot",
    "Read HEARTBEAT",
    "Afterglow Pulse Diary",
  ];
  return skip.some((s) => text.startsWith(s));
}

function extractTopics(body: string): string {
  const cleaned = extractUserMessageFromPrompt(body)
    .replace(/https?:\/\/\S+/g, "")
    .replace(/\[[^\]]+\]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (cleaned.length < 5) return "";
  const text = cleaned.slice(0, 500);
  const properNouns = (text.match(/\b[A-Z][a-z]{2,}\b/g) || []).map((n) => n.toLowerCase());
  const stopWords = new Set([
    "the", "and", "that", "with", "from", "this", "your", "have", "what",
    "when", "just", "like", "please", "also", "they", "them", "about",
    "there", "would", "could", "should", "were", "been", "into", "because",
    "while", "yeah", "okay", "good", "want", "think", "know", "going",
    "really", "actually", "something", "everything", "anything", "here",
    "will", "make", "take", "being", "does", "done", "working", "looking",
    "getting", "trying", "thing", "things", "need", "check", "memory",
  ]);
  const words = (text.toLowerCase().match(/\b[a-z]{4,}\b/g) || []).filter((w) => !stopWords.has(w));
  return [...new Set([...properNouns, ...words])].slice(0, 8).join(" ");
}

function runPython(scriptPath: string, args: string[], timeoutMs: number): Promise<{ code: number | null; stdout: string; stderr: string; timedOut: boolean; elapsedMs: number; }> {
  return new Promise((resolve) => {
    const startedAt = Date.now();
    const child = spawn(PYTHON, [scriptPath, ...args], {
      env: { ...process.env, PYTHONPATH: join(WORKSPACE, "scripts") },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      child.kill("SIGKILL");
    }, timeoutMs);
    timeout.unref?.();
    child.stdout.setEncoding("utf-8");
    child.stderr.setEncoding("utf-8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
      if (stdout.length > MAX_CONTEXT_CHARS) stdout = stdout.slice(-MAX_CONTEXT_CHARS);
    });
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
      if (stderr.length > 8000) stderr = stderr.slice(-8000);
    });
    child.on("error", (err: Error) => {
      clearTimeout(timeout);
      resolve({ code: 1, stdout, stderr: stderr || err.message, timedOut, elapsedMs: Date.now() - startedAt });
    });
    child.on("close", (code: number | null) => {
      clearTimeout(timeout);
      resolve({ code, stdout, stderr, timedOut, elapsedMs: Date.now() - startedAt });
    });
  });
}

async function buildTurnContext(prompt: string, event: any, ctx: any, api: any): Promise<string | null> {
  if (!existsSync(TURN_CONTEXT_SCRIPT)) return null;
  if (isSystemishPrompt(prompt)) return null;
  const userPrompt = extractUserMessageFromPrompt(prompt);
  const query = extractTopics(userPrompt) || oneLine(userPrompt, 160) || "recent context";
  const turnPayload = Buffer.from(JSON.stringify({ ...(ctx || {}), ...(event || {}) })).toString("base64");
  const args = [query, "--turn-json-base64", turnPayload];
  if (BLOCKING_CONTEXT_COMPACT) args.push("--compact");
  if (BLOCKING_CONTEXT_FAST) args.push("--fast");
  const result = await runPython(TURN_CONTEXT_SCRIPT, args, BLOCKING_CONTEXT_TIMEOUT_MS);
  const combined = [result.stdout.trim(), result.stderr.trim()].filter(Boolean).join("\n").trim();
  if (result.code !== 0) {
    api?.logger?.warn?.(`[afterglow-memory] turn context failed code=${result.code} timeout=${result.timedOut} elapsed=${result.elapsedMs}ms`);
    return null;
  }
  const context = combined.slice(0, MAX_CONTEXT_CHARS);
  try {
    writeFileSync(RECALL_OUTPUT, context, "utf-8");
    lastBlockingContextText = context.trim();
  } catch {}
  api?.logger?.info?.(`[afterglow-memory] turn context OK in ${result.elapsedMs}ms query="${query}"`);
  return context;
}

function ingestMessage(text: string, role: string, source: string): void {
  if (!existsSync(AFTERGLOW_SCRIPT)) return;
  const clean = oneLine(text, 4000);
  if (!clean || clean.length < 3 || isSystemishPrompt(clean)) return;
  try {
    const child = spawn(PYTHON, [AFTERGLOW_SCRIPT, "ingest-message", clean, "--role", role, "--source", source], {
      env: { ...process.env, PYTHONPATH: join(WORKSPACE, "scripts") },
      stdio: ["ignore", "ignore", "pipe"],
    });
    const timeout = setTimeout(() => child.kill("SIGKILL"), 12000);
    timeout.unref?.();
    child.on("close", () => clearTimeout(timeout));
    writeFileSync(INBOUND_PATH, clean.slice(0, 4000), "utf-8");
  } catch {}
}

function appendDelivery(event: any, ctx: any): void {
  try {
    const content = String(event?.content || event?.body || "");
    if (!content.trim()) return;
    appendFileSync(DELIVERY_LOG, `${JSON.stringify({
      ts: new Date().toISOString(),
      event: "delivery",
      to: event?.to || ctx?.to || "",
      channel: ctx?.channelId || ctx?.channel || ctx?.source || "",
      sessionKey: ctx?.sessionKey || event?.sessionKey || "",
      final: oneLine(content),
    })}\n`);
    ingestMessage(content, "assistant", "openclaw.message_sending");
  } catch {}
}

export default definePluginEntry({
  id: "afterglow-memory",
  name: "Afterglow Memory",
  description: "Injects local Afterglow recall, emotional state, diary context, and cross-session context before OpenClaw replies.",
  register(api) {
    api.on?.("before_prompt_build", async (event: any, ctx: any) => {
      try {
        const prompt = String(event?.prompt || event?.body || event?.content || "");
        const context = await buildTurnContext(prompt, event, ctx, api);
        if (!context) return;
        return { prependContext: context };
      } catch (err: any) {
        api?.logger?.warn?.(`[afterglow-memory] before_prompt_build failed: ${err.message?.substring(0, 160)}`);
        return;
      }
    }, { name: "afterglow-turn-context", timeoutMs: BLOCKING_CONTEXT_TIMEOUT_MS + 5000 });

    api.registerHook?.(["message_received"], (event: any) => {
      const content = event?.content || event?.bodyForAgent || event?.body || event?.context?.content || event?.context?.body || "";
      const text = extractUserMessageFromPrompt(String(content || ""));
      ingestMessage(text, "user", "openclaw.message_received");
    }, { name: "afterglow-ingest-inbound" });

    api.on?.("message_sending", async (event: any, ctx: any) => {
      appendDelivery(event, ctx);
      const original = String(event?.content || "");
      if (!original) return;
      const result = redactPublicOutbound(original);
      if (result.content === original) return;
      api?.logger?.warn?.(`[afterglow-memory] redacted outbound content (${result.reasons.join(", ")})`);
      return { content: result.content };
    }, { name: "afterglow-delivery-writeback", priority: 1000, timeoutMs: 1200 });

    api.registerMemoryPromptSupplement?.((_params: any) => {
      const lines: string[] = [];
      try {
        if (existsSync(RECALL_OUTPUT)) {
          const content = readFileSync(RECALL_OUTPUT, "utf-8").trim();
          if (content && content !== lastBlockingContextText) lines.push(content.slice(0, MAX_SUPPLEMENT_CHARS));
        }
      } catch {}
      try {
        if (existsSync(RESPONSE_CONTEXT)) {
          const raw = readFileSync(RESPONSE_CONTEXT, "utf-8").trim();
          if (raw) {
            lines.push("");
            lines.push("## Afterglow Response Context");
            lines.push(raw.slice(0, 12000));
          }
        }
      } catch {}
      try {
        if (existsSync(EMOTIONAL_STATE)) {
          const emotional = readFileSync(EMOTIONAL_STATE, "utf-8").trim();
          if (emotional) {
            lines.push("");
            lines.push(emotional.slice(0, 8000));
          }
        }
      } catch {}
      return lines.join("\n").split("\n");
    });
  },
});
