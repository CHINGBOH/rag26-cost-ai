package main

import (
	"log"

	"rag-system/internal/websocket"
)

func main() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)

	hub := websocket.NewHub()
	server := websocket.NewServer(hub)

	log.Println("🚀 Starting WebSocket Gateway on port 8081")
	if err := server.Run(":8081"); err != nil {
		log.Fatalf("Failed to start WebSocket server: %v", err)
	}
}
