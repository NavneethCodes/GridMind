package com.gridmind.model;

import lombok.Data;
import java.io.Serializable;
import java.util.UUID;

@Data
public class Job implements Serializable {
    private String jobId;
    private String filename;
    private int totalChunks;
    private int completedChunks;
    private String status; // "PENDING", "IN_PROGRESS", "COMPLETED"
    private String jobType; // "REGEX" or "AI_SCAN" (The Opening!)
    
    // For simple regex jobs
    private String searchPattern; 

    public Job(String filename, int totalChunks, String searchPattern) {
        this.jobId = UUID.randomUUID().toString();
        this.filename = filename;
        this.totalChunks = totalChunks;
        this.searchPattern = searchPattern;
        this.status = "PENDING";
        this.jobType = "REGEX"; // Default for now
        this.completedChunks = 0;
    }
}
