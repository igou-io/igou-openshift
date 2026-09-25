// Test receiver: log correlation metadata only after verifying the raw body signature.
const http = require('node:http');
const crypto = require('node:crypto');
if (!process.env.WEBHOOK_SECRET) throw new Error('Set WEBHOOK_SECRET');
http.createServer((req, res) => {
  const chunks = [];
  req.on('data', chunk => chunks.push(chunk));
  req.on('end', () => {
    const body = Buffer.concat(chunks);
    const expected = crypto.createHmac('sha256', process.env.WEBHOOK_SECRET).update(body).digest();
    const supplied = Buffer.from(req.headers['x-forgejo-signature'] || '', 'hex');
    if (supplied.length !== expected.length || !crypto.timingSafeEqual(supplied, expected)) {
      res.writeHead(401).end();
      return;
    }
    let event;
    try { event = JSON.parse(body); } catch { res.writeHead(400).end(); return; }
    console.log(JSON.stringify({
      event: req.headers['x-forgejo-event'],
      action: event.action || '',
      repository: event.repository?.full_name,
      issue: event.issue?.number,
      delivery: req.headers['x-forgejo-delivery'],
      signature_verified: true
    }));
    res.writeHead(204).end();
  });
}).listen(Number(process.env.PORT || 39991), '0.0.0.0');
