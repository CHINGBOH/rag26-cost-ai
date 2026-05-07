package websocket

import (
	"encoding/json"
	"log"
	"net/http"
	"net/url"
	"strings"

	"github.com/gorilla/websocket"

	runtimeconfig "rag-system/config"
)

// BroadcastRequest is the expected payload for the POST /broadcast endpoint.
type BroadcastRequest struct {
	Room    string          `json:"room"`
	Message json.RawMessage `json:"message"`
}

// Server handles websocket upgrades and HTTP broadcast requests.
type Server struct {
	hub      *Hub
	upgrader websocket.Upgrader
}

// NewServer creates a new Server.
func NewServer(hub *Hub, cfg runtimeconfig.WebSocketConfig) *Server {
	return &Server{
		hub: hub,
		upgrader: websocket.Upgrader{
			ReadBufferSize:  cfg.ReadBufferSize,
			WriteBufferSize: cfg.WriteBufferSize,
			CheckOrigin: func(r *http.Request) bool {
				if cfg.AllowAllOrigins {
					return true
				}
				origin := r.Header.Get("Origin")
				if origin == "" {
					return true
				}
				parsedOrigin, err := url.Parse(origin)
				if err != nil {
					return false
				}
				return strings.EqualFold(parsedOrigin.Host, r.Host)
			},
		},
	}
}

// ServeWS handles websocket upgrades at GET /ws?room=<roomId>.
func (s *Server) ServeWS(w http.ResponseWriter, r *http.Request) {
	room := r.URL.Query().Get("room")
	if room == "" {
		http.Error(w, "room parameter required", http.StatusBadRequest)
		return
	}

	conn, err := s.upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("websocket upgrade failed: %v", err)
		return
	}

	client := NewClient(s.hub, conn, room)
	s.hub.Register(client)

	// Each connection gets independent read and write goroutines.
	go client.WritePump()
	go client.ReadPump()
}

// ServeBroadcast handles POST /broadcast and forwards the message to the target room.
func (s *Server) ServeBroadcast(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req BroadcastRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}

	if req.Room == "" {
		http.Error(w, "room is required", http.StatusBadRequest)
		return
	}

	s.hub.Broadcast(req.Room, []byte(req.Message))

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted)
	w.Write([]byte(`{"status":"ok"}`))
}

// Run starts the HTTP server on the given address.
func (s *Server) Run(addr string) error {
	mux := http.NewServeMux()
	mux.HandleFunc("/ws", s.ServeWS)
	mux.HandleFunc("/broadcast", s.ServeBroadcast)
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"ok"}`))
	})
	log.Printf("🚀 WebSocket Gateway starting on %s", addr)
	return http.ListenAndServe(addr, mux)
}
