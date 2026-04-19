package websocket

import "sync"

// Hub maintains the set of active clients and broadcasts messages to rooms.
type Hub struct {
	clients map[*Client]bool
	rooms   map[string]map[*Client]bool
	mu      sync.RWMutex
}

// NewHub creates a new Hub.
func NewHub() *Hub {
	return &Hub{
		clients: make(map[*Client]bool),
		rooms:   make(map[string]map[*Client]bool),
	}
}

// Register adds a client to the hub and its room.
func (h *Hub) Register(client *Client) {
	h.mu.Lock()
	defer h.mu.Unlock()

	h.clients[client] = true
	if client.room != "" {
		if h.rooms[client.room] == nil {
			h.rooms[client.room] = make(map[*Client]bool)
		}
		h.rooms[client.room][client] = true
	}
}

// Unregister removes a client from the hub and its room, then closes its send channel.
func (h *Hub) Unregister(client *Client) {
	h.mu.Lock()
	defer h.mu.Unlock()

	if _, ok := h.clients[client]; !ok {
		return
	}
	delete(h.clients, client)

	if client.room != "" {
		if room, ok := h.rooms[client.room]; ok {
			delete(room, client)
			if len(room) == 0 {
				delete(h.rooms, client.room)
			}
		}
	}

	close(client.send)
}

// Broadcast sends a message to all clients in the specified room.
// If room is empty, it broadcasts to all connected clients.
func (h *Hub) Broadcast(room string, message []byte) {
	h.mu.RLock()
	var targets map[*Client]bool
	if room != "" {
		targets = make(map[*Client]bool, len(h.rooms[room]))
		for c := range h.rooms[room] {
			targets[c] = true
		}
	} else {
		targets = make(map[*Client]bool, len(h.clients))
		for c := range h.clients {
			targets[c] = true
		}
	}
	h.mu.RUnlock()

	for client := range targets {
		select {
		case client.send <- message:
		default:
			// Slow client: unregister and close connection.
			h.Unregister(client)
			client.conn.Close()
		}
	}
}
