/**
 * Red Hat Lightspeed Linux MCP Bridge
 *
 * Connects pi to the RHEL Lightspeed linux-mcp-server via STDIO.
 * Provides read-only Linux system diagnostics (SSH or local).
 * 18 tools: system info, services, processes, network, storage, logs.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";

interface McpTool {
  name: string;
  description?: string;
  inputSchema: Record<string, unknown>;
}

let serverProcess: ChildProcess | null = null;
let requestId = 0;
const pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();

function sendRequest(method: string, params?: unknown): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const id = ++requestId;
    const msg = JSON.stringify({ jsonrpc: "2.0", id, method, params });
    pending.set(id, { resolve, reject });
    serverProcess?.stdin?.write(msg + "\n");
  });
}

export default function linuxMcpExtension(pi: ExtensionAPI) {
  pi.on("session_start", async () => {
    serverProcess = spawn("linux-mcp-server", ["--transport", "stdio"], {
      stdio: ["pipe", "pipe", "pipe"],
    });

    const rl = createInterface({ input: serverProcess.stdout! });

    rl.on("line", (line: string) => {
      try {
        const msg = JSON.parse(line);
        if (msg.id && pending.has(msg.id)) {
          const { resolve, reject } = pending.get(msg.id)!;
          pending.delete(msg.id);
          if (msg.error) reject(new Error(msg.error.message));
          else resolve(msg.result);
        }
      } catch {
        // ignore non-JSON lines
      }
    });

    serverProcess.on("exit", (code) => {
      pi.log?.("warn", `Linux MCP server exited with code ${code}`);
    });

    try {
      await sendRequest("initialize", {
        protocolVersion: "2025-06-18",
        capabilities: {},
        clientInfo: { name: "pi", version: "1.0" },
      });
      await sendRequest("notifications/initialized", {});

      const result = await sendRequest("tools/list", { client_params: {} }) as { tools: McpTool[] };
      const tools = result.tools || [];

      for (const tool of tools) {
        pi.registerTool({
          name: `linux_${tool.name}`,
          description: tool.description || `Linux: ${tool.name}`,
          parameters: tool.inputSchema as Record<string, unknown>,
          handler: async (params: Record<string, unknown>) => {
            const result = await sendRequest("tools/call", {
              name: tool.name,
              arguments: params,
            });
            return JSON.stringify(result, null, 2);
          },
        });
      }

      pi.log?.("info", `Registered ${tools.length} Linux diagnostic tools`);
    } catch (err) {
      pi.log?.("error", `Failed to init Linux MCP: ${err}`);
    }
  });

  pi.on("session_end", () => {
    if (serverProcess) {
      serverProcess.kill();
      serverProcess = null;
    }
  });
}
