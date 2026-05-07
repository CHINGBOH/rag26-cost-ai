package main

import (
	"context"
	"log"
	"os"
	"time"

	"rag-system/internal/gateway"
	"rag-system/internal/telemetry"
)

func main() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)

	cfg, telemetryCfg, err := gateway.LoadConfig(os.Args[1:])
	if err != nil {
		log.Fatalf("Failed to load gateway config: %v", err)
	}

	shutdown, err := telemetry.Init(telemetryCfg.Endpoint, cfg.TelemetryServiceName)
	if err != nil {
		log.Printf("[OTEL] init failed (continuing without tracing): %v", err)
		shutdown = func(context.Context) error { return nil }
	}
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		_ = shutdown(ctx)
	}()

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
