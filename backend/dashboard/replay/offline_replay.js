const MAX_REPLAY_RETRIES = 5;
const BASE_RETRY_DELAY = 1000;
const MAX_RETRY_DELAY = 30000;

class OfflineReplay {
  constructor(queue, apiBase) {
    this.queue = queue;
    this.apiBase = apiBase;
    this.replaying = false;
    this.progressListeners = [];
    this.conflictStrategies = {
      server_wins: this._serverWins.bind(this),
      client_wins: this._clientWins.bind(this),
      merge: this._merge.bind(this),
      manual: this._manualResolve.bind(this)
    };
  }

  async replay() {
    if (this.replaying) return { status: 'in_progress' };
    if (!navigator.onLine) return { status: 'offline', message: 'Cannot replay while offline' };
    
    this.replaying = true;
    this._emitProgress({ phase: 'starting', progress: 0 });
    
    try {
      const pending = await this.queue.getPendingOperations();
      
      if (pending.length === 0) {
        this.replaying = false;
        return { status: 'completed', message: 'No operations to replay' };
      }
      
      this._emitProgress({ phase: 'replaying', total: pending.length, progress: 0 });
      
      let completed = 0;
      let failed = 0;
      let conflicts = 0;
      
      for (const op of pending) {
        if (op.status !== 'pending') continue;
        
        this._emitProgress({ 
          phase: 'replaying', 
          current: op, 
          progress: (completed / pending.length) * 100 
        });
        
        try {
          const result = await this._executeWithRetry(op);
          
          if (result.conflict) {
            conflicts++;
            await this._handleConflict(op, result);
          } else {
            await this.queue.markCompleted(op.opId);
            completed++;
          }
        } catch (error) {
          failed++;
          await this.queue.markFailed(op.opId, error.message);
        }
      }
      
      this.replaying = false;
      this._emitProgress({ phase: 'completed', completed, failed, conflicts });
      
      return {
        status: 'completed',
        completed,
        failed,
        conflicts,
        total: pending.length
      };
    } catch (error) {
      this.replaying = false;
      return { status: 'error', message: error.message };
    }
  }

  async _executeWithRetry(operation) {
    let lastError;
    const strategy = operation.metadata.conflictStrategy || 'server_wins';
    
    for (let attempt = 0; attempt < MAX_REPLAY_RETRIES; attempt++) {
      try {
        const response = await this._sendOperation(operation);
        
        if (response.status === 409) {
          return { conflict: true, response, operation };
        }
        
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        return { success: true, data: await response.json() };
      } catch (error) {
        lastError = error;
        
        if (attempt < MAX_REPLAY_RETRIES - 1) {
          const delay = this._calculateBackoff(attempt);
          await this._sleep(delay);
        }
      }
    }
    
    throw lastError;
  }

  async _sendOperation(operation) {
    const endpoints = {
      mark_read: '/emails/read',
      mark_unread: '/emails/unread',
      move: '/emails/move',
      delete: '/emails/delete',
      apply_rule: '/rules/apply',
      update_category: '/emails/categorize'
    };
    
    const endpoint = endpoints[operation.type];
    if (!endpoint) {
      throw new Error(`Unknown operation type: ${operation.type}`);
    }
    
    return fetch(`${this.apiBase}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(operation.payload)
    });
  }

  _calculateBackoff(attempt) {
    const delay = Math.min(BASE_RETRY_DELAY * Math.pow(2, attempt), MAX_RETRY_DELAY);
    return delay + (Math.random() * 1000);
  }

  _sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  async _handleConflict(operation, result) {
    const strategy = operation.metadata.conflictStrategy || 'server_wins';
    const handler = this.conflictStrategies[strategy];
    
    if (handler) {
      await handler(operation, result);
    }
  }

  async _serverWins(operation, result) {
    await this.queue.markCompleted(operation.opId);
  }

  async _clientWins(operation, result) {
    operation.payload.force = true;
    const response = await this._sendOperation(operation);
    if (response.ok) {
      await this.queue.markCompleted(operation.opId);
    } else {
      await this.queue.markFailed(operation.opId, 'Client wins strategy failed');
    }
  }

  async _merge(operation, result) {
    const serverData = await result.response.json();
    const merged = { ...operation.payload, ...serverData, merged: true };
    operation.payload = merged;
    
    const response = await this._sendOperation(operation);
    if (response.ok) {
      await this.queue.markCompleted(operation.opId);
    } else {
      await this.queue.markFailed(operation.opId, 'Merge strategy failed');
    }
  }

  async _manualResolve(operation, result) {
    operation.status = 'conflict';
    operation.conflictData = await result.response.json();
    operation.metadata.pendingResolution = true;
  }

  onProgress(handler) {
    this.progressListeners.push(handler);
    return () => {
      const index = this.progressListeners.indexOf(handler);
      if (index > -1) this.progressListeners.splice(index, 1);
    };
  }

  _emitProgress(data) {
    this.progressListeners.forEach(handler => handler(data));
  }

  setConflictStrategy(operation, strategy) {
    operation.metadata = operation.metadata || {};
    operation.metadata.conflictStrategy = strategy;
  }

  isReplaying() {
    return this.replaying;
  }
}

window.OfflineReplay = OfflineReplay;
