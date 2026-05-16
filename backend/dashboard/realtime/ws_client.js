/**
 * WebSocket Client with Resumable Connections and Delta Sync
 * ============================================================
 * 
 * Features:
 * - Resumable connection with session tokens
 * - Auto-reconnect with exponential backoff
 * - Subscription management
 * - Event buffering for offline
 * - Delta replay requests
 * - Backpressure handling
 * - Optimistic UI updates
 * 
 */

(function(global) {
    'use strict';

    const ConnectionState = {
        DISCONNECTED: 'disconnected',
        CONNECTING: 'connecting',
        CONNECTED: 'connected',
        RECONNECTING: 'reconnecting',
        FAILED: 'failed'
    };

    const Priority = {
        HIGH: 1,
        NORMAL: 2,
        LOW: 3,
        BATCH: 4
    };

    class SessionToken {
        constructor(data) {
            this.tokenId = data.token_id || data.tokenId;
            this.clientId = data.client_id || data.clientId;
            this.createdAt = data.created_at || data.createdAt;
            this.expiresAt = data.expires_at || data.expiresAt;
            this.lastEventId = data.last_event_id || data.lastEventId;
            this.lastSequence = data.last_sequence || data.lastSequence || {};
        }

        toString() {
            return btoa(JSON.stringify({
                token_id: this.tokenId,
                client_id: this.clientId,
                created_at: this.createdAt,
                expires_at: this.expiresAt,
                last_event_id: this.lastEventId,
                last_sequence: this.lastSequence
            }));
        }

        static fromString(str) {
            try {
                return new SessionToken(JSON.parse(atob(str)));
            } catch (e) {
                return null;
            }
        }
    }

    class OfflineMutation {
        constructor(topic, action, payload) {
            this.id = 'mut_' + Math.random().toString(36).substr(2, 9);
            this.topic = topic;
            this.action = action;
            this.payload = payload;
            this.timestamp = Date.now();
        }

        toJSON() {
            return {
                mutation_id: this.id,
                topic: this.topic,
                action: this.action,
                payload: this.payload,
                timestamp: this.timestamp
            };
        }
    }

    class EventBuffer {
        constructor(maxSize = 1000) {
            this.maxSize = maxSize;
            this.buffer = [];
        }

        add(event) {
            this.buffer.push(event);
            if (this.buffer.length > this.maxSize) {
                this.buffer.shift();
            }
        }

        getSince(sequence, topic = null) {
            return this.buffer.filter(e => 
                e.sequence > sequence && (!topic || e.topic === topic)
            );
        }

        getLatest(count = 10) {
            return this.buffer.slice(-count);
        }

        clear() {
            this.buffer = [];
        }
    }

    class PendingUpdate {
        constructor(topic, payload, optimisticId) {
            this.id = optimisticId || 'opt_' + Math.random().toString(36).substr(2, 9);
            this.topic = topic;
            this.payload = payload;
            this.timestamp = Date.now();
            this.confirmed = false;
            this.rolledBack = false;
            this.error = null;
        }
    }

    class WebSocketRealtimeClient {
        constructor(config = {}) {
            this.config = Object.assign({
                apiBase: window.location.origin || 'http://127.0.0.1:4597',
                wsEndpoint: '/api/v1/ws',
                reconnectBaseDelay: 1000,
                reconnectMaxDelay: 30000,
                reconnectMultiplier: 2,
                maxReconnectAttempts: 10,
                heartbeatInterval: 30000,
                bufferSize: 1000,
                maxOfflineQueue: 250,
                reconnectJitter: 0.25,
                heartbeatMissLimit: 3,
                enableDeltaSync: true,
                enableOfflineQueue: true,
                batchDelay: 100,
                batchSize: 10
            }, config);

            this.state = ConnectionState.DISCONNECTED;
            this.ws = null;
            this.clientId = this._generateClientId();

            this.reconnectAttempts = 0;
            this.reconnectDelay = this.config.reconnectBaseDelay;

            this.sessionToken = this._loadSessionToken();
            this.subscriptions = new Map();
            this.subscriptionCallbacks = new Map();

            this.eventBuffer = new EventBuffer(this.config.bufferSize);
            this.offlineQueue = [];
            this.pendingUpdates = [];
            this.optimisticUpdates = new Map();

            this.lastSequence = {};
            this.lastEventId = null;
            this.seenEvents = new Set();
            this.heartbeatMisses = 0;
            this.accountScope = config.accountScope || { tenantId: 'local', accountId: 'default', provider: 'local', mailboxId: 'inbox' };

            this.isOnline = navigator.onLine;
            this.backpressureState = null;

            this._heartbeatTimer = null;
            this._reconnectTimer = null;
            this._batchTimer = null;
            this._pendingBatch = [];

            this._setupEventListeners();
        }

        _generateClientId() {
            let id = localStorage.getItem('ws_client_id');
            if (!id) {
                id = 'client_' + ((crypto && crypto.randomUUID) ? crypto.randomUUID() : Math.random().toString(36).substr(2, 12));
                localStorage.setItem('ws_client_id', id);
            }
            return id;
        }

        _loadSessionToken() {
            // Keep websocket continuation tokens in memory only. They are not
            // provider/OAuth credentials, but persisting them in browser storage
            // increases replay risk after XSS or local compromise.
            return null;
        }

        _saveSessionToken(token) {
            this.sessionToken = token;
        }

        _setupEventListeners() {
            window.addEventListener('online', () => this._handleOnline());
            window.addEventListener('offline', () => this._handleOffline());

        }

        async connect() {
            if (this.state === ConnectionState.CONNECTED) {
                return;
            }

            this._setState(ConnectionState.CONNECTING);

            try {
                const wsUrl = this._buildWebSocketUrl();
                this.ws = new WebSocket(wsUrl);

                this.ws.onopen = () => this._handleOpen();
                this.ws.onclose = (event) => this._handleClose(event);
                this.ws.onerror = (err) => this._handleError(err);
                this.ws.onmessage = (msg) => this._handleMessage(msg);

            } catch (err) {
                console.error('WebSocket connection failed:', err);
                this._setState(ConnectionState.FAILED);
                this._scheduleReconnect();
            }
        }



        _buildWebSocketUrl() {
            const base = this.config.apiBase || window.location.origin || 'http://127.0.0.1:4597';
            const url = new URL(this.config.wsEndpoint, base);
            url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
            url.searchParams.set('client_id', this.clientId);
            url.searchParams.set('tenant_id', this.accountScope.tenantId || 'local');
            url.searchParams.set('account_id', this.accountScope.accountId || 'default');
            return url.toString();
        }

        _requestId() {
            return (crypto && crypto.randomUUID) ? crypto.randomUUID() : ('req_' + Math.random().toString(36).slice(2));
        }

        _eventKey(event) {
            const topic = event.topic || 'unknown';
            const id = event.event_id || event.id || `${topic}:${event.sequence || ''}`;
            return `${this.accountScope.tenantId || 'local'}:${this.accountScope.accountId || 'default'}:${topic}:${id}`;
        }

        _shouldApplyEvent(event) {
            if (!event || !event.topic) return false;
            const key = this._eventKey(event);
            if (this.seenEvents.has(key)) return false;
            const sequence = Number(event.sequence || 0);
            const last = Number(this.lastSequence[event.topic] || 0);
            if (sequence && last && sequence <= last) return false;
            this.seenEvents.add(key);
            if (this.seenEvents.size > this.config.bufferSize * 2) {
                this.seenEvents.delete(this.seenEvents.values().next().value);
            }
            return true;
        }

        _ackEvent(event, status = 'applied') {
            if (!event || !(event.event_id || event.id || event.sequence)) return;
            this._send({
                type: 'ack',
                topic: event.topic,
                event_id: event.event_id || event.id,
                sequence: event.sequence,
                status,
                scope: this.accountScope
            });
        }

        _handleAck(message) {
            if (message.optimistic_id) {
                this.confirmOptimisticUpdate(message.optimistic_id, message.success !== false, message.error || null);
            }
        }

        _handleOpen() {
            console.log('WebSocket connected');
            this.reconnectAttempts = 0;
            this.reconnectDelay = this.config.reconnectBaseDelay;
            this._setState(ConnectionState.CONNECTED);

            if (this.sessionToken) {
                this._sendResumeSession();
            } else {
                this._sendCreateSession();
            }

            this._startHeartbeat();
            this._flushOfflineQueue();
        }

        _handleClose() {
            console.log('WebSocket closed');
            this._stopHeartbeat();
            this._setState(ConnectionState.RECONNECTING);
            this._scheduleReconnect();
        }

        _handleError(err) {
            console.error('WebSocket error:', err);
        }

        async _handleMessage(event) {
            try {
                const message = JSON.parse(event.data);
                
                switch (message.type) {
                    case 'session_created':
                        this._handleSessionCreated(message);
                        break;
                    case 'session_resumed':
                        this._handleSessionResumed(message);
                        break;
                    case 'heartbeat_ack':
                        this.heartbeatMisses = 0;
                        break;
                    case 'ack':
                        this._handleAck(message);
                        break;
                    case 'event':
                        await this._handleEvent(message);
                        break;
                    case 'delta_sync':
                        await this._handleDeltaSync(message);
                        break;
                    case 'recovery_events':
                        await this._handleRecoveryEvents(message);
                        break;
                    case 'backpressure':
                        this._handleBackpressure(message);
                        break;
                    case 'conflict':
                        await this._handleConflict(message);
                        break;
                    case 'error':
                        console.error('Server error:', message.error);
                        break;
                    default:
                        console.warn('Unknown message type:', message.type);
                }
            } catch (err) {
                console.error('Error handling message:', err);
            }
        }

        _handleSessionCreated(message) {
            const token = new SessionToken(message.session);
            this._saveSessionToken(token);

            for (const topic of this.subscriptions.keys()) {
                this._sendSubscribe(topic);
            }
        }

        _handleSessionResumed(message) {
            const token = new SessionToken(message.session);
            this._saveSessionToken(token);

            if (message.sequence_info) {
                for (const [topic, sequence] of Object.entries(message.sequence_info)) {
                    this.lastSequence[topic] = sequence;
                }
            }

            console.log('Session resumed');

            for (const topic of this.subscriptions.keys()) {
                const lastSeq = this.lastSequence[topic] || 0;
                if (this.config.enableDeltaSync && lastSeq > 0) {
                    this._requestDeltaReplay(topic, lastSeq);
                } else {
                    this._sendSubscribe(topic);
                }
            }
        }

        async _handleEvent(message) {
            const event = message.event || {};
            if (!this._shouldApplyEvent(event)) {
                this._ackEvent(event, 'duplicate_or_stale');
                return;
            }
            
            this.eventBuffer.add(event);
            this.lastSequence[event.topic] = event.sequence;
            this.lastEventId = event.event_id;

            if (this.config.enableDeltaSync) {
                this._updateLocalState(event.topic, event.payload);
            }
            this._ackEvent(event, 'applied');
            if (global.AIOFrontendRuntime && global.AIOFrontendRuntime.mailboxState) {
                global.AIOFrontendRuntime.mailboxState.applyEvent(this.accountScope, event);
            }

            const callbacks = this.subscriptionCallbacks.get(event.topic);
            if (callbacks) {
                for (const callback of callbacks) {
                    try {
                        if (callback.isAsync) {
                            await callback(event.payload);
                        } else {
                            callback(event.payload);
                        }
                    } catch (err) {
                        console.error('Callback error:', err);
                    }
                }
            }
        }

        async _handleDeltaSync(message) {
            const topic = message.topic;
            const deltas = message.deltas || [];
            const snapshot = message.snapshot;

            if (snapshot && this.config.enableDeltaSync) {
                this._setFullState(topic, snapshot);
            }

            for (const delta of deltas) {
                const event = {
                    topic: topic,
                    sequence: delta.sequence,
                    event_id: delta.event_id,
                    payload: delta.delta || delta.full,
                    version: delta.version
                };
                
                if (!this._shouldApplyEvent(event)) {
                    this._ackEvent(event, 'duplicate_or_stale');
                    continue;
                }
                this.eventBuffer.add(event);
                this.lastSequence[topic] = delta.sequence;
                this._ackEvent(event, 'applied');

                const callbacks = this.subscriptionCallbacks.get(topic);
                if (callbacks) {
                    for (const callback of callbacks) {
                        try {
                            callback(event.payload);
                        } catch (err) {
                            console.error('Callback error:', err);
                        }
                    }
                }
            }
        }

        async _handleRecoveryEvents(message) {
            console.log('Recovered events:', message.events.length);
            
            for (const event of message.events) {
                await this._handleEvent({
                    type: 'event',
                    event: event
                });
            }
        }

        _handleBackpressure(message) {
            this.backpressureState = message.state;
            
            if (this.onBackpressureChange) {
                this.onBackpressureChange(message.state, message.details);
            }
        }

        async _handleConflict(message) {
            const conflict = message.conflict;
            console.warn('Conflict detected:', conflict);

            if (this.onConflictDetected) {
                await this.onConflictDetected(conflict);
            }
        }

        _setState(newState) {
            this.state = newState;
            if (this.onStateChange) {
                this.onStateChange(newState);
            }
        }

        _send(message) {
            const payload = {
                ...message,
                client_id: message.client_id || this.clientId,
                scope: message.scope || this.accountScope,
                request_id: message.request_id || this._requestId()
            };
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify(payload));
            } else if (this.config.enableOfflineQueue) {
                this._queueOfflineAction(message);
            }
        }

        _sendCreateSession() {
            this._send({
                type: 'create_session',
                client_id: this.clientId,
                subscriptions: Array.from(this.subscriptions.keys())
            });
        }

        _sendResumeSession() {
            this._send({
                type: 'resume_session',
                session_token: this.sessionToken.toString(),
                client_id: this.clientId
            });
        }

        _sendSubscribe(topic) {
            this._send({
                type: 'subscribe',
                topic: topic
            });
        }

        _sendUnsubscribe(topic) {
            this._send({
                type: 'unsubscribe',
                topic: topic
            });
        }

        _sendHeartbeat() {
            this._send({
                type: 'heartbeat',
                client_id: this.clientId
            });
        }

        _requestDeltaReplay(topic, lastSequence) {
            this._send({
                type: 'request_delta',
                topic: topic,
                from_sequence: lastSequence,
                client_id: this.clientId
            });
        }

        _queueOfflineAction(message) {
            if (!this.config.enableOfflineQueue) return;
            
            const item = { ...message, timestamp: Date.now(), request_id: message.request_id || this._requestId() };
            const dedupeKey = `${item.type}:${item.topic || ''}:${item.request_id}`;
            if (this.offlineQueue.some(existing => `${existing.type}:${existing.topic || ''}:${existing.request_id}` === dedupeKey)) return;
            this.offlineQueue.push(item);
            if (this.offlineQueue.length > this.config.maxOfflineQueue) {
                this.offlineQueue.splice(0, this.offlineQueue.length - this.config.maxOfflineQueue);
                global.AIOFrontendRuntime?.capture('offline_queue_pruned', { max: this.config.maxOfflineQueue }, 'warning');
            }
        }

        async _flushOfflineQueue() {
            if (this.offlineQueue.length === 0) return;

            console.log('Flushing offline queue:', this.offlineQueue.length);

            for (const action of this.offlineQueue) {
                this._send(action);
            }

            this.offlineQueue = [];
        }

        _startHeartbeat() {
            this._heartbeatTimer = setInterval(() => {
                this.heartbeatMisses += 1;
                if (this.heartbeatMisses > this.config.heartbeatMissLimit) {
                    global.AIOFrontendRuntime?.capture('websocket_heartbeat_missed', { misses: this.heartbeatMisses }, 'warning');
                    try { this.ws && this.ws.close(); } catch {}
                    return;
                }
                this._sendHeartbeat();
            }, this.config.heartbeatInterval);
        }

        _stopHeartbeat() {
            if (this._heartbeatTimer) {
                clearInterval(this._heartbeatTimer);
                this._heartbeatTimer = null;
            }
        }

        _scheduleReconnect() {
            if (this.reconnectAttempts >= this.config.maxReconnectAttempts) {
                console.error('Max reconnect attempts reached');
                this._setState(ConnectionState.FAILED);
                return;
            }

            if (this._reconnectTimer) {
                clearTimeout(this._reconnectTimer);
            }

            const rawDelay = Math.min(
                this.reconnectDelay * Math.pow(this.config.reconnectMultiplier, this.reconnectAttempts),
                this.config.reconnectMaxDelay
            );
            const jitter = rawDelay * this.config.reconnectJitter * Math.random();
            const delay = Math.round(rawDelay + jitter);

            console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1})`);

            this._reconnectTimer = setTimeout(() => {
                this.reconnectAttempts++;
                this.connect();
            }, delay);
        }

        _handleOnline() {
            console.log('Back online');
            this.isOnline = true;
            this.connect();
        }

        _handleOffline() {
            console.log('Went offline');
            this.isOnline = false;
        }

        subscribe(topic, callback) {
            if (!this.subscriptions.has(topic)) {
                this.subscriptions.set(topic, new Set());
                if (this.state === ConnectionState.CONNECTED) {
                    this._sendSubscribe(topic);
                }
            }

            const callbacks = this.subscriptionCallbacks.get(topic) || [];
            callback.isAsync = callback.constructor.name === 'AsyncFunction';
            callbacks.push(callback);
            this.subscriptionCallbacks.set(topic, callbacks);

            return () => this.unsubscribe(topic, callback);
        }

        unsubscribe(topic, callback) {
            const callbacks = this.subscriptionCallbacks.get(topic);
            if (callbacks) {
                const index = callbacks.indexOf(callback);
                if (index > -1) {
                    callbacks.splice(index, 1);
                }
                if (callbacks.length === 0) {
                    this.subscriptions.delete(topic);
                    if (this.state === ConnectionState.CONNECTED) {
                        this._sendUnsubscribe(topic);
                    }
                }
            }
        }

        publish(topic, payload, priority = Priority.NORMAL, optimistic = false) {
            if (optimistic) {
                return this._publishOptimistic(topic, payload, priority);
            }

            if (!this.isOnline || this.state !== ConnectionState.CONNECTED) {
                const mutation = new OfflineMutation(topic, 'publish', payload);
                this.offlineQueue.push(mutation.toJSON());
                return mutation.id;
            }

            this._send({
                type: 'publish',
                topic: topic,
                payload: payload,
                priority: priority
            });

            return null;
        }

        _publishOptimistic(topic, payload, priority) {
            const updateId = 'opt_' + Math.random().toString(36).substr(2, 9);
            
            const pending = new PendingUpdate(topic, payload, updateId);
            this.pendingUpdates.push(pending);
            this.optimisticUpdates.set(updateId, pending);

            const optimisticPayload = { ...payload, _optimistic_id: updateId };
            
            const callbacks = this.subscriptionCallbacks.get(topic);
            if (callbacks) {
                for (const callback of callbacks) {
                    try {
                        callback(optimisticPayload);
                    } catch (err) {
                        console.error('Optimistic update error:', err);
                    }
                }
            }

            if (!this.isOnline || this.state !== ConnectionState.CONNECTED) {
                return updateId;
            }

            this._send({
                type: 'publish',
                topic: topic,
                payload: payload,
                priority: priority,
                optimistic_id: updateId
            });

            return updateId;
        }

        confirmOptimisticUpdate(updateId, success, error = null) {
            const update = this.optimisticUpdates.get(updateId);
            if (!update) return;

            update.confirmed = true;
            if (!success) {
                update.rolledBack = true;
                update.error = error;

                const callbacks = this.subscriptionCallbacks.get(update.topic);
                if (callbacks) {
                    for (const callback of callbacks) {
                        try {
                            callback({
                                _rollback: true,
                                _optimistic_id: updateId,
                                _original_payload: update.payload
                            });
                        } catch (err) {
                            console.error('Rollback error:', err);
                        }
                    }
                }
            }

            this.optimisticUpdates.delete(updateId);
        }

        requestRecovery(topic, lastSequence) {
            this._send({
                type: 'request_recovery',
                topic: topic,
                last_sequence: lastSequence,
                client_id: this.clientId
            });
        }

        getBufferedEvents(topic = null) {
            return this.eventBuffer.getSince(0, topic);
        }

        getLastSequence(topic) {
            return this.lastSequence[topic] || 0;
        }

        localStates = {};

        _updateLocalState(topic, delta) {
            if (!this.localStates[topic]) {
                this.localStates[topic] = {};
            }

            for (const [key, value] of Object.entries(delta)) {
                if (value === null) {
                    delete this.localStates[topic][key];
                } else {
                    this.localStates[topic][key] = value;
                }
            }
        }

        _setFullState(topic, data) {
            this.localStates[topic] = JSON.parse(JSON.stringify(data));
        }

        getLocalState(topic) {
            return this.localStates[topic] || {};
        }

        async batchPublish(patches) {
            if (!this.isOnline || this.state !== ConnectionState.CONNECTED) {
                for (const patch of patches) {
                    this.publish(patch.topic, patch.payload, Priority.BATCH);
                }
                return;
            }

            this._send({
                type: 'batch_publish',
                patches: patches.map(p => ({
                    topic: p.topic,
                    payload: p.payload,
                    priority: p.priority || Priority.BATCH
                }))
            });
        }

        getStatus() {
            return {
                state: this.state,
                isOnline: this.isOnline,
                reconnectAttempts: this.reconnectAttempts,
                subscriptions: Array.from(this.subscriptions.keys()),
                bufferedEvents: this.eventBuffer.buffer.length,
                pendingUpdates: this.pendingUpdates.length,
                offlineQueue: this.offlineQueue.length,
                backpressureState: this.backpressureState,
                clientId: this.clientId,
                hasSession: !!this.sessionToken
            };
        }

        disconnect() {
            this._stopHeartbeat();
            
            if (this._reconnectTimer) {
                clearTimeout(this._reconnectTimer);
            }

            if (this.ws) {
                this._send({
                    type: 'close_session',
                    session_token: this.sessionToken?.toString()
                });
                this.ws.close();
            }

            this.sessionToken = null;
            this._setState(ConnectionState.DISCONNECTED);
        }

        clearSession() {
            this.sessionToken = null;
            this.lastSequence = {};
            this.lastEventId = null;
            this.eventBuffer.clear();
        }
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = WebSocketRealtimeClient;
    } else {
        global.WebSocketRealtimeClient = WebSocketRealtimeClient;
    }

})(typeof window !== 'undefined' ? window : this);