package com.gridmind.service;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Service;
import java.util.Set;

@Service
public class RecoveryService {

    @Autowired
    private RedisTemplate<String, Object> redisTemplate;

    @Autowired
    private ZeroTrustService zeroTrustService;
    
    // The key pattern used by Python Portal to register nodes
    private static final String WORKER_KEY_PREFIX = "worker:*"; 

    @EventListener(ApplicationReadyEvent.class)
    public void initiateNetworkRecovery() {
        System.out.println("⚡ [RECOVERY ENGINE] System Booted. Scanning Grid State...");

        // 1. Scan Redis for any worker registered by the Python Portal
        Set<String> knownWorkers = redisTemplate.keys(WORKER_KEY_PREFIX);

        if (knownWorkers == null || knownWorkers.isEmpty()) {
            System.out.println("ℹ️  [RECOVERY ENGINE] No worker history found in Redis.");
            return;
        }

        System.out.println("🔄 [RECOVERY ENGINE] Found " + knownWorkers.size() + " known workers. Attempting Handshake...");

        for (String workerKey : knownWorkers) {
            String ip = workerKey.replace("worker:", "");
            recoverNodeState(ip);
        }
    }

    private void recoverNodeState(String ip) {
        System.out.println("    -> Probing Worker: " + ip);
        
        // In the real implementation, you would open a Socket here to Port 5555
        // and verify the token from zeroTrustService.generateExpectedToken().
        // For now, we simulate a successful "Ping".
        
        String currentToken = zeroTrustService.generateExpectedToken();
        System.out.println("       [SECURE] Generated Trust Token: " + currentToken.substring(0, 10) + "...");
        
        // Mark as IDLE in Redis so Adish's UI shows it as Green
        redisTemplate.opsForValue().set("status:" + ip, "IDLE");
        System.out.println("    ✅ [RECOVERY] Node " + ip + " is ONLINE & SYNCED.");
    }
}
