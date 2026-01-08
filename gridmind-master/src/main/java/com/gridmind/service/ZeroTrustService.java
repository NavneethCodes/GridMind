package com.gridmind.service;

import org.springframework.stereotype.Service;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@Service
public class ZeroTrustService {

    private static final String SECRET_KEY = "edge123"; // Must match Python Agent

    /**
     * Generates the Time-Based Token (SHA256 of Key + Minute)
     */
    public String generateExpectedToken() {
        try {
            long timeMinute = System.currentTimeMillis() / 1000 / 60;
            String data = SECRET_KEY + timeMinute;
            
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] encodedhash = digest.digest(data.getBytes(StandardCharsets.UTF_8));
            
            return bytesToHex(encodedhash);
        } catch (Exception e) {
            throw new RuntimeException("Crypto Error", e);
        }
    }
    
    // Helper to make SHA256 readable
    private static String bytesToHex(byte[] hash) {
        StringBuilder hexString = new StringBuilder(2 * hash.length);
        for (int i = 0; i < hash.length; i++) {
            String hex = Integer.toHexString(0xff & hash[i]);
            if(hex.length() == 1) {
                hexString.append('0');
            }
            hexString.append(hex);
        }
        return hexString.toString();
    }
}
