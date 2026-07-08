/**
 * WhatsApp registration-check sidecar (Baileys).
 *
 * Holds one long-lived, logged-in WhatsApp Web (multi-device) session and
 * exposes it over a tiny local HTTP API so the Python provider (../provider.py)
 * can ask "is this number on WhatsApp?" without needing a Node runtime itself.
 *
 * This is read-only by design: the only Baileys call ever made is
 * `sock.onWhatsApp(...)`, a passive lookup used by WhatsApp's own client to
 * decide whether a contact can be messaged. `sock.sendMessage` is never
 * imported or called anywhere in this file — no message is ever sent to a
 * checked number.
 *
 * First run: no session exists yet, so a QR code is printed to this
 * process's console. Scan it from the phone that should hold the session
 * (WhatsApp > Linked Devices > Link a Device) — this links a device under
 * that account, the same as WhatsApp Web/Desktop. Credentials are then
 * persisted to AUTH_DIR so subsequent restarts reconnect without rescanning,
 * until the device is unlinked or WhatsApp invalidates the session.
 *
 * Using an automated client like this against your own real account carries
 * some risk of WhatsApp flagging/restricting it if used heavily — this is
 * exactly why it's scoped to read-only existence checks and nothing else.
 */
import type { Boom } from '@hapi/boom'
import makeWASocket, {
  type WASocket,
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys'
import { createServer } from 'node:http'
import qrcodeTerminal from 'qrcode-terminal'

const AUTH_DIR = process.env.AUTH_DIR ?? './auth_state'
const PORT = Number(process.env.PORT ?? 3025)

let sock: WASocket | undefined
let connected = false

async function startSock(): Promise<void> {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR)
  const { version } = await fetchLatestBaileysVersion()

  sock = makeWASocket({ version, auth: state })

  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update

    if (qr) {
      console.log('\nScan this QR code in WhatsApp -> Linked Devices -> Link a Device:\n')
      qrcodeTerminal.generate(qr, { small: true })
    }

    if (connection === 'open') {
      connected = true
      console.log('WhatsApp connected.')
    }

    if (connection === 'close') {
      connected = false
      const statusCode = (lastDisconnect?.error as Boom | undefined)?.output?.statusCode
      if (statusCode !== DisconnectReason.loggedOut) {
        console.log('Connection closed, reconnecting...')
        void startSock()
      } else {
        console.log(`Logged out. Delete ${AUTH_DIR} and restart to re-link a device.`)
      }
    }
  })
}

void startSock()

function normalizeNumber(raw: string): string {
  return raw.replace(/[^\d]/g, '')
}

const server = createServer((req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ status: 'ok', service: 'whatsapp_baileys_sidecar', connected }))
    return
  }

  if (req.method === 'POST' && req.url === '/check') {
    let body = ''
    req.on('data', (chunk) => { body += chunk })
    req.on('end', () => { void handleCheck(body, res) })
    return
  }

  res.writeHead(404, { 'content-type': 'application/json' })
  res.end(JSON.stringify({ error: 'not found' }))
})

async function handleCheck(body: string, res: import('node:http').ServerResponse): Promise<void> {
  let number: unknown
  try {
    ;({ number } = JSON.parse(body || '{}'))
  } catch {
    res.writeHead(400, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ error: 'invalid JSON body' }))
    return
  }

  if (typeof number !== 'string' || !number.trim()) {
    res.writeHead(400, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ error: 'body must include "number" (a phone number with country code)' }))
    return
  }

  if (!sock || !connected) {
    res.writeHead(503, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ error: 'WhatsApp not connected yet — scan the QR code in the sidecar console' }))
    return
  }

  const digits = normalizeNumber(number)
  try {
    const results = await sock.onWhatsApp(`${digits}@s.whatsapp.net`)
    const hit = results?.[0]
    res.writeHead(200, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ number: digits, exists: !!hit?.exists, jid: hit?.jid ?? null }))
  } catch (err) {
    res.writeHead(500, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ error: String(err) }))
  }
}

server.listen(PORT, () => {
  console.log(`Baileys WhatsApp sidecar listening on :${PORT}`)
})
