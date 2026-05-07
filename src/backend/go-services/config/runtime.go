package config

import (
	_ "embed"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

//go:embed default.json
var defaultConfigData []byte

type ServiceConfig struct {
	Name    string
	URL     string
	Health  string
	Timeout time.Duration
}

type GatewayConfig struct {
	Port                 string
	Debug                bool
	HealthCheckTimeout   time.Duration
	TelemetryServiceName string
	Services             map[string]ServiceConfig
}

type WebSocketConfig struct {
	Port            string
	ReadBufferSize  int
	WriteBufferSize int
	AllowAllOrigins bool
}

type TelemetryConfig struct {
	Endpoint string
}

type RuntimeConfig struct {
	Gateway   GatewayConfig
	WebSocket WebSocketConfig
	Telemetry TelemetryConfig
}

type runtimePatch struct {
	Gateway   *gatewayPatch   `json:"gateway,omitempty"`
	WebSocket *websocketPatch `json:"websocket,omitempty"`
	Telemetry *telemetryPatch `json:"telemetry,omitempty"`
}

type gatewayPatch struct {
	Port                 *string                 `json:"port,omitempty"`
	Debug                *bool                   `json:"debug,omitempty"`
	HealthCheckTimeout   *string                 `json:"healthCheckTimeout,omitempty"`
	TelemetryServiceName *string                 `json:"telemetryServiceName,omitempty"`
	Services             map[string]servicePatch `json:"services,omitempty"`
}

type servicePatch struct {
	Name    *string `json:"name,omitempty"`
	URL     *string `json:"url,omitempty"`
	Health  *string `json:"health,omitempty"`
	Timeout *string `json:"timeout,omitempty"`
}

type websocketPatch struct {
	Port            *string `json:"port,omitempty"`
	ReadBufferSize  *int    `json:"readBufferSize,omitempty"`
	WriteBufferSize *int    `json:"writeBufferSize,omitempty"`
	AllowAllOrigins *bool   `json:"allowAllOrigins,omitempty"`
}

type telemetryPatch struct {
	Endpoint *string `json:"endpoint,omitempty"`
}

func LoadGatewayConfig(args []string) (GatewayConfig, TelemetryConfig, error) {
	cfg, err := loadRuntimeConfig(resolveConfigPath(args))
	if err != nil {
		return GatewayConfig{}, TelemetryConfig{}, err
	}
	deriveGatewayHealthURLs(&cfg)
	if err := applyGatewayCLIOverrides(&cfg, args); err != nil {
		return GatewayConfig{}, TelemetryConfig{}, err
	}
	deriveGatewayHealthURLs(&cfg)
	if err := validateRuntimeConfig(cfg); err != nil {
		return GatewayConfig{}, TelemetryConfig{}, err
	}
	return cfg.Gateway, cfg.Telemetry, nil
}

func LoadWebSocketConfig(args []string) (WebSocketConfig, error) {
	cfg, err := loadRuntimeConfig(resolveConfigPath(args))
	if err != nil {
		return WebSocketConfig{}, err
	}
	if err := applyWebSocketCLIOverrides(&cfg, args); err != nil {
		return WebSocketConfig{}, err
	}
	deriveGatewayHealthURLs(&cfg)
	if err := validateRuntimeConfig(cfg); err != nil {
		return WebSocketConfig{}, err
	}
	return cfg.WebSocket, nil
}

func loadRuntimeConfig(configPath string) (RuntimeConfig, error) {
	var defaults runtimePatch
	if err := json.Unmarshal(defaultConfigData, &defaults); err != nil {
		return RuntimeConfig{}, fmt.Errorf("parse embedded defaults: %w", err)
	}

	cfg := RuntimeConfig{}
	if err := applyPatch(&cfg, defaults); err != nil {
		return RuntimeConfig{}, err
	}
	if configPath != "" {
		if err := applyConfigFile(&cfg, configPath); err != nil {
			return RuntimeConfig{}, err
		}
	}
	if err := applyEnvOverrides(&cfg); err != nil {
		return RuntimeConfig{}, err
	}
	return cfg, nil
}

func resolveConfigPath(args []string) string {
	var cliPath string
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch {
		case arg == "--config" && i+1 < len(args):
			cliPath = args[i+1]
			i++
		case strings.HasPrefix(arg, "--config="):
			cliPath = strings.TrimPrefix(arg, "--config=")
		}
	}
	if cliPath != "" {
		return cliPath
	}
	return os.Getenv("GO_SERVICES_CONFIG_FILE")
}

func applyConfigFile(cfg *RuntimeConfig, path string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("read config file %q: %w", path, err)
	}

	var patch runtimePatch
	if err := json.Unmarshal(data, &patch); err != nil {
		return fmt.Errorf("parse config file %q: %w", path, err)
	}
	return applyPatch(cfg, patch)
}

func applyPatch(cfg *RuntimeConfig, patch runtimePatch) error {
	if patch.Gateway != nil {
		if patch.Gateway.Port != nil {
			cfg.Gateway.Port = *patch.Gateway.Port
		}
		if patch.Gateway.Debug != nil {
			cfg.Gateway.Debug = *patch.Gateway.Debug
		}
		if patch.Gateway.HealthCheckTimeout != nil {
			d, err := time.ParseDuration(*patch.Gateway.HealthCheckTimeout)
			if err != nil {
				return fmt.Errorf("parse gateway.healthCheckTimeout: %w", err)
			}
			cfg.Gateway.HealthCheckTimeout = d
		}
		if patch.Gateway.TelemetryServiceName != nil {
			cfg.Gateway.TelemetryServiceName = *patch.Gateway.TelemetryServiceName
		}
		if len(patch.Gateway.Services) > 0 {
			if cfg.Gateway.Services == nil {
				cfg.Gateway.Services = make(map[string]ServiceConfig, len(patch.Gateway.Services))
			}
			for name, servicePatch := range patch.Gateway.Services {
				serviceCfg := cfg.Gateway.Services[name]
				if servicePatch.Name != nil {
					serviceCfg.Name = *servicePatch.Name
				}
				if servicePatch.URL != nil {
					serviceCfg.URL = *servicePatch.URL
				}
				if servicePatch.Health != nil {
					serviceCfg.Health = *servicePatch.Health
				}
				if servicePatch.Timeout != nil {
					d, err := time.ParseDuration(*servicePatch.Timeout)
					if err != nil {
						return fmt.Errorf("parse gateway.services.%s.timeout: %w", name, err)
					}
					serviceCfg.Timeout = d
				}
				cfg.Gateway.Services[name] = serviceCfg
			}
		}
	}

	if patch.WebSocket != nil {
		if patch.WebSocket.Port != nil {
			cfg.WebSocket.Port = *patch.WebSocket.Port
		}
		if patch.WebSocket.ReadBufferSize != nil {
			cfg.WebSocket.ReadBufferSize = *patch.WebSocket.ReadBufferSize
		}
		if patch.WebSocket.WriteBufferSize != nil {
			cfg.WebSocket.WriteBufferSize = *patch.WebSocket.WriteBufferSize
		}
		if patch.WebSocket.AllowAllOrigins != nil {
			cfg.WebSocket.AllowAllOrigins = *patch.WebSocket.AllowAllOrigins
		}
	}

	if patch.Telemetry != nil && patch.Telemetry.Endpoint != nil {
		cfg.Telemetry.Endpoint = *patch.Telemetry.Endpoint
	}

	return nil
}

func applyEnvOverrides(cfg *RuntimeConfig) error {
	if value := firstNonEmpty(os.Getenv("GATEWAY_PORT"), os.Getenv("PORT")); value != "" {
		cfg.Gateway.Port = value
	}
	if value, ok, err := lookupEnvBool("GATEWAY_DEBUG", "DEBUG"); err != nil {
		return err
	} else if ok {
		cfg.Gateway.Debug = value
	}
	if value, ok, err := lookupEnvDuration("GATEWAY_HEALTHCHECK_TIMEOUT"); err != nil {
		return err
	} else if ok {
		cfg.Gateway.HealthCheckTimeout = value
	}
	if value := os.Getenv("OTEL_SERVICE_NAME"); value != "" {
		cfg.Gateway.TelemetryServiceName = value
	}
	if value := os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT"); value != "" {
		cfg.Telemetry.Endpoint = value
	}

	if value := firstNonEmpty(os.Getenv("WS_GATEWAY_PORT"), os.Getenv("PORT")); value != "" {
		cfg.WebSocket.Port = value
	}
	if value, ok, err := lookupEnvInt("WS_READ_BUFFER_SIZE"); err != nil {
		return err
	} else if ok {
		cfg.WebSocket.ReadBufferSize = value
	}
	if value, ok, err := lookupEnvInt("WS_WRITE_BUFFER_SIZE"); err != nil {
		return err
	} else if ok {
		cfg.WebSocket.WriteBufferSize = value
	}
	if value, ok, err := lookupEnvBool("WS_ALLOW_ALL_ORIGINS"); err != nil {
		return err
	} else if ok {
		cfg.WebSocket.AllowAllOrigins = value
	}

	for serviceName, keys := range gatewayServiceEnvKeys() {
		serviceCfg := cfg.Gateway.Services[serviceName]
		if value := os.Getenv(keys.url); value != "" {
			serviceCfg.URL = value
			if os.Getenv(keys.health) == "" {
				serviceCfg.Health = deriveHealthURL(value)
			}
		}
		if value := os.Getenv(keys.health); value != "" {
			serviceCfg.Health = value
		}
		if value, ok, err := lookupEnvDuration(keys.timeout); err != nil {
			return err
		} else if ok {
			serviceCfg.Timeout = value
		}
		cfg.Gateway.Services[serviceName] = serviceCfg
	}

	return nil
}

func applyGatewayCLIOverrides(cfg *RuntimeConfig, args []string) error {
	flags := flag.NewFlagSet("gateway", flag.ContinueOnError)
	flags.SetOutput(io.Discard)

	port := flags.String("port", cfg.Gateway.Port, "gateway listen port")
	debug := flags.Bool("debug", cfg.Gateway.Debug, "enable Gin debug mode")
	healthCheckTimeout := flags.Duration("health-check-timeout", cfg.Gateway.HealthCheckTimeout, "gateway aggregated health timeout")
	otelEndpoint := flags.String("otel-endpoint", cfg.Telemetry.Endpoint, "OpenTelemetry OTLP HTTP endpoint")
	otelServiceName := flags.String("otel-service-name", cfg.Gateway.TelemetryServiceName, "OpenTelemetry service name")
	_ = flags.String("config", resolveConfigPath(args), "runtime config file path")

	nodeURL := flags.String("nodejs-url", cfg.Gateway.Services["nodejs"].URL, "node backend base URL")
	nodeHealth := flags.String("nodejs-health-url", cfg.Gateway.Services["nodejs"].Health, "node backend health URL")
	nodeTimeout := flags.Duration("nodejs-timeout", cfg.Gateway.Services["nodejs"].Timeout, "node backend timeout")
	pythonURL := flags.String("python-url", cfg.Gateway.Services["python"].URL, "python backend base URL")
	pythonHealth := flags.String("python-health-url", cfg.Gateway.Services["python"].Health, "python backend health URL")
	pythonTimeout := flags.Duration("python-timeout", cfg.Gateway.Services["python"].Timeout, "python backend timeout")
	ocrURL := flags.String("ocr-url", cfg.Gateway.Services["ocr"].URL, "OCR backend base URL")
	ocrHealth := flags.String("ocr-health-url", cfg.Gateway.Services["ocr"].Health, "OCR backend health URL")
	ocrTimeout := flags.Duration("ocr-timeout", cfg.Gateway.Services["ocr"].Timeout, "OCR backend timeout")
	retrievalURL := flags.String("retrieval-url", cfg.Gateway.Services["retrieval"].URL, "retrieval backend base URL")
	retrievalHealth := flags.String("retrieval-health-url", cfg.Gateway.Services["retrieval"].Health, "retrieval backend health URL")
	retrievalTimeout := flags.Duration("retrieval-timeout", cfg.Gateway.Services["retrieval"].Timeout, "retrieval backend timeout")
	llmURL := flags.String("llm-url", cfg.Gateway.Services["llm"].URL, "LLM backend base URL")
	llmHealth := flags.String("llm-health-url", cfg.Gateway.Services["llm"].Health, "LLM backend health URL")
	llmTimeout := flags.Duration("llm-timeout", cfg.Gateway.Services["llm"].Timeout, "LLM backend timeout")
	wsURL := flags.String("ws-gateway-url", cfg.Gateway.Services["websocket"].URL, "websocket gateway base URL")
	wsHealth := flags.String("ws-gateway-health-url", cfg.Gateway.Services["websocket"].Health, "websocket gateway health URL")
	wsTimeout := flags.Duration("ws-gateway-timeout", cfg.Gateway.Services["websocket"].Timeout, "websocket gateway timeout")

	if err := flags.Parse(args); err != nil {
		return err
	}
	visited := visitedFlags(flags)

	cfg.Gateway.Port = *port
	cfg.Gateway.Debug = *debug
	cfg.Gateway.HealthCheckTimeout = *healthCheckTimeout
	cfg.Gateway.TelemetryServiceName = *otelServiceName
	cfg.Telemetry.Endpoint = *otelEndpoint

	cfg.Gateway.Services["nodejs"] = buildCLIServiceConfig(cfg.Gateway.Services["nodejs"].Name, *nodeURL, *nodeHealth, *nodeTimeout, visited["nodejs-url"], visited["nodejs-health-url"])
	cfg.Gateway.Services["python"] = buildCLIServiceConfig(cfg.Gateway.Services["python"].Name, *pythonURL, *pythonHealth, *pythonTimeout, visited["python-url"], visited["python-health-url"])
	cfg.Gateway.Services["ocr"] = buildCLIServiceConfig(cfg.Gateway.Services["ocr"].Name, *ocrURL, *ocrHealth, *ocrTimeout, visited["ocr-url"], visited["ocr-health-url"])
	cfg.Gateway.Services["retrieval"] = buildCLIServiceConfig(cfg.Gateway.Services["retrieval"].Name, *retrievalURL, *retrievalHealth, *retrievalTimeout, visited["retrieval-url"], visited["retrieval-health-url"])
	cfg.Gateway.Services["llm"] = buildCLIServiceConfig(cfg.Gateway.Services["llm"].Name, *llmURL, *llmHealth, *llmTimeout, visited["llm-url"], visited["llm-health-url"])
	cfg.Gateway.Services["websocket"] = buildCLIServiceConfig(cfg.Gateway.Services["websocket"].Name, *wsURL, *wsHealth, *wsTimeout, visited["ws-gateway-url"], visited["ws-gateway-health-url"])

	return nil
}

func applyWebSocketCLIOverrides(cfg *RuntimeConfig, args []string) error {
	flags := flag.NewFlagSet("websocket", flag.ContinueOnError)
	flags.SetOutput(io.Discard)

	port := flags.String("port", cfg.WebSocket.Port, "websocket gateway listen port")
	readBufferSize := flags.Int("read-buffer-size", cfg.WebSocket.ReadBufferSize, "websocket read buffer size")
	writeBufferSize := flags.Int("write-buffer-size", cfg.WebSocket.WriteBufferSize, "websocket write buffer size")
	allowAllOrigins := flags.Bool("allow-all-origins", cfg.WebSocket.AllowAllOrigins, "allow all websocket origins")
	_ = flags.String("config", resolveConfigPath(args), "runtime config file path")

	if err := flags.Parse(args); err != nil {
		return err
	}

	cfg.WebSocket.Port = *port
	cfg.WebSocket.ReadBufferSize = *readBufferSize
	cfg.WebSocket.WriteBufferSize = *writeBufferSize
	cfg.WebSocket.AllowAllOrigins = *allowAllOrigins
	return nil
}

func gatewayServiceEnvKeys() map[string]struct {
	url     string
	health  string
	timeout string
} {
	return map[string]struct {
		url     string
		health  string
		timeout string
	}{
		"nodejs":    {url: "NODEJS_URL", health: "NODEJS_HEALTH_URL", timeout: "NODEJS_TIMEOUT"},
		"python":    {url: "PYTHON_URL", health: "PYTHON_HEALTH_URL", timeout: "PYTHON_TIMEOUT"},
		"ocr":       {url: "OCR_URL", health: "OCR_HEALTH_URL", timeout: "OCR_TIMEOUT"},
		"retrieval": {url: "RETRIEVAL_URL", health: "RETRIEVAL_HEALTH_URL", timeout: "RETRIEVAL_TIMEOUT"},
		"llm":       {url: "LLM_URL", health: "LLM_HEALTH_URL", timeout: "LLM_TIMEOUT"},
		"websocket": {url: "WS_GATEWAY_URL", health: "WS_GATEWAY_HEALTH_URL", timeout: "WS_GATEWAY_TIMEOUT"},
	}
}

func deriveGatewayHealthURLs(cfg *RuntimeConfig) {
	for name, serviceCfg := range cfg.Gateway.Services {
		if serviceCfg.Health == "" && serviceCfg.URL != "" {
			serviceCfg.Health = deriveHealthURL(serviceCfg.URL)
			cfg.Gateway.Services[name] = serviceCfg
		}
	}
}

func buildCLIServiceConfig(name, rawURL, rawHealth string, timeout time.Duration, urlVisited, healthVisited bool) ServiceConfig {
	health := rawHealth
	if urlVisited && !healthVisited {
		health = deriveHealthURL(rawURL)
	}
	return ServiceConfig{
		Name:    name,
		URL:     rawURL,
		Health:  health,
		Timeout: timeout,
	}
}

func deriveHealthURL(rawURL string) string {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return rawURL
	}
	if parsed.Path == "" || parsed.Path == "/" {
		parsed.Path = "/health"
		return parsed.String()
	}
	parsed.Path = strings.TrimRight(parsed.Path, "/") + "/health"
	return parsed.String()
}

func validateRuntimeConfig(cfg RuntimeConfig) error {
	if cfg.Gateway.Port == "" {
		return fmt.Errorf("gateway.port must not be empty")
	}
	if cfg.Gateway.HealthCheckTimeout <= 0 {
		return fmt.Errorf("gateway.healthCheckTimeout must be > 0")
	}
	if cfg.Gateway.TelemetryServiceName == "" {
		return fmt.Errorf("gateway.telemetryServiceName must not be empty")
	}
	for name, serviceCfg := range cfg.Gateway.Services {
		if serviceCfg.Name == "" {
			return fmt.Errorf("gateway.services.%s.name must not be empty", name)
		}
		if serviceCfg.URL == "" {
			return fmt.Errorf("gateway.services.%s.url must not be empty", name)
		}
		if serviceCfg.Health == "" {
			return fmt.Errorf("gateway.services.%s.health must not be empty", name)
		}
		if serviceCfg.Timeout <= 0 {
			return fmt.Errorf("gateway.services.%s.timeout must be > 0", name)
		}
	}
	if cfg.WebSocket.Port == "" {
		return fmt.Errorf("websocket.port must not be empty")
	}
	if cfg.WebSocket.ReadBufferSize <= 0 {
		return fmt.Errorf("websocket.readBufferSize must be > 0")
	}
	if cfg.WebSocket.WriteBufferSize <= 0 {
		return fmt.Errorf("websocket.writeBufferSize must be > 0")
	}
	return nil
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

func visitedFlags(flags *flag.FlagSet) map[string]bool {
	visited := make(map[string]bool)
	flags.Visit(func(current *flag.Flag) {
		visited[current.Name] = true
	})
	return visited
}

func lookupEnvBool(keys ...string) (bool, bool, error) {
	for _, key := range keys {
		value := os.Getenv(key)
		if value == "" {
			continue
		}
		parsed, err := strconv.ParseBool(value)
		if err != nil {
			return false, false, fmt.Errorf("parse %s: %w", key, err)
		}
		return parsed, true, nil
	}
	return false, false, nil
}

func lookupEnvDuration(key string) (time.Duration, bool, error) {
	value := os.Getenv(key)
	if value == "" {
		return 0, false, nil
	}
	duration, err := time.ParseDuration(value)
	if err != nil {
		return 0, false, fmt.Errorf("parse %s: %w", key, err)
	}
	return duration, true, nil
}

func lookupEnvInt(key string) (int, bool, error) {
	value := os.Getenv(key)
	if value == "" {
		return 0, false, nil
	}
	parsed, err := strconv.Atoi(value)
	if err != nil {
		return 0, false, fmt.Errorf("parse %s: %w", key, err)
	}
	return parsed, true, nil
}
