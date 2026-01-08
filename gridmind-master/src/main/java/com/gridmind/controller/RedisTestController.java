package com.gridmind.controller;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/test")
public class RedisTestController {

    @Autowired
    private RedisTemplate<String, Object> redisTemplate;

    @GetMapping("/ping")
    public String testRedis(@RequestParam String msg) {
        // 1. Write to Redis
        redisTemplate.opsForValue().set("test:ping", msg);
        
        // 2. Read back from Redis
        String value = (String) redisTemplate.opsForValue().get("test:ping");
        
        return "Redis says: " + value + " (Status: CONNECTED)";
    }
}
