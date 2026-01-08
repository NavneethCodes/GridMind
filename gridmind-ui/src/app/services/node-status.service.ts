import { Injectable } from '@angular/core';
import { Observable, interval, map } from 'rxjs';

export interface GridNode {
  ip: string;
  status: 'idle' | 'busy' | 'offline';
  isTrusted: boolean;
}

@Injectable({ providedIn: 'root' })
export class NodeStatusService {
  // Task 1: Polling interval: every 2 seconds
  getNodes(): Observable<GridNode[]> {
    return interval(2000).pipe(
      map(() => [
        { ip: '192.168.0.101', status: Math.random() > 0.5 ? 'idle' : 'busy', isTrusted: true },
        { ip: '192.168.0.102', status: 'busy', isTrusted: true },
        { ip: '192.168.0.103', status: 'offline', isTrusted: false },
        { ip: '192.168.0.104', status: 'idle', isTrusted: true }
      ])
    );
  }
}
