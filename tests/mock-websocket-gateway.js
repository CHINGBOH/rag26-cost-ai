/**
 * Mock WebSocket Gateway for testing
 * Mimics the behavior of the Go WebSocket gateway on port 8081
 */
const http = require('http');
const WebSocket = require('ws');
const url = require('url');

const PORT = process.env.WS_GATEWAY_PORT || 8081;
const NODE_BACKEND = process.env.NODE_BACKEND_URL || 'http://localhost:3001';

// Map of room -> Set of ws clients
const rooms = new Map();

const server = http.createServer((req, res) => {
  // CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, PUT, DELETE');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  // POST /broadcast endpoint
  if (req.url === '/broadcast' && req.method === 'POST') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      try {
        const data = JSON.parse(body);
        const room = data.room || '';
        const message = JSON.stringify(data.message || data);
        const clients = room ? (rooms.get(room) || new Set()) : getAllClients();
        let sent = 0;
        clients.forEach(ws => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(message);
            sent++;
          }
        });
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: true, sent }));
      } catch (err) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: false, error: err.message }));
      }
    });
    return;
  }

  // Forward everything else to Node backend as HTTP proxy
  const parsed = url.parse(NODE_BACKEND);
  const options = {
    hostname: parsed.hostname,
    port: parsed.port || 80,
    path: req.url,
    method: req.method,
    headers: { ...req.headers, host: parsed.host }
  };

  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res);
  });

  proxyReq.on('error', (err) => {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Node backend unavailable', details: err.message }));
  });

  req.pipe(proxyReq);
});

const wss = new WebSocket.Server({ server, path: '/ws' });

wss.on('connection', (ws, req) => {
  const parsedUrl = url.parse(req.url, true);
  const room = parsedUrl.query.room || '';

  if (room) {
    if (!rooms.has(room)) rooms.set(room, new Set());
    rooms.get(room).add(ws);
  }

  ws.on('close', () => {
    if (room && rooms.has(room)) {
      rooms.get(room).delete(ws);
      if (rooms.get(room).size === 0) rooms.delete(room);
    }
  });
});

function getAllClients() {
  const all = new Set();
  rooms.forEach(set => set.forEach(ws => all.add(ws)));
  return all;
}

server.listen(PORT, () => {
  // Keep output minimal for tests
  console.log(`Mock WebSocket Gateway listening on port ${PORT}`);
});
