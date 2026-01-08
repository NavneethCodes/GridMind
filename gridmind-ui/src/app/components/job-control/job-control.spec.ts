import { ComponentFixture, TestBed } from '@angular/core/testing';

import { JobControl } from './job-control';

describe('JobControl', () => {
  let component: JobControl;
  let fixture: ComponentFixture<JobControl>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [JobControl]
    })
    .compileComponents();

    fixture = TestBed.createComponent(JobControl);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
