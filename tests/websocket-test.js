/**
 * Minimal WebSocket test client
 * Connects to the gateway and waits for a broadcast message.
 */
const WebSocket = require('ws');
const fs = require('fs');

const WS_URL = process.env.WS_TEST_URL || 'ws://localhost:8081/ws?room=test-room';
const RESULT_FILE = process.env.WS_TEST_RESULT || '/tmp/websocket-test-result.txt';
const TIMEOUT_MS = parseInt(process.env.WS_TEST_TIMEOUT || '5000', 10);

fs.writeFileSync(RESULT_FILE, 'PENDING');

const ws = new WebSocket(WS_URL);
let received = false;

ws.on('open', () => {
  // Connection established
});

ws.on('message', (data) => {
  received = true;
  const msg = data.toString();
  fs.writeFileSync(RESULT_FILE, 'RECEIVED:' + msg);
  ws.close();
});

ws.on('error', (err) => {
  fs.writeFileSync(RESULT_FILE, 'ERROR:' + err.message);
  process.exit(1);
});

ws.on('close', () => {
  if (!received) {
    fs.writeFileSync(RESULT_FILE, 'ERROR:Connection closed without receiving message');
    process.exit(1);
  }
  process.exit(0);
});

setTimeout(() => {
  if (!received) {
    fs.writeFileSync(RESULT_FILE, 'ERROR:Timeout waiting for message');
    ws.terminate();
    process.exit(1);
  }
}, TIMEOUT_MS);
