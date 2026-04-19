package gateway

import (
	"os"
	"strconv"
	"time"
)

// ServiceConfig represents a downstream microservice configuration.
type ServiceConfig struct {
	Name    string
	URL     string
	Health  string
	Timeout time.Duration
}

// GatewayConfig holds all gateway-level configurations.
type GatewayConfig struct {
	Port     string
	Debug    bool
	Services map[string]ServiceConfig
}

// getEnv returns the environment variable value or a default.
func getEnv(key, defaultValue string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return defaultValue
}

// getEnvBool returns the environment variable as a bool or a default.
func getEnvBool(key string, defaultValue bool) bool {
	v := os.Getenv(key)
	if v == "" {
		return defaultValue
	}
	b, err := strconv.ParseBool(v)
	if err != nil {
		return defaultValue
	}
	return b
}

// getEnvDuration returns the environment variable as a duration or a default.
func getEnvDuration(key string, defaultValue time.Duration) time.Duration {
	v := os.Getenv(key)
	if v == "" {
		return defaultValue
	}
	d, err := time.ParseDuration(v)
	if err != nil {
		return defaultValue
	}
	return d
}

// LoadConfig builds the gateway configuration from environment variables.
func LoadConfig() *GatewayConfig {
	cfg := &GatewayConfig{
		Port:  getEnv("PORT", "8080"),
		Debug: getEnvBool("DEBUG", false),
		Services: map[string]ServiceConfig{
			"nodejs": {
				Name:    "nodejs-backend",
				URL:     getEnv("NODEJS_URL", "http://localhost:3001"),
				Health:  getEnv("NODEJS_HEALTH_URL", "http://localhost:3001/health"),
				Timeout: getEnvDuration("NODEJS_TIMEOUT", 30*time.Second),
			},
			"python": {
				Name:    "python-backend",
				URL:     getEnv("PYTHON_URL", "http://localhost:8000"),
				Health:  getEnv("PYTHON_HEALTH_URL", "http://localhost:8000/health"),
				Timeout: getEnvDuration("PYTHON_TIMEOUT", 30*time.Second),
			},
			"ocr": {
				Name:    "ocr-service",
				URL:     getEnv("OCR_URL", "http://localhost:8001"),
				Health:  getEnv("OCR_HEALTH_URL", "http://localhost:8001/health"),
				Timeout: getEnvDuration("OCR_TIMEOUT", 60*time.Second),
			},
			"retrieval": {
				Name:    "retrieval-service",
				URL:     getEnv("RETRIEVAL_URL", "http://localhost:8002"),
				Health:  getEnv("RETRIEVAL_HEALTH_URL", "http://localhost:8002/health"),
				Timeout: getEnvDuration("RETRIEVAL_TIMEOUT", 30*time.Second),
			},
			"llm": {
				Name:    "llm-service",
				URL:     getEnv("LLM_URL", "http://localhost:8003"),
				Health:  getEnv("LLM_HEALTH_URL", "http://localhost:8003/health"),
				Timeout: getEnvDuration("LLM_TIMEOUT", 120*time.Second),
			},
			"websocket": {
				Name:    "websocket-gateway",
				URL:     getEnv("WS_GATEWAY_URL", "http://localhost:8081"),
				Health:  getEnv("WS_GATEWAY_HEALTH_URL", "http://localhost:8081/health"),
				Timeout: getEnvDuration("WS_GATEWAY_TIMEOUT", 30*time.Second),
			},
		},
	}
	return cfg
}
