# NetBox MCP Read-Write Integration

This repository includes a configured **Model Context Protocol (MCP)** server for NetBox, allowing AI agents (like Gemini CLI, Claude Code, etc.) to query and modify your NetBox inventory directly.

## Setup

1.  **Dependencies:** Ensure you have `uv` installed.
2.  **API Token:** Fetch your NetBox API token from Bitwarden:
    ```bash
    export NETBOX_API_TOKEN=$(bw get password netbox-api-token)
    ```
3.  **Environment Variables:** You can also create a `.env` file based on `.env.example`.

## Usage

### Gemini CLI
The configuration is located in `.gemini/settings.json`. When you run `gemini` from this directory, it will automatically load the `netbox-rw` tools.

To verify:
```bash
/mcp list
```

### Claude Code
The configuration is located in `.mcp.json`. Claude Code will pick this up automatically when started in the repository root.

### Other Tools
Most MCP-compatible tools will look for `.mcp.json` or can be manually pointed to the `tools/netbox-mcp-rw` directory.

## Capabilities
- **Read:** Devices, IP addresses, sites, racks, etc.
- **Write:** Create, update, and delete objects.
- **Bulk:** Efficient bulk operations.

## Security
- The API token is **not** committed to the repository.
- Use `export NETBOX_API_TOKEN` before starting your AI agent.
