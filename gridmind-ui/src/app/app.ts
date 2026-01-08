import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

// 1. We "Import" the code from the other files so this file knows they exist
import { NodeGridComponent } from './components/node-grid/node-grid.component';
import { JobControlComponent } from './components/job-control/job-control';

@Component({
  selector: 'app-root',
  standalone: true,
  // 2. This is the "Imports Array".
  // We add JobControlComponent here so it can be used in your HTML
  imports: [
    CommonModule,
    NodeGridComponent,
    JobControlComponent
  ],
  templateUrl: './app.component.html',
  styleUrl: './app.scss'
})
export class AppComponent {
  title = 'GridMind Dashboard';
}
