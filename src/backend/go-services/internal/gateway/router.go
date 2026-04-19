package gateway

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// HealthCheckHandler aggregates health status from all configured downstream services.
func HealthCheckHandler(cfg *GatewayConfig) gin.HandlerFunc {
	return func(c *gin.Context) {
		servicesStatus := make(map[string]string)
		allHealthy := true

		for name, svc := range cfg.Services {
			client := &http.Client{Timeout: 5 * time.Second}
			resp, err := client.Get(svc.Health)
			if err != nil {
				servicesStatus[name] = "unhealthy"
				allHealthy = false
				continue
			}
			resp.Body.Close()
			if resp.StatusCode == 200 {
				servicesStatus[name] = "healthy"
			} else {
				servicesStatus[name] = "unhealthy"
				allHealthy = false
			}
		}

		if allHealthy {
			c.JSON(200, gin.H{
				"status":    "ok",
				"services":  servicesStatus,
				"version":   "0.2.0",
				"timestamp": time.Now().Unix(),
			})
		} else {
			c.JSON(503, gin.H{
				"status":    "degraded",
				"services":  servicesStatus,
				"message":   "some services are unhealthy",
				"timestamp": time.Now().Unix(),
			})
		}
	}
}

// SetupRouter configures the Gin router with all routes and middleware.
func SetupRouter(cfg *GatewayConfig) *gin.Engine {
	if cfg.Debug {
		gin.SetMode(gin.DebugMode)
	} else {
		gin.SetMode(gin.ReleaseMode)
	}

	router := gin.New()
	router.Use(gin.Recovery())
	router.Use(RequestIDMiddleware())
	router.Use(CORSMiddleware())
	router.Use(LoggingMiddleware())

	// Gateway self endpoints
	router.GET("/health", HealthCheckHandler(cfg))
	router.GET("/metrics", gin.WrapH(promhttp.Handler()))

	// Explicit WebSocket route to ensure upgrade headers are preserved
	router.GET("/ws", ProxyHandler(cfg))

	// Proxy all unmatched requests via NoRoute to avoid wildcard conflicts
	router.NoRoute(ProxyHandler(cfg))

	return router
}
