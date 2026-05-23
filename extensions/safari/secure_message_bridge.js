(function (global) {
  'use strict';

  const MAX_PAYLOAD_BYTES = 64 * 1024;
  const MAX_NONCES = 1500;
  const seenNonces = new Set();
  const nonceOrder = [];
  const allowedMessageTypes = new Set([
    'AIO_CLASSIFY_EMAIL',
    'AIO_SEND_FEEDBACK',
    'AIO_GET_STATUS',
    'AIO_GET_PROVIDERS',
    'AIO_OPEN_DASHBOARD',
    'AIO_RUNTIME_TELEMETRY',
    'AIO_GET_THREAT_STATS',
    'AIO_GET_RECENT_THREATS',
    'AIO_ANALYZE_DOMAIN',
    'AIO_REPORT_SCAM',
    'AIO_MARK_SAFE',
    'AIO_BLACKLIST_SENDER',
    'AIO_WHITELIST_SENDER',
    'AIO_SHOW_NOTIFICATION',
    'AIO_UPDATE_BADGE',
    'AIO_GET_SETTINGS',
    'AIO_SAVE_SETTINGS'
  ]);

  function browserApi() { return global.browser || global.chrome; }

  function requestId(prefix = 'ext_req') {
    const v = global.crypto && crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2);
    return `${prefix}_${v}`;
  }

  function safeJson(value) {
    try { return JSON.parse(JSON.stringify(value || {})); } catch { return {}; }
  }

  function payloadBytes(payload) {
    try { return new Blob([JSON.stringify(payload || {})]).size; } catch { return MAX_PAYLOAD_BYTES + 1; }
  }

  function rememberNonce(nonce) {
    if (!nonce) return false;
    if (seenNonces.has(nonce)) return false;
    seenNonces.add(nonce);
    nonceOrder.push(nonce);
    while (nonceOrder.length > MAX_NONCES) seenNonces.delete(nonceOrder.shift());
    return true;
  }

  // Schema keys match what content.js / popup.js / background.js actually
  // exchange. Keys follow the Python backend's snake_case convention so the
  // backend can consume payloads verbatim. `AIO_SAVE_SETTINGS` is open-ended
  // (allowlist:null) because the popup spreads the entire settings object.
  const MESSAGE_SCHEMAS = {
    AIO_CLASSIFY_EMAIL:     ['message_id', 'subject', 'sender', 'sender_email', 'body'],
    AIO_SEND_FEEDBACK:      ['email_id', 'category', 'correct'],
    AIO_GET_STATUS:         [],
    AIO_GET_PROVIDERS:      [],
    AIO_OPEN_DASHBOARD:     ['path', 'tab'],
    AIO_RUNTIME_TELEMETRY:  ['event', 'data'],
    AIO_GET_THREAT_STATS:   ['force'],
    AIO_GET_RECENT_THREATS: ['limit'],
    AIO_ANALYZE_DOMAIN:     ['domain'],
    AIO_REPORT_SCAM:        ['email_id', 'sender_email', 'block_sender'],
    AIO_MARK_SAFE:          ['email_id'],
    AIO_BLACKLIST_SENDER:   ['entry', 'entry_type', 'reason'],
    AIO_WHITELIST_SENDER:   ['entry', 'entry_type', 'notes'],
    AIO_SHOW_NOTIFICATION:  ['title', 'message'],
    AIO_UPDATE_BADGE:       ['count', 'color'],
    AIO_GET_SETTINGS:       [],
    AIO_SAVE_SETTINGS:      null
  };

  function validatePayloadSchema(type, payload) {
    if (!(type in MESSAGE_SCHEMAS)) return false;
    const allowedFields = MESSAGE_SCHEMAS[type];
    if (allowedFields === null) return true;
    const payloadKeys = Object.keys(payload || {});
    for (const key of payloadKeys) {
      if (!allowedFields.includes(key)) return false;
    }
    return true;
  }

  function validateMessage(message) {
    const msg = safeJson(message);
    if (!allowedMessageTypes.has(msg.type)) return { ok: false, reason: 'unsupported_message_type' };
    if (!msg.nonce || !rememberNonce(String(msg.nonce))) return { ok: false, reason: 'nonce_replay_or_missing' };
    if (payloadBytes(msg.payload) > MAX_PAYLOAD_BYTES) return { ok: false, reason: 'payload_too_large' };
    if (!validatePayloadSchema(msg.type, msg.payload)) {
      return { ok: false, reason: 'payload_schema_violation' };
    }
    return { ok: true, message: msg };
  }

  async function sendToRuntime(type, payload = {}) {
    const api = browserApi();
    const message = {
      type,
      payload: safeJson(payload),
      nonce: requestId('nonce'),
      request_id: requestId()
    };
    return new Promise(resolve => {
      try {
        api.runtime.sendMessage(message, response => {
          const lastError = api.runtime.lastError;
          if (lastError) resolve({ ok: false, error: lastError.message });
          else resolve(response || { ok: false, error: 'empty_response' });
        });
      } catch (error) {
        resolve({ ok: false, error: error.message });
      }
    });
  }

  global.AIOExtensionBridge = {
    requestId, validateMessage, sendToRuntime,
    allowedMessageTypes: Array.from(allowedMessageTypes)
  };
})(typeof globalThis !== 'undefined' ? globalThis : window);
