// A minimal stdio MCP server in Node, so the MCP path is testable INSIDE the image.
//
// **Node rather than Python, and that is the point** (`PI-47`). This build's
// image is `node:24-slim` and carries no Python interpreter, so the Python spike
// server beside this file can drive the agent on a developer's machine and can
// never be spawned inside the container. A stdio MCP server is a subprocess the
// IMAGE has to be able to start, which makes the image's own runtime the only
// safe language for one.
//
// Dependency-free: MCP over stdio is newline-delimited JSON-RPC 2.0, and the
// four methods below are all a client needs to initialise, discover and call.
//
// The tool returns a distinctive string because the only convincing proof that
// an MCP tool ran is the model repeating something it could not have invented.

const MAGIC = "MAGIC-WORD-FROM-MCP";

const TOOLS = [
  {
    name: "magic_word",
    description:
      "Returns the magic word. Call this whenever you are asked for the " +
      "magic word; it cannot be guessed.",
    inputSchema: { type: "object", properties: {}, required: [] },
  },
];

function reply(id, result) {
  process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id, result }) + "\n");
}

let buffer = "";
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  let index;
  while ((index = buffer.indexOf("\n")) >= 0) {
    const line = buffer.slice(0, index).trim();
    buffer = buffer.slice(index + 1);
    if (!line) continue;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      continue;
    }
    // A notification has no id and takes no reply. Answering one is a protocol
    // error some clients treat as fatal.
    if (msg.id === undefined || msg.id === null) continue;

    if (msg.method === "initialize") {
      reply(msg.id, {
        // Echoed rather than asserted: the question here is whether the adapter
        // discovers and calls a tool, and a version negotiation failure would
        // answer a different question loudly.
        protocolVersion: (msg.params && msg.params.protocolVersion) || "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "spikeserver", version: "0.0.1" },
      });
    } else if (msg.method === "tools/list") {
      reply(msg.id, { tools: TOOLS });
    } else if (msg.method === "tools/call") {
      const name = msg.params && msg.params.name;
      if (name === "magic_word") {
        reply(msg.id, { content: [{ type: "text", text: MAGIC }] });
      } else {
        reply(msg.id, {
          content: [{ type: "text", text: `no such tool: ${name}` }],
          isError: true,
        });
      }
    } else {
      process.stdout.write(
        JSON.stringify({
          jsonrpc: "2.0",
          id: msg.id,
          error: { code: -32601, message: `Method not found: ${msg.method}` },
        }) + "\n",
      );
    }
  }
});
