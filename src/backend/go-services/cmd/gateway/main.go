package main

import (
	"context"
	"log"
	"time"

	"rag-system/internal/gateway"
	"rag-system/internal/telemetry"
)

func main() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)

	shutdown, err := telemetry.Init("go-gateway")
	if err != nil {
		log.Printf("[OTEL] init failed (continuing without tracing): %v", err)
	}
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		_ = shutdown(ctx)
	}()

	cfg := gateway.LoadConfig()
	router := gateway.SetupRouter(cfg)

	log.Printf("🚀 Starting Gateway on port %s", cfg.Port)
	log.Printf("📡 Proxying to:")
	for name, svc := range cfg.Services {
		log.Printf("  - %s: %s (timeout: %v)", name, svc.URL, svc.Timeout)
	}

	if err := router.Run(":" + cfg.Port); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}
