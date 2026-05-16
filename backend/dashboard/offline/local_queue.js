const OPERATION_STORE = 'operations';
const MAX_RETRIES = 5;
const BASE_DELAY = 1000;
const MAX_DELAY = 60000;

class LocalQueue {
  constructor(db) {
    this.db = db;
    this.processing = false;
    this.retryDelays = new Map();
  }

  async addOperation(operation) {
    const entry = {
      type: operation.type,
      payload: operation.payload,
      timestamp: Date.now(),
      status: 'pending',
      retries: 0,
      priority: operation.priority || 0,
      conflictKey: operation.conflictKey || null,
      metadata: operation.metadata || {},
      accountId: operation.accountId || operation.payload?.account_id || null,
      nextAttemptAt: Date.now()
    };
    
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(OPERATION_STORE, 'readwrite');
      const store = tx.objectStore(OPERATION_STORE);
      const request = store.add(entry);
      
      request.onsuccess = () => {
        entry.opId = request.result;
        resolve(entry);
      };
      request.onerror = () => reject(request.error);
    });
  }

  async addBatch(operations) {
    const entries = operations.map(op => ({
      type: op.type,
      payload: op.payload,
      timestamp: Date.now(),
      status: 'pending',
      retries: 0,
      priority: op.priority || 0,
      conflictKey: op.conflictKey || null,
      metadata: op.metadata || {},
      accountId: op.accountId || op.payload?.account_id || null,
      nextAttemptAt: Date.now()
    }));
    
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(OPERATION_STORE, 'readwrite');
      const store = tx.objectStore(OPERATION_STORE);
      
      entries.forEach(entry => store.add(entry));
      
      tx.oncomplete = () => resolve(entries.length);
      tx.onerror = () => reject(tx.error);
    });
  }

  async getPendingOperations() {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(OPERATION_STORE, 'readonly');
      const store = tx.objectStore(OPERATION_STORE);
      const index = store.index('status');
      const request = index.getAll('pending');
      
      request.onsuccess = () => {
        const ops = request.result.sort((a, b) => {
          if (a.priority !== b.priority) return b.priority - a.priority;
          return a.timestamp - b.timestamp;
        });
        resolve(ops);
      };
      request.onerror = () => reject(request.error);
    });
  }

  async markCompleted(opId) {
    return this._updateStatus(opId, 'completed');
  }

  async markFailed(opId, error) {
    const op = await this._getOperation(opId);
    if (!op) return;
    
    op.retries++;
    op.lastError = error;
    
    if (op.retries >= MAX_RETRIES) {
      op.status = 'failed';
    } else {
      op.status = 'pending';
      op.nextAttemptAt = Date.now() + this._calculateBackoff(op.retries);
    }
    
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(OPERATION_STORE, 'readwrite');
      const request = tx.objectStore(OPERATION_STORE).put(op);
      request.onsuccess = () => resolve(op);
      request.onerror = () => reject(request.error);
    });
  }

  async _updateStatus(opId, status) {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(OPERATION_STORE, 'readwrite');
      const store = tx.objectStore(OPERATION_STORE);
      const getReq = store.get(opId);
      
      getReq.onsuccess = () => {
        const op = getReq.result;
        if (op) {
          op.status = status;
          op.completedAt = Date.now();
          store.put(op);
        }
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      };
      getReq.onerror = () => reject(getReq.error);
    });
  }

  async _getOperation(opId) {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(OPERATION_STORE, 'readonly');
      const request = tx.objectStore(OPERATION_STORE).get(opId);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  _calculateBackoff(retries) {
    const delay = Math.min(BASE_DELAY * Math.pow(2, retries), MAX_DELAY);
    const jitter = delay * 0.1 * Math.random();
    return delay + jitter;
  }

  async detectConflict(operation) {
    if (!operation.conflictKey) return false;
    
    const pending = await this.getPendingOperations();
    return pending.some(op => 
      op.conflictKey === operation.conflictKey && 
      op.opId !== operation.opId
    );
  }

  async processQueue(apiCall) {
    if (this.processing) return;
    this.processing = true;
    
    try {
      const pending = await this.getPendingOperations();
      
      for (const op of pending) {
        if (op.nextAttemptAt && op.nextAttemptAt > Date.now()) {
          continue;
        }
        
        try {
          await apiCall(op);
          await this.markCompleted(op.opId);
        } catch (error) {
          await this.markFailed(op.opId, error.message);
        }
      }
    } finally {
      this.processing = false;
    }
  }

  _sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  async clearCompleted() {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(OPERATION_STORE, 'readwrite');
      const store = tx.objectStore(OPERATION_STORE);
      const request = store.openCursor();
      
      let count = 0;
      request.onsuccess = (event) => {
        const cursor = event.target.result;
        if (cursor) {
          if (cursor.value.status === 'completed') {
            cursor.delete();
            count++;
          }
          cursor.continue();
        } else {
          resolve(count);
        }
      };
      request.onerror = () => reject(request.error);
    });
  }

  async getQueueStats() {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(OPERATION_STORE, 'readonly');
      const store = tx.objectStore(OPERATION_STORE);
      const request = store.getAll();
      
      request.onsuccess = () => {
        const ops = request.result;
        resolve({
          total: ops.length,
          pending: ops.filter(op => op.status === 'pending').length,
          completed: ops.filter(op => op.status === 'completed').length,
          failed: ops.filter(op => op.status === 'failed').length
        });
      };
      request.onerror = () => reject(request.error);
    });
  }
}

window.LocalQueue = LocalQueue;
