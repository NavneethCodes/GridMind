import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-job-control',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './job-control.html', // Matches your file 'job-control.html'
  styleUrl: './job-control.scss'     // Matches your file 'job-control.scss'
})
export class JobControlComponent {
  selectedFile: File | null = null;
  logs: string[] = [];
  trustedNodeCount: number = 1; // Simulated for now

  // Task 2: Drag & Drop / File Upload
  onFileSelected(event: any) {
    const file = event.target.files[0];
    // Requirement: Accepts only .log files
    if (file && file.name.endsWith('.log')) {
      this.selectedFile = file;
      this.addLog(`File uploaded: ${file.name}`);
    } else {
      alert('Error: Only .log files are allowed.');
    }
  }

  // Task 2: Control Button
  startAnalysis() {
    this.addLog('Verifying 192.168.0.101...');
    this.addLog('Trust OK.');
    this.addLog('Sending chunk 1/4...');
    this.addLog('Node 192.168.0.103 rejected (Untrusted).');
    this.addLog('Re-routing task...');
  }

  addLog(message: string) {
    const time = new Date().toLocaleTimeString();
    this.logs.push(`[${time}] ${message}`);
  }
}
