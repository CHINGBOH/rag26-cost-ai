package main

import (
	"log"
	"os"

	runtimeconfig "rag-system/config"
	"rag-system/internal/websocket"
)

func main() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)

	cfg, err := runtimeconfig.LoadWebSocketConfig(os.Args[1:])
	if err != nil {
		log.Fatalf("Failed to load websocket config: %v", err)
	}

	hub := websocket.NewHub()
	server := websocket.NewServer(hub, cfg)

	log.Printf("🚀 Starting WebSocket Gateway on port %s", cfg.Port)
	if err := server.Run(":" + cfg.Port); err != nil {
		log.Fatalf("Failed to start WebSocket server: %v", err)
	}
}
