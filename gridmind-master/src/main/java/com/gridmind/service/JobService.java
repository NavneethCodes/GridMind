package com.gridmind.service;

import com.gridmind.model.Job;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class JobService {

    @Autowired
    private RedisTemplate<String, Object> redisTemplate;

    // Local storage for uploaded files
    private final Path fileStorageLocation = Paths.get("gridmind-master/uploads").toAbsolutePath().normalize();
    
    // In-memory queue for chunks (In real prod, use Redis List)
    // Key: JobID, Value: List of Chunk Indexes [0, 1, 2, 3]
    private final ConcurrentHashMap<String, List<Integer>> jobQueue = new ConcurrentHashMap<>();
    
    // Registry of Active Jobs
    private final ConcurrentHashMap<String, Job> activeJobs = new ConcurrentHashMap<>();

    public JobService() {
        try {
            Files.createDirectories(this.fileStorageLocation);
        } catch (Exception ex) {
            throw new RuntimeException("Could not create upload dir", ex);
        }
    }

    public Job createJob(MultipartFile file, String pattern) throws IOException {
        // 1. Save the file locally
        String fileName = file.getOriginalFilename();
        Path targetLocation = this.fileStorageLocation.resolve(fileName);
        Files.copy(file.getInputStream(), targetLocation, java.nio.file.StandardCopyOption.REPLACE_EXISTING);

        // 2. Calculate Chunks (Simulated: 1 Chunk = 1MB for demo)
        long fileSize = file.getSize();
        int chunkSize = 1024 * 1024; // 1MB
        int totalChunks = (int) Math.ceil((double) fileSize / chunkSize);

        // 3. Create Job Object
        Job newJob = new Job(fileName, totalChunks, pattern);
        activeJobs.put(newJob.getJobId(), newJob);
        
        // 4. Fill the Queue
        List<Integer> chunks = new ArrayList<>();
        for(int i=0; i<totalChunks; i++) chunks.add(i);
        jobQueue.put(newJob.getJobId(), chunks);
        
        System.out.println("Created Job: " + newJob.getJobId() + " with " + totalChunks + " chunks.");
        return newJob;
    }

    // Worker calls this to get work
    public synchronized String getNextTask() {
        for (String jobId : jobQueue.keySet()) {
            List<Integer> chunks = jobQueue.get(jobId);
            if (!chunks.isEmpty()) {
                int chunkId = chunks.remove(0); // Pop the first chunk
                return jobId + "|" + chunkId; // "UUID|0"
            }
        }
        return "NO_WORK";
    }
}
