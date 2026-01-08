import { TestBed } from '@angular/core/testing';

import { NodeStatus } from './node-status.service';

describe('NodeStatus', () => {
  let service: NodeStatus;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(NodeStatus);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
