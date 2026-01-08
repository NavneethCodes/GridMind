import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';

// Task 1: Defining the data structure for the 4 nodes
interface GridNode {
  ip: string;
  status: 'Idle' | 'Busy' | 'Offline';
  isTrusted: boolean;
}

@Component({
  selector: 'app-node-grid',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './node-grid.component.html',
  styleUrl: './node-grid.component.scss'
})
export class NodeGridComponent implements OnInit, OnDestroy {

  // Requirement: Display exactly 4 nodes
  nodes: GridNode[] = [
    { ip: '192.168.0.101', status: 'Idle', isTrusted: true },
    { ip: '192.168.0.102', status: 'Idle', isTrusted: true },
    { ip: '192.168.0.103', status: 'Idle', isTrusted: false },
    { ip: '192.168.0.104', status: 'Idle', isTrusted: true }
  ];

  private pollingTimer: any;

  ngOnInit(): void {
    // Task 1 Logic: Polling every 2 seconds
    this.startStatusPolling();
  }

  startStatusPolling(): void {
    this.pollingTimer = setInterval(() => {
      this.fetchNodeStatus();
    }, 2000); // 2000ms = 2 seconds
  }

  fetchNodeStatus(): void {
    // Requirement: Poll GET /api/nodes
    console.log('Fetching node updates from GET /api/nodes...');

    // For now, this simulates random status changes to test your UI.
    // Later, you will replace this with a real FastAPI call.
    this.nodes = this.nodes.map(node => {
      if (node.ip === '192.168.0.103') return node; // Keep node 3 offline

      const statuses: ('Idle' | 'Busy' | 'Offline')[] = ['Idle', 'Busy'];
      return {
        ...node,
        status: statuses[Math.floor(Math.random() * statuses.length)]
      };
    });
  }

  // Clean up the timer when the component is destroyed to prevent memory leaks
  ngOnDestroy(): void {
    if (this.pollingTimer) {
      clearInterval(this.pollingTimer);
    }
  }
}
