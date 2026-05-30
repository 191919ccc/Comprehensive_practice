package com.recruitment.backend.controller;

import com.recruitment.backend.service.AiChatService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/ai")
public class AiChatController {

    private final AiChatService aiChatService;

    public AiChatController(AiChatService aiChatService) {
        this.aiChatService = aiChatService;
    }

    @PostMapping("/chat")
    public ResponseEntity<?> chat(@RequestBody Map<String, Object> payload) {
        return ResponseEntity.ok(aiChatService.chat(payload));
    }

    @PostMapping("/clear")
    public Map<String, Object> clear() {
        return Map.of("status", "ok");
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of(
                "status", "ok",
                "model", aiChatService.modelName(),
                "api_key_configured", aiChatService.apiKeyConfigured(),
                "web_enabled", aiChatService.webEnabled()
        );
    }
}
