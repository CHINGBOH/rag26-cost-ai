package main

import (
	"log"

	"rag-system/internal/gateway"
)

func main() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)

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
