package config

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLoadGatewayConfigDefaults(t *testing.T) {
	t.Setenv("GO_SERVICES_CONFIG_FILE", "")
	t.Setenv("PORT", "")
	t.Setenv("GATEWAY_PORT", "")
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
	t.Setenv("OTEL_SERVICE_NAME", "")
	t.Setenv("NODEJS_URL", "")
	t.Setenv("NODEJS_HEALTH_URL", "")

	cfg, telemetryCfg, err := LoadGatewayConfig(nil)
	if err != nil {
		t.Fatalf("LoadGatewayConfig returned error: %v", err)
	}

	if cfg.Port != "8080" {
		t.Fatalf("expected default gateway port 8080, got %q", cfg.Port)
	}
	if cfg.HealthCheckTimeout != 5*time.Second {
		t.Fatalf("expected default health timeout 5s, got %v", cfg.HealthCheckTimeout)
	}
	if telemetryCfg.Endpoint != "" {
		t.Fatalf("expected OTEL endpoint to be empty by default, got %q", telemetryCfg.Endpoint)
	}
	if cfg.Services["nodejs"].Health != "http://localhost:3001/health" {
		t.Fatalf("expected derived node health URL, got %q", cfg.Services["nodejs"].Health)
	}
}

func TestLoadGatewayConfigConfigEnvAndCLIOverrides(t *testing.T) {
	tempDir := t.TempDir()
	configPath := filepath.Join(tempDir, "gateway.json")
	configBody := []byte(`{
  "gateway": {
    "port": "18080",
    "healthCheckTimeout": "12s",
    "telemetryServiceName": "gateway-from-file",
    "services": {
      "nodejs": {
        "url": "http://file-node:3100"
      }
    }
  },
  "telemetry": {
    "endpoint": "http://tempo-file:4318"
  }
}`)
	if err := os.WriteFile(configPath, configBody, 0o644); err != nil {
		t.Fatalf("write temp config: %v", err)
	}

	t.Setenv("NODEJS_URL", "http://env-node:3200")
	t.Setenv("OTEL_SERVICE_NAME", "gateway-from-env")
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://tempo-env:4318")

	cfg, telemetryCfg, err := LoadGatewayConfig([]string{
		"--config", configPath,
		"--port", "19080",
		"--nodejs-url", "http://cli-node:3300",
	})
	if err != nil {
		t.Fatalf("LoadGatewayConfig returned error: %v", err)
	}

	if cfg.Port != "19080" {
		t.Fatalf("expected CLI port override, got %q", cfg.Port)
	}
	if cfg.Services["nodejs"].URL != "http://cli-node:3300" {
		t.Fatalf("expected CLI node URL override, got %q", cfg.Services["nodejs"].URL)
	}
	if cfg.Services["nodejs"].Health != "http://cli-node:3300/health" {
		t.Fatalf("expected derived node health from CLI URL, got %q", cfg.Services["nodejs"].Health)
	}
	if cfg.TelemetryServiceName != "gateway-from-env" {
		t.Fatalf("expected env OTEL service name override, got %q", cfg.TelemetryServiceName)
	}
	if telemetryCfg.Endpoint != "http://tempo-env:4318" {
		t.Fatalf("expected env OTEL endpoint override, got %q", telemetryCfg.Endpoint)
	}
	if cfg.HealthCheckTimeout != 12*time.Second {
		t.Fatalf("expected file health timeout 12s, got %v", cfg.HealthCheckTimeout)
	}
}

func TestLoadWebSocketConfigOverrides(t *testing.T) {
	t.Setenv("GO_SERVICES_CONFIG_FILE", "")
	t.Setenv("PORT", "")
	t.Setenv("WS_GATEWAY_PORT", "18081")
	t.Setenv("WS_READ_BUFFER_SIZE", "2048")
	t.Setenv("WS_WRITE_BUFFER_SIZE", "4096")
	t.Setenv("WS_ALLOW_ALL_ORIGINS", "false")

	cfg, err := LoadWebSocketConfig([]string{"--port", "19081"})
	if err != nil {
		t.Fatalf("LoadWebSocketConfig returned error: %v", err)
	}

	if cfg.Port != "19081" {
		t.Fatalf("expected CLI websocket port override, got %q", cfg.Port)
	}
	if cfg.ReadBufferSize != 2048 {
		t.Fatalf("expected env read buffer override, got %d", cfg.ReadBufferSize)
	}
	if cfg.WriteBufferSize != 4096 {
		t.Fatalf("expected env write buffer override, got %d", cfg.WriteBufferSize)
	}
	if cfg.AllowAllOrigins {
		t.Fatalf("expected allowAllOrigins=false from env override")
	}
}
