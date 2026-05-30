/**
 * Forgejo MCP Bridge
 *
 * Spawns forgejo-mcp in stdio mode and bridges its tools to pi.
 * Requires: forgejo-mcp installed (go install or binary in PATH)
 *
 * Configuration via environment variables:
 *   FORGEJO_URL   — your Forgejo instance URL
 *   FORGEJO_TOKEN — API access token
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawn, type ChildProcess } from "node:child_process";

interface McpRequest {
  jsonrpc: "2.0";
  method: string;
  params?: Record<string, unknown>;
  id: number;
}

interface McpResponse {
  jsonrpc: "2.0";
  id: number;
  result?: unknown;
  // deno-lint-ignore no-explicit-any
  error?: any;
}

interface McpTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

const FORGEJO_URL =
  process.env.FORGEJO_URL || "https://forgejo.manatee-basking.ts.net";
const FORGEJO_TOKEN = process.env.FORGEJO_TOKEN || "";

export default function forgejoMcpExtension(pi: ExtensionAPI) {
  if (!FORGEJO_TOKEN) {
    pi.on("session_start", async (_, ctx) => {
      ctx.ui.notify("Forgejo MCP: FORGEJO_TOKEN not set", "warning");
    });
    return;
  }

  let proc: ChildProcess | null = null;
  let requestId = 0;
  let pending = new Map<
    number,
    { resolve: (value: McpResponse) => void; reject: (err: Error) => void }
  >();
  let buffer = "";
  let initializePromise: Promise<void> | null = null;

  function startServer(): ChildProcess {
    const p = spawn("forgejo-mcp", [
      "--transport",
      "stdio",
      "--url",
      FORGEJO_URL,
      "--token",
      FORGEJO_TOKEN,
      "--debug=false",
    ], {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, FORGEJO_ACCESS_TOKEN: FORGEJO_TOKEN },
    });

    p.stdout!.on("data", (chunk: Buffer) => {
      buffer += chunk.toString();
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const msg: McpResponse = JSON.parse(line);
          const cb = pending.get(msg.id);
          if (cb) {
            pending.delete(msg.id);
            if (msg.error) {
              cb.reject(new Error(JSON.stringify(msg.error)));
            } else {
              cb.resolve(msg);
            }
          }
        } catch {
          // Skip non-JSON lines (stderr output, logs, etc.)
        }
      }
    });

    p.stderr!.on("data", (chunk: Buffer) => {
      // Log to stderr for debugging
      process.stderr.write(`[forgejo-mcp] ${chunk}`);
    });

    p.on("exit", (code) => {
      if (code !== null && code !== 0) {
        process.stderr.write(`[forgejo-mcp] exited with code ${code}\n`);
      }
    });

    return p;
  }

  function callMcp(
    method: string,
    params?: Record<string, unknown>,
  ): Promise<McpResponse> {
    if (!proc || proc.exitCode !== null) {
      proc = startServer();
    }

    const id = ++requestId;
    const req: McpRequest = { jsonrpc: "2.0", method, id };
    if (params) req.params = params;

    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      proc!.stdin!.write(JSON.stringify(req) + "\n");

      // Timeout after 30 seconds
      setTimeout(() => {
        if (pending.has(id)) {
          pending.delete(id);
          reject(new Error(`MCP call ${method} timed out`));
        }
      }, 30_000);
    });
  }

  async function initialize(): Promise<void> {
    if (initializePromise) return initializePromise;

    initializePromise = (async () => {
      proc = startServer();

      // MCP initialization handshake
      const initResp = await callMcp("initialize", {
        protocolVersion: "2024-11-05",
        capabilities: {},
        clientInfo: { name: "pi-forgejo-bridge", version: "1.0.0" },
      });
      // deno-lint-ignore no-explicit-any
      const serverInfo = (initResp.result as any)?.serverInfo;
      process.stderr.write(
        `[forgejo-mcp] connected to ${FORGEJO_URL} (${serverInfo?.name || "Forgejo"} v${serverInfo?.version || "?"})\n`,
      );

      // Send initialized notification
      await callMcp("notifications/initialized", {});

      // List tools and register them with pi
      const toolsResp = await callMcp("tools/list");
      const tools = (toolsResp.result as { tools?: McpTool[] })?.tools || [];

      for (const tool of tools) {
        pi.registerTool({
          name: `forgejo_${tool.name}`,
          label: `Forgejo: ${tool.name}`,
          description: tool.description,
          parameters: tool.inputSchema || { type: "object", properties: {} },
          handler: async (args, _ctx) => {
            const resp = await callMcp("tools/call", {
              name: tool.name,
              arguments: args as Record<string, unknown>,
            });
            const content = (resp.result as { content?: Array<{ text?: string }> })?.content;
            if (content && content.length > 0) {
              return content[0].text || JSON.stringify(content);
            }
            return JSON.stringify(resp.result);
          },
        });
      }

      process.stderr.write(
        `[forgejo-mcp] registered ${tools.length} tools\n`,
      );
    })();

    return initializePromise;
  }

  // Initialize on session start
  pi.on("session_start", async () => {
    try {
      await initialize();
    } catch (err) {
      process.stderr.write(`[forgejo-mcp] init failed: ${err}\n`);
    }
  });

  // Clean up on shutdown
  pi.on("session_end", () => {
    if (proc) {
      proc.kill();
      proc = null;
    }
    initializePromise = null;
  });
}
