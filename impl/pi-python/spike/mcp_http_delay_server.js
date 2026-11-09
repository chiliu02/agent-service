// A streamable-HTTP MCP server that answers one tool at once and holds the other
// open, so the two things nobody has measured on this build can be measured
// together.
//
// **Two questions, one server** (`PI-46`, `PI-49`):
//
//   1. does the adapter reach an MCP server over HTTP at all? `stdio` is
//      measured end to end; HTTP is accepted by shape and has never been driven.
//      Agent Harness's own server is the HTTP one, so this is the transport that
//      decides whether that build is frontable for them.
//   2. what ends a tool call that never answers? The four `mcp_tool_call` timers
//      publish `null` meaning *no bound found*, which is not the same as *no
//      bound*. Harness's first tool holds a call open until another agent
//      replies, so a bound nobody has located bites them and nobody else.
//
// **The measurement is the DISCONNECT, not the wait.** `slow_answer` never
// responds; the server records how long until the client drops the socket. That
// gives the bound exactly rather than by bisection, and a run that reaches the
// cap prints `>cap` rather than a number it did not observe.
//
//     node mcp_http_delay_server.js <port> [cap-seconds]
//
// Dependency-free, and Node rather than Python because a server this build's
// IMAGE has to reach must run on the image's own runtime (`PI-47`).

const http = require("http");

const PORT = Number(process.argv[2] || 8931);
const CAP_S = Number(process.argv[3] || 360);

const MAGIC = "MAGIC-WORD-OVER-HTTP";

const TOOLS = [
  {
    name: "magic_word",
    description:
      "Returns the magic word over HTTP. Call this when asked for the magic " +
      "word; it cannot be guessed.",
    inputSchema: { type: "object", properties: {}, required: [] },
  },
  {
    name: "slow_ticks",
    description:
      "Asks another agent and sends progress while it waits, returning when the "
      + "reply comes. Call this when asked to wait with progress.",
    inputSchema: { type: "object", properties: {}, required: [] },
  },
  {
    name: "slow_stream",
    description:
      "Asks another agent and streams the reply when it comes. Call this when " +
      "asked to wait for another agent over a stream.",
    inputSchema: { type: "object", properties: {}, required: [] },
  },
  {
    name: "slow_answer",
    description:
      "Asks another agent and returns when it replies. May take a long time. " +
      "Call this when asked to wait for another agent.",
    inputSchema: { type: "object", properties: {}, required: [] },
  },
];

function log(msg) {
  process.stdout.write(`${new Date().toISOString()} ${msg}\n`);
}

function send(res, id, result) {
  const body = JSON.stringify({ jsonrpc: "2.0", id, result });
  res.writeHead(200, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

const server = http.createServer((req, res) => {
  if (req.method !== "POST") {
    res.writeHead(405, { "content-length": "0" });
    res.end();
    return;
  }
  let raw = "";
  req.on("data", (c) => (raw += c));
  req.on("end", () => {
    let msg;
    try {
      msg = JSON.parse(raw);
    } catch {
      res.writeHead(400, { "content-length": "0" });
      res.end();
      return;
    }
    log(`<- ${msg.method || "(response)"}`);

    // A notification carries no id and takes no reply; 202 is what the
    // streamable-HTTP transport expects for one.
    if (msg.id === undefined || msg.id === null) {
      res.writeHead(202, { "content-length": "0" });
      res.end();
      return;
    }

    if (msg.method === "initialize") {
      send(res, msg.id, {
        protocolVersion: (msg.params && msg.params.protocolVersion) || "2025-06-18",
        capabilities: { tools: {} },
        serverInfo: { name: "httpspike", version: "0.0.1" },
      });
    } else if (msg.method === "tools/list") {
      send(res, msg.id, { tools: TOOLS });
    } else if (msg.method === "tools/call") {
      const name = msg.params && msg.params.name;
      if (name === "magic_word") {
        send(res, msg.id, { content: [{ type: "text", text: MAGIC }] });
        return;
      }
      if (name === "slow_ticks") {
        // **Headers now, and DATA every 20 s.** This is the third timer the
        // specification separates: a bound cleared by a frame that counts, as
        // against one cleared by responding and one cleared by nothing. The
        // consumer's own held call ticks progress every 30 s, so this is the
        // shape that decides whether their design survives on this build.
        const started = Date.now();
        let settled = false;
        res.writeHead(200, {
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
          connection: "keep-alive",
        });
        res.write(": open\n\n");
        const tick = setInterval(() => {
          if (settled) return;
          const secs = ((Date.now() - started) / 1000).toFixed(0);
          res.write(`: tick ${secs}\n\n`);
          log(`-> tick at ${secs}s`);
        }, 20000);
        const finish = (why) => {
          if (settled) return;
          settled = true;
          clearInterval(tick);
          const secs = ((Date.now() - started) / 1000).toFixed(1);
          log(`TICKING CALL ENDED AFTER ${secs}s BY ${why}`);
        };
        req.on("aborted", () => finish("client abort"));
        res.on("close", () => finish("socket close"));
        setTimeout(() => {
          if (!settled) {
            settled = true;
            clearInterval(tick);
            log(`TICKING CALL STILL OPEN AT CAP >${CAP_S}s -- ticks held it`);
            res.end();
          }
        }, CAP_S * 1000);
        return;
      }
      if (name === "slow_stream") {
        // **Headers NOW, body never.** This is what separates a bound cleared by
        // RESPONDING from one cleared by nothing: an SSE stream that opens
        // immediately and then says nothing.
        const started = Date.now();
        let settled = false;
        res.writeHead(200, {
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
          connection: "keep-alive",
        });
        res.write(": open\n\n");
        const finish = (why) => {
          if (settled) return;
          settled = true;
          const secs = ((Date.now() - started) / 1000).toFixed(1);
          log(`STREAMED CALL ENDED AFTER ${secs}s BY ${why}`);
        };
        req.on("aborted", () => finish("client abort"));
        res.on("close", () => finish("socket close"));
        setTimeout(() => {
          if (!settled) {
            settled = true;
            log(`STREAMED CALL STILL OPEN AT CAP >${CAP_S}s -- headers cleared it`);
            res.end();
          }
        }, CAP_S * 1000);
        return;
      }
      if (name === "slow_answer") {
        // **Never answers.** The client's own patience is the measurement.
        const started = Date.now();
        let settled = false;
        const finish = (why) => {
          if (settled) return;
          settled = true;
          const secs = ((Date.now() - started) / 1000).toFixed(1);
          log(`TOOL CALL ENDED AFTER ${secs}s BY ${why}`);
        };
        req.on("aborted", () => finish("client abort"));
        res.on("close", () => finish("socket close"));
        setTimeout(() => {
          if (!settled) {
            settled = true;
            log(`TOOL CALL STILL OPEN AT CAP >${CAP_S}s -- no bound observed`);
            send(res, msg.id, {
              content: [{ type: "text", text: "gave up waiting" }],
            });
          }
        }, CAP_S * 1000);
        return;
      }
      send(res, msg.id, {
        content: [{ type: "text", text: `no such tool: ${name}` }],
        isError: true,
      });
    } else {
      const body = JSON.stringify({
        jsonrpc: "2.0",
        id: msg.id,
        error: { code: -32601, message: `Method not found: ${msg.method}` },
      });
      res.writeHead(200, {
        "content-type": "application/json",
        "content-length": Buffer.byteLength(body),
      });
      res.end(body);
    }
  });
});

server.listen(PORT, "127.0.0.1", () => log(`listening on ${PORT}, cap ${CAP_S}s`));
