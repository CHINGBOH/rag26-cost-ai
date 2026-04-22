package gateway

import (
	"crypto/rand"
	"fmt"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

// createReverseProxy builds a reverse proxy for the given target URL.
func createReverseProxy(targetURL string) *httputil.ReverseProxy {
	target, err := url.Parse(targetURL)
	if err != nil {
		log.Fatalf("Failed to parse target URL %s: %v", targetURL, err)
	}

	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.Director = func(req *http.Request) {
		req.URL.Scheme = target.Scheme
		req.URL.Host = target.Host
		req.URL.Path = singleJoiningSlash(target.Path, req.URL.Path)
		req.Host = target.Host

		if req.Header.Get("X-Request-ID") == "" {
			req.Header.Set("X-Request-ID", generateRequestID())
		}
	}
	return proxy
}

// singleJoiningSlash merges two URL paths avoiding double slashes.
func singleJoiningSlash(a, b string) string {
	aslash := strings.HasSuffix(a, "/")
	bslash := strings.HasPrefix(b, "/")
	switch {
	case aslash && bslash:
		return a + b[1:]
	case !aslash && !bslash:
		return a + "/" + b
	}
	return a + b
}

// generateRequestID creates a unique request identifier.
func generateRequestID() string {
	return fmt.Sprintf("req-%d-%s", time.Now().UnixNano(), randomString(8))
}

// randomString generates a random alphanumeric string of given length.
func randomString(length int) string {
	charset := "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
	b := make([]byte, length)
	rand.Read(b)
	for i := range b {
		b[i] = charset[int(b[i])%len(charset)]
	}
	return string(b)
}

// findTargetService resolves the downstream service name from the request path.
func findTargetService(path string) (string, bool) {
	mappings := getRouteMapping()
	// sort prefixes by length descending for deterministic longest-match
	var prefixes []string
	for p := range mappings {
		prefixes = append(prefixes, p)
	}
	// simple bubble sort by length desc
	for i := 0; i < len(prefixes); i++ {
		for j := i + 1; j < len(prefixes); j++ {
			if len(prefixes[j]) > len(prefixes[i]) {
				prefixes[i], prefixes[j] = prefixes[j], prefixes[i]
			}
		}
	}
	for _, prefix := range prefixes {
		if strings.HasPrefix(path, prefix) {
			return mappings[prefix], true
		}
	}
	return "nodejs", false
}

// getRouteMapping returns the static route-to-service mapping.
func getRouteMapping() map[string]string {
	return map[string]string{
		"/api/sessions":     "nodejs",
		"/api/activity":     "nodejs",
		"/api/heartbeat":    "nodejs",
		"/api/auth":         "nodejs",
		"/api/llm/chat":     "nodejs",
		"/api/cache":        "nodejs",
		"/api/queue":        "nodejs",
		"/api/system":       "nodejs",
		"/api/pipeline":     "nodejs",
		"/api/agent":        "nodejs",
		"/api/ocr":          "ocr",
		"/api/v1/embedding": "python",
		"/api/v1/documents": "python",
		"/api/stats":        "python",
		"/api/v1/stats":     "python",
		"/api/search":       "retrieval",
		"/api/v1/sandbox":   "retrieval",
		"/api/v1/search":    "retrieval",
		"/api/v1/rerank":    "retrieval",
		"/api/v1/evaluate":  "retrieval",
		"/api/v1/decompose": "retrieval",
		"/api/v1/rag":       "retrieval",
		"/api/v1/agent":     "retrieval",
		"/api/v1/feedback":  "retrieval",
		"/api/v1/metrics":   "retrieval",
		"/api/v1/health":    "retrieval",
		"/api/retrieval":    "retrieval",
		"/api/generate":     "llm",
		"/api/chat":         "llm",
		"/ws":               "websocket",
	}
}

// ProxyHandler forwards the request to the appropriate backend service.
func ProxyHandler(cfg *GatewayConfig) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		path := c.Request.URL.Path
		method := c.Request.Method

		serviceName, found := findTargetService(path)
		if !found {
			c.JSON(404, gin.H{
				"error":   "Route not found",
				"path":    path,
				"message": "No service mapping found for this path",
			})
			return
		}

		service, exists := cfg.Services[serviceName]
		if !exists {
			c.JSON(503, gin.H{
				"error":   "Service not configured",
				"service": serviceName,
				"message": "Service configuration not found",
			})
			return
		}

		proxy := createReverseProxy(service.URL)

		defer func() {
			duration := time.Since(start).Seconds()
			status := fmt.Sprintf("%d", c.Writer.Status())
			RecordMetrics(method, path, status, duration)
			log.Printf("[%s] %s %s -> %s (%s) %.3fs",
				c.Request.Header.Get("X-Request-ID"),
				method, path, serviceName, status, duration)
		}()

		proxy.ServeHTTP(c.Writer, c.Request)
	}
}
