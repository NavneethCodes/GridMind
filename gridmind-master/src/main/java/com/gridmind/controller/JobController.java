package com.gridmind.controller;

import com.gridmind.model.Job;
import com.gridmind.service.JobService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;

@RestController
@RequestMapping("/api/jobs")
public class JobController {

    @Autowired
    private JobService jobService;

    // 1. MASTER: Upload a file to start the grid
    @PostMapping("/submit")
    public ResponseEntity<Job> submitJob(@RequestParam("file") MultipartFile file, 
                                         @RequestParam("pattern") String pattern) {
        try {
            Job job = jobService.createJob(file, pattern);
            return ResponseEntity.ok(job);
        } catch (IOException e) {
            return ResponseEntity.internalServerError().build();
        }
    }

    // 2. WORKER: Polls this to see if work is available
    @GetMapping("/poll")
    public String pollForWork() {
        // "Leave an opening": In the future, this response can contain 
        // { type: "AI", weights: "..." }
        return jobService.getNextTask();
    }
}
